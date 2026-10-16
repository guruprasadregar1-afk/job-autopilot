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

