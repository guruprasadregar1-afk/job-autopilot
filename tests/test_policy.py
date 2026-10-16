import pytest
from unittest.mock import MagicMock
from src.policy import (
    PolicyEngine,
    PolicyBlockError,
    CriticalPolicyViolationError,
    SafeLocator,
    SafePage,
    OBSERVE_ONLY,
    ALLOWED_URL_PATTERNS,
    DENIED_PATH_PATTERNS,
    DENIED_ACTION_PATTERNS
)

# ==============================================================================
# 1. NAVIGATION & DEFAULT-DENY TESTS (PATH-ONLY DENIALS)
# ==============================================================================

def test_allowed_urls():
    valid_urls = [
        "https://www.linkedin.com/jobs/",
        "https://www.linkedin.com/jobs/search/?keywords=Senior+Full+Stack+Developer",
        "https://in.linkedin.com/jobs/view/3920192841/?eBP=CwEAAAG...",
        "https://www.linkedin.com/jobs/collections/?currentJobId=123",
        "https://www.naukri.com/senior-full-stack-developer-jobs-in-bengaluru",
        "https://www.naukri.com/senior-full-stack-developer-jobs-in-bengaluru-2",
        "https://www.naukri.com/job-listings-senior-developer-tech-corp-12345?src=seo_srp",
        "https://www.naukri.com/mnjuser/homepage",
        "https://www.naukri.com/nlogin/login",
    ]
    for url in valid_urls:
        PolicyEngine.validate_navigation(url)

def test_default_deny_navigation():
    """
    Enforces default-deny: any URL not explicitly on the allowlist is blocked.
    """
    blocked_urls = [
        "https://www.google.com",
        "https://www.example.com",
        "https://www.linkedin.com/feed/",  # /feed/ replaced with /jobs/
        "https://www.linkedin.com/search/results/all/?keywords=test",
        "https://www.naukri.com/candidate-services",
    ]
    for url in blocked_urls:
        with pytest.raises(PolicyBlockError) as exc_info:
            PolicyEngine.validate_navigation(url)
        assert "default-deny policy" in str(exc_info.value)

def test_naukri_slug_containing_premium_allowed():
    """
    URL denials must match URL path sections (e.g. /premium), NEVER job slugs or query strings.
    A Naukri job-listings URL whose slug contains 'premium' must be ALLOWED.
    """
    # 1. Job listing with 'premium' in slug -> ALLOWED
    job_with_premium_slug = "https://www.naukri.com/job-listings-premium-developer-tech-corp-12345?src=seo_srp"
    PolicyEngine.validate_navigation(job_with_premium_slug)

    # 2. LinkedIn search query containing 'premium' -> ALLOWED
    linkedin_search_with_premium_query = "https://www.linkedin.com/jobs/search/?keywords=premium+lead&location=India"
    PolicyEngine.validate_navigation(linkedin_search_with_premium_query)

    # 3. Actual Premium section on Naukri -> BLOCKED
    with pytest.raises(CriticalPolicyViolationError):
        PolicyEngine.validate_navigation("https://www.naukri.com/premium")

    # 4. Actual Premium section on LinkedIn -> BLOCKED
    with pytest.raises(CriticalPolicyViolationError):
        PolicyEngine.validate_navigation("https://www.linkedin.com/premium/products")

def test_denied_sensitive_urls_critical_violation():
    forbidden_urls = [
        "https://www.linkedin.com/in/sample-candidate-12345/edit",
        "https://www.linkedin.com/company/google",
        "https://www.linkedin.com/notifications/",
        "https://www.linkedin.com/jobs/job-alert/create",
        "https://www.linkedin.com/premium/products",
        "https://www.linkedin.com/mypreferences/d/categories/privacy",
        "https://www.linkedin.com/messaging/thread/12345678/",
        "https://www.linkedin.com/feed/update/urn:li:activity:123456789/",
        "https://www.linkedin.com/jobs/open-to-work-settings",
        "https://www.naukri.com/mnjuser/profile",
        "https://www.naukri.com/mnjuser/account/settings",
        "https://www.naukri.com/notifications",
        "https://www.naukri.com/fastforward/resume-display",
    ]
    for url in forbidden_urls:
        with pytest.raises(CriticalPolicyViolationError):
            PolicyEngine.validate_navigation(url)

