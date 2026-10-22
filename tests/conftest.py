import pytest
from pathlib import Path

@pytest.fixture(autouse=True)
def isolated_logs_dir(tmp_path, monkeypatch):
    """
    Autouse fixture ensuring all tests write approval sheets, snapshots,
    and log artifacts to a temporary directory instead of the real logs/ folder.
    """
    test_logs = tmp_path / "logs"
    test_logs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JOB_AUTOPILOT_LOGS_DIR", str(test_logs))
    return test_logs
