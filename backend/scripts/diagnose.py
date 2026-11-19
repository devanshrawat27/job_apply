"""Why is the agent not finding jobs? Run this on the machine that runs JobPilot:

    .venv\\Scripts\\python.exe scripts\\diagnose.py

It prints the profile the agent is using, the X session, the last scans with
their real numbers, and the reasons posts were rejected.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow "python scripts/diagnose.py" from the backend folder.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AgentSettings,
    JobPost,
    Profile,
    Run,
    SearchQuery,
    User,
    XAccount,
)


def main() -> None:
    db = SessionLocal()
    try:
        users = list(db.scalars(select(User)).all())
        print("USERS:", [(u.id, u.email, u.is_active) for u in users] or "none (legacy mode)")

        profile = db.scalar(select(Profile).order_by(Profile.id))
        if profile is None:
            print("\nNO PROFILE: onboarding was never finished.")
            return

        uid = profile.user_id
        print("\nPROFILE")
        print(f"  user_id       : {uid}")
        print(f"  name          : {profile.full_name!r}")
        print(f"  job_title     : {profile.job_title!r}")
        print(f"  target_roles  : {profile.target_roles}")
        print(f"  seniority     : {profile.seniority!r} | experience: {profile.experience_months} months")
        print(f"  domain        : {profile.domain!r} | strict_fit: {profile.strict_fit}")
        print(f"  skills        : {(profile.skills or [])[:10]}")
        print(f"  avoid         : {profile.avoid}")
        print(f"  onboarded     : {profile.onboarding_completed}")

        settings_row = db.scalar(
            select(AgentSettings).where(
                AgentSettings.user_id == uid if uid is not None else AgentSettings.user_id.is_(None)
            )
        )
        if settings_row is None:
            print("\nNO SETTINGS ROW: the agent never started.")
        else:
            print("\nSETTINGS")
            print(
                f"  enabled={settings_row.enabled} scan_every={settings_row.scan_interval_minutes}min "
                f"gap={settings_row.min_minutes_between_writes}min "
                f"caps={settings_row.daily_reply_cap}/{settings_row.daily_dm_cap} "
                f"chatgpt_browser={settings_row.chatgpt_browser_enabled}"
            )

        account = db.scalar(
            select(XAccount).where(XAccount.user_id == uid)
            if uid is not None
            else select(XAccount).where(XAccount.user_id.is_(None))
        )
        print("\nX ACCOUNT:", account.username if account else "NOT CONNECTED")

        print("\nLAST RUNS")
        runs = list(
            db.scalars(
                select(Run)
                .where(Run.user_id == uid)
                .order_by(Run.id.desc())
                .limit(6)
            ).all()
        )
        for run in runs:
            stats = run.stats or {}
            print(f"  #{run.id} {run.kind:5} {run.status:9} {run.started_at}")
            if run.kind == "scan":
                print(
                    "      seen={} new={} relevant={} queued={} rejected={} keywords={}".format(
                        stats.get("posts_seen"),
                        stats.get("posts_new"),
                        stats.get("relevant"),
                        stats.get("queued"),
                        stats.get("rejected"),
                        stats.get("keywords"),
                    )
                )
            if run.error:
                print(f"      error: {run.error[:160]}")

        since = datetime.now(timezone.utc) - timedelta(days=3)
        rows = db.execute(
            select(JobPost.decision_reason, JobPost.status)
            .where(JobPost.user_id == uid, JobPost.discovered_at >= since)
        ).all()
        print("\nLAST 3 DAYS: posts by status:", dict(Counter(status for _, status in rows)) or "none")
        reasons = Counter((reason or "")[:90] for reason, status in rows if status == "rejected")
        print("TOP REJECTION REASONS")
        for reason, count in reasons.most_common(10):
            print(f"  {count:4}x {reason}")
        if not reasons:
            print("  (nothing rejected - either no posts arrived or the scan never ran)")

        keywords = list(
            db.scalars(
                select(SearchQuery)
                .where(SearchQuery.user_id == uid)
                .order_by(SearchQuery.score.desc())
                .limit(12)
            ).all()
        )
        print("\nKEYWORDS")
        for row in keywords:
            print(
                f"  {row.keyword!r:34} {row.status:9} uses={row.uses} "
                f"seen={row.posts_seen} relevant={row.posts_relevant} score={row.score:.2f}"
            )
        if not keywords:
            print("  none - the keyword lab never ran (no scan yet)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