def test_tightened_naukri_search_pattern():
    r"""
    Naukri search URLs must match -jobs(-in-[a-zA-Z0-9_-]+)?(-\d+)?(\?.*)?$
    """
    valid_searches = [
        "https://www.naukri.com/full-stack-developer-jobs",
        "https://www.naukri.com/senior-full-stack-developer-jobs-in-bengaluru",
        "https://www.naukri.com/senior-full-stack-developer-jobs-in-bengaluru-2",
        "https://www.naukri.com/mern-stack-developer-jobs-in-india?experience=4",
    ]
    for url in valid_searches:
        PolicyEngine.validate_navigation(url)

# ==============================================================================
# 2. JOB TITLES & FORM LABELS VS CONTROLS (PURCHASE MANAGER & ALERT SYSTEMS)
# ==============================================================================

def test_job_titles_purchase_manager_and_alert_systems_engineer_allowed():
    """
    Action-denylist words ('purchase', 'alert') must never be tested against job titles.
    Both 'Purchase Manager' and 'Alert Systems Engineer' must be ALLOWED when selecting job cards.
    """
    # 1. Job titled "Purchase Manager" clicked via structural selector
    PolicyEngine.validate_action(
        action_type="click",
        text="Purchase Manager",
        selector="div[data-job-id='1001']",
        is_job_card=True
    )

    # 2. Job titled "Alert Systems Engineer" clicked via structural selector
    PolicyEngine.validate_action(
        action_type="click",
        text="Alert Systems Engineer",
        selector="div[data-job-id='1002']",
        is_job_card=True
    )

    # 3. Job titled "React Developer" clicked via structural selector
    PolicyEngine.validate_action(
        action_type="click",
        text="React Developer",
        selector="div[data-job-id='1003']",
        is_job_card=True
    )

    # 4. In contrast, an actual 'Purchase' or 'Set alert' button outside job content is BLOCKED
    with pytest.raises(PolicyBlockError):
        PolicyEngine.validate_action(action_type="click", text="Purchase", selector="button.buy-button")

    with pytest.raises(PolicyBlockError):
        PolicyEngine.validate_action(action_type="click", text="Set job alert", selector="button.alert-btn")

def test_easy_apply_accessible_name_with_denylisted_words():
    """
    Accessible name 'Easy Apply to Purchase Manager at Upgrade Labs' contains
    words that would otherwise be blocked ('purchase', 'upgrade').
    Because the action is allowlisted ('Easy Apply'), it must be ALLOWED.
    A standalone 'Purchase' button and a 'Follow Upgrade Labs' checkbox-check
    must still be BLOCKED.
    """
    # 1. Easy Apply with job title containing 'Purchase' and company containing 'Upgrade' -> ALLOWED
    PolicyEngine.validate_action(
        action_type="click",
        text="Easy Apply to Purchase Manager at Upgrade Labs",
        selector="button.jobs-apply-button"
    )

    # 2. Standalone Purchase button -> BLOCKED
    with pytest.raises(PolicyBlockError) as exc_info:
        PolicyEngine.validate_action(
            action_type="click",
            text="Purchase",
            selector="button.buy-button"
        )
    assert "purchase" in str(exc_info.value).lower()

    # 3. Follow Upgrade Labs checkbox check -> BLOCKED
    with pytest.raises(PolicyBlockError) as exc_info:
        PolicyEngine.validate_action(
            action_type="check",
            text="Follow Upgrade Labs",
            selector="input[type='checkbox']"
        )
    assert "follow" in str(exc_info.value).lower()

def test_form_label_relocate_allowed():
    """
    Interacting with or filling a form field with question 'Would you like to relocate?'
    must NOT be blocked by the social 'like' denylist.
    """
    PolicyEngine.validate_action(
        action_type="fill",
        text="Would you like to relocate?",
        selector="input[name='relocation_answer']",
        is_form_field=True
    )
    PolicyEngine.validate_action(
        action_type="check",
        text="Would you like to relocate?",
        selector="input[type='radio'][value='Yes']",
        is_form_field=True
    )

