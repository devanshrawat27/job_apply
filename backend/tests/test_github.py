"""GitHub link parsing and profile summary building (offline)."""

from __future__ import annotations

from app.services import github_profile


def test_username_from_variants():
    assert github_profile.username_from("https://github.com/example-user") == "example-user"
    assert github_profile.username_from("github.com/example-user/") == "example-user"
    assert github_profile.username_from("example-user") == "example-user"
    assert github_profile.username_from("https://github.com/example-user/repo") == "example-user"
    assert github_profile.username_from("") == ""
    assert github_profile.username_from("https://example.com/x") == ""


def test_summary_uses_real_repos_not_forks():
    user = {
        "login": "dev",
        "name": "Dev",
        "bio": "Full stack developer",
        "public_repos": 3,
        "followers": 5,
        "html_url": "https://github.com/dev",
        "updated_at": "2026-11-13T10:00:00Z",
    }
    repos = [
        {"name": "jobpilot", "language": "TypeScript", "stargazers_count": 12, "fork": False,
         "description": "Job agent", "html_url": "https://github.com/dev/jobpilot", "topics": ["ai"]},
        {"name": "api", "language": "Python", "stargazers_count": 3, "fork": False,
         "description": "Backend", "html_url": "https://github.com/dev/api", "topics": []},
        {"name": "forked", "language": "Go", "stargazers_count": 999, "fork": True,
         "description": "not mine", "html_url": "", "topics": []},
    ]

    summary, data = github_profile._build_summary(user, repos)
    assert data["login"] == "dev"
    assert data["stars"] == 15  # fork's stars excluded
    assert data["languages"] == ["TypeScript", "Python"]
    assert [p["name"] for p in data["projects"]] == ["jobpilot", "api"]
    assert "jobpilot" in summary
    assert "forked" not in summary
    assert "12" in summary
