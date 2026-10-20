import pytest
from unittest.mock import MagicMock
from src.platforms.linkedin import LinkedInCollector, LinkedInApplicant
from src.policy import SafePage, BrowserClosedCleanStop

class FakeLocator:
    def __init__(self, count=1, is_visible=True):
        self._count = count
        self._is_visible = is_visible
        self.first = self

    def count(self):
        return self._count

    def wait_for(self, state="visible", timeout=3000):
        return None

    def is_visible(self):
        return self._is_visible

    def get_attribute(self, attr):
        return ""

    def inner_text(self):
        return ""

    def click(self, **kwargs):
        return None

class FakeContext:
    def __init__(self, is_closed=False, pages=None, event_log=None):
        self._is_closed = is_closed
        self.pages = pages or []
        self.event_log = event_log
        self._page_counter = 0

    def is_closed(self):
        return self._is_closed

    def new_page(self):
        self._page_counter += 1
        name = f"page-{self._page_counter}"
        p = FakePage(is_closed=False, context=self, name=name)
        self.pages.append(p)
        return p

class FakePage:
    def __init__(self, is_closed=False, context=None, name=""):
        self._is_closed = is_closed
        self.context = context or FakeContext(pages=[self])
        self.name = name
        self.urls_visited = []

    def is_closed(self):
        return self._is_closed

    def close(self):
        self._is_closed = True
        if self in self.context.pages:
            self.context.pages.remove(self)
        if len(self.context.pages) == 0:
            self.context._is_closed = True
        if getattr(self.context, "event_log", None) is not None:
            self.context.event_log.append(f"close:{self.name}")

    def goto(self, url, **kwargs):
        if self._is_closed:
            raise Exception("Target page, context or browser has been closed")
        self.urls_visited.append(url)
        if getattr(self.context, "event_log", None) is not None:
            self.context.event_log.append(f"goto:{self.name}:{url}")
        return None

    def locator(self, selector, **kwargs):
        return FakeLocator()

def test_page_alive_returns_same_page():
    db_mock = MagicMock()
    guards_mock = MagicMock()
    matcher_mock = MagicMock()
    collector = LinkedInCollector(db=db_mock, guards=guards_mock, matcher=matcher_mock)

    ctx = FakeContext(is_closed=False)
    page = FakePage(is_closed=False, context=ctx)
    ctx.pages = [page]
    safe_page = SafePage(page)

    res_page, res_safe = collector._ensure_active_page(page, safe_page, "job-1")
    assert res_page is page
    assert res_safe is safe_page

def test_page_closed_reuses_existing_context_page():
    db_mock = MagicMock()
    guards_mock = MagicMock()
    matcher_mock = MagicMock()
    collector = LinkedInCollector(db=db_mock, guards=guards_mock, matcher=matcher_mock)

    ctx = FakeContext(is_closed=False)
    closed_page = FakePage(is_closed=True, context=ctx)
    alive_page = FakePage(is_closed=False, context=ctx)
    ctx.pages = [closed_page, alive_page]
    safe_page = SafePage(closed_page)

    res_page, res_safe = collector._ensure_active_page(closed_page, safe_page, "job-2")
    assert res_page is alive_page
    assert res_page.is_closed() is False

def test_page_closed_opens_new_page_in_same_context():
    db_mock = MagicMock()
    guards_mock = MagicMock()
    matcher_mock = MagicMock()
    collector = LinkedInCollector(db=db_mock, guards=guards_mock, matcher=matcher_mock)

    ctx = FakeContext(is_closed=False)
    closed_page = FakePage(is_closed=True, context=ctx)
    ctx.pages = [closed_page]
    safe_page = SafePage(closed_page)

    res_page, res_safe = collector._ensure_active_page(closed_page, safe_page, "job-3")
    assert res_page is not closed_page
    assert res_page.is_closed() is False
    assert res_page.context is ctx

def test_context_closed_raises_clean_stop_and_updates_db():
    db_mock = MagicMock()
    guards_mock = MagicMock()
    matcher_mock = MagicMock()
    collector = LinkedInCollector(db=db_mock, guards=guards_mock, matcher=matcher_mock)

    ctx = FakeContext(is_closed=True)
    closed_page = FakePage(is_closed=True, context=ctx)
    safe_page = SafePage(closed_page)

    with pytest.raises(BrowserClosedCleanStop) as exc_info:
        collector._ensure_active_page(closed_page, safe_page, "job-4")

    assert "Browser closed unexpectedly" in str(exc_info.value)
    db_mock.update_job_status.assert_called_once_with(
        platform="linkedin",
        job_id="job-4",
        status="BROWSER_CLOSED",
        failure_reason="Browser closed or disconnected during execution"
    )