def test_standalone_social_buttons_denied():
    social_controls = [
        ("click", "Like", "button.like-button"),
        ("click", "React", "button.react-button"),
        ("click", "Share", "button.share-button"),
        ("click", "Comment", "button.comment-button"),
        ("click", "Connect", "button.connect-button"),
        ("click", "Recommend", "button.recommend-button"),
    ]
    for action_type, text, selector in social_controls:
        with pytest.raises(PolicyBlockError):
            PolicyEngine.validate_action(action_type, text=text, selector=selector)

# ==============================================================================
# 3. REPLAY REAL SNAPSHOT CLICKABLE ELEMENTS
# ==============================================================================

def test_snapshot_clickable_elements_replay():
    """
    Replays every real clickable element captured in docs/snapshots/:
    - LinkedIn Easy Apply button (visible text & accessible name) -> ALLOWED
    - LinkedIn Modal Next / Continue to next step -> ALLOWED
    - LinkedIn Modal Review / Review your application -> ALLOWED
    - LinkedIn Modal Dismiss -> ALLOWED
    - LinkedIn Pagination Page 2 -> ALLOWED
    - LinkedIn Submit application -> BLOCKED by OBSERVE_ONLY
    - Naukri Quick Apply button -> BLOCKED by OBSERVE_ONLY
    - Naukri Apply on company site -> BLOCKED by Denylist (EXTERNAL_SITE)
    """
    # 1. LinkedIn Easy Apply (exact accessible name from snapshot)
    PolicyEngine.validate_action(
        action_type="click",
        text="Easy Apply to Full-Stack Developer (Remote) at Hired",
        selector="button.jobs-apply-button id=jobs-apply-button-id"
    )

    # 2. LinkedIn Modal Next (from snapshot step 1)
    PolicyEngine.validate_action(
        action_type="click",
        text="Continue to next step",
        selector="button.artdeco-button--primary id=ember366"
    )

    # 3. LinkedIn Modal Review (from snapshot step 2)
    PolicyEngine.validate_action(
        action_type="click",
        text="Review your application",
        selector="button.artdeco-button--primary id=ember373"
    )

    # 4. LinkedIn Modal Dismiss (from snapshot step 1)
    PolicyEngine.validate_action(
        action_type="click",
        text="Dismiss",
        selector="button.artdeco-modal__dismiss id=ember353"
    )

    # 5. LinkedIn Pagination (from snapshot search results)
    PolicyEngine.validate_action(
        action_type="click",
        text="Page 2",
        selector="button[aria-label='Page 2']"
    )

    # 6. LinkedIn Submit application -> BLOCKED by OBSERVE_ONLY
    with pytest.raises(PolicyBlockError) as exc_info:
        PolicyEngine.validate_action(
            action_type="click",
            text="Submit application",
            selector="button.artdeco-button--primary"
        )
    assert "OBSERVE_ONLY" in str(exc_info.value)

    # 7. Naukri Quick Apply button -> BLOCKED by OBSERVE_ONLY
    with pytest.raises(PolicyBlockError) as exc_info:
        PolicyEngine.validate_action(
            action_type="click",
            text="Apply",
            selector="button.apply-button role=button"
        )
    assert "OBSERVE_ONLY" in str(exc_info.value)

    # 8. Naukri Apply on company site -> BLOCKED by denylist
    with pytest.raises(PolicyBlockError) as exc_info:
        PolicyEngine.validate_action(
            action_type="click",
            text="Apply on company site",
            selector="button.company-site-button id=company-site-button"
        )
    assert "apply on company" in str(exc_info.value)

# ==============================================================================
# 4. FOLLOW CHECKBOX RULES
# ==============================================================================

def test_follow_checkbox_check_denied():
    with pytest.raises(PolicyBlockError):
        PolicyEngine.validate_action("check", text="Follow Infosys", selector="input[type='checkbox']")

    with pytest.raises(PolicyBlockError):
        PolicyEngine.validate_action("click", text="Follow company", selector="button")

def test_follow_checkbox_uncheck_allowed():
    PolicyEngine.validate_action("uncheck", text="Follow Infosys", selector="input[type='checkbox']")

def test_safe_uncheck_and_verify_success():
    loc = MagicMock()
    loc.is_checked.side_effect = [True, False, False]
    safe = SafeLocator(loc, selector_hint="checkbox")
    safe.safe_uncheck_and_verify()
    assert loc.uncheck.called

