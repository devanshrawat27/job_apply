"""Composer: draft the public reply and the personal DM.

Two things matter here:

1. **Never generic.** Every message must reference something concrete from the
   post (the role, the company, the stack they listed, or the specific problem).
   `is_generic()` checks that after drafting and the pipeline forces a human
   review when it is not specific.

2. **It learns from you.** Messages you approved (often after editing) are fed
   back as style examples, so the drafts start sounding like you instead of a
   template.
"""

from __future__ import annotations

import logging
import re

from app.agents.resume import format_experience
from app.llm import LLMUnavailable, complete_json
from app.models import JobPost, Profile

logger = logging.getLogger(__name__)

SYSTEM = """You write outreach for a job seeker on X (Twitter).

Hard rules:
- Never invent experience, companies, degrees or metrics that are not in the profile.
- Every message must reference a CONCRETE detail from the post: the role, the
  company, the product, the stack they listed, or the problem they described.
  A message that could be copy-pasted under any other hiring post is a failure.
- The public reply must be useful on its own, specific to THIS post, and under 260 characters.
- Never claim you sent a DM, and never say "my DMs are open". The reply must
  stand alone even if no DM is sent.
- No links, no hashtags, no emoji spam in the public reply.
- The DM is personal: 3 short lines. Name the exact stack/domain detail from
  the post, connect it to hands-on experience in that stack/domain, then ask one
  specific question about the role or team. Include the candidate's portfolio or
  GitHub link once.
- NEVER name a specific project, product, client, repository, or side project.
  Talk about the technology/domain ("event-driven Node services", "Postgres
  reporting pipelines"), not "my project X".
- Show effort: the message should prove the post was read (a responsibility, a
  stack choice, a constraint), not just restate the job title.
- Sound like a person, not a recruiter. No "I hope this message finds you well",
  no "I am writing to express my interest", no "I came across your post".
- Return strict JSON only.
"""

PROMPT = """CANDIDATE
name: {name}
looking for: {roles}
level: {seniority}, experience: {experience}
current role: {current_role} at {current_company}
skills: {skills}
links: {links}
about: {pitch}
github: {github}
tone: {tone}
country: {country}
work authorization: {work_authorization}
graduation year: {graduation_year}
willing to relocate: {relocate}

JOB POST
author: @{author}
company: {company}
role: {role}
location: {job_location}
how to apply: {apply_method} {contact}
text:
---
{content}
---

{match_note}
{followup_note}
{redraft_note}

{examples}
Return JSON:
{{
  "eligible": true,
  "eligibility_reason": "why the candidate cannot qualify, or empty",
  "reply_text": "the public reply, under 260 chars",
  "dm_text": "the DM, max 600 chars, 3 short lines",
  "used_detail": "the exact stack/domain phrase from the post you referenced",
  "confidence": 0.0,
  "uncertainties": ["specific reasons you are not sure this is the right move"]
}}

DM quality bar (this is what humans judge):
  - Line 1: the exact stack/domain/responsibility from the post, in your own words.
  - Line 2: how you work with that stack/domain today, without naming a project.
  - Line 3: one specific question about the role/team + availability, then the link.
  - No project names, product names, client names, or "I built <thing>".
  - Pick one or two technologies the post actually cares about. Do not list five skills.
  - Do not restate the job title. Do not open with "I saw your post" or "I'm interested".

eligibility (do this FIRST):
  Check the post against the candidate above. Set "eligible": false and fill
  "eligibility_reason" when any of these is true:
  - it requires citizenship, a work permit/visa, or a security clearance the
    candidate does not have
  - it needs more experience than the candidate has
  - it is a senior/staff/lead role and the candidate is early-career
  - the role is outside the candidate's target roles and skills
  - it needs a graduation batch or student status the candidate does not match
  When the post states such a requirement and the candidate's data is unknown,
  treat it as NOT eligible. When not eligible, leave both texts empty.
  Otherwise set "eligible": true.

confidence guidance:
  0.9-1.0  the post clearly hires for a role the candidate matches, contact is obvious
  0.7-0.89 good match but one detail is ambiguous (seniority, location, how to apply)
  0.4-0.69 partial match, or the post may be stale/spam
  0.0-0.39 do not contact
"""

EXAMPLES_HEADER = """STYLE EXAMPLES (approved by the candidate - match this voice, not the wording):

"""

RETRY_NOTE = """
IMPORTANT: your previous draft was too generic. This time you MUST quote or
name one exact thing from the post (the company, a technology they listed, the
product, or the problem) in BOTH the reply and the DM. Do not write anything
that could be pasted under another hiring post.
"""

