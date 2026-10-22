import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.answerer import FormAnswerer
from src.matcher import JobMatcher
from src.platforms.linkedin import LinkedInApplicant

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def test_python_not_claimed_as_skill():
    profile_path = PROJECT_ROOT / "config" / "profile.yaml"
    if not profile_path.exists():
        profile_path = PROJECT_ROOT / "config" / "profile.example.yaml"
    with open(profile_path, "r", encoding="utf-8") as f:
        profile = yaml.safe_load(f)

    # 1. Python must NOT be in skills.languages
    languages = profile.get("skills", {}).get("languages", [])
    assert "Python" not in languages, f"Python must not be claimed in skills.languages: {languages}"

    # 2. Python must NOT be in any primary skills list
    all_skills = []
    for cat, items in profile.get("skills", {}).items():
        if isinstance(items, list):
            all_skills.extend(items)
    assert "Python" not in all_skills

    # 3. Python must only appear in used_in_projects / projects
    used = profile.get("used_in_projects", [])
    python_used = [u for u in used if u.get("skill") == "Python"]
    assert len(python_used) == 1
    assert python_used[0]["project"] == "Advanced AI Chat Platform"

    # 4. Check matcher condensed profile facts
    matcher = JobMatcher()
    facts = {
        "primary_skills": matcher.profile.get("skills", {}),
        "used_in_projects": matcher.profile.get("used_in_projects", [])
    }
    assert "Python" not in facts["primary_skills"].get("languages", [])
    assert any(u["skill"] == "Python" for u in facts["used_in_projects"])

def test_go_gin_learning_skill_representation():
    profile_path = PROJECT_ROOT / "config" / "profile.yaml"
    if not profile_path.exists():
        profile_path = PROJECT_ROOT / "config" / "profile.example.yaml"
    with open(profile_path, "r", encoding="utf-8") as f:
        profile = yaml.safe_load(f)

    languages = profile.get("skills", {}).get("languages", [])
    # Must be stored as "Go (Gin, learning)"
    assert "Go (Gin, learning)" in languages
    # Must never be stored as an experienced skill
    assert "Go" not in languages
    assert "Golang" not in languages

def test_server_management_note_stored_verbatim_not_skill_with_years():
    profile_path = PROJECT_ROOT / "config" / "profile.yaml"
    if not profile_path.exists():
        profile_path = PROJECT_ROOT / "config" / "profile.example.yaml"
    with open(profile_path, "r", encoding="utf-8") as f:
        profile = yaml.safe_load(f)

    expected_note = "started project services, fixed server errors, and resolved a compromised (hacked) server"
    # 1. Stored verbatim
    assert profile.get("server_management_note") == expected_note

    # 2. Must NOT claim to be security expert or incident response specialist
    note_lower = profile.get("server_management_note", "").lower()
    assert "security expert" not in note_lower
    assert "incident response" not in note_lower

    # 3. Must not have years assigned to server management
    answerer = FormAnswerer()
    ans = answerer.find_direct_answer("How many years of experience do you have in server management?", field_type="number")
    assert ans is None or ans == "UNKNOWN"

def test_per_skill_years_return_unknown_and_total_experience_returns_5():
    answerer = FormAnswerer()

    # Per-skill years questions must all return None / UNKNOWN -> NEEDS_INPUT
    assert answerer.find_direct_answer("How many years of experience do you have with React?", field_type="number") is None
    assert answerer.find_direct_answer("React.js experience in years", field_type="number") is None
    assert answerer.find_direct_answer("Node.js experience", field_type="number") is None
    assert answerer.find_direct_answer("Years of JavaScript experience", field_type="number") is None
    assert answerer.find_direct_answer("TypeScript experience", field_type="number") is None

    # Total experience question must return 5
    ans_total = answerer.find_direct_answer("What is your total years of experience?", field_type="number")
    assert ans_total == "5"
    ans_overall = answerer.find_direct_answer("Overall experience in years", field_type="number")
    assert ans_overall == "5"

def test_pending_resume_name_blocks_live_apply():
    from src.guards import ResumeMismatchHaltError
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    page = MagicMock()
    modal = MagicMock()
    # Mock locator with 1 card present (resume step)
    mock_cards = MagicMock()
    mock_cards.count.return_value = 1
    modal.locator.return_value = mock_cards
    page.locator.return_value.first = modal

    # Test that PENDING_USER_CONFIRMATION blocks live apply and halts run
    applicant.profile["resume"]["selected_filename"] = "PENDING_USER_CONFIRMATION"

    # 1. select_resume_by_name raises ResumeMismatchHaltError immediately
    with pytest.raises(ResumeMismatchHaltError) as exc_info:
        applicant.select_resume_by_name(modal)
    assert "RESUME_PENDING_CONFIRMATION" in str(exc_info.value)

    # 2. process_application safely stops, discards modal, records RESUME_PENDING_CONFIRMATION, and raises ResumeMismatchHaltError
    with patch.object(applicant, "discard_modal") as mock_discard:
        with pytest.raises(ResumeMismatchHaltError):
            applicant.process_application(page, job_id="li-pending-1", title="React Dev", company="Acme")
        mock_discard.assert_called_once()
        db.update_job_status.assert_called_with(
            platform="linkedin",
            job_id="li-pending-1",
            status="RESUME_PENDING_CONFIRMATION",
            failure_reason="RESUME_PENDING_CONFIRMATION: Resume filename is 'PENDING_USER_CONFIRMATION'. Run halted."
        )


def test_confirmed_resume_filename_in_both_configs():
    settings_file = PROJECT_ROOT / "config" / "settings.yaml"
    if not settings_file.exists():
        settings_file = PROJECT_ROOT / "config" / "settings.example.yaml"
    profile_file = PROJECT_ROOT / "config" / "profile.yaml"
    if not profile_file.exists():
        profile_file = PROJECT_ROOT / "config" / "profile.example.yaml"

    with open(settings_file, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    with open(profile_file, "r", encoding="utf-8") as f:
        profile = yaml.safe_load(f)

    # Both configs must agree on the configured resume filename
    assert settings.get("paths", {}).get("resume") == profile.get("resume", {}).get("selected_filename")