def test_safe_uncheck_and_verify_failure_blocks_application():
    loc = MagicMock()
    loc.is_checked.return_value = True
    safe = SafeLocator(loc, selector_hint="checkbox")
    with pytest.raises(PolicyBlockError) as exc_info:
        safe.safe_uncheck_and_verify()
    assert "checkbox remains checked" in str(exc_info.value)

# ==============================================================================
# 5. OBSERVE_ONLY CONSTANT ENFORCEMENT
# ==============================================================================

def test_observe_only_is_code_constant():
    """
    OBSERVE_ONLY must be a top-level code constant equal to True.
    """
    assert OBSERVE_ONLY is True

def test_observe_only_mode_blocks_any_submit_and_naukri_apply():
    """
    OBSERVE_ONLY blocks:
    - Any click containing 'submit' on LinkedIn
    - Any Naukri apply button by role, text, or class
    """
    # 1. Submit by text
    with pytest.raises(PolicyBlockError):
        PolicyEngine.validate_action("click", text="Submit", selector="button")

    # 2. Submit by aria-label / selector
    with pytest.raises(PolicyBlockError):
        PolicyEngine.validate_action("click", text="", selector="button[aria-label='Submit application']")

    # 3. Submit by class name
    with pytest.raises(PolicyBlockError):
        PolicyEngine.validate_action("click", text="", selector="button.submit-btn")

    # 4. Naukri Apply by text
    with pytest.raises(PolicyBlockError):
        PolicyEngine.validate_action("click", text="Apply", selector="button")

    # 5. Naukri Apply by class
    with pytest.raises(PolicyBlockError):
        PolicyEngine.validate_action("click", text="", selector="button.apply-button")

    # 6. Naukri Apply by role
    with pytest.raises(PolicyBlockError):
        PolicyEngine.validate_action("click", text="Apply", selector="role=button")

# ==============================================================================
# 6. EXPANDED ACTION DENIALS & FILE UPLOAD BLOCKING
# ==============================================================================

def test_expanded_action_denials():
    denied = [
        ("click", "Save job"),
        ("click", "Set alert"),
        ("click", "Set job alert"),
        ("click", "Turn on"),
        ("click", "Try Premium"),
        ("click", "Get Premium"),
        ("click", "Message"),
        ("click", "Send message"),
    ]
    for action_type, text in denied:
        with pytest.raises(PolicyBlockError):
            PolicyEngine.validate_action(action_type, text=text)

def test_resume_file_upload_blocked():
    loc = MagicMock()
    safe = SafeLocator(loc, selector_hint="input[type='file']")
    with pytest.raises(PolicyBlockError) as exc_info:
        safe.safe_set_input_files("resumes/new_resume.pdf")
    assert "Uploading new resume files is strictly forbidden" in str(exc_info.value)

    with pytest.raises(PolicyBlockError):
        PolicyEngine.validate_action("click", text="Upload resume", selector="input[id*='upload-resume']")

    # Selecting existing resume radio is allowed
    PolicyEngine.validate_action("check", text="Candidate_Resume.pdf", selector="input[type='radio'][id*='jobsDocumentCardToggle']")

def test_post_submit_confirmation_success_and_unverified():
    from src.policy import verify_and_record_post_submit, UnverifiedApplicationHaltError
    db = MagicMock()
    page = MagicMock()
    page.content.return_value = "<html><body>Confirmation page</body></html>"

    # 1. Success case: Confirmation detected -> status APPLIED
    mock_success_loc = MagicMock()
    mock_success_loc.count.return_value = 1
    page.locator.return_value = mock_success_loc

    status = verify_and_record_post_submit(page, "linkedin", db, "job-123")
    assert status == "APPLIED"
    # Succeeded saving HTML and screenshot BEFORE deciding status
    page.content.assert_called()
    page.screenshot.assert_called()
    db.update_job_status.assert_called_with(platform="linkedin", job_id="job-123", status="APPLIED")

    # 2. Failure case: No confirmation detected -> status UNVERIFIED and stops run
    mock_missing_loc = MagicMock()
    mock_missing_loc.count.return_value = 0
    page.locator.return_value = mock_missing_loc

    with pytest.raises(UnverifiedApplicationHaltError):
        verify_and_record_post_submit(page, "linkedin", db, "job-456")

    db.update_job_status.assert_called_with(
        platform="linkedin",
        job_id="job-456",
        status="UNVERIFIED",
        failure_reason="Confirmation not detected on page after submit"
    )

