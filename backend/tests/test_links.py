"""Application-link validation: dead, empty and non-job pages."""

from __future__ import annotations

from app.services import link_check


def test_video_and_homepage_links_are_dead():
    assert link_check.dead_reason(
        "<html></html>", "a" * 300, "https://www.youtube.com/watch?v=abc"
    )
    assert link_check.dead_reason("<html></html>", "b" * 300, "https://jobs.comcast.com/")
    assert link_check.dead_reason("<html></html>", "c" * 300, "https://smarthub.ai")


def test_expired_job_page_is_dead():
    text = "This job has expired. The position is no longer available."
    assert link_check.dead_reason("<html></html>", text * 5, "https://acme.com/job/1")


def test_ats_job_pages_are_not_called_empty():
    assert (
        link_check.dead_reason(
            "<html></html>",
            "short",
            "https://ptc.wd1.myworkdayjobs.com/en-US/PTC/job/x",
        )
        == ""
    )
    assert (
        link_check.dead_reason(
            "<html></html>", "short", "https://boards.greenhouse.io/acme/jobs/123"
        )
        == ""
    )


def test_page_experience_is_parsed():
    assert link_check.page_experience_months("Requires 5+ years of experience") == 60
    assert link_check.page_experience_months("1-3 years experience") == 12
    assert link_check.page_experience_months("No experience required, freshers welcome") == 0
