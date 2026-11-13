"""Fake / scam job post detection.

X is full of "earn ₹50,000/month from home, DM me" posts. This module scores a
post 0-100 using signals that real hiring posts almost never contain:

  * money asked from the candidate (fees, deposits, training charges)
  * off-platform contact (WhatsApp / Telegram / short links)
  * no concrete role, no company, "DM for details" only
  * unrealistic pay promises and shouting

The pipeline hard-rejects >= 60, and forces human approval for 40-59. A post can
never be auto-sent if it looks even slightly fake.
"""

from __future__ import annotations

import re

REJECT_THRESHOLD = 60
REVIEW_THRESHOLD = 40

# Asking the candidate for money is never a real job.
_HARD_SIGNALS: tuple[tuple[str, int, str], ...] = (
    ("registration fee", 45, "asks for a registration fee"),
    ("registration charge", 45, "asks for a registration charge"),
    ("pay to apply", 45, "asks you to pay to apply"),
    ("security deposit", 45, "asks for a security deposit"),
    ("refundable deposit", 45, "asks for a refundable deposit"),
    ("training fee", 40, "asks for a training fee"),
    ("processing fee", 40, "asks for a processing fee"),
    ("joining fee", 40, "asks for a joining fee"),
    ("send money", 40, "asks you to send money"),
    ("pay ₹", 35, "asks for a payment"),
    ("investment required", 35, "asks for an investment"),
    ("buy a laptop", 30, "asks you to buy equipment"),
)

_SOFT_SIGNALS: tuple[tuple[str, int, str], ...] = (
    ("dm for details", 14, "no details, only 'DM for details'"),
    ("dm me for details", 14, "no details, only 'DM for details'"),
    ("dm for more details", 14, "no details, only 'DM for details'"),
    ("no interview", 18, "no interview process"),
    ("direct joining", 18, "guaranteed direct joining"),
    ("no experience needed", 14, "no experience needed"),
    ("no experience required", 10, "no experience required"),
    ("any graduate", 8, "any graduate welcome"),
    ("work from home", 8, "work-from-home bait"),
    ("part time job", 10, "part-time bait"),
    ("earn up to", 12, "unrealistic earnings promise"),
    ("earn ₹", 12, "unrealistic earnings promise"),
    ("per day", 8, "daily-pay promise"),
    ("guaranteed income", 18, "guaranteed income"),
    ("urgent requirement", 6, "urgent requirement with no detail"),
    ("whatsapp", 18, "contact on WhatsApp"),
    ("telegram", 18, "contact on Telegram"),
    ("t.me/", 18, "Telegram link"),
    ("wa.me/", 18, "WhatsApp link"),
    ("bit.ly", 14, "shortened link"),
    ("tinyurl", 14, "shortened link"),
    ("click here", 8, "click-here link"),
    ("apply fast", 6, "pressure to apply fast"),
    ("limited seats", 10, "limited seats pressure"),
)

_ROLE_WORDS = (
    "developer", "engineer", "designer", "manager", "analyst", "intern",
    "scientist", "architect", "consultant", "specialist", "lead", "sde",
    "recruiter", "executive", "associate",
)

_COMPANY_WORDS = (
    "pvt", "ltd", "inc", "llp", "technologies", "labs", "solutions", "systems",
    "corp", "company", "startup", "foundation", "studio",
)

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]",
    flags=re.UNICODE,
)
_BOT_HANDLE_RE = re.compile(r"\d{6,}$")


def assess(text: str, author_handle: str = "") -> dict:
    """Return {"score": 0-100, "reasons": [...]}."""
    lowered = (text or "").lower()
    score = 0
    reasons: list[str] = []

    for phrase, weight, reason in _HARD_SIGNALS:
        if phrase in lowered:
            score += weight
            reasons.append(reason)

    for phrase, weight, reason in _SOFT_SIGNALS:
        if phrase in lowered:
            score += weight
            reasons.append(reason)

    if not any(word in lowered for word in _ROLE_WORDS):
        score += 12
        reasons.append("no concrete role named")

    if not any(word in lowered for word in _COMPANY_WORDS):
        score += 6

    letters = [ch for ch in text if ch.isalpha()]
    if letters:
        caps_ratio = sum(1 for ch in text if ch.isupper()) / len(letters)
        if caps_ratio > 0.5 and len(text) > 40:
            score += 8
            reasons.append("written in all caps")

    emojis = len(_EMOJI_RE.findall(text or ""))
    if emojis >= 6:
        score += 8
        reasons.append("emoji spam")

    if len(text or "") < 90 and "dm" in lowered:
        score += 8
        reasons.append("too short to be a real posting")

    handle = (author_handle or "").lstrip("@")
    if _BOT_HANDLE_RE.search(handle):
        score += 8
        reasons.append("handle looks generated")

    # Deduplicate while keeping order.
    seen: set[str] = set()
    unique = [reason for reason in reasons if not (reason in seen or seen.add(reason))]

    return {"score": min(100, score), "reasons": unique[:6]}