def test_naukri_apply_blocked_even_when_observe_only_is_false():
    import src.policy as policy
    from src.policy import SafeLocator, PolicyBlockError

    mock_loc = MagicMock()
    mock_loc.inner_text.return_value = "Apply"
    safe = SafeLocator(mock_loc, selector_hint="button.apply-button")

    original_observe = policy.OBSERVE_ONLY
    try:
        policy.OBSERVE_ONLY = False
        assert policy.NAUKRI_APPLY_ENABLED is False
        with pytest.raises(PolicyBlockError) as exc_info:
            safe.safe_click()
        assert "NAUKRI_APPLY_ENABLED = False" in str(exc_info.value)
    finally:
        policy.OBSERVE_ONLY = original_observe


def test_open_to_work_and_profile_controls_denied():
    from src.policy import PolicyEngine, PolicyBlockError

    open_to_work_and_profile_controls = [
        ("click", "Open to work", "button"),
        ("click", "Open to Work", "button.profile-badge"),
        ("click", "Career interests", "a"),
        ("click", "Job-seeking visibility", "div.toggle"),
        ("click", "Edit profile", "button"),
        ("click", "Update profile", "button"),
        ("click", "Refresh profile", "button"),
        ("click", "Resume highlight", "button"),
        ("click", "Profile visibility", "input[type='checkbox']"),
        ("click", "Actively searching", "button"),
        ("click", "Share my profile with recruiter", "button"),
    ]

    for action_type, text, selector in open_to_work_and_profile_controls:
        with pytest.raises(PolicyBlockError) as exc_info:
            PolicyEngine.validate_action(action_type, text=text, selector=selector)
        assert "blocked on forbidden target" in str(exc_info.value)


def test_validate_startup_tabs_allows_whitelisted_and_aborts_on_disallowed():
    from src.browser import validate_startup_tabs
    from src.policy import CriticalPolicyViolationError

    mock_context = MagicMock()

    # 1. Allowed startup tabs: about:blank, chrome://newtab/, https://www.linkedin.com/jobs/
    p1 = MagicMock()
    p1.url = "about:blank"
    p2 = MagicMock()
    p2.url = "https://www.linkedin.com/jobs/"
    mock_context.pages = [p1, p2]

    # Must pass without error
    validate_startup_tabs(mock_context)

    # 2. Disallowed tab: LinkedIn profile (/in/...)
    p_profile = MagicMock()
    p_profile.url = "https://www.linkedin.com/in/sample-candidate-12345/"
    mock_context.pages = [p1, p_profile]
    with pytest.raises(CriticalPolicyViolationError) as exc1:
        validate_startup_tabs(mock_context)
    assert "Disallowed URL found in open browser tab at startup" in str(exc1.value)

    # 3. Disallowed tab: LinkedIn feed (/feed/...)
    p_feed = MagicMock()
    p_feed.url = "https://www.linkedin.com/feed/"
    mock_context.pages = [p1, p_feed]
    with pytest.raises(CriticalPolicyViolationError) as exc2:
        validate_startup_tabs(mock_context)
    assert "Disallowed URL found in open browser tab at startup" in str(exc2.value)

    # 4. Disallowed tab: Open to work settings
    p_otw = MagicMock()
    p_otw.url = "https://www.linkedin.com/jobs/open-to-work-settings"
    mock_context.pages = [p1, p_otw]
    with pytest.raises(CriticalPolicyViolationError) as exc3:
        validate_startup_tabs(mock_context)
    assert "Disallowed URL found in open browser tab at startup" in str(exc3.value)

    # 5. Disallowed tab: Naukri profile (/mnjuser/profile)
    p_nk = MagicMock()
    p_nk.url = "https://www.naukri.com/mnjuser/profile"
    mock_context.pages = [p1, p_nk]
    with pytest.raises(CriticalPolicyViolationError) as exc4:
        validate_startup_tabs(mock_context)
    assert "Disallowed URL found in open browser tab at startup" in str(exc4.value)