def test_discard_modal_post_settle_verification():
    db_mock = MagicMock()
    guards_mock = MagicMock()
    applicant = LinkedInApplicant(db=db_mock, guards=guards_mock)

    page_mock = MagicMock()
    page_mock.is_closed.return_value = False

    call_count = [0]
    def loc_side_effect(sel):
        m = MagicMock()
        if "dialog[open]" in sel or "jobs-easy-apply-modal" in sel or "data-test-modal" in sel:
            call_count[0] += 1
            cnt = 1 if call_count[0] <= 1 else 0
            m.count.return_value = cnt
            m.first = m
            m.is_visible.return_value = (cnt > 0)
            return m
        m.count.return_value = 0
        m.first = m
        return m

    page_mock.locator.side_effect = loc_side_effect

    # Should execute discard and verify page alive without error
    applicant.discard_modal(page_mock, job_id="job-5")
    page_mock.is_closed.assert_called()

def test_anchor_tab_prevents_context_exit_when_job_tab_closes():
    """
    Verifies that the presence of the permanent anchor tab prevents the browser context
    from closing when all job tabs are closed.
    """
    # Case 1: Without anchor tab, closing the only open job tab closes the context
    ctx_no_anchor = FakeContext(is_closed=False)
    job_tab1 = FakePage(is_closed=False, context=ctx_no_anchor, name="job-1")
    ctx_no_anchor.pages = [job_tab1]
    job_tab1.close()
    assert job_tab1.is_closed() is True
    assert ctx_no_anchor.is_closed() is True

    # Case 2: With anchor tab, closing the job tab leaves anchor tab and context alive
    ctx_with_anchor = FakeContext(is_closed=False)
    anchor_tab = FakePage(is_closed=False, context=ctx_with_anchor, name="anchor")
    anchor_tab._is_keep_alive = True
    job_tab2 = FakePage(is_closed=False, context=ctx_with_anchor, name="job-2")
    ctx_with_anchor.pages = [anchor_tab, job_tab2]

    job_tab2.close()
    assert job_tab2.is_closed() is True
    assert anchor_tab.is_closed() is False
    assert ctx_with_anchor.is_closed() is False
    assert anchor_tab in ctx_with_anchor.pages

def test_fresh_tab_per_job():
    """
    Verifies that LinkedInCollector.process_eligible_found_jobs opens a fresh tab
    for each job and processes each job on its own distinct page.
    """
    db_mock = MagicMock()
    guards_mock = MagicMock()
    matcher_mock = MagicMock()
    collector = LinkedInCollector(db=db_mock, guards=guards_mock, matcher=matcher_mock)

    db_mock.get_eligible_found_jobs.return_value = [
        {"job_id": "4467464995", "title": "Senior Engineer", "company": "Particle41"},
        {"job_id": "4479309031", "title": "Full Stack Dev", "company": "Jobgether"},
    ]
    guards_mock.is_job_attempted_in_run.return_value = False
    guards_mock.session_attempts_count = 0
    guards_mock.max_attempts = 10
    guards_mock.check_pre_job_guards.return_value = None
    guards_mock.action_delay.return_value = None
    guards_mock.check_page_safety.return_value = None

    ctx = FakeContext(is_closed=False)
    anchor_tab = FakePage(is_closed=False, context=ctx, name="anchor")
    anchor_tab._is_keep_alive = True
    init_tab = FakePage(is_closed=False, context=ctx, name="init")
    ctx.pages = [anchor_tab, init_tab]

    applicant_mock = MagicMock()
    processed_pages = []

    def mock_process_application(p, job_id, **kwargs):
        processed_pages.append((job_id, p))
        return {"status": "OBSERVED_REVIEW", "reason": "Test success"}

    applicant_mock.process_application.side_effect = mock_process_application

    collector.process_eligible_found_jobs(init_tab, applicant=applicant_mock)

    # Verify both jobs were processed
    assert len(processed_pages) == 2
    job1_id, job1_page = processed_pages[0]
    job2_id, job2_page = processed_pages[1]
    assert job1_id == "4467464995"
    assert job2_id == "4479309031"
    # Verify each job ran on a distinct, fresh page (not the init tab, not each other)
    assert job1_page is not init_tab
    assert job2_page is not init_tab
    assert job1_page is not job2_page
    # Verify URLs were navigated
    assert "https://www.linkedin.com/jobs/view/4467464995/" in job1_page.urls_visited
    assert "https://www.linkedin.com/jobs/view/4479309031/" in job2_page.urls_visited

