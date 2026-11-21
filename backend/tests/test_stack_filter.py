"""A role has to match the candidate's actual stack, not just the word "developer"."""

from __future__ import annotations

from app.agents import composer, discovery
from app.models import Profile


def profile(**overrides) -> Profile:
    values = {
        "full_name": "Dev Rawat",
        "domain": "tech",
        "current_role": "SDE Intern",
        "job_title": "Full Stack Developer",
        "skills": ["python", "react", "node.js", "postgresql"],
        "target_roles": ["python developer", "full stack developer"],
        "resume_text": "Built web apps with Python, React and PostgreSQL.",
    }
    values.update(overrides)
    return Profile(**values)


def test_sap_abap_role_is_rejected_for_a_web_developer():
    text = "WE ARE HIRING - SAP ABAP DEVELOPER. Candidates can comment Interested below."
    assert discovery.stack_mismatch(profile(), text)
    assert discovery.domain_mismatch(profile(), text)


def test_sap_as_a_company_name_is_not_a_stack_mismatch():
    text = "Software Engineer at SAP. Build web apps with React and Node.js."
    assert discovery.stack_mismatch(profile(), text) is None


def test_a_candidate_who_really_has_sap_is_not_blocked():
    text = "WE ARE HIRING - SAP ABAP DEVELOPER."
    with_sap = profile(skills=["python", "sap", "abap"], resume_text="SAP ABAP developer with 2 years.")
    assert discovery.stack_mismatch(with_sap, text) is None


def test_mainframe_and_salesforce_roles_are_rejected():
    assert discovery.stack_mismatch(profile(), "COBOL mainframe developer needed")
    assert discovery.stack_mismatch(profile(), "Salesforce developer with Apex experience")


def test_the_model_saying_it_does_not_match_is_an_auto_reject():
    reason = composer.auto_reject_reason(
        ["Role requires specific SAP ABAP stack which does not match candidate's background."]
    )
    assert reason
    assert composer.auto_reject_reason(["The candidate lacks experience with this stack."])
    assert composer.auto_reject_reason(["This is a poor fit for the profile."])