REDRAFT_NOTE = """REDRAFT REQUEST: the candidate read the previous draft and it was too simple.
Write a noticeably better one from scratch:
- Do not reuse the previous opening sentence, structure or wording.
- Name one exact stack/domain detail from the post and connect it to hands-on
  experience in that stack/domain. No project names, products or clients.
- Show that you read the responsibilities: mention one specific thing the role
  owns ("background jobs", "reporting pipelines", "design-system work").
- End with a sharper question about the team/role, not "can I send my resume".
Previous draft:
---
{previous}
---
"""

PROJECT_NOTE = """
IMPORTANT: do not mention any project, side project, repository, product or
client by name. Talk only about the stack/domain and the work you do with it.
Also make the message specific to this post.
"""

_PROJECT_RE = re.compile(
    r"\b(projects?|side project|repository|repo|portfolio project|built an app)\b",
    re.I,
)

# Posts with these signals are never auto-sent, no matter what the model says.
BLOCKERS = (
    "unpaid",
    "no pay",
    "commission only",
    "commission-only",
    "equity only",
    "equity-only",
    "internship unpaid",
    "pay to apply",
    "registration fee",
)

_STOPWORDS = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will", "have",
    "this", "that", "from", "they", "them", "who", "what", "when", "where",
    "hiring", "looking", "apply", "please", "role", "job", "team", "work",
    "more", "about", "into", "also", "been", "their", "would", "could",
}


def _short(text: str, limit: int) -> str:
    text = re.sub(r"[ \t]+", " ", (text or "").strip())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


def _specific_tokens(post: JobPost) -> set[str]:
    """Words that make a message specific to this post."""
    tokens: set[str] = set()

    for value in (post.role, post.company, post.author_handle):
        if value:
            tokens.add(str(value).lower().strip())

    for word in re.findall(r"[A-Za-z][A-Za-z0-9.+#-]{2,}", post.content or ""):
        lowered = word.lower()
        if lowered in _STOPWORDS or len(lowered) < 3:
            continue
        tokens.add(lowered)

    return tokens


def is_generic(text: str, post: JobPost) -> bool:
    """True when the draft could be pasted under any other hiring post."""
    body = (text or "").lower()
    if len(body) < 20:
        return True
    return not any(token in body for token in _specific_tokens(post) if len(token) >= 4)


def _link_line(profile: Profile) -> str:
    links = profile.links or {}
    portfolio = (links.get("portfolio") or "").strip()
    github = (links.get("github") or "").strip()
    parts = [link for link in (portfolio, github) if link]
    return " · ".join(parts[:2])


def _fallback(profile: Profile, post: JobPost) -> dict:
    """Deterministic, deliberately low confidence -> goes to approval."""
    role = post.role or "this role"
    company = post.company or ""
    target = f"{role} at {company}" if company else role

    # A skill the post itself mentions and the candidate also has.
    post_text = (post.content or "").lower()
    shared = [skill for skill in (profile.skills or []) if skill and skill.lower() in post_text]

    stack = ", ".join(shared[:3]) or ", ".join((profile.skills or [])[:3]) or "this stack"

    if profile.current_role:
        proof = f"I'm currently {profile.current_role}" + (
            f" at {profile.current_company}" if profile.current_company else ""
        )
        proof += f", working with {stack} day to day."
    elif profile.pitch:
        proof = profile.pitch
    elif profile.skills:
        proof = f"I work with {stack} day to day."
    else:
        proof = "I build software."

    reply = _short(
        f"You're hiring for {target} \u2014 I work with {stack} day to day, "
        f"so this is a strong fit. Happy to talk about the role.",
        250,
    )

    dm_lines = [f"Hi \u2014 your {target} post mentions {stack}.", proof]
    link = _link_line(profile)
    if link:
        dm_lines.append(link)
    shared_skill = shared[0] if shared else ""
    question = (
        f"How is the team set up around {shared_skill}?"
        if shared_skill
        else "Would you be open to a short chat about the role this week?"
    )
    dm_lines.append(question)

    return {
        "eligible": True,
        "eligibility_reason": "",
        "reply_text": reply,
        "dm_text": _short("\n".join(dm_lines), 600),
        "used_detail": f"{role}" if not company else f"{role} at {company}",
        "confidence": 0.35,
        "uncertainties": ["template draft (LLM unavailable) - please review"],
        "template": True,
    }


def _style_examples(examples: list | None) -> str:
    if not examples:
        return ""
    blocks = []
    for example in examples[:3]:
        block = []
        if example.reply_text:
            block.append(f"reply: {example.reply_text}")
        if example.dm_text:
            block.append(f"dm: {example.dm_text}")
        if block:
            blocks.append("\n".join(block))
    if not blocks:
        return ""
    return EXAMPLES_HEADER + "\n\n".join(blocks) + "\n\n"


