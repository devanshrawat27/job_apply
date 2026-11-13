from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import resume as resume_agent
from app.database import get_db
from app.deps import CurrentUser
from app.models import Profile, Resume
from app.schemas import ProfileIn, ProfileOut, ResumeOut, ResumeParseOut
from app.services import github_profile, resume_store

router = APIRouter(prefix="/profile", tags=["profile"])


def _uid(user: CurrentUser) -> int | None:
    return user.id if user is not None else None


def _get_or_create(db: Session, user_id: int | None = None) -> Profile:
    if user_id is None:
        profile = db.get(Profile, 1)
    else:
        profile = db.scalar(select(Profile).where(Profile.user_id == user_id))
    if profile is None:
        profile = Profile(user_id=user_id)
        if user_id is None:
            profile.id = 1
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _to_out(resume: Resume) -> ResumeOut:
    return ResumeOut(
        id=resume.id,
        label=resume.label or resume.filename,
        filename=resume.filename,
        is_primary=resume.is_primary,
        chars=len(resume.text or ""),
        created_at=resume.created_at,
    )


def _apply_extraction(profile: Profile, extracted: dict, filename: str, text: str, path: str) -> None:
    """Copy extracted fields onto the profile (only for the primary resume)."""
    profile.resume_text = text
    profile.resume_filename = filename
    profile.resume_path = path

    simple = {
        "full_name": "full_name",
        "email": "email",
        "phone": "phone",
        "location": "location",
        "seniority": "seniority",
        "job_title": "job_title",
        "current_company": "current_company",
        "current_role": "current_role",
        "experience_months": "experience_months",
        "domain": "domain",
    }
    for source, target in simple.items():
        if extracted.get(source):
            setattr(profile, target, extracted[source])

    for key in ("skills", "target_roles", "avoid"):
        if isinstance(extracted.get(key), list):
            setattr(profile, key, extracted[key])
    if isinstance(extracted.get("links"), dict):
        profile.links = extracted["links"]


async def _add_resume(
    db: Session,
    file: UploadFile,
    *,
    user_id: int | None = None,
    label: str = "",
    make_primary: bool = True,
) -> tuple[Resume, dict]:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file")
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="file too large (max 8 MB)")

    try:
        text = resume_agent.read_resume_file(file.filename or "", raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - corrupt/encrypted PDFs land here
        raise HTTPException(
            status_code=400,
            detail="Could not read that file. Try a text-based PDF, DOCX or TXT.",
        ) from exc

    if not text.strip():
        raise HTTPException(status_code=400, detail="could not read any text from the file")

    extracted = resume_agent.extract_profile(text)
    path = resume_store.save(file.filename or "resume", raw)

    existing_stmt = select(Resume)
    if user_id is not None:
        existing_stmt = existing_stmt.where(Resume.user_id == user_id)
    existing = list(db.scalars(existing_stmt).all())
    primary = make_primary or not existing
    if primary:
        for resume in existing:
            resume.is_primary = False

    row = Resume(
        user_id=user_id,
        label=(label or "").strip()[:120] or (file.filename or "resume"),
        filename=file.filename or "resume",
        text=text,
        path=path,
        is_primary=primary,
    )
    db.add(row)
    db.flush()

    if primary:
        profile = _get_or_create(db, user_id)
        _apply_extraction(profile, extracted, row.filename, text, path)
        db.commit()
        # The resume often contains the GitHub link; pull the public repos now
        # so drafts can cite real projects.
        if (profile.links or {}).get("github"):
            github_profile.sync(db, profile)

    db.commit()
    db.refresh(row)
    return row, extracted


@router.get("", response_model=ProfileOut)
def read_profile(user: CurrentUser = None, db: Session = Depends(get_db)) -> Profile:
    return _get_or_create(db, _uid(user))


@router.put("", response_model=ProfileOut)
def update_profile(
    payload: ProfileIn, user: CurrentUser = None, db: Session = Depends(get_db)
) -> Profile:
    profile = _get_or_create(db, _uid(user))
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)

    # A new/changed GitHub link is turned into project evidence right away.
    if (profile.links or {}).get("github"):
        github_profile.sync(db, profile)
        db.refresh(profile)
    return profile