def test_cleanup_startup_tabs_closes_restored_profile_and_leaves_blank():
    from src.browser import cleanup_startup_tabs, validate_startup_tabs
    mock_context = MagicMock()
    p_profile = MagicMock()
    p_profile.url = "https://www.linkedin.com/in/sample-candidate-12345/"
    mock_context.pages = [p_profile]

    p_blank = MagicMock()
    p_blank.url = "about:blank"
    mock_context.new_page.side_effect = lambda: (mock_context.pages.append(p_blank), p_blank)[1]

    def close_profile():
        if p_profile in mock_context.pages:
            mock_context.pages.remove(p_profile)
    p_profile.close.side_effect = close_profile

    cleanup_startup_tabs(mock_context)

    assert p_profile.close.called
    assert not p_blank.close.called
    assert mock_context.pages == [p_blank]
    validate_startup_tabs(mock_context)


def test_cleanup_startup_tabs_closes_restored_feed_and_leaves_blank():
    from src.browser import cleanup_startup_tabs, validate_startup_tabs
    mock_context = MagicMock()
    p_feed = MagicMock()
    p_feed.url = "https://www.linkedin.com/feed/"
    mock_context.pages = [p_feed]

    p_blank = MagicMock()
    p_blank.url = "about:blank"
    mock_context.new_page.side_effect = lambda: (mock_context.pages.append(p_blank), p_blank)[1]

    def close_feed():
        if p_feed in mock_context.pages:
            mock_context.pages.remove(p_feed)
    p_feed.close.side_effect = close_feed

    cleanup_startup_tabs(mock_context)

    assert p_feed.close.called
    assert not p_blank.close.called
    assert mock_context.pages == [p_blank]
    validate_startup_tabs(mock_context)


def test_cleanup_startup_tabs_closes_empty_url_that_later_loads_profile():
    from src.browser import cleanup_startup_tabs, validate_startup_tabs
    mock_context = MagicMock()
    p_loading = MagicMock()
    p_loading.url = ""
    mock_context.pages = [p_loading]

    p_blank = MagicMock()
    p_blank.url = "about:blank"
    mock_context.new_page.side_effect = lambda: (mock_context.pages.append(p_blank), p_blank)[1]

    closed = False
    def close_loading():
        nonlocal closed
        closed = True
        if p_loading in mock_context.pages:
            mock_context.pages.remove(p_loading)
    p_loading.close.side_effect = close_loading

    cleanup_startup_tabs(mock_context)

    assert closed
    assert p_loading.close.called
    assert mock_context.pages == [p_blank]
    validate_startup_tabs(mock_context)


def test_login_path_flow_and_subsequent_run_feed_cleanup():
    from src.browser import cleanup_startup_tabs, validate_startup_tabs
    from src.policy import PolicyEngine
    # 1. Login path: allowlisted login URLs
    mock_context = MagicMock()
    p_initial = MagicMock()
    p_initial.url = "about:blank"
    mock_context.pages = [p_initial]

    cleanup_startup_tabs(mock_context)
    validate_startup_tabs(mock_context)

    # In login flow, user navigates to login pages:
    PolicyEngine.validate_navigation("https://www.linkedin.com/login")
    PolicyEngine.validate_navigation("https://www.naukri.com/nlogin/login")

    # After login, LinkedIn lands on /feed/ and context is saved to disk
    p_feed_saved = MagicMock()
    p_feed_saved.url = "https://www.linkedin.com/feed/"
    mock_context.pages = [p_feed_saved]

    # 2. Next run: browser restores /feed/ tab
    p_next_blank = MagicMock()
    p_next_blank.url = "about:blank"
    mock_context.new_page.side_effect = lambda: (mock_context.pages.append(p_next_blank), p_next_blank)[1]

    def close_feed_saved():
        if p_feed_saved in mock_context.pages:
            mock_context.pages.remove(p_feed_saved)
    p_feed_saved.close.side_effect = close_feed_saved

    cleanup_startup_tabs(mock_context)
    assert p_feed_saved.close.called
    assert mock_context.pages == [p_next_blank]
    validate_startup_tabs(mock_context)


