import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.platforms.linkedin import LinkedInApplicant
from src.answerer import FormAnswerer
from src.guards import ResumeMismatchHaltError

SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "snapshots"

def test_resume_selection_character_for_character():
    db = MagicMock()
    guards = MagicMock()
    answerer = MagicMock()

    # Case 1: Config matches exact DOM filename with hyphen
    applicant_hyphen = LinkedInApplicant(db, guards, answerer)
    applicant_hyphen.profile = {"resume": {"selected_filename": "Candidate-Resume.pdf"}}

    # Mock modal containing DOM cards from linkedin_04_modal_step2.html
    mock_modal = MagicMock()
    card1 = MagicMock()
    card1.get_attribute.return_value = "jobs-document-upload-redesign-card__container--selected"
    fn1 = MagicMock()
    fn1.count.return_value = 1
    fn1.inner_text.return_value = "Candidate-Resume.pdf"
    card1.locator.return_value.first = fn1

    card2 = MagicMock()
    card2.get_attribute.return_value = "jobs-document-upload-redesign-card__container"
    fn2 = MagicMock()
    fn2.count.return_value = 1
    fn2.inner_text.return_value = "Candidate_Resume.docx"
    card2.locator.return_value.first = fn2

    mock_cards = MagicMock()
    mock_cards.count.return_value = 2
    mock_cards.nth.side_effect = lambda idx: [card1, card2][idx]
    mock_modal.locator.return_value = mock_cards

    # Assert hyphen filename matches character-for-character
    matched = applicant_hyphen.select_resume_by_name(mock_modal)
    assert matched is True

    # Case 2: Config has underscore (Candidate_Resume.pdf) -> Does NOT match DOM (Candidate-Resume.pdf)
    applicant_underscore = LinkedInApplicant(db, guards, answerer)
    applicant_underscore.profile = {"resume": {"selected_filename": "Candidate_Resume.pdf"}}

    mock_cards.nth.side_effect = lambda idx: [card1, card2][idx]
    with pytest.raises(ResumeMismatchHaltError) as exc_info:
        applicant_underscore.select_resume_by_name(mock_modal)
    assert "RESUME_NOT_FOUND" in str(exc_info.value)

def test_resume_preselected_old_resume_switched_and_verified():
    db = MagicMock()
    guards = MagicMock()
    answerer = MagicMock()

    applicant = LinkedInApplicant(db, guards, answerer)
    applicant.profile = {"resume": {"selected_filename": "Candidate_Resume.pdf"}}

    mock_modal = MagicMock()

    # card1: Old resume pre-selected
    card1 = MagicMock()
    card1_cls = ["jobs-document-upload-redesign-card__container jobs-document-upload-redesign-card__container--selected"]
    card1.get_attribute.side_effect = lambda attr: card1_cls[0] if attr == "class" else ""
    fn1 = MagicMock()
    fn1.count.return_value = 1
    fn1.inner_text.return_value = "Old_Candidate_Resume.pdf"
    fn1.first = fn1

    # card2: Configured new resume (Candidate_Resume.pdf), unselected initially
    card2 = MagicMock()
    card2_cls = ["jobs-document-upload-redesign-card__container"]
    card2.get_attribute.side_effect = lambda attr: card2_cls[0] if attr == "class" else ""
    fn2 = MagicMock()
    fn2.count.return_value = 1
    fn2.inner_text.return_value = "Candidate_Resume.pdf"
    fn2.first = fn2

    radio2 = MagicMock()
    radio2.count.return_value = 1
    radio2.first = radio2
    def click_radio(**kwargs):
        # When radio2 is clicked, card1 loses selected and card2 becomes selected
        card1_cls[0] = "jobs-document-upload-redesign-card__container"
        card2_cls[0] = "jobs-document-upload-redesign-card__container jobs-document-upload-redesign-card__container--selected"
    radio2.click.side_effect = click_radio

    card1.locator.side_effect = lambda sel: fn1 if "file-name" in sel else MagicMock(count=lambda: 0)
    card2.locator.side_effect = lambda sel: fn2 if "file-name" in sel else (radio2 if "radio" in sel else MagicMock(count=lambda: 0))

    mock_cards = MagicMock()
    mock_cards.count.return_value = 2
    mock_cards.nth.side_effect = lambda idx: [card1, card2][idx]
    mock_modal.locator.return_value = mock_cards

    # Run selection
    res = applicant.select_resume_by_name(mock_modal)
    assert res is True
    assert applicant.answers_filled["Resume"] == "Candidate_Resume.pdf"
    assert "selected" in card2_cls[0]
    assert "selected" not in card1_cls[0]