def _match_note(post: JobPost) -> str:
    """Extra instruction when the post is a very close match for the candidate."""
    relevance = int(post.relevance or 0)
    if relevance >= 80:
        return (
            "MATCH LEVEL: very high. This post closely matches the candidate's role. "
            "In BOTH the reply and the DM, name TWO exact requirements from the post "
            "(specific stack, product, or problem) and map each to the candidate's "
            "hands-on experience in that stack/domain. Do not name a project or client. "
            "Be concrete - no generic enthusiasm, no restating the job title back at them."
        )
    if relevance >= 60:
        return (
            "MATCH LEVEL: good. Reference one exact requirement from the post and tie it "
            "to real hands-on experience in that stack/domain. Do not name a project."
        )
    return ""


def _followup_note(follow_up: int) -> str:
    if follow_up <= 0:
        return ""
    return (
        f"FOLLOW-UP: this is DM #{follow_up + 1} to this person on a newer post. They did not "
        "reply to the earlier one. Do NOT repeat the introduction, your current role, or your "
        "links. Write 1-2 short lines that reference ONE new concrete detail from THIS post, "
        "add one new proof point, and end with a short question. Keep it under 320 chars."
    )


def _redraft_note(previous: str | None) -> str:
    text = " ".join((previous or "").split())
    if not text:
        return ""
    return REDRAFT_NOTE.format(previous=_short(text, 800))


def compose(
    profile: Profile,
    post: JobPost,
    examples: list | None = None,
    *,
    budget_s: float | None = None,
    follow_up: int = 0,
    previous: str | None = None,
    providers: list[dict] | None = None,
    browser_fallback: bool = False,
    browser_user_id: int | None = None,
) -> dict:
    if not _llm_ready():
        return _apply_safety(post, _fallback(profile, post))

    prompt = PROMPT.format(
        name=profile.full_name or "the candidate",
        roles=", ".join([profile.job_title, *(profile.target_roles or [])]).strip(", "),
        seniority=profile.seniority or "",
        experience=format_experience(profile.experience_months),
        current_role=profile.current_role or "not stated",
        current_company=profile.current_company or "",
        skills=", ".join((profile.skills or [])[:12]),
        links=profile.links or {},
        pitch=profile.pitch or "not provided",
        github=profile.github_summary or "not linked",
        tone=profile.tone or "friendly-professional",
        country=getattr(profile, "country", "") or "not stated",
        work_authorization=getattr(profile, "work_authorization", "") or "not stated",
        graduation_year=getattr(profile, "graduation_year", 0) or "not stated",
        relocate="yes" if getattr(profile, "willing_to_relocate", True) is not False else "no",
        author=post.author_handle,
        company=post.company or "",
        role=post.role or "",
        job_location=post.job_location or "",
        apply_method=post.outreach_method or post.apply_method or "unknown",
        contact=post.contact_email or post.contact or "",
        content=(post.content or "")[:1200],
        examples=_style_examples(examples),
        match_note=_match_note(post),
        followup_note=_followup_note(follow_up),
        redraft_note=_redraft_note(previous),
    )

    result: dict | None = None
    for attempt in range(2):
        if attempt == 0:
            user_prompt = prompt
        elif result and result.get("mentions_project"):
            user_prompt = prompt + PROJECT_NOTE
        else:
            user_prompt = prompt + RETRY_NOTE
        try:
            data = complete_json(
                SYSTEM,
                user_prompt,
                temperature=0.6 if attempt == 0 else 0.75,
                max_tokens=650,
                budget_s=budget_s,
                providers=providers,
            )
        except LLMUnavailable as exc:
            # No API key/health? Use the logged-in ChatGPT browser instead of
            # falling back to a template. The window is visible while it writes.
            data = None
            if browser_fallback:
                try:
                    from app.services import browser_chatgpt

                    logger.info("composer: API LLM unavailable (%s), using browser ChatGPT", exc)
                    data = browser_chatgpt.ask_json(
                        SYSTEM, user_prompt, user_id=browser_user_id,
                        purpose="draft", timeout=150,
                    )
                except Exception as browser_exc:  # noqa: BLE001
                    logger.warning("composer browser ChatGPT failed: %s", browser_exc)
            if data is None:
                logger.warning("composer fell back to template: %s", exc)
                break
        if not isinstance(data, dict):
            break

        result = _build_result(profile, post, data)
        if not result["generic"] and not result.get("mentions_project"):
            break
        logger.info("draft was generic or mentioned a project, retrying once")

    if result is None:
        return _apply_safety(post, _fallback(profile, post))
    return _apply_safety(post, result)


