"""Store uploaded resumes on disk so they can be attached to emails."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "resumes"
ALLOWED = {".pdf", ".docx", ".txt", ".md"}
MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def save(filename: str, raw: bytes) -> str:
    """Write one resume to disk under a unique name."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED:
        suffix = ".pdf"

    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(filename or "resume").stem)[:50] or "resume"
    path = DATA_DIR / f"resume_{safe_stem}_{uuid.uuid4().hex[:8]}{suffix}"
    path.write_bytes(raw)
    return str(path)


def read(path: str) -> tuple[bytes, str] | None:
    if not path:
        return None
    file = Path(path)
    if not file.exists():
        return None
    return file.read_bytes(), file.name


def delete(path: str) -> None:
    if not path:
        return
    Path(path).unlink(missing_ok=True)