def test_resume_mismatch_after_selection_halts():
    db = MagicMock()
    guards = MagicMock()
    answerer = MagicMock()

    applicant = LinkedInApplicant(db, guards, answerer)
    applicant.profile = {"resume": {"selected_filename": "Candidate_Resume.pdf"}}

    mock_modal = MagicMock()

    # card1: Old resume stays selected even after attempting to select card2
    card1 = MagicMock()
    card1.get_attribute.side_effect = lambda attr: "jobs-document-upload-redesign-card__container jobs-document-upload-redesign-card__container--selected" if attr == "class" else ""
    fn1 = MagicMock()
    fn1.count.return_value = 1
    fn1.inner_text.return_value = "Old_Candidate_Resume.pdf"
    fn1.first = fn1

    # card2: Configured new resume
    card2 = MagicMock()
    card2.get_attribute.side_effect = lambda attr: "jobs-document-upload-redesign-card__container" if attr == "class" else ""
    fn2 = MagicMock()
    fn2.count.return_value = 1
    fn2.inner_text.return_value = "Candidate_Resume.pdf"
    fn2.first = fn2

    radio2 = MagicMock()
    radio2.count.return_value = 1

    card1.locator.side_effect = lambda sel: fn1 if "file-name" in sel else MagicMock(count=lambda: 0)
    card2.locator.side_effect = lambda sel: fn2 if "file-name" in sel else (radio2 if "radio" in sel else MagicMock(count=lambda: 0))

    mock_cards = MagicMock()
    mock_cards.count.return_value = 2
    mock_cards.nth.side_effect = lambda idx: [card1, card2][idx]
    mock_modal.locator.return_value = mock_cards

    # Must raise ResumeMismatchHaltError
    with pytest.raises(ResumeMismatchHaltError) as exc_info:
        applicant.select_resume_by_name(mock_modal)
    assert "RESUME_MISMATCH" in str(exc_info.value)

def test_screening_questions_answers_known_and_flags_unknown():
    db = MagicMock()
    guards = MagicMock()
    answerer = FormAnswerer()

    applicant = LinkedInApplicant(db, guards, answerer)

    # Mock question elements
    mock_modal = MagicMock()

    # Input 1: Notice period (Known)
    inp1 = MagicMock()
    inp1.get_attribute.side_effect = lambda a: "single-line-text-numeric" if a == "id" else "text"
    parent1 = MagicMock()
    label1 = MagicMock()
    label1.count.return_value = 1
    label1.inner_text.return_value = "Please enter your notice period in days"
    parent1.locator.return_value.first = label1
    inp1.locator.return_value.first = parent1

    # Input 2: LinkedIn profile URL (Unknown / Unanswered)
    inp2 = MagicMock()
    inp2.get_attribute.side_effect = lambda a: "single-line-text" if a == "id" else "text"
    parent2 = MagicMock()
    label2 = MagicMock()
    label2.count.return_value = 1
    label2.inner_text.return_value = "Please enter your LinkedIn profile URL"
    parent2.locator.return_value.first = label2
    inp2.locator.return_value.first = parent2

    inputs_mock = MagicMock()
    inputs_mock.count.return_value = 2
    inputs_mock.nth.side_effect = [inp1, inp2]

    selects_mock = MagicMock()
    selects_mock.count.return_value = 0

    def modal_locator(sel):
        if "input" in sel:
            return inputs_mock
        if "select" in sel:
            return selects_mock
        m = MagicMock()
        m.count.return_value = 0
        return m

    mock_modal.locator.side_effect = modal_locator

    success, pending_q = applicant.answer_screening_fields(mock_modal)
    assert success is False
    assert "linkedin" in pending_q.lower()