def _build_result(profile: Profile, post: JobPost, data: dict) -> dict:
    eligible = data.get("eligible", True) is not False
    result = {
        "eligible": eligible,
        "eligibility_reason": str(
            data.get("eligibility_reason") or data.get("reason") or ""
        )[:300],
        "reply_text": _short(str(data.get("reply_text", "")), 260),
        "dm_text": str(data.get("dm_text", "")).strip(),
        "used_detail": str(data.get("used_detail") or ""),
        "confidence": _clamp(data.get("confidence", 0.0)),
        "uncertainties": [str(u) for u in (data.get("uncertainties") or [])][:6],
    }

    if not eligible:
        # The model already decided this role is not for the candidate. Never
        # replace that with a template DM - the caller rejects the job.
        result.update({"reply_text": "", "dm_text": "", "confidence": 0.0, "generic": False})
        return result

    if not result["dm_text"]:
        fallback = _fallback(profile, post)
        result["dm_text"] = fallback["dm_text"]
        result["confidence"] = min(result["confidence"], 0.45)
        result["uncertainties"].append("composer produced no DM text")

    # The DM must carry both links when the profile has them.
    links = profile.links or {}
    wanted = [value for value in (links.get("portfolio"), links.get("github")) if value]
    lowered = result["dm_text"].lower()
    missing = [link for link in wanted if link.lower() not in lowered]
    if missing:
        result["dm_text"] = _short(
            result["dm_text"].rstrip() + "\n" + " \u00b7 ".join(missing),
            600,
        )

    result["generic"] = is_generic(result["reply_text"], post) and is_generic(
        result["dm_text"], post
    )
    result["mentions_project"] = bool(_PROJECT_RE.search(result["dm_text"]))
    return result


def _apply_safety(post: JobPost, result: dict) -> dict:
    """Deterministic overrides that apply to LLM and template drafts alike."""
    lowered = (post.content or "").lower()
    for phrase in BLOCKERS:
        if phrase in lowered:
            result["confidence"] = min(result["confidence"], 0.2)
            result["uncertainties"].append(f"post contains a red flag: {phrase}")
            break

    if len(result.get("dm_text", "")) > 900:
        result["dm_text"] = result["dm_text"][:900]
        result["uncertainties"].append("DM was truncated")

    # Specificity check: a draft that ignores the post must not auto-send.
    generic = is_generic(result.get("reply_text", ""), post) and is_generic(
        result.get("dm_text", ""), post
    )
    result["generic"] = generic
    if generic:
        result["confidence"] = min(result["confidence"], 0.45)
        result["uncertainties"].append("draft looks generic - it does not reference the post")

    result["mentions_project"] = bool(_PROJECT_RE.search(result.get("dm_text", "")))
    if result["mentions_project"]:
        # The candidate explicitly asked for no project names. Drop the sentence
        # that names one instead of sending it with a warning.
        pieces = re.split(r"(?<=[.!?])\s+|\n+", result.get("dm_text", ""))
        kept = [piece for piece in pieces if piece.strip() and not _PROJECT_RE.search(piece)]
        if kept:
            result["dm_text"] = _short(" ".join(kept), 600)
        result["confidence"] = min(result["confidence"], 0.5)
        result["uncertainties"].append("removed a project mention from the draft")

    return result


def _clamp(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _llm_ready() -> bool:
    from app.config import settings

    return settings.llm_enabled


def auto_reject_reason(uncertainties: list[str] | None) -> str:
    """A clear reason from the model that means: do not show this to a human.

    Commentary, resources, wrong-domain roles and roles the candidate cannot
    qualify for should be rejected, not parked in Approvals.
    """
    text = " ".join(str(item) for item in (uncertainties or [])).lower()
    markers = (
        "not an actual job",
        "not a job opening",
        "not a hiring post",
        "commentary",
        "opinion piece",
        "sharing a resource",
        "no company, role",
        "no specific hiring",
        "rather than a direct job",
        "not a direct job",
        "mismatch in job function",
        "not a software",
        "non-tech role",
        "non-technical",
        "civil",
        "public works",
        "different engineering",
        "senior-level",
        "senior role",
        "quantitative finance",
        "senior staff",
        "requires senior",
        "outside the candidate's",
        "candidate's profile contains no",
        "no documented",
        "does not match the candidate",
        "does not match candidate",
        "does not match your",
        "does not match the profile",
        "doesn't match the candidate",
        "candidate's background",
        "candidate lacks",
        "candidate does not have",
        "no experience with",
        "not in the candidate",
        "unrelated to the candidate",
        "poor fit",
        "not a fit",
        "academic role",
        "lecturing role",
        "lecturer role",
        "whereas the candidate",
        "different tech stack",
        "specific stack",
        "stack which",
    )
    for marker in markers:
        if marker in text:
            return marker
    return ""


def blockers_for(post: JobPost, result: dict) -> list[str]:
    """Extra reasons the pipeline must stop and ask a human."""
    blockers: list[str] = []
    if not post.author_handle:
        blockers.append("author handle missing")
    if not (result.get("dm_text") or "").strip():
        blockers.append("no DM draft")
    if result.get("generic"):
        blockers.append("draft is too generic")
    return blockers


