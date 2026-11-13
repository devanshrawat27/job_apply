"""Resume -> structured profile.

Only the fields that matter when applying are extracted: contact details, links,
skills, the *current* role/company, total experience and the job title to search
for. No headline, no invented pitch.

Two paths:
  * LLM extraction when a key is configured (best accuracy)
  * a deterministic parser as the fallback

The deterministic parser handles the common real-world cases:
  - PDF hyperlinks live in annotations, not text -> read them from the PDF
  - "Aug 2026 - Present" marks the current role -> parse company/role/months
  - months, not years, so a 4-month internship is represented correctly
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from app.llm import LLMUnavailable, complete_json

logger = logging.getLogger(__name__)

SYSTEM = """You extract a structured candidate profile from a resume.
Return strict JSON only. Never invent facts that are not in the resume.
If a field is unknown use an empty string / empty list / 0.
Do not write summaries, headlines or marketing sentences.
"""

PROMPT = """Resume:
---
{resume}
---

Return JSON with exactly these keys:
{{
  "full_name": "",
  "email": "",
  "phone": "",
  "location": "city, state/country if present",
  "links": {{"github": "", "portfolio": "", "linkedin": ""}},
  "skills": ["concrete technologies only, max 20"],
  "job_title": "the single best job title this person should be hired for",
  "target_roles": ["other realistic job titles, max 3"],
  "current_company": "employer of the most recent / ongoing role, or empty",
  "current_role": "title of the most recent / ongoing role, or empty",
  "experience_months": 0,
  "seniority": "fresher|experienced",
  "domain": "tech|non-tech"
}}

Rules:
- current_company/current_role come from the entry marked "Present",
  "Current", or the most recent date range. Not from a target role.
- domain is "tech" for software/engineering/data/product/design work and
  "non-tech" for sales/marketing/HR/support/operations resumes.
- experience_months is total professional experience in MONTHS as an integer.
  4 months -> 4. 2 years -> 24. 1 year 6 months -> 18. Use 0 if unknown.