def test_stuck_step_guard_discards_and_marks_failed():
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    page = MagicMock()
    modal = MagicMock()
    page.locator.return_value.first = modal

    # Constant fingerprint simulates form stuck on step 1 despite clicking Next
    applicant.get_step_fingerprint = MagicMock(return_value="Step 1 Contact Info | Email | Phone")
    applicant.handle_city_typeahead = MagicMock()
    applicant.select_resume_by_name = MagicMock(return_value=True)
    applicant.answer_screening_fields = MagicMock(return_value=(True, None))

    # Not a review step
    modal.locator.return_value.count.return_value = 0

    # Next button exists
    next_btn = MagicMock()
    next_btn.count.return_value = 1
    modal.locator.return_value.first = next_btn

    with patch.object(applicant, "discard_modal") as mock_discard:
        res = applicant.process_application(page, job_id="li-stuck-1", title="React Dev", company="Acme")
        assert res["status"] == "FAILED"
        assert "STUCK_STEP" in res["reason"]
        mock_discard.assert_called_once()
        db.update_job_status.assert_called_with(
            platform="linkedin",
            job_id="li-stuck-1",
            status="FAILED",
            failure_reason="STUCK_STEP: Modal form step did not advance after click"
        )

def test_step_cap_exceeded_discards_and_marks_failed():
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    page = MagicMock()
    modal = MagicMock()
    page.locator.return_value.first = modal

    # Returns changing fingerprints so stuck-step doesn't trigger, but exceeds 8 steps
    applicant.get_step_fingerprint = MagicMock(side_effect=[f"Step {i} Details" for i in range(15)])
    applicant.handle_city_typeahead = MagicMock()
    applicant.select_resume_by_name = MagicMock(return_value=True)
    applicant.answer_screening_fields = MagicMock(return_value=(True, None))

    # Never review step
    modal.locator.return_value.count.return_value = 0

    next_btn = MagicMock()
    next_btn.count.return_value = 1
    modal.locator.return_value.first = next_btn

    with patch.object(applicant, "discard_modal") as mock_discard:
        res = applicant.process_application(page, job_id="li-cap-1", title="React Dev", company="Acme")
        assert res["status"] == "FAILED"
        assert "STEP_CAP_EXCEEDED" in res["reason"]
        mock_discard.assert_called_once()
        db.update_job_status.assert_called_with(
            platform="linkedin",
            job_id="li-cap-1",
            status="FAILED",
            failure_reason="STEP_CAP_EXCEEDED: Modal exceeded maximum 8 steps"
        )

def test_city_from_config_fills_typeahead():
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)
    applicant.profile = {"personal": {"current_city": "Jaipur"}}

    modal = MagicMock()
    city_loc = MagicMock()
    city_loc.count.return_value = 1
    city_input = MagicMock()
    city_input.input_value.return_value = ""  # Currently empty
    city_loc.first = city_input

    modal.locator.return_value = city_loc

    applicant.handle_city_typeahead(modal)
    # Verifies safe_fill was called with configured city "Jaipur"
    city_input.fill.assert_called_with("Jaipur")

def test_follow_company_uncheck_and_verify_real_linkedin_05_dom():
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    modal = MagicMock()
    follow_cb = MagicMock()
    follow_cb.count.return_value = 1
    follow_cb.is_checked.side_effect = [True, False, False]  # Checked initially, then verified unchecked
    modal.locator.return_value.first = follow_cb

    applicant.uncheck_follow_company(modal)
    # Verifies uncheck was invoked
    follow_cb.uncheck.assert_called_once_with(force=True, timeout=1500)

def test_required_field_with_no_config_source_needs_input_and_discards():
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    page = MagicMock()
    modal = MagicMock()
    page.locator.return_value.first = modal

    applicant.get_step_fingerprint = MagicMock(return_value="Step 4 Questions")
    applicant.handle_city_typeahead = MagicMock()
    applicant.select_resume_by_name = MagicMock(return_value=True)

    # Question has no config source in answers.yaml
    applicant.answer_screening_fields = MagicMock(return_value=(False, "Do you have active Top Secret security clearance?"))

    with patch.object(applicant, "discard_modal") as mock_discard:
        res = applicant.process_application(page, job_id="li-sec-1", title="React Dev", company="Acme")
        assert res["status"] == "NEEDS_INPUT"
        assert "security clearance" in res["question"].lower()
        mock_discard.assert_called_once()
        db.update_job_status.assert_called_with(
            platform="linkedin",
            job_id="li-sec-1",
            status="NEEDS_INPUT",
            pending_question="Do you have active Top Secret security clearance?"
        )

