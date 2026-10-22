import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.platforms.indeed import IndeedCollector, IndeedApplicant
from src.matcher import JobMatcher, MatchResult
from src.guards import GuardsManager, DailyCapReachedError
from src.policy import PolicyEngine, PolicyBlockError, OBSERVE_ONLY


# ==============================================================================
# 1. URL BUILDER TESTS
# ==============================================================================

def test_indeed_collector_build_search_url_default():
    db = MagicMock()
    guards = MagicMock()
    matcher = MagicMock()
    collector = IndeedCollector(db, guards, matcher)

    query = {
        "keywords": "Senior Full Stack Developer",
        "location": "India",
        "iafilter": True,
    }
    url = collector.build_search_url(query)
    assert url.startswith("https://in.indeed.com/jobs?")
    assert "q=Senior+Full+Stack+Developer" in url
    assert "l=India" in url
    assert "iafilter=1" in url
    assert "filter=0" in url


def test_indeed_collector_build_search_url_dubai_uae():
    db = MagicMock()
    guards = MagicMock()
    matcher = MagicMock()
    collector = IndeedCollector(db, guards, matcher)

    # Dubai location
    query_dubai = {
        "keywords": "Full Stack Developer",
        "location": "Dubai, UAE",
        "iafilter": True,
    }
    url_dubai = collector.build_search_url(query_dubai)
    assert url_dubai.startswith("https://ae.indeed.com/jobs?")
    assert "q=Full+Stack+Developer" in url_dubai
    assert "iafilter=1" in url_dubai

    # UAE location
    query_uae = {
        "keywords": "Python Engineer",
        "location": "United Arab Emirates",
        "iafilter": False,
    }
    url_uae = collector.build_search_url(query_uae)
    assert url_uae.startswith("https://ae.indeed.com/jobs?")
    assert "iafilter=1" not in url_uae


def test_indeed_collector_build_search_url_custom_domain():
    db = MagicMock()
    guards = MagicMock()
    matcher = MagicMock()
    collector = IndeedCollector(db, guards, matcher)

    query = {
        "keywords": "Software Engineer",
        "location": "London",
        "domain": "uk.indeed.com",
    }
    url = collector.build_search_url(query)
    assert url.startswith("https://uk.indeed.com/jobs?")


# ==============================================================================
# 2. CARD DATA EXTRACTION TESTS
# ==============================================================================

def test_indeed_collector_extract_job_card_data_success():
    db = MagicMock()
    guards = MagicMock()
    matcher = MagicMock()
    collector = IndeedCollector(db, guards, matcher)

    card = MagicMock()
    card.get_attribute.side_effect = lambda attr: "jk_abc123" if attr == "data-jk" else None

    # Title
    title_elem = MagicMock()
    title_elem.count.return_value = 1
    title_elem.inner_text.return_value = "Lead Full Stack Developer"

    # Company
    comp_elem = MagicMock()
    comp_elem.count.return_value = 1
    comp_elem.inner_text.return_value = "Acme Global Tech"

    # Location
    loc_elem = MagicMock()
    loc_elem.count.return_value = 1
    loc_elem.inner_text.return_value = "Dubai"

    # Easily Apply badge
    apply_badge = MagicMock()
    apply_badge.count.return_value = 1

    def locator_side_effect(selector):
        loc = MagicMock()
        if "jobTitle" in selector or "jcs-JobTitle" in selector:
            loc.first = title_elem
        elif "company-name" in selector or "companyName" in selector:
            loc.first = comp_elem
        elif "location" in selector:
            loc.first = loc_elem
        elif "indeedApply" in selector or "Easily apply" in selector:
            loc.first = apply_badge
        else:
            empty = MagicMock()
            empty.count.return_value = 0
            loc.first = empty
        return loc

    card.locator.side_effect = locator_side_effect

    data = collector.extract_job_card_data(card, default_domain="ae.indeed.com")
    assert data is not None
    assert data["job_id"] == "jk_abc123"
    assert data["title"] == "Lead Full Stack Developer"
    assert data["company"] == "Acme Global Tech"
    assert data["location"] == "Dubai"
    assert data["is_easily_apply"] is True
    assert data["url"] == "https://ae.indeed.com/viewjob?jk=jk_abc123"