- job_title must be a plain role name like "Frontend Developer", not a sentence.
- skills must be technologies/tools, not soft skills.
"""

# --------------------------------------------------------------------- vocab

# Longest first so "full stack developer" wins over "developer".
_TITLE_WORDS = [
    "full stack developer", "full-stack developer", "full stack engineer",
    "frontend developer", "front-end developer", "frontend engineer",
    "backend developer", "back-end developer", "backend engineer",
    "software engineer", "software developer", "react developer",
    "node.js developer", "python developer", "web developer",
    "mobile developer", "android developer", "ios developer",
    "devops engineer", "data scientist", "data analyst", "ml engineer",
    "machine learning engineer", "qa engineer", "test engineer",
    "ui developer", "ui/ux designer", "cloud engineer", "sde",
]

_SKILL_WORDS = [
    "python", "javascript", "typescript", "react", "next.js", "node.js", "node",
    "fastapi", "django", "flask", "sql", "postgres", "postgresql", "mysql",
    "mongodb", "redis", "docker", "kubernetes", "aws", "gcp", "azure",
    "langchain", "llm", "openai", "pytorch", "tensorflow", "pandas", "numpy",
    "tailwind", "graphql", "rest", "git", "ci/cd", "playwright", "selenium",
    "java", "go", "rust", "c++", "kotlin", "swift", "flutter", "react native",
    "html", "css", "express", "nestjs", "spring", "redux", "prisma", "supabase",
    "firebase", "rabbitmq", "qdrant", "neo4j", "zod", "jwt", "nginx", "linux",
]

_CITIES = [
    "bengaluru", "bangalore", "mumbai", "delhi", "new delhi", "noida", "gurgaon",
    "gurugram", "hyderabad", "pune", "chennai", "kolkata", "ahmedabad", "jaipur",
    "lucknow", "indore", "bhopal", "chandigarh", "kochi", "coimbatore", "nagpur",
    "dehradun", "haridwar", "roorkee", "meerut", "agra", "varanasi", "patna",
    "ranchi", "bhubaneswar", "visakhapatnam", "mysore", "surat", "vadodara",
    "thiruvananthapuram", "goa", "remote",
]

_COMPANY_HINTS = (
    "technologies", "technology", "labs", "solutions", "systems", "software",
    "inc", "llc", "ltd", "limited", "pvt", "corp", "consulting", "services",
    "infotech", "company", "studio", "group",
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_RE = re.compile(r"(\+?\d[\d\s\-()]{7,}\d)")
_MONTHS_RE = re.compile(r"(\d{1,3})\+?\s*(?:months?|mos?)\b", re.I)
_YEARS_RE = re.compile(r"(\d{1,2})(?:\.(\d))?\+?\s*(?:years?|yrs?)\b", re.I)
_URL_RE = re.compile(r"https?://[^\s)>\]]+", re.I)
_BARE_GITHUB_RE = re.compile(r"(?<![\w./])github\.com/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", re.I)
_BARE_LINKEDIN_RE = re.compile(r"(?<![\w./])linkedin\.com/in/[A-Za-z0-9_.-]+", re.I)
_MAILTO_RE = re.compile(r"mailto:([^\s)>\]]+)", re.I)

_MONTH_NUMBERS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DASH_CLASS = "-\u2013\u2014"
_PRESENT_RE = re.compile(
    r"(?P<start>(?:[A-Z][a-z]{2,8}\.?\s*)?\d{4})\s*[" + _DASH_CLASS + r"]\s*"
    r"(?P<end>present|current|now|till date|ongoing|today)",
    re.I,
)

_NAME_STOPWORDS = {
    "resume", "curriculum", "vitae", "cv", "profile", "contact", "email",
    "phone", "address", "summary", "objective", "skills", "experience",
}

_TECH_WORDS = (
    "software", "developer", "engineer", "programming", "python", "java",
    "javascript", "typescript", "react", "node", "api", "database", "sql",
    "cloud", "devops", "docker", "kubernetes", "data science", "machine learning",
    "frontend", "backend", "full stack", "web", "testing", "qa", "android", "ios",
)
_NON_TECH_WORDS = (
    "sales", "marketing", "human resources", "recruiter", "accounting", "finance",
    "legal", "nurse", "teaching", "teacher", "customer support", "content writing",
    "graphic design", "operations", "business development", "hospitality", "retail",
)


def _detect_domain(text: str) -> str:
    lowered = (text or "").lower()
    tech = sum(1 for word in _TECH_WORDS if word in lowered)
    non_tech = sum(1 for word in _NON_TECH_WORDS if word in lowered)
    if tech == 0 and non_tech == 0:
        return "tech"
    return "tech" if tech >= non_tech else "non-tech"


# ------------------------------------------------------------------- helpers

def _clean_url(url: str) -> str:
    url = url.strip().rstrip(".,;)]}")
    url = url.replace("https://", "").replace("http://", "")
    url = re.sub(r"^www\.", "", url, flags=re.I)
    return url.rstrip("/")


def _fix_kerning(text: str) -> str:
    """Repair PDF kerning artefacts like 'T echnologies' or 'F rontend'."""
    fixed = re.sub(r"\b([A-Z]) ([a-z]{2,})", r"\1\2", text)
    return re.sub(r"\s{2,}", " ", fixed).strip()


def _parse_month_year(value: str) -> tuple[int, int] | None:
    text = (value or "").strip()
    year_match = re.search(r"(\d{4})", text)
    if not year_match:
        return None
    year = int(year_match.group(1))
    month = 1
    month_match = re.search(r"([A-Za-z]{3,9})", text)
    if month_match:
        month = _MONTH_NUMBERS.get(month_match.group(1)[:4].lower()[:3], 1)
    return year, month


def _months_since(year: int, month: int, now: datetime) -> int:
    months = (now.year - year) * 12 + (now.month - month)
    return max(0, min(months, 600))


def _seniority_for(months: int) -> str:
    return "experienced" if months >= 12 else "fresher"


def format_experience(months: int) -> str:
    """4 -> '4 mo', 18 -> '1 yr 6 mo', 24 -> '2 yrs'."""
    months = max(0, int(months or 0))
    years, remainder = divmod(months, 12)
    parts: list[str] = []
    if years:
        parts.append(f"{years} yr{'s' if years != 1 else ''}")
    if remainder:
        parts.append(f"{remainder} mo")
    return " ".join(parts) or "no professional experience"


# -------------------------------------------------------------- extractors

def _guess_name(resume: str) -> str:
    for raw in resume.splitlines()[:12]:
        line = raw.replace("\ufeff", "").strip().strip("|\u2022-\u2014").strip()
        if not line or len(line) > 60:
            continue
        lowered = line.lower()
        if any(word in lowered for word in _NAME_STOPWORDS):
            continue
        if "@" in line or "http" in lowered or any(ch.isdigit() for ch in line):
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-z.'-]+", w) for w in words):
            return " ".join(words)
    return ""


def _guess_location(resume: str) -> str:
    # "City, State" style is the strongest signal.
    pattern = re.compile(r"^[A-Z][A-Za-z .'-]{2,30},\s*[A-Z][A-Za-z .'-]{2,30}$")
    for raw in resume.splitlines()[:25]:
        line = raw.strip()
        if pattern.match(line) and "http" not in line.lower():
            return line

    lowered = resume.lower()
    for city in _CITIES:
        if re.search(rf"\b{re.escape(city)}\b", lowered):
            return city.title()
    return ""


def _guess_experience_months(resume: str, now: datetime) -> int:
    # An explicit statement on the resume wins.
    months = 0
    years = 0
    year_matches = _YEARS_RE.findall(resume)
    if year_matches:
        whole, fraction = max(year_matches, key=lambda m: int(m[0]))
        years = int(whole)
        if fraction:
            months += round(int(fraction) / 10 * 12)
    month_matches = _MONTHS_RE.findall(resume)
    if month_matches:
        months += max(int(m) for m in month_matches)
    if years or months:
        return min(years * 12 + months, 600)

    # Otherwise use the ongoing role's date range.
    entry = _parse_current_entry(resume, now)
    if entry and entry.get("months"):
        return int(entry["months"])
    return 0


def _split_company_role(text: str) -> tuple[str, str]:
    text = _fix_kerning(text).strip(" " + _DASH_CLASS + "|,:")

    for separator in (" - ", " \u2013 ", " \u2014 ", " | ", " @ ", " at "):
        if separator in text:
            left, right = text.split(separator, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                return left, right

    if "," in text:
        left, right = text.rsplit(",", 1)
        if left.strip() and right.strip():
            return left.strip(), right.strip()

    lowered = text.lower()
    if any(hint in lowered for hint in _COMPANY_HINTS):
        return text, ""
    return "", text


def _parse_current_entry(resume: str, now: datetime) -> dict | None:
    lines = [line.strip() for line in resume.splitlines() if line.strip()]

    for index, line in enumerate(lines):
        match = _PRESENT_RE.search(line)
        if not match:
            continue

        start = _parse_month_year(match.group("start"))
        if not start:
            continue

        head = line[: match.start()].strip(" " + _DASH_CLASS + "|,:")

        # The role sometimes sits on the following line.
        if not head and index + 1 < len(lines):
            head = lines[index + 1].strip()

        company, role = _split_company_role(head)

        if not role and index + 1 < len(lines):
            candidate = lines[index + 1].strip()
            if candidate and not _PRESENT_RE.search(candidate) and len(candidate) < 90:
                role = _fix_kerning(candidate)

        if not company and role:
            # "Software Engineering Internship" style lines have no company.
            company = ""

        months = _months_since(start[0], start[1], now)
        return {"company": company, "role": role, "months": months}

    return None


def _guess_links(resume: str) -> dict:
    raw_urls = _URL_RE.findall(resume)
    raw_urls += _BARE_GITHUB_RE.findall(resume)
    raw_urls += _BARE_LINKEDIN_RE.findall(resume)

    emails = _MAILTO_RE.findall(resume)
    urls = [_clean_url(u) for u in raw_urls]
    for email in emails:
        urls.append(_clean_url(f"mailto:{email}"))

    github = [u for u in urls if "github.com" in u.lower() and u.lower().startswith("github.com")]
    linkedin = [u for u in urls if "linkedin.com/in/" in u.lower()]

    # A profile URL has one path segment; repo links have two.
    def path_depth(url: str) -> int:
        return len([part for part in url.split("/") if part])

    github.sort(key=path_depth)

    portfolio_candidates = [
        u
        for u in urls
        if "github.com" not in u.lower()
        and "linkedin.com" not in u.lower()
        and not u.lower().startswith("mailto:")
    ]
    portfolio_candidates.sort(
        key=lambda u: (
            0 if "portfolio" in u.lower() else 1,
            0 if any(host in u.lower() for host in (".vercel.app", ".netlify.app", ".dev", ".me")) else 1,
            path_depth(u),
        )
    )

    return {
        "github": github[0] if github else "",
        "portfolio": portfolio_candidates[0] if portfolio_candidates else "",
        "linkedin": _clean_url(linkedin[0]) if linkedin else "",
    }


def _guess_skills(resume: str) -> list[str]:
    lower = resume.lower()
    found = [word for word in _SKILL_WORDS if word in lower]
    # "node" is noise when "node.js" was found; "sql" when "postgresql" was.
    skills: list[str] = []
    for word in found:
        if any(word != other and word in other for other in found):
            continue
        if word not in skills:
            skills.append(word)
    return skills[:20]


def _derive_job_title(resume: str, current_role: str, skills: list[str]) -> str:
    role = (current_role or "").strip()
    if role and not any(word in role.lower() for word in ("intern", "trainee", "student")):
        return role

    lower = resume.lower()
    front = any(w in lower for w in ("react", "next.js", "vue", "angular", "frontend", "front-end", "tailwind"))
    back = any(w in lower for w in ("node", "nestjs", "express", "backend", "back-end", "django", "fastapi", "spring"))
    if front and back:
        return "Full Stack Developer"
    if front:
        return "Frontend Developer"
    if back:
        return "Backend Developer"

    lowered_skills = " ".join(skills).lower()
    if "python" in lowered_skills:
        return "Python Developer"
    return "Software Engineer"


def _fallback(resume: str) -> dict:
    now = datetime.now(timezone.utc)
    entry = _parse_current_entry(resume, now)
    current_company = (entry or {}).get("company", "")
    current_role = (entry or {}).get("role", "")
    months = _guess_experience_months(resume, now)
    skills = _guess_skills(resume)
    title = _derive_job_title(resume, current_role, skills)

    email = _EMAIL_RE.search(resume)
    phone = _PHONE_RE.search(resume)

    return {
        "full_name": _guess_name(resume),
        "email": email.group(0) if email else "",
        "phone": phone.group(1).strip() if phone else "",
        "location": _guess_location(resume),
        "links": _guess_links(resume),
        "skills": skills,
        "job_title": title,
        "target_roles": [],
        "current_company": current_company,
        "current_role": current_role,
        "experience_months": months,
        "seniority": _seniority_for(months),
        "domain": _detect_domain(f"{resume} {current_role} {' '.join(skills)}"),
    }


def extract_profile(resume_text: str) -> dict:
    text = (resume_text or "").strip()
    if not text:
        raise ValueError("resume text is empty")

    try:
        data = complete_json(SYSTEM, PROMPT.format(resume=text[:12000]), temperature=0.1, max_tokens=1000)
        if not isinstance(data, dict):
            raise LLMUnavailable("model did not return an object")
    except Exception as exc:  # noqa: BLE001 - fallback is intentional
        logger.info("profile extraction falling back to rules: %s", exc)
        data = _fallback(text)

    # One experience bucket only: fresher (< 12 months) or experienced.
    try:
        months = max(0, int(data.get("experience_months") or 0))
    except (TypeError, ValueError):
        months = 0
    data["experience_months"] = months
    data["seniority"] = _seniority_for(months)
    return data


# ---------------------------------------------------------------- file input

def _pdf_text_and_links(raw: bytes) -> tuple[str, list[str]]:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()

    links: list[str] = []
    for page in reader.pages:
        annotations = page.get("/Annots") or []
        for annotation in annotations:
            try:
                obj = annotation.get_object()
                action = obj.get("/A")
                if not action:
                    continue
                uri = action.get_object().get("/URI")
                if uri:
                    links.append(str(uri))
            except Exception:  # noqa: BLE001 - malformed annotation
                continue

    return text, list(dict.fromkeys(links))


def read_resume_file(filename: str, raw: bytes) -> str:
    """Extract plain text from a .pdf, .docx, or .txt/.md upload.

    PDF hyperlinks are appended under a ``Links:`` section so the parser (and
    the LLM) can see GitHub/LinkedIn/portfolio URLs that are not in the text.
    """
    name = (filename or "").lower()

    if name.endswith(".pdf"):
        text, links = _pdf_text_and_links(raw)
        if links:
            text = f"{text}\n\nLinks:\n" + "\n".join(links)
        return text

    if name.endswith(".docx"):
        import io

        from docx import Document

        doc = Document(io.BytesIO(raw))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.extend(cell.text for cell in row.cells)
        return "\n".join(p for p in parts if p).strip()

    if name.endswith((".txt", ".md", ".rtf")):
        return raw.decode("utf-8-sig", errors="ignore").strip()

    raise ValueError("unsupported file type - upload a PDF, DOCX, TXT or MD resume")