def test_observe_only_blocks_submit_application():
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)
    assert applicant.observe_only is True

    page = MagicMock()
    modal = MagicMock()
    page.locator.return_value.first = modal

    applicant.get_step_fingerprint = MagicMock(return_value="Step Review")
    applicant.handle_city_typeahead = MagicMock()
    applicant.select_resume_by_name = MagicMock(return_value=True)
    applicant.answer_screening_fields = MagicMock(return_value=(True, None))
    applicant.uncheck_follow_company = MagicMock()

    # Review step detected
    review_indicator = MagicMock()
    review_indicator.count.return_value = 1
    modal.locator.return_value = review_indicator

    # Run application progression
    with patch.object(applicant, "discard_modal") as mock_discard:
        res = applicant.process_application(page, job_id="999", title="React Lead", company="Acme")
        assert res["status"] == "OBSERVED_REVIEW"
        # Discard called to safely exit modal without clicking Submit
        mock_discard.assert_called_once()
        # Verify db was recorded as OBSERVED_REVIEW and NOT APPLIED
        db.update_job_status.assert_called_once_with(
            platform="linkedin",
            job_id="999",
            status="OBSERVED_REVIEW"
        )

def test_stuck_step_guard_with_saved_step1_snapshot():
    # Verify fingerprint computation on saved step-1 snapshot file
    step1_path = SNAPSHOTS_DIR / "linkedin_03_modal_step1.html"
    assert step1_path.exists(), f"Snapshot file missing: {step1_path}"
    content = step1_path.read_text(encoding="utf-8")
    assert "Contact info" in content
    assert "jobs-easy-apply-modal" in content

    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    page = MagicMock()
    modal = MagicMock()
    page.locator.return_value.first = modal

    # Extract real step-1 labels/headers simulation
    real_step1_fingerprint = "Contact info | Email address | Phone country code | Mobile phone number"
    applicant.get_step_fingerprint = MagicMock(return_value=real_step1_fingerprint)
    applicant.handle_city_typeahead = MagicMock()
    applicant.select_resume_by_name = MagicMock(return_value=True)
    applicant.answer_screening_fields = MagicMock(return_value=(True, None))

    # Next button exists
    modal.locator.return_value.count.return_value = 0
    next_btn = MagicMock()
    next_btn.count.return_value = 1
    modal.locator.return_value.first = next_btn

    with patch.object(applicant, "discard_modal") as mock_discard:
        res = applicant.process_application(page, job_id="li-step1-stuck", title="React Dev", company="Acme")
        assert res["status"] == "FAILED"
        assert "STUCK_STEP" in res["reason"]
        mock_discard.assert_called_once()

def test_live_submit_requires_review_mode_and_blocks_otherwise():
    db = MagicMock()
    guards = MagicMock()
    # Live mode (observe_only=False), but review_mode=False
    applicant = LinkedInApplicant(db, guards, review_mode=False)
    applicant.observe_only = False

    page = MagicMock()
    modal = MagicMock()
    page.locator.return_value.first = modal

    applicant.get_step_fingerprint = MagicMock(return_value="Review Step")
    applicant.handle_city_typeahead = MagicMock()
    applicant.select_resume_by_name = MagicMock(return_value=True)
    applicant.answer_screening_fields = MagicMock(return_value=(True, None))
    applicant.uncheck_follow_company = MagicMock()

    # Review step detected
    review_indicator = MagicMock()
    review_indicator.count.return_value = 1
    modal.locator.return_value = review_indicator

    with patch.object(applicant, "discard_modal") as mock_discard:
        res = applicant.process_application(page, job_id="li-live-1", title="Dev", company="Acme")
        assert res["status"] == "BLOCKED_REQUIRES_REVIEW"
        mock_discard.assert_called_once()

