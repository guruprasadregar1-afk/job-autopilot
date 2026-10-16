import re
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.db import Database
from src.dashboard import load_data_readonly, render_dashboard_html, generate_dashboard, serve_dashboard

def test_db_opened_strictly_read_only(tmp_path):
    db_file = tmp_path / "test_ro.db"
    db = Database(db_file)
    db.record_job(
        platform="linkedin",
        job_id="999",
        title="Software Engineer",
        company="TestCorp",
        status="FOUND"
    )

    # Load via read-only URI
    data = load_data_readonly(db_file)
    assert len(data["jobs"]) == 1

    # Verify write attempt on read-only URI fails with OperationalError
    ro_uri = f"file:{db_file.resolve().as_posix()}?mode=ro"
    ro_conn = sqlite3.connect(ro_uri, uri=True)
    with pytest.raises(sqlite3.OperationalError, match="readonly database"):
        ro_conn.execute("INSERT INTO jobs (status) VALUES ('APPLIED')")
    ro_conn.close()

def test_html_contains_no_external_resource_loads(tmp_path):
    db_file = tmp_path / "test_resources.db"
    db = Database(db_file)
    db.record_job(
        platform="linkedin",
        job_id="12345",
        title="React Engineer",
        company="Acme Labs",
        location="Bengaluru",
        url="https://www.linkedin.com/jobs/view/12345/",
        status="APPLIED"
    )

    out_html = tmp_path / "dashboard.html"
    generate_dashboard(db_path=db_file, output_path=out_html)

    content = out_html.read_text(encoding="utf-8")

    # Ensure no script, link, img, or iframe tags load external http(s) resources
    forbidden_external_loaders = re.findall(r'<(?:script|link|img|iframe)\b[^>]*(?:src|href)=["\']https?://[^"\']+', content, re.IGNORECASE)
    assert len(forbidden_external_loaders) == 0, f"Found external resource loads: {forbidden_external_loaders}"

    # Only allowed external links are job links with rel="noopener noreferrer"
    for m in re.finditer(r'<a\b([^>]*)href=["\'](https?://[^"\']+)["\']([^>]*)>', content, re.IGNORECASE):
        attrs = m.group(1) + " " + m.group(3)
        assert 'rel="noopener noreferrer"' in attrs

def test_no_personal_pii_fields_rendered(tmp_path):
    db_file = tmp_path / "test_privacy.db"
    db = Database(db_file)
    # Storing job with diagnostics
    db.record_job(
        platform="linkedin",
        job_id="12345",
        title="React Developer",
        company="Safe Labs",
        location="Bengaluru",
        status="NEEDS_INPUT",
        pending_question="Notice period in days?"
    )

    out_html = tmp_path / "dashboard.html"
    generate_dashboard(db_path=db_file, output_path=out_html)
    content = out_html.read_text(encoding="utf-8")

    # Personal PII must NEVER be in dashboard HTML
    assert "candidate@example.com" not in content
    assert "555-0199" not in content
    assert "1500000" not in content  # Private CTC values
    assert "2500000" not in content

def test_dashboard_renders_with_zero_rows(tmp_path):
    db_file = tmp_path / "test_empty.db"
    db = Database(db_file)
    out_html = tmp_path / "dashboard_empty.html"
    generate_dashboard(db_path=db_file, output_path=out_html)

    content = out_html.read_text(encoding="utf-8")
    assert "Job Autopilot History" in content
    assert "Total Applied" in content
    assert "No matching jobs found" in content

def test_serve_dashboard_binds_localhost_only():
    with patch("src.dashboard.HTTPServer") as mock_server:
        mock_instance = MagicMock()
        mock_instance.serve_forever.side_effect = KeyboardInterrupt()
        mock_server.return_value = mock_instance

        serve_dashboard(port=8080, host="127.0.0.1")

        # Verify server bound strictly to 127.0.0.1
        mock_server.assert_called_once()
        bind_args = mock_server.call_args[0][0]
        assert bind_args[0] == "127.0.0.1"
        assert bind_args[1] == 8080

def test_job_events_recorded_on_status_change(tmp_path):
    db_file = tmp_path / "test_events.db"
    db = Database(db_file)

    # 1. New job recorded -> FOUND event
    db.record_job(
        platform="linkedin",
        job_id="101",
        title="Frontend Dev",
        company="TechCorp",
        status="FOUND",
        match_reason="Strong React fit"
    )

    # 2. Status updated -> NEEDS_INPUT event
    db.update_job_status(
        platform="linkedin",
        job_id="101",
        status="NEEDS_INPUT",
        pending_question="Expected CTC?"
    )

    # 3. Status updated -> APPLIED event
    db.update_job_status(
        platform="linkedin",
        job_id="101",
        status="APPLIED"
    )

    # 4. Review approval recorded -> REVIEW_APPROVAL event
    db.record_review_approval(
        platform="linkedin",
        job_id="101"
    )

    events = db.get_timeline_events()
    event_names = [e["event"] for e in events]
    assert "REVIEW_APPROVAL" in event_names
    assert "APPLIED" in event_names
    assert "NEEDS_INPUT" in event_names
    assert "FOUND" in event_names

def test_dashboard_xss_protection_and_script_injection_safety(tmp_path):
    db_file = tmp_path / "test_xss.db"
    db = Database(db_file)
    db.record_job(
        platform="linkedin",
        job_id="xss-001",
        title="<script>alert(1)</script>",
        company="<b onmouseover=alert('xss')>EvilCorp</b>",
        location="Bengaluru",
        match_reason="Matches <img src=x onerror=alert(2)>",
        status="NEEDS_INPUT",
        pending_question="What is your PIN? <script>document.cookie</script>"
    )

    out_html = tmp_path / "dashboard_xss.html"
    generate_dashboard(db_path=db_file, output_path=out_html)

    content = out_html.read_text(encoding="utf-8")

    # 1. Raw unescaped script tags from job data must NEVER appear in HTML
    assert "<script>alert(1)</script>" not in content
    assert "<script>document.cookie</script>" not in content
    assert "<b onmouseover" not in content
    assert "<img src=x" not in content

    # 2. Properly escaped versions must be present in HTML
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content
    assert "&lt;script&gt;document.cookie&lt;/script&gt;" in content
    assert ("&lt;b onmouseover=alert(&#x27;xss&#x27;)&gt;EvilCorp&lt;/b&gt;" in content or
            "&lt;b onmouseover=alert(&#39;xss&#39;)&gt;EvilCorp&lt;/b&gt;" in content)

    # 3. Embedded JSON must be safe against closing script tag breakout
    # There should only be exactly ONE opening <script> and ONE closing </script> in the whole document
    script_closes = re.findall(r"</script>", content, re.IGNORECASE)
    assert len(script_closes) == 1, f"Found unescaped script tag breakout: {script_closes}"