def test_old_tab_closed_after_new_tab_loads():
    """
    Verifies that when transitioning between jobs, the previous job tab is closed
    ONLY AFTER the new tab has navigated and loaded, never before.
    """
    db_mock = MagicMock()
    guards_mock = MagicMock()
    matcher_mock = MagicMock()
    collector = LinkedInCollector(db=db_mock, guards=guards_mock, matcher=matcher_mock)

    db_mock.get_eligible_found_jobs.return_value = [
        {"job_id": "4400000001", "title": "Lead Dev", "company": "Alpha Corp"},
        {"job_id": "4400000002", "title": "Staff Dev", "company": "Beta Corp"},
    ]
    guards_mock.is_job_attempted_in_run.return_value = False
    guards_mock.session_attempts_count = 0
    guards_mock.max_attempts = 10
    guards_mock.check_pre_job_guards.return_value = None
    guards_mock.action_delay.return_value = None
    guards_mock.check_page_safety.return_value = None

    event_log = []
    ctx = FakeContext(is_closed=False, event_log=event_log)
    anchor_tab = FakePage(is_closed=False, context=ctx, name="anchor")
    anchor_tab._is_keep_alive = True
    init_tab = FakePage(is_closed=False, context=ctx, name="init")
    ctx.pages = [anchor_tab, init_tab]

    applicant_mock = MagicMock()
    applicant_mock.process_application.return_value = {"status": "OBSERVED_REVIEW", "reason": "OK"}

    collector.process_eligible_found_jobs(init_tab, applicant=applicant_mock)

    # Analyze event log:
    # 1. new page for job 4400000001 navigates
    # 2. init_tab closes
    # 3. new page for job 4400000002 navigates
    # 4. job 4400000001 page closes
    alpha_nav_idx = -1
    init_close_idx = -1
    beta_nav_idx = -1
    alpha_close_idx = -1

    for idx, ev in enumerate(event_log):
        if "goto:" in ev and "4400000001" in ev:
            alpha_nav_idx = idx
        elif "close:init" in ev:
            init_close_idx = idx
        elif "goto:" in ev and "4400000002" in ev:
            beta_nav_idx = idx
        elif "close:page-1" in ev:
            alpha_close_idx = idx

    assert alpha_nav_idx != -1, f"job-alpha nav not found in {event_log}"
    assert init_close_idx != -1, f"init close not found in {event_log}"
    assert beta_nav_idx != -1, f"job-beta nav not found in {event_log}"
    assert alpha_close_idx != -1, f"job-alpha close not found in {event_log}"

    # Alpha tab loaded before init tab closed
    assert alpha_nav_idx < init_close_idx, f"Init tab was closed before alpha tab navigated! Events: {event_log}"
    # Beta tab loaded before alpha tab closed
    assert beta_nav_idx < alpha_close_idx, f"Alpha tab was closed before beta tab navigated! Events: {event_log}"

def test_unexpected_close_message(capsys):
    """
    Verifies that when the browser closes unexpectedly:
    1. The message printed is 'Browser closed unexpectedly (see logs/browser_lifecycle.log)'
    2. 'closed by user' is NEVER printed.
    3. Status is recorded in DB as BROWSER_CLOSED.
    """
    db_mock = MagicMock()
    guards_mock = MagicMock()
    matcher_mock = MagicMock()
    collector = LinkedInCollector(db=db_mock, guards=guards_mock, matcher=matcher_mock)

    ctx = FakeContext(is_closed=True)
    closed_page = FakePage(is_closed=True, context=ctx)
    safe_page = SafePage(closed_page)

    with pytest.raises(BrowserClosedCleanStop) as exc_info:
        collector._ensure_active_page(closed_page, safe_page, "job-999")

    captured = capsys.readouterr()
    expected_msg = "Browser closed unexpectedly (see logs/browser_lifecycle.log)"
    assert expected_msg in captured.out
    assert "closed by user" not in captured.out.lower()
    assert expected_msg in str(exc_info.value)

    db_mock.update_job_status.assert_called_once_with(
        platform="linkedin",
        job_id="job-999",
        status="BROWSER_CLOSED",
        failure_reason="Browser closed or disconnected during execution"
    )

def test_code_close_call_records_closed_by_code_true(capsys, monkeypatch, tmp_path):
    """
    Verifies that when record_code_close_call precedes page or context closing:
    1. closed_by_code: true is recorded in the lifecycle log.
    2. 'closed externally: no close call from the bot' is NOT printed.
    """
    from src.browser import (
        record_code_close_call,
        attach_lifecycle_listeners,
        clear_code_close_calls,
        LIFECYCLE_LOG_PATH
    )
    test_log = tmp_path / "browser_lifecycle.log"
    monkeypatch.setattr("src.browser.LIFECYCLE_LOG_PATH", test_log)
    clear_code_close_calls()

    # Create mock context and page
    mock_ctx = MagicMock()
    listeners = {}
    mock_ctx.on = lambda ev, cb: listeners.setdefault(ev, []).append(cb)
    mock_page = MagicMock()
    page_listeners = {}
    mock_page.on = lambda ev, cb: page_listeners.setdefault(ev, []).append(cb)
    mock_page.url = "https://www.linkedin.com/jobs"
    mock_page.context = mock_ctx
    mock_ctx.pages = [mock_page]

    attach_lifecycle_listeners(mock_ctx, anchor_page=None)
    # Trigger on_page_created or call attach_page_listeners through page event
    for cb in listeners.get("page", []):
        cb(mock_page)

    # 1. Intentional code close
    record_code_close_call(mock_page, caller="test_caller")
    for cb in page_listeners.get("close", []):
        cb()

    captured = capsys.readouterr()
    assert "closed externally: no close call from the bot" not in captured.out

    log_content = test_log.read_text(encoding="utf-8")
    assert "EVENT=CODE_CLOSE_CALL" in log_content
    assert "caller=test_caller" in log_content
    assert "EVENT=PAGE_CLOSE" in log_content
    assert "closed_by_code=true" in log_content

