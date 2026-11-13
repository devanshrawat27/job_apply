from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import query_lab
from app.database import get_db
from app.deps import CurrentUser
from app.models import SearchQuery

router = APIRouter(prefix="/keywords", tags=["keywords"])


def _uid(user: CurrentUser) -> int | None:
    return user.id if user is not None else None


class PinIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=160)
    pinned: bool = True


@router.get("")
def list_keywords(user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    """Which search keywords are winning, and which are still being tested."""
    return query_lab.snapshot(db, _uid(user))


@router.post("/pin")
def pin_keyword(payload: PinIn, user: CurrentUser = None, db: Session = Depends(get_db)) -> dict:
    """Pin a keyword so every scan schedules it, regardless of its score."""
    user_id = _uid(user)
    stmt = select(SearchQuery).where(
        func.lower(SearchQuery.keyword) == payload.keyword.strip().lower()
    )
    if user_id is not None:
        stmt = stmt.where(SearchQuery.user_id == user_id)
    else:
        stmt = stmt.where(SearchQuery.user_id.is_(None))
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=404, detail="keyword not found")

    row.pinned = payload.pinned
    db.commit()
    return {"keyword": row.keyword, "pinned": bool(row.pinned)}