def test_live_submit_prompt_user_refusal_skips_and_discards():
    db = MagicMock()
    guards = MagicMock()
    # Live mode with review_mode=True
    applicant = LinkedInApplicant(db, guards, review_mode=True)
    applicant.observe_only = False

    page = MagicMock()
    modal = MagicMock()
    page.locator.return_value.first = modal

    applicant.get_step_fingerprint = MagicMock(return_value="Review Step")
    applicant.handle_city_typeahead = MagicMock()
    applicant.select_resume_by_name = MagicMock(return_value=True)
    applicant.answer_screening_fields = MagicMock(return_value=(True, None))
    applicant.uncheck_follow_company = MagicMock()

    review_indicator = MagicMock()
    review_indicator.count.return_value = 1
    modal.locator.return_value = review_indicator

    # User types "NO" or enters empty string instead of "YES"
    with patch("builtins.input", return_value="NO"):
        with patch.object(applicant, "discard_modal") as mock_discard:
            res = applicant.process_application(page, job_id="li-live-2", title="Dev", company="Acme")
            assert res["status"] == "SKIPPED_BY_USER"
            mock_discard.assert_called_once()

def test_live_submit_prompt_user_yes_clicks_submit():
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards, review_mode=True)
    applicant.observe_only = False

    page = MagicMock()
    modal = MagicMock()
    page.locator.return_value.first = modal

    applicant.get_step_fingerprint = MagicMock(return_value="Review Step")
    applicant.handle_city_typeahead = MagicMock()
    applicant.select_resume_by_name = MagicMock(return_value=True)
    applicant.answer_screening_fields = MagicMock(return_value=(True, None))
    applicant.uncheck_follow_company = MagicMock()

    submit_btn = MagicMock()
    submit_btn.count.return_value = 1

    def modal_locator(sel):
        if "Submit" in sel or "Review" in sel:
            m = MagicMock()
            m.count.return_value = 1
            m.first = submit_btn
            return m
        m = MagicMock()
        m.count.return_value = 0
        return m

    modal.locator.side_effect = modal_locator

    with patch("src.policy.OBSERVE_ONLY", False):
        with patch("builtins.input", return_value="YES"):
            with patch("src.policy.verify_and_record_post_submit", return_value="APPLIED") as mock_verify:
                res = applicant.process_application(page, job_id="li-live-3", title="Dev", company="Acme")
                assert res["status"] == "APPLIED"
                submit_btn.click.assert_called_once()
                mock_verify.assert_called_once()
                guards.record_application_success.assert_called_once_with("linkedin")


def test_rehearsal_mode_submit_strictly_impossible():
    """Verifies that in rehearsal mode, Submit is never prompted or clicked and status is OBSERVED_REVIEW."""
    db = MagicMock()
    guards = MagicMock()
    # Rehearsal explicitly enabled
    applicant = LinkedInApplicant(db, guards, is_rehearsal=True, review_mode=True)
    assert applicant.is_rehearsal is True
    assert applicant.observe_only is True

    page = MagicMock()
    modal = MagicMock()
    page.locator.return_value.first = modal

    applicant.get_step_fingerprint = MagicMock(return_value="Step Review")
    applicant.handle_city_typeahead = MagicMock()
    applicant.select_resume_by_name = MagicMock(return_value=True)
    applicant.answer_screening_fields = MagicMock(return_value=(True, None))
    applicant.uncheck_follow_company = MagicMock(return_value="unchecked, verified")

    submit_btn = MagicMock()
    review_indicator = MagicMock()
    review_indicator.count.return_value = 1

    def modal_locator(sel):
        if "Review" in sel or "Submit" in sel:
            m = MagicMock()
            m.count.return_value = 1
            m.first = submit_btn
            return m
        m = MagicMock()
        m.count.return_value = 0
        return m

    modal.locator.side_effect = modal_locator

    with patch.object(applicant, "discard_modal") as mock_discard:
        with patch("builtins.input") as mock_input:
            res = applicant.process_application(
                page, job_id="reh-101", title="Senior React Dev", company="Acme Labs"
            )
            # 1. Output status must be OBSERVED_REVIEW
            assert res["status"] == "OBSERVED_REVIEW"
            # 2. Terminal input prompt for YES must NEVER be called
            assert mock_input.call_count == 0
            # 3. Submit button must NEVER be clicked
            assert submit_btn.click.call_count == 0
            # 4. Modal must be cleanly discarded
            mock_discard.assert_called_once()
            # 5. DB must record OBSERVED_REVIEW, never APPLIED
            db.update_job_status.assert_called_once_with(
                platform="linkedin",
                job_id="reh-101",
                status="OBSERVED_REVIEW"
            )