def test_broadened_open_to_work_and_preference_patterns():
    from src.policy import PolicyEngine, SafeLocator, PolicyBlockError

    # 1. Text variants:
    text_variants = [
        "open to work",
        "open-to-work",
        "open_to_work",
        "OpenToWork",
        "#OpenToWork",
        "job search preferences",
        "job-search-preferences",
        "let recruiters know",
        "hiring preferences",
    ]
    for text in text_variants:
        with pytest.raises(PolicyBlockError) as exc:
            PolicyEngine.validate_action("click", text=text, selector="button")
        assert "blocked on forbidden target" in str(exc.value)

    # 2. Inside class names:
    class_variants = [
        "btn open-to-work-badge",
        "toggle-open_to_work",
        "badge-OpenToWork",
        "section-#OpenToWork",
        "btn job-search-preferences",
        "recruiters-let-recruiters-know-link",
        "pref hiring-preferences-box",
    ]
    for cls in class_variants:
        mock_loc = MagicMock()
        mock_loc.inner_text.return_value = "Click Here"
        mock_loc.get_attribute.side_effect = lambda attr, timeout=None: cls if attr == "class" else ""
        safe = SafeLocator(mock_loc, selector_hint="button")
        with pytest.raises(PolicyBlockError) as exc:
            safe.safe_click()
        assert "blocked on forbidden target" in str(exc.value)

    # 3. Inside IDs:
    id_variants = [
        "open-to-work",
        "open_to_work",
        "OpenToWork",
        "#OpenToWork",
        "job-search-preferences",
        "let-recruiters-know",
        "hiring-preferences",
    ]
    for elem_id in id_variants:
        mock_loc = MagicMock()
        mock_loc.inner_text.return_value = "Enable"
        mock_loc.get_attribute.side_effect = lambda attr, timeout=None: elem_id if attr == "id" else ""
        safe = SafeLocator(mock_loc, selector_hint="div")
        with pytest.raises(PolicyBlockError) as exc:
            safe.safe_click()
        assert "blocked on forbidden target" in str(exc.value)

    # 4. Inside aria-label:
    aria_variants = [
        "Open to work",
        "OpenToWork toggle",
        "job search preferences",
        "let recruiters know you are available",
        "hiring preferences settings",
    ]
    for aria in aria_variants:
        mock_loc = MagicMock()
        mock_loc.inner_text.return_value = ""
        mock_loc.get_attribute.side_effect = lambda attr, timeout=None: aria if attr == "aria-label" else ""
        safe = SafeLocator(mock_loc, selector_hint="button")
        with pytest.raises(PolicyBlockError) as exc:
            safe.safe_click()
        assert "blocked on forbidden target" in str(exc.value)


def test_post_apply_dialog_allows_only_dismiss_close_done():
    from src.policy import PolicyEngine, SafeLocator, PolicyBlockError

    dialog_text = (
        "Application sent! Let recruiters know you're open to work and update your "
        "job search preferences to be discovered for more roles."
    )

    assert PolicyEngine.is_sensitive_modal(dialog_text)

    # 1. Non-dismiss actions must be BLOCKED
    forbidden_actions = ["Turn on", "Update preferences", "Save", "Yes", "Next", "Confirm", "Submit"]
    for act in forbidden_actions:
        with pytest.raises(PolicyBlockError) as exc:
            PolicyEngine.validate_modal_action(dialog_text, action_text=act)
        assert "The only allowed action is Dismiss/Close/Done" in str(exc.value)

        mock_btn = MagicMock()
        mock_btn.inner_text.return_value = act
        mock_btn.get_attribute.return_value = ""
        safe_btn = SafeLocator(mock_btn, selector_hint="button", dialog_text=dialog_text)
        with pytest.raises(PolicyBlockError) as exc2:
            safe_btn.safe_click()
        assert "The only allowed action is Dismiss/Close/Done" in str(exc2.value)

    # 2. Allowed actions (Dismiss, Close, Done) must PASS
    allowed_actions = ["Dismiss", "dismiss", "Close", "close", "Done", "done"]
    for act in allowed_actions:
        PolicyEngine.validate_modal_action(dialog_text, action_text=act)

        mock_btn = MagicMock()
        mock_btn.inner_text.return_value = act
        mock_btn.get_attribute.return_value = ""
        safe_btn = SafeLocator(mock_btn, selector_hint="button", dialog_text=dialog_text)
        safe_btn.safe_click()
        assert mock_btn.click.called