def test_indeed_collector_extract_job_card_data_external_apply():
    db = MagicMock()
    guards = MagicMock()
    matcher = MagicMock()
    collector = IndeedCollector(db, guards, matcher)

    card = MagicMock()
    card.get_attribute.side_effect = lambda attr: "jk_external99" if attr == "data-jk" else None

    title_elem = MagicMock(count=lambda: 1, inner_text=lambda: "Backend Dev")
    comp_elem = MagicMock(count=lambda: 1, inner_text=lambda: "External Corp")
    loc_elem = MagicMock(count=lambda: 1, inner_text=lambda: "Bengaluru")
    no_apply = MagicMock(count=lambda: 0)

    def locator_side_effect(selector):
        loc = MagicMock()
        if "jobTitle" in selector:
            loc.first = title_elem
        elif "company-name" in selector:
            loc.first = comp_elem
        elif "location" in selector:
            loc.first = loc_elem
        elif "indeedApply" in selector or "Easily apply" in selector:
            loc.first = no_apply
        else:
            loc.first = MagicMock(count=lambda: 0)
        return loc

    card.locator.side_effect = locator_side_effect

    data = collector.extract_job_card_data(card, default_domain="in.indeed.com")
    assert data is not None
    assert data["job_id"] == "jk_external99"
    assert data["is_easily_apply"] is False


def test_indeed_collector_extract_job_card_data_missing_id():
    db = MagicMock()
    guards = MagicMock()
    matcher = MagicMock()
    collector = IndeedCollector(db, guards, matcher)

    card = MagicMock()
    card.get_attribute.return_value = None
    empty = MagicMock(count=lambda: 0)
    card.locator.return_value.first = empty

    data = collector.extract_job_card_data(card)
    assert data is None


# ==============================================================================
# 3. COLLECTOR FLOW & GUARDS
# ==============================================================================

def test_indeed_collector_skips_external_site():
    db = MagicMock()
    guards = MagicMock()
    matcher = MagicMock()
    collector = IndeedCollector(db, guards, matcher)

    db.is_job_eligible.return_value = True

    # Card with is_easily_apply = False
    card_data = {
        "job_id": "ext_123",
        "title": "Full Stack Dev",
        "company": "Offsite Tech",
        "location": "India",
        "is_easily_apply": False,
        "url": "https://in.indeed.com/viewjob?jk=ext_123",
    }
    collector.extract_job_card_data = MagicMock(return_value=card_data)

    mock_card = MagicMock()
    cards_loc = MagicMock()
    cards_loc.count.return_value = 1
    cards_loc.nth.return_value = mock_card

    page = MagicMock()
    page.locator.return_value = cards_loc

    applicant = MagicMock()
    collector.run_search_and_apply(page, {"keywords": "Dev"}, applicant=applicant, max_jobs=1)

    # Verifies EXTERNAL_SITE recorded and applicant never called
    db.record_job.assert_called_once()
    call_kwargs = db.record_job.call_args[1]
    assert call_kwargs["status"] == "EXTERNAL_SITE"
    assert call_kwargs["job_id"] == "ext_123"
    applicant.process_application.assert_not_called()


def test_indeed_collector_skips_same_company_applied_recently():
    db = MagicMock()
    guards = MagicMock()
    matcher = MagicMock()
    collector = IndeedCollector(db, guards, matcher)

    db.is_job_eligible.return_value = True
    guards.can_apply_to_company.return_value = (False, "Applied 2 days ago")

    card_data = {
        "job_id": "same_comp_123",
        "title": "Senior Engineer",
        "company": "Enterprise Bot",
        "location": "India",
        "is_easily_apply": True,
        "url": "https://in.indeed.com/viewjob?jk=same_comp_123",
    }
    collector.extract_job_card_data = MagicMock(return_value=card_data)

    mock_card = MagicMock()
    cards_loc = MagicMock(count=lambda: 1, nth=lambda i: mock_card)
    page = MagicMock()
    page.locator.return_value = cards_loc

    applicant = MagicMock()
    collector.run_search_and_apply(page, {"keywords": "Dev"}, applicant=applicant, max_jobs=1)

    db.record_job.assert_called_once()
    call_kwargs = db.record_job.call_args[1]
    assert call_kwargs["status"] == "SKIPPED"
    assert call_kwargs["failure_reason"] == "SAME_COMPANY_RECENTLY_APPLIED"
    applicant.process_application.assert_not_called()


