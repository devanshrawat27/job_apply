"""The search query formula stays valid X syntax and actually returns posts.

Live testing showed exact phrase groups plus the level group returned 0 posts for
niche roles, so the query uses short intent words and relies on scoring for the
level/experience gate.
"""

from __future__ import annotations

from app.agents import keywords
from app.models import Profile


def test_query_has_role_intent_and_filters():
    query = keywords.build_query("Full Stack Developer", "fresher", "2026-11-10")
    assert len(query) <= keywords.MAX_QUERY_LEN
    assert '"Full Stack Developer"' in query
    assert "(hiring OR opening OR refer OR referral OR apply)" in query
    assert "-senior" in query
    assert "-filter:replies" in query
    assert "lang:en" in query
    assert "since:2026-11-10" in query


def test_query_does_not_force_a_level_group():
    query = keywords.build_query("founding engineer", "fresher", "2026-11-10")
    assert "(intern OR" not in query
    assert '"founding engineer"' in query


def test_single_word_keyword_stays_unquoted():
    query = keywords.build_query("react", "", "2026-11-10")
    assert "(react)" in query
    assert "(hiring" in query


def test_pool_includes_ai_and_startup_terms():
    pool = " ".join(keywords.keyword_pool()).lower()
    assert "ai engineer" in pool
    assert "agentic" in pool
    assert "founding engineer" not in pool


def test_senior_titles_are_kept_out_of_the_junior_pool():
    pool = " ".join(keywords.keyword_pool()).lower()
    assert "first technical hire" not in pool
    assert "staff engineer" not in pool
    assert "junior developer" in pool
    assert "entry level developer" in pool
    assert "sde intern" in pool
    assert "full stack intern" in pool


def test_vocabulary_keeps_new_hiring_and_referral_phrases():
    all_signals = set(keywords.HIRING_SIGNALS) | set(keywords.REFERRAL_SIGNALS)
    for phrase in (
        '"is hiring for"',
        '"looking to hire"',
        '"I\'m hiring"',
        '"opening for"',
        '"referrals open"',
        '"happy to refer"',
    ):
        assert phrase in all_signals


def test_fresher_level_words_are_known():
    # Still used by scoring and kept in the vocabulary, just not in the query.
    assert "intern" in keywords.LEVEL_FRESHER
    assert '"2027 batch"' in keywords.LEVEL_FRESHER
    assert '"new grad"' in keywords.LEVEL_FRESHER


def test_pool_includes_new_role_titles():
    pool = " ".join(keywords.keyword_pool()).lower()
    assert "sde intern" in pool
    assert "full stack intern" in pool
    assert "developer internship" in pool
    assert "graduate engineer trainee" in pool


def test_hiring_phrases_are_searchable_keywords():
    pool = {term.lower() for term in keywords.keyword_pool()}
    for phrase in ("we are hiring", "we're hiring", "now hiring", "hiring interns", "hiring freshers"):
        assert phrase in pool


def test_quoted_keyword_is_not_double_quoted():
    query = keywords.build_query('"software engineer"', "fresher", "2026-11-10")
    assert '""software engineer""' not in query
    assert '"software engineer"' in query


def test_fresher_query_negates_senior_titles():
    query = keywords.build_query("Full Stack Developer", "fresher", "2026-11-10")
    assert "-founding" in query
    assert "-staff" in query


def test_junior_keyword_filter():
    from app.agents import query_lab

    profile = Profile(id=1, seniority="fresher", experience_months=3, domain="tech")
    assert query_lab.keyword_fits_profile("full stack developer", profile) is True
    assert query_lab.keyword_fits_profile("sde intern", profile) is True
    assert query_lab.keyword_fits_profile("founding engineer", profile) is False
    assert query_lab.keyword_fits_profile("senior backend developer", profile) is False
    assert query_lab.keyword_fits_profile("first technical hire", profile) is False

    senior = Profile(id=2, seniority="senior", experience_months=72, domain="tech")
    assert query_lab.keyword_fits_profile("founding engineer", senior) is True
