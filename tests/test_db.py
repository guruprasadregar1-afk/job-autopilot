import pytest
from pathlib import Path
from src.db import Database

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_jobs.db"
    return Database(db_file)

def test_job_dedupe(temp_db):
    assert not temp_db.job_exists("linkedin", "101")
    temp_db.record_job("linkedin", "101", "Senior Dev", "Tech Corp", status="FOUND")
    assert temp_db.job_exists("linkedin", "101")
    assert not temp_db.job_exists("naukri", "101")

def test_status_update_and_applied_count(temp_db):
    temp_db.record_job("linkedin", "101", "Senior Dev", "Tech Corp", status="APPLIED")
    assert temp_db.get_applied_count_today("linkedin") == 1
    assert temp_db.get_applied_count_today("naukri") == 0

def test_review_approval_persistence(temp_db):
    assert temp_db.get_review_approval_count() == 0
    temp_db.record_review_approval("linkedin", "101")
    assert temp_db.get_review_approval_count() == 1
    # Duplicate approval shouldn't increment
    temp_db.record_review_approval("linkedin", "101")
    assert temp_db.get_review_approval_count() == 1

def test_needs_input_pending_questions(temp_db):
    temp_db.record_job(
        platform="naukri",
        job_id="202",
        title="Full Stack Engineer",
        company="Startup Co",
        status="NEEDS_INPUT",
        pending_question="What is your experience with Kubernetes?"
    )
    pending = temp_db.get_pending_questions()
    assert len(pending) == 1
    assert pending[0]["job_id"] == "202"
    assert "Kubernetes" in pending[0]["pending_question"]

def test_job_eligibility_by_status(temp_db):
    # 1. Job not in DB is eligible
    assert temp_db.is_job_eligible("linkedin", "unseen-1") is True
    assert temp_db.is_job_blocked("linkedin", "unseen-1") is False

    # 2. Non-blocking statuses are eligible again when seen
    non_blocking = ["FOUND", "NEEDS_INPUT", "OBSERVED_REVIEW", "RESUME_PENDING_CONFIRMATION"]
    for idx, st in enumerate(non_blocking):
        jid = f"non-block-{idx}"
        temp_db.record_job("linkedin", jid, "Title", "Company", status=st)
        assert temp_db.is_job_eligible("linkedin", jid) is True, f"{st} should be eligible"
        assert temp_db.is_job_blocked("linkedin", jid) is False

    # 3. Blocking final outcomes
    blocking = ["APPLIED", "UNVERIFIED", "EXTERNAL_SITE", "SKIPPED", "SKIPPED_BY_USER"]
    for idx, st in enumerate(blocking):
        jid = f"block-{idx}"
        temp_db.record_job("linkedin", jid, "Title", "Company", status=st)
        assert temp_db.is_job_eligible("linkedin", jid) is False, f"{st} should be blocked"
        assert temp_db.is_job_blocked("linkedin", jid) is True

    # 4. FAILED status failure counter:
    # 1 failure -> eligible (failure_count = 1)
    temp_db.record_job("linkedin", "fail-test", "Title", "Company", status="FAILED", failure_reason="timeout")
    assert temp_db.get_failure_count("linkedin", "fail-test") == 1
    assert temp_db.is_job_eligible("linkedin", "fail-test") is True

    # 2nd failure -> blocked (failure_count = 2)
    temp_db.update_job_status("linkedin", "fail-test", status="FAILED", failure_reason="crash")
    assert temp_db.get_failure_count("linkedin", "fail-test") == 2
    assert temp_db.is_job_eligible("linkedin", "fail-test") is False
    assert temp_db.is_job_blocked("linkedin", "fail-test") is True