def test_indeed_collector_skips_already_ineligible_job():
    db = MagicMock()
    guards = MagicMock()
    matcher = MagicMock()
    collector = IndeedCollector(db, guards, matcher)

    db.is_job_eligible.return_value = False  # Already in DB / applied

    card_data = {
        "job_id": "already_applied_1",
        "title": "Engineer",
        "company": "Some Company",
        "location": "India",
        "is_easily_apply": True,
        "url": "https://in.indeed.com/viewjob?jk=already_applied_1",
    }
    collector.extract_job_card_data = MagicMock(return_value=card_data)

    mock_card = MagicMock()
    cards_loc = MagicMock(count=lambda: 1, nth=lambda i: mock_card)
    page = MagicMock()
    page.locator.return_value = cards_loc

    applicant = MagicMock()
    collector.run_search_and_apply(page, {"keywords": "Dev"}, applicant=applicant, max_jobs=1)

    # Neither record_job nor applicant should be triggered
    db.record_job.assert_not_called()
    applicant.process_application.assert_not_called()


# ==============================================================================
# 4. APPLICANT LOCATE APPLY BUTTON TESTS
# ==============================================================================

def test_indeed_applicant_locate_apply_button_direct():
    db = MagicMock()
    guards = MagicMock()
    applicant = IndeedApplicant(db, guards)

    page = MagicMock()
    btn = MagicMock(count=lambda: 1, inner_text=lambda: "Apply now")
    page.locator.return_value.first = btn

    found_btn, desc = applicant.locate_apply_button(page)
    assert found_btn is not None
    assert desc == "Apply now"


def test_indeed_applicant_locate_apply_button_external_site():
    db = MagicMock()
    guards = MagicMock()
    applicant = IndeedApplicant(db, guards)

    page = MagicMock()
    empty = MagicMock(count=lambda: 0)
    ext_btn = MagicMock(count=lambda: 1, inner_text=lambda: "Apply on company site")

    def locator_side_effect(sel):
        loc = MagicMock()
        if "indeedApply" in sel or "Apply now" in sel:
            loc.first = empty
        elif "company site" in sel:
            loc.first = ext_btn
        else:
            loc.first = empty
        return loc

    page.locator.side_effect = locator_side_effect

    found_btn, desc = applicant.locate_apply_button(page)
    assert found_btn is None
    assert desc == "EXTERNAL_SITE"


# ==============================================================================
# 5. SAME COMPANY GUARD IN APPLICANT
# ==============================================================================

def test_indeed_applicant_same_company_guard_blocks_application():
    db = MagicMock()
    guards = MagicMock()
    applicant = IndeedApplicant(db, guards)

    # Guards reports company applied recently within 7 days
    guards.can_apply_to_company.return_value = (False, "Applied to Jobgether 3 days ago")

    page = MagicMock()
    res = applicant.process_application(
        page=page,
        job_id="job_same_comp",
        title="Full Stack Developer",
        company="Jobgether"
    )

    assert res["status"] == "SKIPPED"
    assert res["reason"] == "SAME_COMPANY_RECENTLY_APPLIED"
    db.update_job_status.assert_called_once_with(
        platform="indeed",
        job_id="job_same_comp",
        status="SKIPPED",
        failure_reason="SAME_COMPANY_RECENTLY_APPLIED"
    )
    # Page navigation shouldn't occur
    page.goto.assert_not_called()


# ==============================================================================
# 6. SCREENING & CONSENT GUARD TESTS
# ==============================================================================

