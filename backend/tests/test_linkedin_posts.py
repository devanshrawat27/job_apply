"""LinkedIn hiring posts: RSC parsing and the individual-hirer filter."""

from __future__ import annotations

import json

from app.agents import linkedin_post_filter
from app.models import Profile
from app.services import linkedin_posts


def rsc_line(identifier: str, value: object) -> str:
    return f"{identifier}:{json.dumps(value)}"


def profile() -> Profile:
    return Profile(
        id=1,
        full_name="Dev Rawat",
        domain="tech",
        seniority="junior",
        experience_months=6,
        skills=["python", "react", "node.js"],
        target_roles=["python developer", "react developer", "full stack developer"],
        current_role="SDE Intern",
        country="India",
        location="Dehradun",
        willing_to_relocate=True,
    )


def test_rsc_posts_are_parsed():
    text = [
        rsc_line(
            "1",
            {
                "legacyControlName": "commentary_text",
                "children": [
                    "$",
                    "$L13b",
                    None,
                    {
                        "textProps": {
                            "children": [
                                [
                                    "$",
                                    "$5",
                                    "text-attr-0",
                                    {
                                        "children": [
                                            [
                                                None,
                                                [
                                                    [
                                                        "$",
                                                        "$5",
                                                        "0",
                                                        {
                                                            "children": [
                                                                None,
                                                                "Hiring designers in Berlin! We need a senior product designer.",
                                                            ]
                                                        },
                                                    ]
                                                ],
                                            ],
                                            ["$", "span", None, {"children": " "}],
                                        ],
                                    },
                                ]
                            ]
                        },
                    },
                ],
            },
        ),
        rsc_line(
            "2",
            {
                "actorName": "Jane Doe",
                "messagingFeedUpdateUrn": {
                    "valueActivityUrn": {"activityUrn": {"activityId": "7000000000000000001"}}
                },
                "postSlugUrl": (
                    "https://www.linkedin.com/posts/jane-doe_hiring-designers-"
                    "activity-7000000000000000001-AbCd"
                ),
            },
        ),
    ]
    posts = linkedin_posts.parse_rsc_posts("\n".join(text))
    assert len(posts) == 1
    post = posts[0]
    assert "Hiring designers in Berlin" in post["content"]
    assert post["author_name"] == "Jane Doe"
    assert post["author_profile_url"] == "https://www.linkedin.com/in/jane-doe/"
    assert post["post_url"].endswith("activity-7000000000000000001-AbCd")
    assert post["post_id"] == "7000000000000000001"


def test_legacy_rsc_shape_is_parsed():
    text = [
        rsc_line(
            "1",
            {
                "legacyControlName": "commentary_text",
                "children": "Legacy response about product design hiring.",
            },
        ),
        rsc_line(
            "2",
            {
                "postUrl": "https://www.linkedin.com/feed/update/urn:li:ugcPost:7000000000000000002/",
                "urn": "urn:li:ugcPost:7000000000000000002",
            },
        ),
    ]
    posts = linkedin_posts.parse_rsc_posts("\n".join(text))
    assert len(posts) == 1
    assert "Legacy response" in posts[0]["content"]
    assert posts[0]["post_id"] == "7000000000000000002"


def test_individual_hiring_post_passes():
    post = {
        "content": (
            "We are hiring 4 React developers at Acme Labs. Remote, 0-2 years welcome. "
            "Apply with your resume or comment below."
        ),
        "author_name": "Jane Doe",
        "author_profile_url": "https://www.linkedin.com/in/jane-doe/",
        "post_url": "https://www.linkedin.com/feed/update/urn:li:activity:1/",
    }
    verdict = linkedin_post_filter.assess(profile(), post)
    assert verdict["ok"] is True, verdict["reason"]
    assert verdict["individual"] is True
    assert verdict["high_volume"] is True
    assert verdict["relevance"] >= 40


def test_company_page_and_community_posts_are_rejected():
    company = {
        "content": "We are hiring React developers at Acme. Apply now.",
        "author_name": "Acme Technologies Pvt Ltd",
        "author_profile_url": "https://www.linkedin.com/company/acme/",
    }
    verdict = linkedin_post_filter.assess(profile(), company)
    assert verdict["ok"] is False
    assert "company page" in verdict["reason"]

    community = {
        "content": "Hiring React developers! Follow for more job updates.",
        "author_name": "Jane Doe",
        "author_profile_url": "https://www.linkedin.com/in/jane-doe/",
    }
    verdict = linkedin_post_filter.assess(profile(), community)
    assert verdict["ok"] is False


def test_job_seeker_and_stack_mismatch_are_rejected():
    seeker = {
        "content": "I am looking for a job as a React developer. Please refer me.",
        "author_name": "Jane Doe",
        "author_profile_url": "https://www.linkedin.com/in/jane-doe/",
    }
    assert linkedin_post_filter.assess(profile(), seeker)["ok"] is False

    stack = {
        "content": "We are hiring SAP ABAP developers at Acme. Apply now.",
        "author_name": "Jane Doe",
        "author_profile_url": "https://www.linkedin.com/in/jane-doe/",
    }
    verdict = linkedin_post_filter.assess(profile(), stack)
    assert verdict["ok"] is False
    assert "SAP" in verdict["reason"] or "target roles" in verdict["reason"]


def test_post_without_hiring_signal_is_rejected():
    chatter = {
        "content": "Had a great chat about React today. Thoughts?",
        "author_name": "Jane Doe",
        "author_profile_url": "https://www.linkedin.com/in/jane-doe/",
    }
    assert linkedin_post_filter.assess(profile(), chatter)["ok"] is False