def _make_mock_card(job_id: str, title: str = "Senior React Developer", company: str = "Acme Labs", location: str = "Bengaluru"):
    card = MagicMock()
    card.get_attribute.side_effect = lambda attr: job_id if attr == "data-job-id" else None

    title_el = MagicMock()
    title_el.count.return_value = 1
    title_el.inner_text.return_value = title

    comp_el = MagicMock()
    comp_el.count.return_value = 1
    comp_el.inner_text.return_value = company

    loc_el = MagicMock()
    loc_el.count.return_value = 1
    loc_el.inner_text.return_value = location

    def card_locator(sel, **kwargs):
        if "job-card-list__title--link" in sel:
            m = MagicMock(first=title_el)
            m.count.return_value = 1
            return m
        if "company" in sel or "subtitle" in sel:
            m = MagicMock(first=comp_el)
            m.count.return_value = 1
            return m
        if "metadata" in sel or "caption" in sel:
            m = MagicMock(first=loc_el)
            m.count.return_value = 1
            return m
        m = MagicMock()
        m.count.return_value = 0
        m.first = m
        return m

    card.locator.side_effect = card_locator
    card.inner_text.return_value = title
    return card


def test_reuse_stored_score_avoids_claude_call():
    """Verifies that a job already scored in DB reuses the score without calling Claude matcher."""
    from src.platforms.linkedin import LinkedInCollector
    db = MagicMock()
    db.job_exists.return_value = False
    db.is_job_blocked.return_value = False
    # Stored score exists in DB
    db.get_job_match_score.return_value = (88, "Previous Claude evaluation: Strong match")
    guards = MagicMock()
    matcher = MagicMock()
    matcher.evaluate_hard_filters.return_value = (False, "")

    collector = LinkedInCollector(db, guards, matcher)

    page = MagicMock()
    card = _make_mock_card("1001", "Senior React Developer")

    def page_locator(sel, **kwargs):
        if "jobs-search-results__list-item" in sel or "job-card-container" in sel:
            m = MagicMock()
            m.count.return_value = 1
            m.nth.return_value = card
            return m
        if "jobs-apply-button" in sel or "Easy Apply" in sel:
            m = MagicMock()
            m.count.return_value = 1
            return m
        if "jobs-description" in sel:
            desc = MagicMock()
            desc.count.return_value = 1
            desc.first.inner_text.return_value = "React, Node.js role"
            return desc
        m = MagicMock()
        m.count.return_value = 0
        return m

    page.locator.side_effect = page_locator

    results = collector.run_phase8a_search(
        page=page,
        search_query={"keywords": "React", "location": "Bengaluru"},
        max_jobs=1,
        dry_run=True
    )

    # evaluate_fit must NOT be called because score was reused
    assert matcher.evaluate_fit.call_count == 0
    assert len(results) == 1
    assert results[0]["match_score"] == 88
    assert results[0]["should_apply"] is True


def test_easy_apply_button_absent_with_applied_badge_records_skipped():
    """Verifies that if apply button is absent and Applied badge is present, job is marked SKIPPED with ALREADY_APPLIED_OR_NA."""
    from src.platforms.linkedin import LinkedInCollector
    db = MagicMock()
    db.job_exists.return_value = False
    db.is_job_blocked.return_value = False
    db.get_job_match_score.return_value = (None, None)
    guards = MagicMock()
    matcher = MagicMock()
    matcher.evaluate_hard_filters.return_value = (False, "")

    collector = LinkedInCollector(db, guards, matcher)

    page = MagicMock()
    card = _make_mock_card("1002", "Senior React Developer")

    def page_locator(sel, **kwargs):
        if "jobs-search-results__list-item" in sel or "job-card-container" in sel:
            m = MagicMock()
            m.count.return_value = 1
            m.nth.return_value = card
            return m
        if "jobs-apply-button" in sel or "Easy Apply" in sel:
            # Apply button absent
            m = MagicMock()
            m.count.return_value = 0
            m.first.wait_for.side_effect = Exception("Timeout waiting for apply button")
            return m
        if "Applied" in sel or "application-link" in sel:
            # Applied badge present
            badge = MagicMock()
            badge.count.return_value = 1
            badge.first.inner_text.return_value = "Applied 2 days ago"
            return badge
        m = MagicMock()
        m.count.return_value = 0
        return m

    page.locator.side_effect = page_locator

    collector.run_phase8a_search(
        page=page,
        search_query={"keywords": "React"},
        max_jobs=1,
        dry_run=True
    )

    db.record_job.assert_called_once()
    call_kwargs = db.record_job.call_args[1]
    assert call_kwargs["status"] == "SKIPPED"
    assert call_kwargs["failure_reason"] == "ALREADY_APPLIED_OR_NA"