def test_indeed_applicant_consent_guard_blocks_unapproved():
    db = MagicMock()
    guards = MagicMock()
    answerer = MagicMock()
    applicant = IndeedApplicant(db, guards, answerer=answerer)

    container = MagicMock()

    # Input asking unapproved consent question
    inp = MagicMock()
    inp.get_attribute.side_effect = lambda attr: "q_consent" if attr == "id" else None
    inputs_loc = MagicMock(count=lambda: 1, nth=lambda i: inp)

    lbl = MagicMock(count=lambda: 1, inner_text=lambda: "Do you agree to the privacy policy and terms?")
    def loc_side_effect(sel):
        loc = MagicMock()
        if "input" in sel:
            return inputs_loc
        elif "label" in sel:
            loc.first = lbl
            return loc
        elif "fieldset" in sel:
            loc.count.return_value = 0
            return loc
        return loc

    container.locator.side_effect = loc_side_effect

    answerer.is_consent_question.return_value = True
    answerer.find_direct_answer.return_value = None  # No user_approved_consent entry

    ok, pending_q = applicant.answer_screening_fields(container)
    assert ok is False
    assert "CONSENT_GUARD" in pending_q


def test_indeed_applicant_consent_guard_allows_approved():
    db = MagicMock()
    guards = MagicMock()
    answerer = MagicMock()
    applicant = IndeedApplicant(db, guards, answerer=answerer)

    container = MagicMock()

    inp = MagicMock()
    inp.get_attribute.side_effect = lambda attr: "q_consent" if attr == "id" else None
    inputs_loc = MagicMock(count=lambda: 1, nth=lambda i: inp)
    lbl = MagicMock(count=lambda: 1, inner_text=lambda: "Do you agree with terms?")

    def loc_side_effect(sel):
        loc = MagicMock()
        if "input" in sel:
            return inputs_loc
        elif "label" in sel:
            loc.first = lbl
            return loc
        elif "fieldset" in sel:
            loc.count.return_value = 0
            return loc
        return loc

    container.locator.side_effect = loc_side_effect

    answerer.is_consent_question.return_value = True
    answerer.find_direct_answer.return_value = "Yes"
    answerer.answer_question.return_value = "Yes"

    ok, pending_q = applicant.answer_screening_fields(container)
    assert ok is True
    assert pending_q is None
    inp.fill.assert_called_with("Yes")


def test_indeed_applicant_unanswered_required_field_triggers_needs_input():
    db = MagicMock()
    guards = MagicMock()
    answerer = MagicMock()
    applicant = IndeedApplicant(db, guards, answerer=answerer)

    container = MagicMock()

    inp = MagicMock()
    inp.get_attribute.side_effect = lambda attr: "q_custom" if attr == "id" else ("required" if attr == "required" else None)
    inputs_loc = MagicMock(count=lambda: 1, nth=lambda i: inp)
    lbl = MagicMock(count=lambda: 1, inner_text=lambda: "What is your desired hourly rate in AED? *")

    def loc_side_effect(sel):
        loc = MagicMock()
        if "input" in sel:
            return inputs_loc
        elif "label" in sel:
            loc.first = lbl
            return loc
        elif "fieldset" in sel:
            loc.count.return_value = 0
            return loc
        return loc

    container.locator.side_effect = loc_side_effect

    answerer.is_consent_question.return_value = False
    answerer.answer_question.return_value = "UNKNOWN"

    ok, pending_q = applicant.answer_screening_fields(container)
    assert ok is False
    assert "hourly rate" in pending_q


# ==============================================================================
# 7. REVIEW STEP & REHEARSAL / LIVE CONFIRMATION TESTS
# ==============================================================================

def test_indeed_applicant_review_step_rehearsal_mode_blocks_submit():
    db = MagicMock()
    guards = MagicMock()
    guards.can_apply_to_company.return_value = (True, "")

    # Rehearsal mode active
    applicant = IndeedApplicant(db, guards, is_rehearsal=True)

    page = MagicMock()
    apply_btn = MagicMock(count=lambda: 1, inner_text=lambda: "Apply now")
    applicant.locate_apply_button = MagicMock(return_value=(apply_btn, "Apply now"))

    # Mock container at review step
    container = MagicMock()
    applicant.locate_application_container = MagicMock(return_value=container)
    applicant.is_review_step = MagicMock(return_value=True)

    with patch("builtins.input") as mock_input:
        res = applicant.process_application(
            page=page,
            job_id="job_rehearsal_1",
            title="Senior Engineer",
            company="Global Tech",
            url="https://in.indeed.com/viewjob?jk=job_rehearsal_1"
        )

    # In rehearsal mode, input prompt must NOT be called, and submit must be blocked
    mock_input.assert_not_called()
    assert res["status"] == "OBSERVED_REVIEW"
    db.update_job_status.assert_called_with(
        platform="indeed",
        job_id="job_rehearsal_1",
        status="OBSERVED_REVIEW"
    )