def test_handle_post_apply_dialog_safely_dismisses():
    from src.policy import handle_post_apply_dialog

    fake_page = MagicMock()
    fake_dialogs = MagicMock()
    fake_dialog = MagicMock()
    fake_dialogs.count.return_value = 1
    fake_dialog.count.return_value = 1
    fake_dialogs.first = fake_dialog

    fake_dialog.inner_text.return_value = (
        "Application sent! Let recruiters know you're open to work."
    )

    fake_dismiss_btn = MagicMock()
    fake_dismiss_btn.count.return_value = 1
    fake_dismiss_btn.inner_text.return_value = "Dismiss"
    fake_dismiss_btn.get_attribute.return_value = "artdeco-modal__dismiss"

    fake_dialog.locator.return_value.first = fake_dismiss_btn
    fake_page.locator.return_value = fake_dialogs

    result = handle_post_apply_dialog(fake_page)
    assert result == "dismissed"
    assert fake_dismiss_btn.click.called


def test_real_snapshot_modal_narrowing():
    from pathlib import Path
    from src.policy import PolicyEngine, SafeLocator, PolicyBlockError

    # Real Easy Apply dialog text containing screening questions and recruiter mention
    # e.g., "Your application will be sent to the recruiter. How many years of experience do you have with Node.js?"
    in_flow_dialog_with_recruiter = (
        "Easy Apply: Senior Full Stack Engineer\n"
        "Contact info\n"
        "Your profile and answers will be reviewed by the job recruiter.\n"
        "Are you proficient in JavaScript?\n"
        "How many years of work experience do you have with Node.js?"
    )

    # During in-flow form step (is_post_apply=False), presence of the word 'recruiter' must NOT block form progression
    assert PolicyEngine.is_sensitive_modal(in_flow_dialog_with_recruiter, is_post_apply=False) is False

    # Normal form actions ("Next", "Continue to next step", "Review your application") pass without error
    PolicyEngine.validate_modal_action(in_flow_dialog_with_recruiter, action_text="Next", is_post_apply=False)
    PolicyEngine.validate_modal_action(in_flow_dialog_with_recruiter, action_text="Continue to next step", is_post_apply=False)
    PolicyEngine.validate_modal_action(in_flow_dialog_with_recruiter, action_text="Review your application", is_post_apply=False)

    # However, after submit (is_post_apply=True), recruiter prompts ARE flagged as sensitive
    post_apply_recruiter_text = "Your application was sent. Connect with the recruiter who posted this job."
    assert PolicyEngine.is_sensitive_modal(post_apply_recruiter_text, is_post_apply=True) is True

    # Non-dismiss actions are blocked post-apply
    with pytest.raises(PolicyBlockError) as exc:
        PolicyEngine.validate_modal_action(post_apply_recruiter_text, action_text="Connect", is_post_apply=True)
    assert "The only allowed action is Dismiss/Close/Done" in str(exc.value)

    # Dismiss / Discard actions are allowed post-apply
    PolicyEngine.validate_modal_action(post_apply_recruiter_text, action_text="Dismiss", is_post_apply=True)
    PolicyEngine.validate_modal_action(post_apply_recruiter_text, action_text="Discard", is_post_apply=True)

    # Open to Work wording is ALWAYS blocked even in-flow (is_post_apply=False)
    in_flow_otw = "Update your profile with #OpenToWork to get noticed."
    assert PolicyEngine.is_sensitive_modal(in_flow_otw, is_post_apply=False) is True
    with pytest.raises(PolicyBlockError):
        PolicyEngine.validate_modal_action(in_flow_otw, action_text="Next", is_post_apply=False)


def test_ensure_clean_tabs_handles_tab_appearing_after_cleanup():
    from src.browser import ensure_clean_tabs
    from src.policy import CriticalPolicyViolationError

    mock_context = MagicMock()
    blank_page = MagicMock()
    blank_page.url = "about:blank"

    # Simulate an asynchronous tab appearing after launch that points to the LinkedIn feed
    restored_feed_page = MagicMock()
    restored_feed_page.url = "https://www.linkedin.com/feed/"

    mock_context.pages = [blank_page, restored_feed_page]

    # ensure_clean_tabs must close the restored feed page before navigation
    ensure_clean_tabs(mock_context)
    restored_feed_page.close.assert_called_once()
    blank_page.close.assert_not_called()