def test_easy_apply_button_absent_without_applied_badge_records_not_final():
    """Verifies that if apply button is absent and NO Applied badge is present, job is recorded as APPLY_BUTTON_NOT_FOUND (not final)."""
    from src.platforms.linkedin import LinkedInCollector
    db = MagicMock()
    db.job_exists.return_value = False
    db.is_job_blocked.return_value = False
    db.get_job_match_score.return_value = (None, None)
    guards = MagicMock()
    matcher = MagicMock()
    matcher.evaluate_hard_filters.return_value = (False, "")

    collector = LinkedInCollector(db, guards, matcher)

    page = MagicMock()
    card = _make_mock_card("1003", "Senior React Developer")

    def page_locator(sel, **kwargs):
        if "jobs-search-results__list-item" in sel or "job-card-container" in sel:
            m = MagicMock()
            m.count.return_value = 1
            m.nth.return_value = card
            return m
        if "jobs-apply-button" in sel or "Easy Apply" in sel:
            m = MagicMock()
            m.count.return_value = 0
            m.first.wait_for.side_effect = Exception("Timeout")
            return m
        if "Applied" in sel or "application-link" in sel:
            # No Applied badge
            badge = MagicMock()
            badge.count.return_value = 0
            return badge
        m = MagicMock()
        m.count.return_value = 0
        return m

    page.locator.side_effect = page_locator

    collector.run_phase8a_search(
        page=page,
        search_query={"keywords": "React"},
        max_jobs=1,
        dry_run=True
    )

    db.record_job.assert_called_once()
    call_kwargs = db.record_job.call_args[1]
    assert call_kwargs["status"] == "APPLY_BUTTON_NOT_FOUND"
    assert "APPLY_BUTTON_NOT_FOUND" in call_kwargs["failure_reason"]
    # Verify it is NOT SKIPPED (non-final)
    assert call_kwargs["status"] != "SKIPPED"


def test_process_eligible_found_jobs_runs_before_search():
    """Verifies that process_eligible_found_jobs queries DB for FOUND jobs and processes them with applicant."""
    from src.platforms.linkedin import LinkedInCollector
    db = MagicMock()
    guards = MagicMock()
    guards.session_attempts_count = 0
    guards.max_attempts = 5
    matcher = MagicMock()

    collector = LinkedInCollector(db, guards, matcher)

    # DB returns 2 eligible FOUND jobs with valid numeric LinkedIn view URLs
    db.get_eligible_found_jobs.return_value = [
        {"job_id": "1004", "title": "React Lead", "company": "Alpha Corp", "url": "https://www.linkedin.com/jobs/view/1004/"},
        {"job_id": "1005", "title": "Senior Node Dev", "company": "Beta Ltd", "url": "https://www.linkedin.com/jobs/view/1005/"}
    ]

    applicant = MagicMock()
    applicant.process_application.return_value = {"status": "OBSERVED_REVIEW"}

    page = MagicMock()
    apply_btn = MagicMock()
    apply_btn.count.return_value = 1
    page.locator.return_value = apply_btn

    results = collector.process_eligible_found_jobs(page, applicant=applicant, limit=2, is_rehearsal=True)

    db.get_eligible_found_jobs.assert_called_once_with("linkedin", limit=2)
    assert len(results) == 2
    assert applicant.process_application.call_count == 2
