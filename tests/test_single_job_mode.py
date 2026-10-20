import pytest
from unittest.mock import MagicMock, patch
import sys
from src.db import Database
from src.platforms.linkedin import LinkedInCollector

def test_single_job_mode_existing_job_in_cli(monkeypatch, tmp_path):
    """
    Verifies that --job-id <id> for a stored job runs only that job and skips search.
    """
    db_path = tmp_path / "test_jobs.db"
    db = Database(str(db_path))
    db.record_job(
        platform="linkedin",
        job_id="4467464995",
        title="Senior Engineer",
        company="Particle41",
        location="Remote",
        status="FOUND"
    )

    from src.main import main
    test_args = ["main.py", "run", "--platform", "linkedin", "--rehearse", "--job-id", "4467464995", "--max-attempts", "1"]
    monkeypatch.setattr(sys, "argv", test_args)
    monkeypatch.setattr("src.main.Database", lambda: db)
    monkeypatch.setattr("builtins.input", lambda prompt="": "START")

    mock_run_pipeline = MagicMock()
    monkeypatch.setattr("src.main.run_pipeline", mock_run_pipeline)

    main()

    mock_run_pipeline.assert_called_once()
    call_kwargs = mock_run_pipeline.call_args[1]
    assert call_kwargs.get("target_job_id") == "4467464995"
    assert call_kwargs.get("is_rehearsal") is True

def test_single_job_mode_nonexistent_job_refuses_to_start(capsys, monkeypatch, tmp_path):
    """
    Verifies that --job-id <id> for a job NOT in the DB refuses to start and exits with code 1.
    """
    db_path = tmp_path / "test_empty.db"
    db = Database(str(db_path))

    from src.main import main
    test_args = ["main.py", "run", "--platform", "linkedin", "--rehearse", "--job-id", "9999999999"]
    monkeypatch.setattr(sys, "argv", test_args)
    monkeypatch.setattr("src.main.Database", lambda: db)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Job ID '9999999999' not found in database" in captured.out
    assert "Single-job mode requires an existing stored job" in captured.out

def test_single_job_mode_skips_search_in_pipeline(monkeypatch):
    """
    Verifies that when target_job_id is provided, search_and_apply is completely skipped.
    """
    db_mock = MagicMock()
    guards_mock = MagicMock()
    guards_mock.max_attempts = 10
    guards_mock.session_attempts_count = 0
    guards_mock.settings = {"search": {"max_jobs_per_platform": 10}}
    matcher_mock = MagicMock()

    mock_mgr = MagicMock()
    mock_ctx = MagicMock()
    mock_page = MagicMock()
    mock_ctx.pages = [mock_page]
    mock_mgr.start.return_value = mock_ctx

    from src.main import run_pipeline

    with patch("src.platforms.linkedin.LinkedInCollector") as MockLICollector:
        mock_li_instance = MockLICollector.return_value
        mock_li_instance.process_eligible_found_jobs.return_value = []

        run_pipeline(
            db=db_mock,
            guards=guards_mock,
            matcher=matcher_mock,
            platform="linkedin",
            browser_manager=mock_mgr,
            target_job_id="4467464995",
            is_rehearsal=True
        )

        mock_li_instance.process_eligible_found_jobs.assert_called_once()
        assert mock_li_instance.process_eligible_found_jobs.call_args[1].get("target_job_id") == "4467464995"
        mock_li_instance.run_search_and_apply.assert_not_called()