def test_indeed_applicant_live_review_typed_yes_submits():
    db = MagicMock()
    guards = MagicMock()
    guards.can_apply_to_company.return_value = (True, "")

    # Live review mode: review_mode=True, is_rehearsal=False, OBSERVE_ONLY=False
    applicant = IndeedApplicant(db, guards, review_mode=True, is_rehearsal=False)
    applicant.observe_only = False

    page = MagicMock()
    apply_btn = MagicMock(count=lambda: 1, inner_text=lambda: "Apply now")
    applicant.locate_apply_button = MagicMock(return_value=(apply_btn, "Apply now"))

    container = MagicMock()
    applicant.locate_application_container = MagicMock(return_value=container)
    applicant.is_review_step = MagicMock(return_value=True)

    submit_btn = MagicMock(count=lambda: 1)
    container.locator.return_value.first = submit_btn

    with patch("builtins.input", return_value="YES"), \
         patch("src.policy.verify_and_record_post_submit", return_value="APPLIED"):
        res = applicant.process_application(
            page=page,
            job_id="job_live_1",
            title="Senior Full Stack",
            company="Dubai Software LLC",
            url="https://ae.indeed.com/viewjob?jk=job_live_1"
        )

    assert res["status"] == "APPLIED"
    submit_btn.click.assert_called_once()
    guards.record_application_success.assert_called_once()


def test_indeed_applicant_live_review_user_cancel():
    db = MagicMock()
    guards = MagicMock()
    guards.can_apply_to_company.return_value = (True, "")

    applicant = IndeedApplicant(db, guards, review_mode=True, is_rehearsal=False)
    applicant.observe_only = False

    page = MagicMock()
    apply_btn = MagicMock(count=lambda: 1, inner_text=lambda: "Apply now")
    applicant.locate_apply_button = MagicMock(return_value=(apply_btn, "Apply now"))

    container = MagicMock()
    applicant.locate_application_container = MagicMock(return_value=container)
    applicant.is_review_step = MagicMock(return_value=True)

    with patch("builtins.input", return_value="NO"):
        res = applicant.process_application(
            page=page,
            job_id="job_cancel_1",
            title="Senior Full Stack",
            company="Dubai Software LLC",
            url="https://ae.indeed.com/viewjob?jk=job_cancel_1"
        )

    assert res["status"] == "SKIPPED_BY_USER"
    guards.record_application_success.assert_not_called()


# ==============================================================================
# 8. POLICY ALLOWLIST & GUARDS DAILY CAP TESTS
# ==============================================================================

def test_indeed_policy_allowlisted_urls():
    valid_urls = [
        "https://in.indeed.com/jobs?q=Senior+Full+Stack+Developer&l=India&iafilter=1",
        "https://ae.indeed.com/jobs?q=Full+Stack&l=Dubai&filter=0",
        "https://www.indeed.com/viewjob?jk=1234567890abcdef",
        "https://in.indeed.com/m/viewjob?jk=1234567890abcdef",
        "https://smartapply.indeed.com/beta/indeedapply/form/123",
        "https://secure.indeed.com/account/login",
    ]
    for url in valid_urls:
        PolicyEngine.validate_navigation(url)


def test_indeed_policy_blocks_unauthorized_urls():
    blocked_urls = [
        "https://unauthorized-domain.com/jobs",
        "https://www.indeed.com/hire",  # employer portal
        "https://indeed.com/resumes",   # resume search portal
    ]
    for url in blocked_urls:
        with pytest.raises(PolicyBlockError):
            PolicyEngine.validate_navigation(url)


def test_indeed_guards_daily_cap_enforced():
    class FakeDB:
        def get_applied_count_today(self, platform):
            return 15 if platform == "indeed" else 0

    db = FakeDB()
    mgr = GuardsManager(db)
    mgr.settings["timing"]["working_hours"]["enabled"] = False
    mgr.settings["caps"]["indeed_daily_cap"] = 15

    with pytest.raises(DailyCapReachedError):
        mgr.check_pre_job_guards("indeed")