@router.post("/github/sync")
def sync_github(user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    profile = _get_or_create(db, _uid(user))
    result = github_profile.sync(db, profile, force=True)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=str(result.get("error") or "sync failed"))
    return result


# ------------------------------------------------------------------ resumes

@router.get("/resumes", response_model=list[ResumeOut])
def list_resumes(user: CurrentUser = None, db: Session = Depends(get_db)) -> list[ResumeOut]:
    uid = _uid(user)
    stmt = select(Resume)
    if uid is not None:
        stmt = stmt.where(Resume.user_id == uid)
    rows = list(db.scalars(stmt.order_by(Resume.is_primary.desc(), Resume.id.asc())).all())

    # Migrate a resume uploaded before multi-resume support.
    if not rows:
        profile = _get_or_create(db, uid)
        if (profile.resume_text or "").strip():
            legacy = Resume(
                user_id=uid,
                label=profile.resume_filename or "Resume",
                filename=profile.resume_filename or "resume",
                text=profile.resume_text,
                path=profile.resume_path or "",
                is_primary=True,
            )
            db.add(legacy)
            db.commit()
            db.refresh(legacy)
            rows = [legacy]

    return [_to_out(row) for row in rows]


@router.post("/resumes", response_model=ResumeOut)
async def add_resume(
    file: UploadFile = File(...),
    label: str = Form(default=""),
    make_primary: bool = Form(default=False),
    user: CurrentUser = None,
    db: Session = Depends(get_db),
) -> ResumeOut:
    row, _ = await _add_resume(
        db, file, user_id=_uid(user), label=label, make_primary=make_primary
    )
    return _to_out(row)


@router.post("/resumes/{resume_id}/primary", response_model=ResumeOut)
def make_primary(
    resume_id: int, user: CurrentUser = None, db: Session = Depends(get_db)
) -> ResumeOut:
    uid = _uid(user)
    row = db.get(Resume, resume_id)
    if row is None or (uid is not None and row.user_id != uid):
        raise HTTPException(status_code=404, detail="resume not found")

    stmt = select(Resume)
    if uid is not None:
        stmt = stmt.where(Resume.user_id == uid)
    for other in db.scalars(stmt).all():
        other.is_primary = other.id == resume_id

    profile = _get_or_create(db, uid)
    profile.resume_text = row.text
    profile.resume_filename = row.filename
    profile.resume_path = row.path

    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/resumes/{resume_id}")
def delete_resume(
    resume_id: int, user: CurrentUser = None, db: Session = Depends(get_db)
) -> dict:
    uid = _uid(user)
    row = db.get(Resume, resume_id)
    if row is None or (uid is not None and row.user_id != uid):
        raise HTTPException(status_code=404, detail="resume not found")

    was_primary = row.is_primary
    resume_store.delete(row.path)
    db.delete(row)
    db.commit()

    if was_primary:
        stmt = select(Resume)
        if uid is not None:
            stmt = stmt.where(Resume.user_id == uid)
        remaining = list(db.scalars(stmt.order_by(Resume.id.asc())).all())
        if remaining:
            remaining[0].is_primary = True
            profile = _get_or_create(db, uid)
            profile.resume_text = remaining[0].text
            profile.resume_filename = remaining[0].filename
            profile.resume_path = remaining[0].path
            db.commit()

    return {"deleted": True}


# Legacy endpoint used by onboarding.
@router.post("/resume", response_model=ResumeParseOut)
async def upload_resume(
    file: UploadFile = File(...), user: CurrentUser = None, db: Session = Depends(get_db)
) -> ResumeParseOut:
    row, extracted = await _add_resume(db, file, user_id=_uid(user), make_primary=True)
    return ResumeParseOut(filename=row.filename, chars=len(row.text or ""), extracted=extracted)
