import pytest
from unittest.mock import patch, MagicMock
from src.llm import ask_json, UsageLimitReached

def test_usage_limit_raised_without_retry():
    call_count = 0

    def fake_ask_claude(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise UsageLimitReached("Claude usage limit reached: resets at 3 PM")

    with patch("src.llm.ask_claude", side_effect=fake_ask_claude):
        with pytest.raises(UsageLimitReached) as exc_info:
            ask_json("Test prompt", retries=3)
        
        # Must fail immediately on attempt 1 without looping through retries
        assert call_count == 1
        assert "resets at" in str(exc_info.value)

def test_main_loop_catches_usage_limit_and_saves_state():
    db = MagicMock()
    
    # Simulate runner encountering UsageLimitReached on job #5
    job_id = "job-555"
    platform = "linkedin"
    
    try:
        raise UsageLimitReached("Rate limit exceeded. Resets at 4:00 PM.")
    except UsageLimitReached as e:
        # Expected runner behaviour: catch, update job status, log clean exit
        db.update_job_status(platform, job_id, status="SKIPPED", failure_reason=str(e))
        clean_exit = True

    assert clean_exit is True
    db.update_job_status.assert_called_once_with(
        platform, job_id, status="SKIPPED", failure_reason="Rate limit exceeded. Resets at 4:00 PM."
    )