def test_needs_input_re_evaluated_after_answer_added(temp_db, tmp_path):
    # Job initially in NEEDS_INPUT is eligible
    temp_db.record_job("linkedin", "needs-ans-1", "Dev", "Acme", status="NEEDS_INPUT", pending_question="GraphQL experience?")
    assert temp_db.is_job_eligible("linkedin", "needs-ans-1") is True

    # FormAnswerer initially has no answer
    from src.answerer import FormAnswerer
    ans_file = tmp_path / "answers.yaml"
    ans_file.write_text("answers:\n  - patterns: ['ctc']\n    value: '1500000'\n", encoding="utf-8")
    answerer = FormAnswerer(answers_path=ans_file)
    assert answerer.find_direct_answer("GraphQL experience?") is None

    # User adds answer to answers.yaml
    ans_file.write_text("""
answers:
  - patterns: ['ctc']
    value: '1500000'
  - patterns: ['graphql']
    value: '3 years'
""", encoding="utf-8")
    answerer.reload_answers()

    # Re-evaluation finds the newly added answer
    assert answerer.find_direct_answer("GraphQL experience?") == "3 years"


def test_get_eligible_found_jobs_requeues_answered_needs_input(temp_db, tmp_path):
    from src.answerer import FormAnswerer

    # 1. Record a job in NEEDS_INPUT with pending question "LinkedIn Profile"
    temp_db.record_job(
        platform="linkedin",
        job_id="test-requeue-1",
        title="Full Stack Engineer",
        company="Particle41",
        status="NEEDS_INPUT",
        pending_question="LinkedIn Profile"
    )

    # Initially, with an answerer that has NO answer for LinkedIn Profile:
    ans_file = tmp_path / "answers.yaml"
    ans_file.write_text("answers:\n  - patterns: ['ctc']\n    value: '1500000'\n", encoding="utf-8")
    empty_answerer = FormAnswerer(answers_path=ans_file)

    # Job is NOT in get_eligible_found_jobs (because status is still NEEDS_INPUT)
    eligible = temp_db.get_eligible_found_jobs("linkedin", answerer=empty_answerer)
    assert not any(j["job_id"] == "test-requeue-1" for j in eligible)

    # 2. Now user adds approved answer to answers.yaml
    ans_file.write_text("""
answers:
  - patterns:
      - "linkedin profile"
      - "linkedin profile url"
    value: "https://www.linkedin.com/in/guru-prasad-769b99227"
    exact_match: true
""", encoding="utf-8")
    updated_answerer = FormAnswerer(answers_path=ans_file)

    # 3. get_eligible_found_jobs automatically requeues the job to FOUND and returns it!
    eligible_after = temp_db.get_eligible_found_jobs("linkedin", answerer=updated_answerer)
    matched_jobs = [j for j in eligible_after if j["job_id"] == "test-requeue-1"]
    assert len(matched_jobs) == 1
    assert matched_jobs[0]["title"] == "Full Stack Engineer"

    # Verify DB status is now FOUND, failure_count is 0, and pending_question is cleared
    with temp_db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, failure_count, pending_question FROM jobs WHERE job_id = 'test-requeue-1'")
        row = cursor.fetchone()
        assert row[0] == "FOUND"
        assert row[1] == 0
        assert row[2] == ""


def test_get_eligible_found_jobs_requeues_join_terms_with_options_metadata(temp_db, tmp_path):
    from src.answerer import FormAnswerer

    temp_db.record_job(
        platform="linkedin",
        job_id="4476699604",
        title="Full Stack Engineer",
        company="Enterprise Bot",
        status="NEEDS_INPUT",
        pending_question="Do you agree with the JOIN Terms & Conditions and have you read the Data Privacy Policy? * [type: radio, options: Yes]"
    )

    ans_file = tmp_path / "answers.yaml"
    ans_file.write_text("""
answers:
  - patterns:
      - "Do you agree with the JOIN Terms & Conditions and have you read the Data Privacy Policy? *"
    value: "Yes"
    allowed_field_types:
      - "radio"
      - "checkbox"
    require_options:
      - "Yes"
    exact_match: true
    user_approved_consent: true
    user_approved_date: "2026-10-22"
""", encoding="utf-8")
    answerer = FormAnswerer(answers_path=ans_file)

    eligible = temp_db.get_eligible_found_jobs("linkedin", answerer=answerer)
    assert any(j["job_id"] == "4476699604" for j in eligible)

    with temp_db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, failure_count, pending_question FROM jobs WHERE job_id = '4476699604'")
        row = cursor.fetchone()
        assert row[0] == "FOUND"
        assert row[1] == 0
        assert row[2] == ""