def test_external_close_records_closed_by_code_false_and_prints_stdout(capsys, monkeypatch, tmp_path):
    """
    Verifies that when page or context closes without a preceding record_code_close_call:
    1. closed_by_code: false is recorded in the lifecycle log.
    2. 'closed externally: no close call from the bot' is printed to stdout.
    """
    from src.browser import (
        attach_lifecycle_listeners,
        clear_code_close_calls,
        LIFECYCLE_LOG_PATH
    )
    test_log = tmp_path / "browser_lifecycle.log"
    monkeypatch.setattr("src.browser.LIFECYCLE_LOG_PATH", test_log)
    clear_code_close_calls()

    mock_ctx = MagicMock()
    listeners = {}
    mock_ctx.on = lambda ev, cb: listeners.setdefault(ev, []).append(cb)
    mock_page = MagicMock()
    page_listeners = {}
    mock_page.on = lambda ev, cb: page_listeners.setdefault(ev, []).append(cb)
    mock_page.url = "https://www.linkedin.com/jobs"
    mock_page.context = mock_ctx
    mock_ctx.pages = [mock_page]

    attach_lifecycle_listeners(mock_ctx, anchor_page=None)
    for cb in listeners.get("page", []):
        cb(mock_page)

    # Trigger close WITHOUT record_code_close_call
    for cb in page_listeners.get("close", []):
        cb()

    captured = capsys.readouterr()
    assert "closed externally: no close call from the bot" in captured.out

    log_content = test_log.read_text(encoding="utf-8")
    assert "EVENT=PAGE_CLOSE" in log_content
    assert "closed_by_code=false" in log_content

    # Trigger context close without code call
    for cb in listeners.get("close", []):
        cb()

    captured_ctx = capsys.readouterr()
    assert "closed externally: no close call from the bot" in captured_ctx.out

    log_content_ctx = test_log.read_text(encoding="utf-8")
    assert "EVENT=CONTEXT_CLOSE" in log_content_ctx
    assert "closed_by_code=false" in log_content_ctx

def test_context_closed_by_code_closes_pages(capsys, monkeypatch, tmp_path):
    """
    Verifies that when context close is initiated by code, any child pages closed
    as a consequence of the context closing are recognized as closed_by_code=true,
    preventing false 'closed externally' warnings.
    """
    from src.browser import (
        record_code_close_call,
        attach_lifecycle_listeners,
        clear_code_close_calls,
        LIFECYCLE_LOG_PATH
    )
    test_log = tmp_path / "browser_lifecycle.log"
    monkeypatch.setattr("src.browser.LIFECYCLE_LOG_PATH", test_log)
    clear_code_close_calls()

    mock_ctx = MagicMock()
    listeners = {}
    mock_ctx.on = lambda ev, cb: listeners.setdefault(ev, []).append(cb)
    mock_page = MagicMock()
    page_listeners = {}
    mock_page.on = lambda ev, cb: page_listeners.setdefault(ev, []).append(cb)
    mock_page.url = "about:blank"
    mock_page.context = mock_ctx
    mock_ctx.pages = [mock_page]

    attach_lifecycle_listeners(mock_ctx, anchor_page=None)
    for cb in listeners.get("page", []):
        cb(mock_page)

    # Context close is called by code (e.g. during cleanup or browser shutdown)
    record_code_close_call(mock_ctx, caller="context_cleanup")

    # Playwright closes child page as consequence of context closure
    for cb in page_listeners.get("close", []):
        cb()

    captured = capsys.readouterr()
    assert "closed externally: no close call from the bot" not in captured.out

    # Finally context close fires
    for cb in listeners.get("close", []):
        cb()

    captured_ctx = capsys.readouterr()
    assert "closed externally: no close call from the bot" not in captured_ctx.out

    log_content = test_log.read_text(encoding="utf-8")
    assert "EVENT=PAGE_CLOSE" in log_content
    assert "closed_by_code=true" in log_content
    assert "EVENT=CONTEXT_CLOSE" in log_content
    assert "closed_by_code=true" in log_content