def test_has_applied_to_company_recently_and_normalization(temp_db):
    import datetime

    # Record an application for Enterprise Bot 2 days ago
    two_days_ago = (datetime.datetime.now() - datetime.timedelta(days=2)).isoformat()
    temp_db.record_job(
        platform="linkedin",
        job_id="job-eb-1",
        title="Senior Full Stack Developer",
        company="Enterprise Bot LLC",
        status="APPLIED"
    )
    with temp_db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET applied_at = ? WHERE job_id = 'job-eb-1'", (two_days_ago,))

    # Record an application for Jobgether 10 days ago (outside 7 day window)
    ten_days_ago = (datetime.datetime.now() - datetime.timedelta(days=10)).isoformat()
    temp_db.record_job(
        platform="linkedin",
        job_id="job-jg-1",
        title="Full Stack Developer",
        company="Jobgether Ltd",
        status="APPLIED"
    )
    with temp_db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET applied_at = ? WHERE job_id = 'job-jg-1'", (ten_days_ago,))

    # 1. Enterprise Bot variations within 7 days -> detected
    applied_eb1, prev_id1 = temp_db.has_applied_to_company_recently("Enterprise Bot", days=7)
    assert applied_eb1 is True
    assert prev_id1 == "job-eb-1"

    applied_eb2, prev_id2 = temp_db.has_applied_to_company_recently("enterprise bot, inc.", days=7)
    assert applied_eb2 is True
    assert prev_id2 == "job-eb-1"

    applied_eb3, prev_id3 = temp_db.has_applied_to_company_recently("Enterprise\u200b Bot", days=7)
    assert applied_eb3 is True
    assert prev_id3 == "job-eb-1"

    # 2. Jobgether was 10 days ago -> NOT within 7 days
    applied_jg, prev_jg = temp_db.has_applied_to_company_recently("Jobgether", days=7)
    assert applied_jg is False
    assert prev_jg is None

    # But within 14 days, Jobgether IS detected
    applied_jg14, prev_jg14 = temp_db.has_applied_to_company_recently("Jobgether", days=14)
    assert applied_jg14 is True
    assert prev_jg14 == "job-jg-1"

    # 3. Different company -> not applied
    applied_other, _ = temp_db.has_applied_to_company_recently("Google LLC", days=7)
    assert applied_other is False



def test_get_eligible_found_jobs_requeues_backend_developer_experience(temp_db, tmp_path):
    from src.answerer import FormAnswerer

    temp_db.record_job(
        platform="linkedin",
        job_id="4481311145",
        title="Back End Developer",
        company="Third Wave Coffee",
        status="NEEDS_INPUT",
        pending_question="Mention your Overall years of experience as Backend Developer ."
    )

    ans_file = tmp_path / "answers.yaml"
    ans_file.write_text("""
answers:
  - patterns:
      - "Mention your Overall years of experience as Backend Developer ."
    value: "5 years 3 months"
    text_value: "5 years 3 months"
    numeric_value: 5
    exact_match: true
""", encoding="utf-8")
    answerer = FormAnswerer(answers_path=ans_file)

    eligible = temp_db.get_eligible_found_jobs("linkedin", answerer=answerer)
    assert any(j["job_id"] == "4481311145" for j in eligible)

    with temp_db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, failure_count, pending_question FROM jobs WHERE job_id = '4481311145'")
        row = cursor.fetchone()
        assert row[0] == "FOUND"
        assert row[1] == 0
        assert row[2] == ""



