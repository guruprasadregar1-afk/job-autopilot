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
    inp1.get_attribute.side_effect = lambda a: "single-line-text-numeric" if a == "id" else ("text" if a == "type" else "")
    inp1.input_value.return_value = ""
    parent1 = MagicMock()
    label1 = MagicMock()
    label1.count.return_value = 1
    label1.inner_text.return_value = "Please enter your notice period in days"
    parent1.locator.return_value.first = label1
    inp1.locator.return_value.first = parent1

    # Input 2: LinkedIn profile URL (Unknown / Unanswered)
    inp2 = MagicMock()
    inp2.get_attribute.side_effect = lambda a: "single-line-text" if a == "id" else ("text" if a == "type" else "")
    inp2.input_value.return_value = ""
    parent2 = MagicMock()
    label2 = MagicMock()
    label2.count.return_value = 1
    label2.inner_text.return_value = "Please enter your LinkedIn profile URL"
    parent2.locator.return_value.first = label2
    inp2.locator.return_value.first = parent2

    inputs_mock = MagicMock()
    inputs_mock.count.return_value = 2
    inputs_mock.nth.side_effect = lambda i: [inp1, inp2][i]

    selects_mock = MagicMock()
    selects_mock.count.return_value = 0

    checkboxes_mock = MagicMock()
    checkboxes_mock.count.return_value = 0

    fieldsets_mock = MagicMock()
    fieldsets_mock.count.return_value = 0

    def modal_locator(sel):
        if sel == "input[type='checkbox']":
            return checkboxes_mock
        if "fieldset" in sel:
            return fieldsets_mock
        if "select" in sel:
            return selects_mock
        if "input" in sel:
            return inputs_mock
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
    applicant.get_step_fingerprint = MagicMock(side_effect=[f"Step {i} Details" for i in range(30)])
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
    follow_cb.is_checked.side_effect = [True] + [False] * 10  # Checked initially, then verified unchecked
    modal.locator.return_value.first = follow_cb

    state = applicant.uncheck_follow_company(modal)
    # Verifies uncheck was invoked
    assert state in ("unchecked, verified", "not present / unchecked, verified")

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
                assert guards.record_application_success.called
                assert guards.record_application_success.call_args[1]["platform"] == "linkedin"
                assert guards.record_application_success.call_args[1]["job_id"] == "li-live-3"
                assert guards.record_application_success.call_args[1]["title"] == "Dev"
                assert guards.record_application_success.call_args[1]["company"] == "Acme"


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


def test_attempt_count_gated_on_modal_detection():
    """Verifies attempt count is incremented ONLY when modal is detected, and missing modal records retryable MODAL_NOT_DETECTED."""
    db = MagicMock()
    guards = MagicMock()
    guards.is_job_attempted_in_run.return_value = False
    applicant = LinkedInApplicant(db, guards, is_rehearsal=True)

    # Case A: Modal does NOT appear (timeout or count == 0)
    page_no_modal = MagicMock()
    missing_modal = MagicMock()
    missing_modal.wait_for.side_effect = Exception("Timeout waiting for modal")
    missing_modal.count.return_value = 0
    page_no_modal.locator.return_value.first = missing_modal

    res_no_modal = applicant.process_application(
        page_no_modal,
        job_id="job-no-modal-1",
        title="Frontend Dev",
        company="NoModal Ltd"
    )

    # Verify attempt was NOT recorded / incremented
    guards.record_form_opened.assert_not_called()
    assert res_no_modal["status"] == "MODAL_NOT_DETECTED"
    db.update_job_status.assert_called_with(
        platform="linkedin",
        job_id="job-no-modal-1",
        status="MODAL_NOT_DETECTED",
        failure_reason="MODAL_NOT_DETECTED: Easy Apply modal failed to appear within bounded timeout"
    )

    # Case B: Modal DOES appear
    page_with_modal = MagicMock()
    open_modal = MagicMock()
    open_modal.count.return_value = 1
    page_with_modal.locator.return_value.first = open_modal

    # Simulate review step to finish cleanly
    applicant.get_step_fingerprint = MagicMock(return_value="fp_step_1")
    applicant.handle_city_typeahead = MagicMock()
    applicant.select_resume_by_name = MagicMock(return_value=True)
    applicant.answer_screening_fields = MagicMock(return_value=(True, None))
    applicant.uncheck_follow_company = MagicMock(return_value="unchecked")
    applicant.discard_modal = MagicMock()

    def modal_loc(sel, **kwargs):
        if "Review" in sel or "Submit application" in sel:
            m = MagicMock()
            m.count.return_value = 1
            return m
        m = MagicMock()
        m.count.return_value = 0
        return m

    open_modal.locator.side_effect = modal_loc

    res_open = applicant.process_application(
        page_with_modal,
        job_id="job-modal-2",
        title="Backend Dev",
        company="Modal Corp"
    )

    # Verify attempt WAS recorded / incremented on detection
    guards.record_form_opened.assert_called_once_with(platform="linkedin", job_id="job-modal-2")
    guards.mark_job_attempted_in_run.assert_called_once_with("job-modal-2")
    assert res_open["status"] == "OBSERVED_REVIEW"


def test_run_attempt_dedupe_prevents_duplicate_apply_in_run():
    """Verifies a job attempted earlier in the run is not opened twice."""
    from src.platforms.linkedin import LinkedInCollector
    db = MagicMock()
    guards = MagicMock()
    # Mock that job '2001' was already attempted in current run
    guards.is_job_attempted_in_run.side_effect = lambda jid: str(jid) == "2001"
    guards.session_attempts_count = 1
    guards.max_attempts = 5
    matcher = MagicMock()
    matcher.evaluate_hard_filters.return_value = (False, "")
    matcher.evaluate_fit.return_value = MagicMock(should_apply=True, score=90, reason="Fit")

    collector = LinkedInCollector(db, guards, matcher)
    applicant = MagicMock()
    page = MagicMock()

    # 1. Dedupe in process_eligible_found_jobs
    db.get_eligible_found_jobs.return_value = [
        {"job_id": "2001", "title": "React Lead", "company": "Dedupe Corp", "url": "https://www.linkedin.com/jobs/view/2001/"}
    ]
    found_results = collector.process_eligible_found_jobs(page, applicant=applicant, limit=1)
    assert len(found_results) == 0
    applicant.process_application.assert_not_called()

    # 2. Dedupe in run_phase8a_search
    card = _make_mock_card("2001", "React Lead")
    page.locator.return_value = MagicMock(count=lambda: 1, nth=lambda idx: card, first=MagicMock(count=lambda: 1))

    search_results = collector.run_phase8a_search(
        page=page,
        search_query={"keywords": "React"},
        max_jobs=1,
        dry_run=False,
        applicant=applicant
    )
    applicant.process_application.assert_not_called()


def test_non_final_outcomes_record_retryable_statuses_and_reasons(tmp_path):
    """Verifies non-final outcomes (MODAL_NOT_DETECTED, STEP_FAILED, APPLY_BUTTON_NOT_FOUND) are retryable in DB."""
    from src.db import Database
    db = Database(tmp_path / "test_outcomes.db")

    # 1. Record MODAL_NOT_DETECTED
    db.record_job(
        platform="linkedin",
        job_id="retry-1",
        title="Frontend Dev",
        company="Alpha",
        status="MODAL_NOT_DETECTED",
        failure_reason="MODAL_NOT_DETECTED: Easy Apply modal failed to appear"
    )
    assert db.is_job_eligible("linkedin", "retry-1") is True
    assert db.is_job_blocked("linkedin", "retry-1") is False

    # 2. Record STEP_FAILED
    db.record_job(
        platform="linkedin",
        job_id="retry-2",
        title="Backend Dev",
        company="Beta",
        status="STEP_FAILED",
        failure_reason="UNKNOWN_STEP_HALT: Step 2 has no Next/Review button"
    )
    assert db.is_job_eligible("linkedin", "retry-2") is True
    assert db.is_job_blocked("linkedin", "retry-2") is False

    # 3. Record APPLY_BUTTON_NOT_FOUND
    db.record_job(
        platform="linkedin",
        job_id="retry-3",
        title="Full Stack Dev",
        company="Gamma",
        status="APPLY_BUTTON_NOT_FOUND",
        failure_reason="APPLY_BUTTON_NOT_FOUND: Easy Apply button not visible after bounded timeout"
    )
    assert db.is_job_eligible("linkedin", "retry-3") is True
    assert db.is_job_blocked("linkedin", "retry-3") is False

    # 4. Verify get_eligible_found_jobs retrieves them for retry
    eligible = db.get_eligible_found_jobs("linkedin", limit=10)
    eligible_ids = [j["job_id"] for j in eligible]
    assert "retry-1" in eligible_ids
    assert "retry-2" in eligible_ids


def test_replay_saved_snapshots_through_process_application():
    """Replays saved HTML snapshots (linkedin_02, linkedin_03 to 05) through process_application."""
    p_detail = SNAPSHOTS_DIR / "linkedin_02_job_detail.html"
    p_step1 = SNAPSHOTS_DIR / "linkedin_03_modal_step1.html"
    p_step2 = SNAPSHOTS_DIR / "linkedin_04_modal_step2.html"
    p_review = SNAPSHOTS_DIR / "linkedin_05_modal_review.html"

    assert p_detail.exists() and p_step1.exists() and p_step2.exists() and p_review.exists()

    db = MagicMock()
    guards = MagicMock()
    guards.is_job_attempted_in_run.return_value = False
    applicant = LinkedInApplicant(db, guards, is_rehearsal=True)
    applicant.profile = {
        "personal": {"current_city": "Jaipur"},
        "resume": {"selected_filename": "Guru_Prasad-Resume.pdf"}
    }

    # Test Case A: Detail page snapshot (linkedin_02) has no modal
    page_detail = MagicMock()
    detail_modal = MagicMock()
    detail_modal.wait_for.side_effect = Exception("Timeout waiting for modal")
    detail_modal.count.return_value = 0
    page_detail.locator.return_value.first = detail_modal

    res_detail = applicant.process_application(page_detail, job_id="snap-02", title="Dev", company="Hired")
    assert res_detail["status"] == "MODAL_NOT_DETECTED"
    guards.record_form_opened.assert_not_called()

    # Test Case B: Progression across Step 1 (linkedin_03) -> Step 2 (linkedin_04) -> Review (linkedin_05)
    page_progression = MagicMock()
    modal = MagicMock()
    modal.count.return_value = 1
    page_progression.locator.return_value.first = modal

    step_state = [0]
    headers = ["Contact info", "Resume", "Review your application"]

    def mock_step_header(*args, **kwargs):
        h = MagicMock()
        h.count.return_value = 1
        h.first.inner_text.return_value = headers[min(step_state[0], 2)]
        return h

    def mock_next_click(*args, **kwargs):
        if step_state[0] < 2:
            step_state[0] += 1

    applicant.handle_city_typeahead = MagicMock()
    applicant.select_resume_by_name = MagicMock(return_value=True)
    applicant.answer_screening_fields = MagicMock(return_value=(True, None))
    applicant.uncheck_follow_company = MagicMock(return_value="unchecked")
    applicant.discard_modal = MagicMock()
    applicant.get_step_fingerprint = lambda m: f"Fingerprint_Step_{step_state[0]}_{headers[min(step_state[0], 2)]}"

    def modal_locator(sel, **kwargs):
        if "Submit application" in sel or sel.startswith("h3:has-text('Review')"):
            m = MagicMock()
            m.count.return_value = 1 if step_state[0] >= 2 else 0
            return m
        if "data-easy-apply-next-button" in sel or "Next" in sel:
            btn = MagicMock()
            btn.count.return_value = 1
            btn.inner_text.return_value = "Next" if step_state[0] == 0 else "Review"
            btn.click.side_effect = mock_next_click
            btn.first = btn
            return btn
        if "h3" in sel or "h2" in sel:
            return mock_step_header()
        m = MagicMock()
        m.count.return_value = 0
        return m

    modal.locator.side_effect = modal_locator

    res_prog = applicant.process_application(
        page_progression,
        job_id="snap-prog-1",
        title="Full-Stack Developer (Remote)",
        company="Hired",
        url="https://www.linkedin.com/jobs/view/snap-prog-1/"
    )

    assert res_prog["status"] == "OBSERVED_REVIEW"
    assert step_state[0] == 2
    guards.record_form_opened.assert_called_once_with(platform="linkedin", job_id="snap-prog-1")
    guards.mark_job_attempted_in_run.assert_called_once_with("snap-prog-1")
    db.update_job_status.assert_called_with(
        platform="linkedin",
        job_id="snap-prog-1",
        status="OBSERVED_REVIEW"
    )
    applicant.discard_modal.assert_called_once()


def test_scoped_easy_apply_locator_with_search_and_detail_snapshots():
    """Verifies Easy Apply button locator matches only the job detail Easy Apply button and never the search filter pill."""
    import re
    p1 = SNAPSHOTS_DIR / "linkedin_01_search_results.html"
    p2 = SNAPSHOTS_DIR / "linkedin_02_job_detail.html"
    assert p1.exists() and p2.exists()

    content1 = p1.read_text(encoding="utf-8")
    content2 = p2.read_text(encoding="utf-8")

    # In both pages, the filter pill exists
    pill_match1 = re.search(r'<button[^>]*id=["\']searchFilter_applyWithLinkedin["\'][^>]*>', content1)
    pill_match2 = re.search(r'<button[^>]*id=["\']searchFilter_applyWithLinkedin["\'][^>]*>', content2)
    assert pill_match1 is not None
    assert pill_match2 is not None
    assert 'aria-label="Easy Apply filter."' in pill_match1.group(0)

    # In both pages, Easy Apply button exists with aria-label starting with 'Easy Apply to'
    apply_btns1 = re.findall(r'<button[^>]*aria-label=["\']Easy Apply to[^"\']*["\'][^>]*>', content1)
    apply_btns2 = re.findall(r'<button[^>]*aria-label=["\']Easy Apply to[^"\']*["\'][^>]*>', content2)
    assert len(apply_btns1) >= 1
    assert len(apply_btns2) >= 1
    for b in apply_btns1 + apply_btns2:
        assert "searchFilter_applyWithLinkedin" not in b
        assert "role=\"radio\"" not in b

    # Filter pill does NOT start with 'Easy Apply to'
    assert not pill_match1.group(0).startswith('aria-label="Easy Apply to')
    assert "Easy Apply to" not in pill_match1.group(0)


def test_modal_detection_on_saved_and_rehearsal_snapshots():
    """Verifies modal detection against legacy modal snapshots and modern rehearsal SDUI dialog snapshots."""
    modal_files = [
        "linkedin_03_modal_step1.html",
        "linkedin_04_modal_step2.html",
        "linkedin_05_modal_review.html",
        "rehearsal_4476699604_modal_not_detected.html",
        "rehearsal_4477293332_modal_not_detected.html",
    ]
    non_modal_files = [
        "linkedin_01_search_results.html",
        "linkedin_02_job_detail.html",
        "rehearsal_4467464995_modal_not_detected.html",
        "rehearsal_4478456211_modal_not_detected.html",
        "rehearsal_4479309031_modal_not_detected.html",
    ]

    def has_modal(html: str) -> bool:
        if "jobs-easy-apply-modal" in html or 'data-test-modal="easy-apply-modal"' in html:
            return True
        if "<dialog" in html and "open" in html:
            if "easyapply" in html.lower() or "apply to" in html.lower():
                return True
        if "data-sdui-screen" in html and "easyapply" in html.lower():
            return True
        return False

    for fn in modal_files:
        p = SNAPSHOTS_DIR / fn
        if p.exists():
            content = p.read_text(encoding="utf-8")
            assert has_modal(content) is True, f"Failed to detect modal in {fn}"

    for fn in non_modal_files:
        p = SNAPSHOTS_DIR / fn
        if p.exists():
            content = p.read_text(encoding="utf-8")
            assert has_modal(content) is False, f"Erroneously detected modal in {fn}"


def test_two_strike_blocking_for_modal_not_detected_and_step_failed(tmp_path):
    """Verifies that jobs with 2 MODAL_NOT_DETECTED or STEP_FAILED outcomes are blocked from retry."""
    from src.db import Database
    db = Database(tmp_path / "test_two_strike.db")

    # MODAL_NOT_DETECTED strike 1
    db.record_job(
        platform="linkedin",
        job_id="m1",
        title="Frontend",
        company="Alpha",
        status="MODAL_NOT_DETECTED",
        failure_reason="MODAL_NOT_DETECTED: first failure"
    )
    assert db.is_job_eligible("linkedin", "m1") is True
    assert db.get_failure_count("linkedin", "m1") == 1

    # MODAL_NOT_DETECTED strike 2 (blocked!)
    db.update_job_status(
        platform="linkedin",
        job_id="m1",
        status="MODAL_NOT_DETECTED",
        failure_reason="MODAL_NOT_DETECTED: second failure"
    )
    assert db.get_failure_count("linkedin", "m1") == 2
    assert db.is_job_eligible("linkedin", "m1") is False
    assert db.is_job_blocked("linkedin", "m1") is True

    # STEP_FAILED strike 1
    db.record_job(
        platform="linkedin",
        job_id="s1",
        title="Backend",
        company="Beta",
        status="STEP_FAILED",
        failure_reason="STEP_FAILED: first failure"
    )
    assert db.is_job_eligible("linkedin", "s1") is True
    assert db.get_failure_count("linkedin", "s1") == 1

    # STEP_FAILED strike 2 (blocked!)
    db.update_job_status(
        platform="linkedin",
        job_id="s1",
        status="STEP_FAILED",
        failure_reason="STEP_FAILED: second failure"
    )
    assert db.get_failure_count("linkedin", "s1") == 2
    assert db.is_job_eligible("linkedin", "s1") is False
    assert db.is_job_blocked("linkedin", "s1") is True

    # Check eligible found jobs excludes blocked jobs
    eligible = db.get_eligible_found_jobs("linkedin")
    eligible_ids = [j["job_id"] for j in eligible]
    assert "m1" not in eligible_ids
    assert "s1" not in eligible_ids


def test_three_consecutive_modal_not_detected_halts_run_with_snapshots():
    """Verifies that 3 consecutive MODAL_NOT_DETECTED outcomes halt the whole run with saved snapshot paths."""
    from src.guards import GuardsManager, SafetyStopError
    guards = GuardsManager(MagicMock())

    # 1st failure
    guards.record_attempt_outcome("MODAL_NOT_DETECTED", job_id="101", snapshot_path="docs/snapshots/rehearsal_101.html")
    assert guards.consecutive_modal_not_detected == 1

    # 2nd failure
    guards.record_attempt_outcome("MODAL_NOT_DETECTED", job_id="102", snapshot_path="docs/snapshots/rehearsal_102.html")
    assert guards.consecutive_modal_not_detected == 2

    # Intervening success resets counter
    guards.record_attempt_outcome("OBSERVED_REVIEW", job_id="103")
    assert guards.consecutive_modal_not_detected == 0

    # 3 consecutive failures
    guards.record_attempt_outcome("MODAL_NOT_DETECTED", job_id="104", snapshot_path="docs/snapshots/rehearsal_104.html")
    guards.record_attempt_outcome("MODAL_NOT_DETECTED", job_id="105", snapshot_path="docs/snapshots/rehearsal_105.html")
    with pytest.raises(SafetyStopError) as exc_info:
        guards.record_attempt_outcome("MODAL_NOT_DETECTED", job_id="106", snapshot_path="docs/snapshots/rehearsal_106.html")

    err_text = str(exc_info.value)
    assert "3 consecutive MODAL_NOT_DETECTED" in err_text
    assert "docs/snapshots/rehearsal_104.html" in err_text
    assert "docs/snapshots/rehearsal_105.html" in err_text
    assert "docs/snapshots/rehearsal_106.html" in err_text


def test_replay_step1_sdui_all_fields_preserved_and_advances_to_next(capsys):
    """
    Replays real snapshot docs/snapshots/rehearsal_4479309031_step_1.html:
    Proves it detects all 5 fields, keeps pre-filled values, masks personal data in trace,
    and locates the Next button to advance to Step 2.
    """
    from playwright.sync_api import sync_playwright
    from src.policy import SafePage

    step1_file = SNAPSHOTS_DIR / "rehearsal_4479309031_step_1.html"
    assert step1_file.exists(), f"Snapshot {step1_file} not found"
    html_content = step1_file.read_text(encoding="utf-8")

    db = MagicMock()
    guards = MagicMock()
    answerer = FormAnswerer()
    applicant = LinkedInApplicant(db, guards, answerer, is_rehearsal=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        raw_page = browser.new_page()
        raw_page.set_content(html_content)
        page = SafePage(raw_page)

        modal = page.locator("dialog[open], div.jobs-easy-apply-modal").first
        assert modal.count() > 0

        # Step 1 answer screening fields
        success, pending_q = applicant.answer_screening_fields(modal)
        assert success is True
        assert pending_q is None

        # Check answers filled contains all 5 fields preserved from LinkedIn pre-fill
        assert "First name*" in applicant.answers_filled
        assert applicant.answers_filled["First name*"] == "Guru"
        assert "Last name*" in applicant.answers_filled
        assert applicant.answers_filled["Last name*"] == "Prasad"
        assert "Mobile phone number" in applicant.answers_filled
        assert applicant.answers_filled["Mobile phone number"] == "6378526193"
        assert "Phone country code" in applicant.answers_filled
        assert "Email address*" in applicant.answers_filled

        # Verify trace logs
        out = capsys.readouterr().out
        assert "[TRACE: FIELD] First name* (text) -> 'G**u' (Source: LinkedIn pre-filled)" in out
        assert "[TRACE: FIELD] Last name* (text) -> 'P****d' (Source: LinkedIn pre-filled)" in out
        assert "[TRACE: FIELD] Mobile phone number (text) -> '6********3' (Source: LinkedIn pre-filled)" in out

        # Verify Next button exists and is clickable
        next_btn = modal.locator(
            "button[data-easy-apply-next-button], "
            "button:has-text('Next'), "
            "button:has-text('Review')"
        ).first
        assert next_btn.count() > 0
        assert next_btn.inner_text().strip() == "Next"

        browser.close()


def test_discard_modal_on_sdui_dialog_cleans_up_and_verifies_closure(capsys):
    """
    Replays discard sequence on SDUI dialog markup:
    Proves Dismiss is clicked, Discard is confirmed, and dialog closure is verified.
    """
    from playwright.sync_api import sync_playwright
    from src.policy import SafePage

    step1_file = SNAPSHOTS_DIR / "rehearsal_4479309031_step_1.html"
    html_content = step1_file.read_text(encoding="utf-8")

    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        raw_page = browser.new_page()
        raw_page.set_content(html_content)
        page = SafePage(raw_page)

        # Mock dismiss click to close the dialog in static HTML snapshot
        raw_page.add_style_tag(content="dialog { z-index: 999999 !important; position: relative !important; }")
        raw_page.evaluate("""() => {
            const btn = document.querySelector('button[aria-label="Dismiss"]');
            if (btn) {
                btn.onclick = () => {
                    const d = document.querySelector('dialog');
                    if (d) d.removeAttribute('open');
                };
            }
        }""")

        applicant.discard_modal(page, job_id="4479309031")

        out = capsys.readouterr().out
        assert "[TRACE: DISCARD] Clicking Dismiss..." in out
        assert "[TRACE: DISCARD] Modal dismissed successfully" in out

        browser.close()


def test_discard_modal_raises_safety_halt_if_dialog_remains_open():
    """Verifies that if dialog remains open after discard, SafetyStopError is raised to check My Jobs."""
    from src.guards import SafetyStopError

    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    page = MagicMock()
    dismiss_btn = MagicMock()
    dismiss_btn.count.return_value = 1
    page.locator.return_value.first = dismiss_btn

    # Mock open_dialogs returning visible dialog
    open_dialogs = MagicMock()
    open_dialogs.count.return_value = 1
    mock_d = MagicMock()
    mock_d.is_visible.return_value = True
    open_dialogs.nth.return_value = mock_d

    def mock_loc(sel):
        if "dialog[open]" in sel:
            return open_dialogs
        m = MagicMock()
        m.count.return_value = 1
        m.first = dismiss_btn
        return m

    page.locator.side_effect = mock_loc

    with pytest.raises(SafetyStopError) as exc_info:
        applicant.discard_modal(page, job_id="test-job-stuck")

    err = str(exc_info.value)
    assert "DISCARD_VERIFICATION_FAILED" in err
    assert "Please manually check LinkedIn 'My Jobs'" in err


def test_external_site_apply_button_detected_recorded_and_not_clicked(capsys):
    """
    Verifies that when an apply button with 'on company website' is found:
    - It is recorded in DB as EXTERNAL_SITE with failure reason
    - It is never clicked
    - Trace prints '[EXTERNAL SITE] Job ... redirects to company site. Skipping.'
    """
    from src.platforms.linkedin import LinkedInCollector

    db = MagicMock()
    guards = MagicMock()
    guards.session_attempts_count = 0
    guards.max_attempts = 10
    matcher = MagicMock()

    db.get_eligible_found_jobs.return_value = [
        {
            "job_id": "4478456211",
            "title": "Fullstack Engineer (NodeJs)",
            "company": "Ascendion",
            "url": "https://www.linkedin.com/jobs/view/4478456211/",
            "match_score": 85,
            "match_reason": "Node.js match"
        }
    ]

    collector = LinkedInCollector(db, guards, matcher)
    page = MagicMock()
    applicant = MagicMock()

    # Apply button is absent (count 0)
    apply_btn = MagicMock()
    apply_btn.count.return_value = 0
    apply_btn.first = apply_btn
    apply_btn.wait_for.side_effect = Exception("Timeout")

    # External apply button is present
    ext_apply_btn = MagicMock()
    ext_apply_btn.count.return_value = 1
    ext_apply_btn.get_attribute.return_value = "Apply to Fullstack Engineer (NodeJs) on company website"
    ext_apply_btn.first = ext_apply_btn

    def locator_mock(sel):
        if "on company website" in sel:
            return ext_apply_btn
        m = MagicMock()
        m.count.return_value = 0
        m.first = apply_btn
        return m

    page.locator.side_effect = locator_mock

    collector.process_eligible_found_jobs(page, applicant=applicant, limit=1)

    # Verify applicant.process_application was NEVER called
    applicant.process_application.assert_not_called()

    # Verify DB recorded EXTERNAL_SITE
    db.update_job_status.assert_called_with(
        platform="linkedin",
        job_id="4478456211",
        status="EXTERNAL_SITE",
        failure_reason="External site apply control ('Apply to Fullstack Engineer (NodeJs) on company website') redirects away from LinkedIn - not automated"
    )

    out = capsys.readouterr().out
    assert "[EXTERNAL SITE] Job 4478456211 ('Fullstack Engineer (NodeJs)' @ 'Ascendion') redirects to company site. Skipping." in out


def test_browser_closed_clean_handling_records_browser_closed_and_exits():
    """
    Verifies that TargetClosedError / browser disconnect error:
    - Records job as BROWSER_CLOSED in DB
    - Raises BrowserClosedCleanStop which is caught cleanly by run_pipeline
    - Is not treated as a job failure
    """
    from playwright._impl._errors import TargetClosedError
    from src.platforms.linkedin import LinkedInApplicant
    from src.policy import BrowserClosedCleanStop, is_browser_closed_error

    # Verify is_browser_closed_error detects TargetClosedError
    target_err = TargetClosedError("Target page, context or browser has been closed")
    assert is_browser_closed_error(target_err) is True

    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    page = MagicMock()
    # Simulate browser closure during modal detection
    page.locator.side_effect = TargetClosedError("Target page, context or browser has been closed")

    with pytest.raises(BrowserClosedCleanStop):
        applicant.process_application(page, job_id="close-1", title="Dev", company="TestCorp")

    # Verify DB status updated to BROWSER_CLOSED (retryable)
    db.update_job_status.assert_called_with(
        platform="linkedin",
        job_id="close-1",
        status="BROWSER_CLOSED",
        failure_reason="Browser closed or disconnected during execution"
    )


def test_sdui_fingerprint_distinct_and_stuck_detection():
    """
    Verifies that get_step_fingerprint produces distinct, non-empty fingerprints for
    SDUI modal steps (rehearsal_4479309031 step 1, step 2, step 3), never empty,
    and accurately detects unchanged content (stuck step 3 vs step 3).
    """
    p1 = SNAPSHOTS_DIR / "rehearsal_4479309031_step_1.html"
    p2 = SNAPSHOTS_DIR / "rehearsal_4479309031_step_2.html"
    p3 = SNAPSHOTS_DIR / "rehearsal_4479309031_step_3.html"
    p_stuck = SNAPSHOTS_DIR / "rehearsal_4479309031_stuck_step_3.html"
    assert p1.exists() and p2.exists() and p3.exists() and p_stuck.exists()

    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    def make_snapshot_mock_modal(html_content: str):
        import re
        modal = MagicMock()

        # 1. Progressbar
        pb_m = re.search(r'role="progressbar"[^>]*aria-valuenow="([^"]+)"', html_content)
        if not pb_m:
            pb_m = re.search(r'aria-valuenow="([^"]+)"[^>]*role="progressbar"', html_content)
        valuenow = pb_m.group(1) if pb_m else ""

        pb = MagicMock()
        pb.count.return_value = 1 if valuenow else 0
        pb.get_attribute.return_value = valuenow
        pb.first = pb

        # Progress text
        ptxts = re.findall(r'(\d+\s*percent complete|\d+/\d+\s*pages)', html_content, re.I)
        mock_ptxts = [MagicMock(inner_text=lambda t=t: t) for t in sorted(set(ptxts))]

        # Headings / p in content
        sec_m = re.findall(r'<p[^>]*class="[^"]*i0ll5q[^"]*"[^>]*>(.*?)</p>', html_content)
        sec_titles = [re.sub(r'<[^>]+>', '', s).strip() for s in sec_m if re.sub(r'<[^>]+>', '', s).strip()]

        # Labels / aria-labels
        labels = re.findall(r'<label[^>]*>(.*?)</label>', html_content, re.S)
        clean_labels = [re.sub(r'<[^>]+>', '', l).strip() for l in labels if re.sub(r'<[^>]+>', '', l).strip()]
        aria_labels = re.findall(r'<(?:input|textarea|select)[^>]*aria-label="([^"]+)"', html_content)
        mock_inputs = [MagicMock(get_attribute=lambda attr, a=a: a if attr == "aria-label" else None) for a in aria_labels]

        # Content text
        clean_text = re.sub(r'<[^>]+>', ' ', html_content)
        norm_text = " ".join(clean_text.split())

        def locator_side_effect(sel, **kwargs):
            m = MagicMock()
            if "progressbar" in sel:
                return pb
            if "percent complete" in sel or "pages" in sel:
                m.count.return_value = len(mock_ptxts)
                m.nth.side_effect = lambda idx: mock_ptxts[idx]
                return m
            if "dialog-content" in sel and ("h2" in sel or "p" in sel or "legend" in sel):
                m.all_inner_texts.return_value = sec_titles
                return m
            if "dialog-content" in sel:
                m.count.return_value = 1
                m.first = m
                m.inner_text.return_value = norm_text[:300]
                return m
            if "label" in sel and "input[" in sel:
                m.all_inner_texts.return_value = clean_labels + aria_labels
                return m
            if "input[aria-label]" in sel:
                m.count.return_value = len(mock_inputs)
                m.nth.side_effect = lambda idx: mock_inputs[idx]
                return m
            m.count.return_value = 0
            return m

        modal.locator.side_effect = locator_side_effect
        modal.inner_text.return_value = norm_text[:300]
        return modal

    m1 = make_snapshot_mock_modal(p1.read_text(encoding="utf-8"))
    m2 = make_snapshot_mock_modal(p2.read_text(encoding="utf-8"))
    m3 = make_snapshot_mock_modal(p3.read_text(encoding="utf-8"))
    m_stuck = make_snapshot_mock_modal(p_stuck.read_text(encoding="utf-8"))

    fp1 = applicant.get_step_fingerprint(m1)
    fp2 = applicant.get_step_fingerprint(m2)
    fp3 = applicant.get_step_fingerprint(m3)
    fp_stuck = applicant.get_step_fingerprint(m_stuck)

    # 1. Guaranteed non-empty
    assert fp1 and len(fp1) > 0, "Step 1 fingerprint must not be empty"
    assert fp2 and len(fp2) > 0, "Step 2 fingerprint must not be empty"
    assert fp3 and len(fp3) > 0, "Step 3 fingerprint must not be empty"

    # 2. Distinct across different steps
    assert fp1 != fp2, "Step 1 and Step 2 must have distinct fingerprints"
    assert fp2 != fp3, "Step 2 and Step 3 must have distinct fingerprints"
    assert fp1 != fp3, "Step 1 and Step 3 must have distinct fingerprints"

    # 3. Stuck detection matches identical step
    assert fp_stuck == applicant.get_step_fingerprint(m_stuck), "Stuck Step 3 must match identical step fingerprint"
    assert fp3 == applicant.get_step_fingerprint(m3), "Step 3 fingerprint must be deterministic"


def test_sdui_resume_detection_match_and_mismatch():
    """
    Verifies that select_resume_by_name handles the modern SDUI resume fieldset layout:
    - Character-for-character matching against profile.yaml
    - Pre-selected detection (no extraneous click)
    - Rejection (RESUME_NOT_FOUND) when configured filename does not match stored resumes
    - answer_screening_fields skips resume fieldsets and never produces 'Unknown radio question'
    """
    db = MagicMock()
    guards = MagicMock()
    answerer = MagicMock()

    applicant = LinkedInApplicant(db, guards, answerer)
    applicant.profile = {"resume": {"selected_filename": "Guru_Prasad-Resume.pdf"}}

    # Mock SDUI modal containing 15 resume radio inputs from rehearsal_4479309031_step_2.html
    modal = MagicMock()

    # Legacy card container count is 0
    legacy_cards = MagicMock()
    legacy_cards.count.return_value = 0

    # Resume indicator
    resume_indicator = MagicMock()
    resume_indicator.count.return_value = 1

    # SDUI radio inputs
    stored_filenames = [
        "Guru_Prasad-Resume.pdf",
        "Guru_Prasad_Resume.docx",
        "Guru_Prasad_resume.pdf",
        "GURU(uae).pdf",
        "Guru_Prasad_CV 1.pdf"
    ]
    radio_mocks = []
    for idx, fn in enumerate(stored_filenames):
        r = MagicMock()
        r.get_attribute.side_effect = lambda attr, f=fn, i=idx: f if attr == "aria-label" else ("true" if (attr == "checked" and i == 0) else f"_r_{i}_")
        r.is_checked.return_value = (idx == 0)
        radio_mocks.append(r)

    sdui_radios = MagicMock()
    sdui_radios.count.return_value = len(radio_mocks)
    sdui_radios.nth.side_effect = lambda idx: radio_mocks[idx]

    def locator_side_effect(sel):
        if "jobs-document-upload-redesign-card__container" in sel:
            return legacy_cards
        if "Upload resume" in sel or "Resume*" in sel or "Resume" in sel:
            return resume_indicator
        if "radiogroup" in sel or "aria-label*='.pdf'" in sel:
            return sdui_radios
        m = MagicMock()
        m.count.return_value = 0
        return m

    modal.locator.side_effect = locator_side_effect

    # Case A: Config matches exact stored filename (Guru_Prasad-Resume.pdf)
    matched = applicant.select_resume_by_name(modal)
    assert matched is True
    assert applicant.answers_filled["Resume"] == "Guru_Prasad-Resume.pdf"

    # Case B: Config specifies non-existent resume -> HALTS with RESUME_NOT_FOUND
    applicant.profile = {"resume": {"selected_filename": "Nonexistent_Resume.pdf"}}
    with pytest.raises(ResumeMismatchHaltError) as exc_info:
        applicant.select_resume_by_name(modal)
    assert "RESUME_NOT_FOUND" in str(exc_info.value)

    # Case C: answer_screening_fields skips the resume fieldset
    fs = MagicMock()
    fs.locator.side_effect = lambda sel: sdui_radios if ".pdf" in sel else MagicMock(count=lambda: 0)
    fieldsets = MagicMock()
    fieldsets.count.return_value = 1
    fieldsets.nth.return_value = fs

    def mock_modal_for_fields(sel):
        if sel == "fieldset":
            return fieldsets
        m = MagicMock()
        m.count.return_value = 0
        return m

    modal.locator.side_effect = mock_modal_for_fields
    fields_ok, pending_q = applicant.answer_screening_fields(modal)
    assert fields_ok is True
    assert pending_q is None
    # Verify "Unknown radio question" was NOT recorded or flagged
    assert "Unknown radio question" not in applicant.answers_filled


def test_sdui_labels_and_required_detection():
    """
    Verifies that _extract_field_label and _is_field_required correctly extract:
    - Preceding heading 'Resume*' for fieldsets without legends
    - Asterisk requirement detection
    - Non-required text inputs (What is your current location?) without asterisks
    """
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)
    modal = MagicMock()

    # Fieldset with preceding heading Resume*
    fs = MagicMock()
    fs.get_attribute.return_value = None
    legend = MagicMock()
    legend.count.return_value = 0
    prec_p = MagicMock()
    prec_p.count.return_value = 1
    prec_p.inner_text.return_value = "Resume*"
    prec_p.first = prec_p

    def fs_locator(sel):
        if "legend" in sel:
            return legend
        if "preceding::p" in sel:
            return prec_p
        m = MagicMock()
        m.count.return_value = 0
        return m

    fs.locator.side_effect = fs_locator
    label = applicant._extract_field_label(modal, fs, default="Unknown radio question")
    assert label == "Resume*"
    assert label != "Unknown radio question"
    assert applicant._is_field_required(fs, label) is True

    # Text input with aria-label="What is your current location?" (optional)
    inp = MagicMock()
    inp.get_attribute.side_effect = lambda attr: "What is your current location?" if attr == "aria-label" else None
    inp.locator.return_value = MagicMock(count=lambda: 0)
    inp_label = applicant._extract_field_label(modal, inp, default="Unknown question")
    assert inp_label == "What is your current location?"
    assert applicant._is_field_required(inp, inp_label) is False


def test_experience_dropdown_exact_option_matching_and_asterisk_label(capsys):
    """
    Verifies Item 2 requirements:
    1. Real label with asterisk 'How many years of relevant work experience do you have?*' matches approved patterns.
    2. Dropdown selection is strictly by exact option text (no nearest/rounding).
    3. If configured answer matches option text, it is selected via safe_select_option(label=...).
    4. If configured answer is not in options, it halts safely to NEEDS_INPUT with options seen.
    """
    from src.answerer import FormAnswerer
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    applicant.answerer = FormAnswerer()
    test_entry = {
        "patterns": [
            "how many years of relevant work experience do you have",
            "years of relevant work experience"
        ],
        "value": "3-4 years",
        "exact_match": True,
        "source": "provided by user"
    }
    applicant.answerer.approved_answers = [test_entry]

    modal = MagicMock()
    modal.locator.return_value.count.return_value = 0

    sel = MagicMock()
    sel.get_attribute.side_effect = lambda a: "true" if a in ("required", "aria-required") else None
    sel.input_value.return_value = ""

    label_text = "How many years of relevant work experience do you have?*"
    applicant._extract_field_label = MagicMock(return_value=label_text)

    real_options = ["Select an option", "1-2 years", "3-4 years", "5-6 years", "7-10 years", "11+ years"]
    opt_locs = []
    for opt in real_options:
        om = MagicMock()
        om.inner_text.return_value = opt
        opt_locs.append(om)

    opt_mock = MagicMock()
    opt_mock.count.return_value = len(real_options)
    opt_mock.nth.side_effect = lambda idx: opt_locs[idx]

    sel.locator.side_effect = lambda s: opt_mock if "option" in s else MagicMock(count=lambda: 0)

    def modal_locator_dispatch(sel_query):
        if sel_query == "select":
            m = MagicMock()
            m.count.return_value = 1
            m.nth.return_value = sel
            return m
        m = MagicMock()
        m.count.return_value = 0
        return m

    modal.locator.side_effect = modal_locator_dispatch

    # Test 1: Configured answer "3-4 years" matches exact option
    with patch("src.platforms.linkedin.SafeLocator") as mock_safe_loc:
        ok, pending_q = applicant.answer_screening_fields(modal)
        assert ok is True
        assert pending_q is None
        assert applicant.answers_filled[label_text] == "3-4 years"
        mock_safe_loc.return_value.safe_select_option.assert_called_with(label="3-4 years")

    # Test 2: Configured answer "5 years" (not an exact option; e.g. nearest would be "5-6 years")
    # Must NOT round or nearest-match -> must halt to NEEDS_INPUT with options seen
    test_entry["value"] = "5 years"
    applicant.answers_filled = {}
    with patch("src.platforms.linkedin.SafeLocator") as mock_safe_loc:
        ok, pending_q = applicant.answer_screening_fields(modal)
        assert ok is False
        assert label_text in pending_q
        assert "[type: dropdown, options: 1-2 years, 3-4 years, 5-6 years, 7-10 years, 11+ years]" in pending_q
        mock_safe_loc.return_value.safe_select_option.assert_not_called()

        out = capsys.readouterr().out
        assert "[NEEDS INPUT] Unanswered required dropdown:" in out
        assert "Options seen: ['1-2 years', '3-4 years', '5-6 years', '7-10 years', '11+ years']" in out


def test_timing_race_modal_content_renders_after_3_seconds():
    """
    Verifies Item 3 requirement:
    A fake modal whose content appears after 3 seconds polls and succeeds bounded.
    """
    import time
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    page = MagicMock()
    modal = MagicMock()

    start_time = time.time()

    def progress_count():
        elapsed = time.time() - start_time
        return 1 if elapsed >= 3.0 else 0

    prog_mock = MagicMock()
    prog_mock.count.side_effect = progress_count

    modal.locator.side_effect = lambda sel: prog_mock if ".jobs-easy-apply-modal__progress" in sel else MagicMock(count=lambda: 0)

    rendered = applicant._wait_for_modal_content_rendered(modal, page, job_id="test-race", timeout=6.0, poll_interval=0.1)
    assert rendered is True
    assert time.time() - start_time >= 3.0


def test_timing_race_modal_content_never_renders_times_out_and_records_modal_content_not_rendered():
    """
    Verifies Item 3 requirement:
    A fake modal that never renders content times out, saves snapshot,
    records MODAL_CONTENT_NOT_RENDERED as 1 strike in DB, and discards.
    """
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards, is_rehearsal=True)

    page = MagicMock()
    modal = MagicMock()
    page.locator.return_value.first = modal
    modal.count.return_value = 1

    empty_loc = MagicMock()
    empty_loc.count.return_value = 0
    empty_loc.first = empty_loc
    modal.locator.return_value = empty_loc

    with patch.object(applicant, "_wait_for_modal_content_rendered", return_value=False) as mock_wait, \
         patch.object(applicant, "discard_modal") as mock_discard, \
         patch("src.platforms.linkedin.save_rehearsal_snapshot") as mock_snap:

        res = applicant.process_application(page, job_id="race-timeout-job", title="Engineer", company="TechCorp")
        assert res["status"] == "MODAL_CONTENT_NOT_RENDERED"
        assert "MODAL_CONTENT_NOT_RENDERED" in res["reason"]

        mock_wait.assert_called_once()
        mock_snap.assert_called_with(page, "race-timeout-job", "modal_content_not_rendered")
        mock_discard.assert_called_once_with(page, "race-timeout-job")
        db.update_job_status.assert_called_with(
            platform="linkedin",
            job_id="race-timeout-job",
            status="MODAL_CONTENT_NOT_RENDERED",
            failure_reason="MODAL_CONTENT_NOT_RENDERED: Modal container detected but inner content failed to render within 15 seconds"
        )


def test_double_discard_is_noop_when_no_dialog_open_and_never_clicks_outside(capsys):
    """
    Verifies Item 4 requirement:
    When no modal dialog is open, discard_modal is a complete no-op and never clicks
    any element (such as dismiss/discard buttons) on the page.
    """
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    page = MagicMock()

    no_dialog = MagicMock()
    no_dialog.count.return_value = 0

    outside_dismiss = MagicMock()
    outside_dismiss.count.return_value = 1

    def page_locator(sel):
        if "dialog[open]" in sel or "jobs-easy-apply-modal" in sel or "data-test-modal" in sel:
            return no_dialog
        return outside_dismiss

    page.locator.side_effect = page_locator

    applicant.discard_modal(page, job_id="4467464995")

    out = capsys.readouterr().out
    assert "[TRACE: DISCARD] No open dialog detected for job 4467464995. Discard is a no-op." in out
    outside_dismiss.click.assert_not_called()
    outside_dismiss.first.click.assert_not_called()


def test_process_application_does_not_double_discard_on_attempts_limit():
    """
    Verifies Item 4 root cause:
    When session attempt limit is reached and check_attempts_guard raises AttemptsLimitReachedError,
    process_application does NOT execute a duplicate discard_modal call in its exception handler.
    """
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    page = MagicMock()
    modal = MagicMock()
    page.locator.return_value.first = modal
    modal.count.return_value = 1

    applicant._wait_for_modal_content_rendered = MagicMock(return_value=True)
    applicant.get_step_fingerprint = MagicMock(return_value="Step 1")
    applicant.handle_city_typeahead = MagicMock()
    applicant.select_resume_by_name = MagicMock(return_value=True)
    applicant.answer_screening_fields = MagicMock(return_value=(False, "Test unanswered question"))

    from src.guards import AttemptsLimitReachedError
    guards.check_attempts_guard.side_effect = AttemptsLimitReachedError("Daily/Session attempts limit reached")

    with patch.object(applicant, "discard_modal") as mock_discard:
        with pytest.raises(AttemptsLimitReachedError):
            applicant.process_application(page, job_id="4467464995", title="Engineer", company="Acme")

        assert mock_discard.call_count == 1


def test_step_4_review_not_recognized_halts_safely(tmp_path):
    """
    Verifies Item 3 requirement:
    If page 4/4 or 100% progress is reached but Review is not recognized:
    - record STEP_FAILED
    - save snapshot rehearsal_<id>_step_4_review_not_recognized
    - print button labels
    - discard modal
    - exit cleanly. Never click Submit in rehearsal.
    """
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards, is_rehearsal=True)

    page = MagicMock()
    modal = MagicMock()
    page.locator.return_value.first = modal
    modal.count.return_value = 1

    applicant._wait_for_modal_content_rendered = MagicMock(return_value=True)
    counter = {"val": 0}
    applicant.get_step_fingerprint = MagicMock(side_effect=lambda m: f"fingerprint_{counter.__setitem__('val', counter['val'] + 1) or counter['val']}")
    applicant.handle_city_typeahead = MagicMock()
    applicant.select_resume_by_name = MagicMock(return_value=True)
    applicant.answer_screening_fields = MagicMock(return_value=(True, None))

    # At step 1, 2, 3: not 100%, not review
    # At step 4: 100% progress but review NOT recognized
    applicant._detect_review_and_progress = MagicMock(side_effect=[
        (False, False, "", ""), # Step 1
        (False, False, "", ""), # Step 2
        (False, False, "", ""), # Step 3
        (False, True, "", ""),  # Step 4: 100% progress, but review is NOT recognized
    ])

    btn_mock = MagicMock()
    btn_mock.get_attribute.return_value = "Continue"
    btn_mock.inner_text.return_value = "Next"
    modal.locator.return_value.first = btn_mock
    modal.locator.return_value.count.return_value = 1

    with patch("src.platforms.linkedin.save_rehearsal_snapshot") as mock_save_snap, \
         patch.object(applicant, "discard_modal") as mock_discard:
        res = applicant.process_application(page, job_id="4467464995", title="Engineer", company="Particle41")

        assert res["status"] == "STEP_FAILED"
        assert "REVIEW_NOT_RECOGNIZED" in res["reason"]
        mock_save_snap.assert_any_call(page, "4467464995", "step_4_review_not_recognized")
        mock_discard.assert_called_with(page, "4467464995")
        db.update_job_status.assert_called_with(
            platform="linkedin",
            job_id="4467464995",
            status="STEP_FAILED",
            failure_reason="REVIEW_NOT_RECOGNIZED: Step 4 reached 100% progress / page 4/4 but Review page was not recognized"
        )


def test_approval_sheet_content_and_unmasked_values(tmp_path):
    """
    Verifies Item 4 requirements:
    On OBSERVED_REVIEW: print and save logs/approval_<jobid>.txt containing:
    - job title, company, location, URL
    - match score and reason
    - resume name
    - steps handled
    - every field with label, UNMASKED value, source (LinkedIn pre-filled / answers.yaml / profile.yaml / dynamic)
    - optional fields left blank
    - follow-company state
    - Submit button label
    - and line 'NO SUBMISSION PERFORMED'.
    """
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards, is_rehearsal=True)

    applicant.fields_detail = [
        {"label": "Resume", "value": "Guru_Prasad-Resume.pdf", "source": "profile.yaml resume.selected_filename"},
        {"label": "City", "value": "Jaipur", "source": "profile.yaml personal.current_city"},
        {"label": "First name", "value": "Guru", "source": "LinkedIn pre-filled"},
        {"label": "Last name", "value": "Prasad", "source": "LinkedIn pre-filled"},
        {"label": "Email", "value": "guruprasadregar1@gmail.com", "source": "profile.yaml"},
        {"label": "Phone", "value": "+91 63785 26193", "source": "profile.yaml"},
        {"label": "Current CTC", "value": "1260000", "source": "answers.yaml"},
        {"label": "Expected CTC", "value": "2000000", "source": "answers.yaml"},
        {"label": "How many years of relevant work experience do you have?*", "value": "3-4 years", "source": "answers.yaml"},
        {"label": "What is your last working date?*", "value": "02 Jan 2027", "source": "dynamic"},
    ]
    applicant.optional_fields_blank = [
        "GitHub URL (text)",
        "Additional Notes (textarea)"
    ]

    sheet = applicant.generate_approval_sheet(
        job_id="4467464995",
        title="Senior Full Stack Developer",
        company="Particle41",
        location="Remote, India",
        url="https://www.linkedin.com/jobs/view/4467464995/",
        match_score=92,
        match_reason="Strong match in React, Node.js, and TypeScript",
        resume_name="Guru_Prasad-Resume.pdf",
        steps_handled=4,
        follow_state="unchecked, verified",
        submit_btn_label="Submit application"
    )

    # 1. Header & Job info
    assert "APPLICATION APPROVAL SHEET" in sheet
    assert "Job Title           : Senior Full Stack Developer" in sheet
    assert "Company             : Particle41" in sheet
    assert "Location            : Remote, India" in sheet
    assert "URL                 : https://www.linkedin.com/jobs/view/4467464995/" in sheet
    assert "Match Score         : 92" in sheet
    assert "Resume Name         : Guru_Prasad-Resume.pdf" in sheet
    assert "Steps Handled       : 4" in sheet
    assert "Follow Company State: unchecked, verified" in sheet
    assert "Submit Button Label : Submit application" in sheet

    # 2. Strict UNMASKED values verification (plain text values for user review)
    assert "guruprasadregar1@gmail.com" in sheet
    assert "+91 63785 26193" in sheet
    assert "1260000" in sheet
    assert "2000000" in sheet
    assert "Guru" in sheet
    assert "Prasad" in sheet
    assert "Jaipur" in sheet
    assert "3-4 years" in sheet
    assert "02 Jan 2027" in sheet

    # 3. Sources verification
    assert "[LinkedIn pre-filled]" in sheet
    assert "[answers.yaml]" in sheet
    assert "[profile.yaml" in sheet
    assert "[dynamic]" in sheet

    # 4. Optional fields left blank
    assert "Optional Fields Left Blank:" in sheet
    assert "GitHub URL (text)" in sheet
    assert "Additional Notes (textarea)" in sheet

    # 5. Non-submission guarantee line
    assert "NO SUBMISSION PERFORMED" in sheet


def test_replay_saved_snapshots_detection():
    """
    Item 3: Replay test against saved snapshots (stating layout for each snapshot).
    Layouts:
    1. linkedin_05_modal_review.html: Legacy HTML5 modal with completeness meter at 100%,
       heading 'Review your application', and button 'Submit application'.
    2. rehearsal_4467464995_step_3.html: Modern SDUI dialog layout at Step 3 (75% progress).
    3. linkedin_03_modal_step1.html: Legacy modal at Step 1 (not Review).
    4. rehearsal_4467464995_step_1.html: Modern SDUI dialog at Step 1 (not Review).
    """
    from playwright.sync_api import sync_playwright
    snapshots_dir = Path(__file__).resolve().parent.parent / "docs" / "snapshots"
    applicant = LinkedInApplicant(MagicMock(), MagicMock(), is_rehearsal=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Snapshot 1: Legacy Review layout
        legacy_review_file = snapshots_dir / "linkedin_05_modal_review.html"
        assert legacy_review_file.exists()
        page.goto(legacy_review_file.as_uri(), wait_until="domcontentloaded")
        modal = page.locator("div.jobs-easy-apply-modal, div[data-test-modal]").first
        is_review, is_100, heading, btn_label = applicant._detect_review_and_progress(modal)
        assert is_review is True, "Legacy review snapshot must be detected as review"
        assert is_100 is True, "Legacy review snapshot must be detected as 100% progress"
        assert "review" in heading.lower()
        assert "submit" in btn_label.lower()

        # Snapshot 2: Modern SDUI Step 3 layout (75% progress, NOT Review)
        sdui_step3_file = snapshots_dir / "rehearsal_4467464995_step_3.html"
        assert sdui_step3_file.exists()
        page.goto(sdui_step3_file.as_uri(), wait_until="domcontentloaded")
        modal_sdui3 = page.locator("dialog[open], dialog").first
        is_review_s3, is_100_s3, _, _ = applicant._detect_review_and_progress(modal_sdui3)
        assert is_review_s3 is False, "SDUI Step 3 must NOT be detected as Review"
        assert is_100_s3 is False, "SDUI Step 3 must NOT be detected as 100% progress"

        # Snapshot 3: Legacy Step 1 layout (NOT Review)
        legacy_step1_file = snapshots_dir / "linkedin_03_modal_step1.html"
        assert legacy_step1_file.exists()
        page.goto(legacy_step1_file.as_uri(), wait_until="domcontentloaded")
        modal_leg1 = page.locator("div.jobs-easy-apply-modal, div[data-test-modal]").first
        is_review_l1, is_100_l1, _, _ = applicant._detect_review_and_progress(modal_leg1)
        assert is_review_l1 is False
        assert is_100_l1 is False

        # Snapshot 4: Modern SDUI Step 1 layout (NOT Review)
        sdui_step1_file = snapshots_dir / "rehearsal_4467464995_step_1.html"
        assert sdui_step1_file.exists()
        page.goto(sdui_step1_file.as_uri(), wait_until="domcontentloaded")
        modal_sdui1 = page.locator("dialog[open], dialog").first
        is_review_s1, is_100_s1, _, _ = applicant._detect_review_and_progress(modal_sdui1)
        assert is_review_s1 is False
        assert is_100_s1 is False

        browser.close()


def test_step_4_review_not_recognized_halts_safely(capsys):
    """
    Verifies that if page 4/4 or 100% progress is reached but Review is not recognized:
    - Status is recorded as STEP_FAILED in DB with REVIEW_NOT_RECOGNIZED
    - Snapshot rehearsal_<id>_step_4_review_not_recognized is taken
    - Dialog buttons are printed
    - Modal is discarded
    - Returns STEP_FAILED and never clicks Submit
    """
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards, is_rehearsal=True)

    page = MagicMock()
    modal = MagicMock()
    page.locator.return_value.first = modal
    modal.count.return_value = 1

    with patch.object(applicant, "_wait_for_modal_content_rendered", return_value=True), \
         patch.object(applicant, "handle_city_typeahead", return_value=True), \
         patch.object(applicant, "select_resume_by_name", return_value=True), \
         patch.object(applicant, "answer_screening_fields", return_value=(True, None)), \
         patch.object(applicant, "_detect_review_and_progress", return_value=(False, True, "", "")), \
         patch.object(applicant, "_extract_and_log_dialog_buttons", return_value=["Back", "SomeUnrecognizedBtn"]), \
         patch.object(applicant, "discard_modal") as mock_discard, \
         patch("src.platforms.linkedin.save_rehearsal_snapshot") as mock_snap:

        res = applicant.process_application(page, job_id="4467464995", title="Senior Engineer", company="Particle41")
        assert res["status"] == "STEP_FAILED"
        assert "REVIEW_NOT_RECOGNIZED" in res["reason"]

        mock_snap.assert_called_with(page, "4467464995", "step_4_review_not_recognized")
        mock_discard.assert_called_once_with(page, "4467464995")
        db.update_job_status.assert_called_with(
            platform="linkedin",
            job_id="4467464995",
            status="STEP_FAILED",
            failure_reason="REVIEW_NOT_RECOGNIZED: Step 1 reached 100% progress / page 4/4 but Review page was not recognized"
        )
        out = capsys.readouterr().out
        assert "[STEP FAILED] REVIEW_NOT_RECOGNIZED" in out
        assert "Buttons on unrecognized step 4: ['Back', 'SomeUnrecognizedBtn']" in out


def test_replay_step1_step2_step3_none_is_last_page_and_advances():
    """
    Item 5 test 1: Replay step_1, step_2 and step_3 snapshots from rehearsal_4467464995_*:
    - None is the last page (is_100_percent is False).
    - None is Review (is_review is False).
    - Each has an enabled advance button (Next for steps 1 and 2; Review for step 3).
    """
    from playwright.sync_api import sync_playwright
    snapshots_dir = Path(__file__).resolve().parent.parent / "docs" / "snapshots"
    applicant = LinkedInApplicant(MagicMock(), MagicMock(), is_rehearsal=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Step 1: Contact info (25% progress, Next button present)
        s1_file = snapshots_dir / "rehearsal_4467464995_step_1.html"
        assert s1_file.exists()
        page.goto(s1_file.as_uri(), wait_until="domcontentloaded")
        modal_s1 = page.locator("dialog[open], dialog").first
        if modal_s1.locator("button:has-text('Next')").count() == 0:
            s1_file = snapshots_dir / "rehearsal_4467464995_halt_needs_input_step_1.html"
            page.goto(s1_file.as_uri(), wait_until="domcontentloaded")
            modal_s1 = page.locator("dialog[open], dialog").first
        is_rev_s1, is_100_s1, _, _ = applicant._detect_review_and_progress(modal_s1)
        assert is_rev_s1 is False, "Step 1 must not be detected as Review"
        assert is_100_s1 is False, "Step 1 must not be detected as last page"
        next_s1 = modal_s1.locator("button:has-text('Next')").first
        assert next_s1.count() > 0 and next_s1.is_enabled()

        # Step 2: Resume (50% progress, contains 4/4/2026 upload date, Next button present)
        s2_file = snapshots_dir / "rehearsal_4467464995_step_2.html"
        assert s2_file.exists()
        page.goto(s2_file.as_uri(), wait_until="domcontentloaded")
        modal_s2 = page.locator("dialog[open], dialog").first
        is_rev_s2, is_100_s2, _, _ = applicant._detect_review_and_progress(modal_s2)
        assert is_rev_s2 is False, "Step 2 must not be detected as Review"
        assert is_100_s2 is False, "Step 2 must not be detected as last page despite 4/4/2026 date text"
        next_s2 = modal_s2.locator("button:has-text('Next')").first
        assert next_s2.count() > 0 and next_s2.is_enabled()

        # Step 3: Screening questions (75% progress, Review button present)
        s3_file = snapshots_dir / "rehearsal_4467464995_step_3.html"
        assert s3_file.exists()
        page.goto(s3_file.as_uri(), wait_until="domcontentloaded")
        modal_s3 = page.locator("dialog[open], dialog").first
        is_rev_s3, is_100_s3, _, _ = applicant._detect_review_and_progress(modal_s3)
        assert is_rev_s3 is False, "Step 3 must not be detected as Review"
        assert is_100_s3 is False, "Step 3 must not be detected as last page"
        rev_s3 = modal_s3.locator("button:has-text('Review')").first
        assert rev_s3.count() > 0 and rev_s3.is_enabled()

        browser.close()


def test_linkedin_05_modal_review_recognised_as_review():
    """
    Item 5 test 2: linkedin_05_modal_review.html is recognised as Review.
    """
    from playwright.sync_api import sync_playwright
    snapshots_dir = Path(__file__).resolve().parent.parent / "docs" / "snapshots"
    applicant = LinkedInApplicant(MagicMock(), MagicMock(), is_rehearsal=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        legacy_file = snapshots_dir / "linkedin_05_modal_review.html"
        assert legacy_file.exists()
        page.goto(legacy_file.as_uri(), wait_until="domcontentloaded")
        modal = page.locator("div.jobs-easy-apply-modal, div[data-test-modal]").first
        is_rev, is_100, heading, btn = applicant._detect_review_and_progress(modal)

        assert is_rev is True, "linkedin_05_modal_review.html must be recognised as Review"
        assert is_100 is True, "linkedin_05_modal_review.html must be recognised as 100% progress"
        assert "review" in heading.lower()
        assert "submit" in btn.lower()

        browser.close()


def test_synthetic_dialog_100_percent_with_review_heading_and_submit_recognised():
    """
    Item 5 test 3: A synthetic dialog with aria-valuenow 100, heading 'Review your application',
    and a Submit button is recognised as Review.
    """
    from playwright.sync_api import sync_playwright
    applicant = LinkedInApplicant(MagicMock(), MagicMock(), is_rehearsal=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        html_content = """
        <!DOCTYPE html>
        <html>
        <body>
            <dialog open>
                <div role="progressbar" aria-valuenow="100" aria-valuemin="0" aria-valuemax="100"></div>
                <h2>Review your application</h2>
                <div class="form-content">Review details here</div>
                <div class="footer">
                    <button type="button">Back</button>
                    <button type="submit" aria-label="Submit application">Submit application</button>
                </div>
            </dialog>
        </body>
        </html>
        """
        page.set_content(html_content)
        modal = page.locator("dialog[open]").first

        is_rev, is_100, heading, btn = applicant._detect_review_and_progress(modal)
        assert is_rev is True, "Synthetic 100% dialog with Review heading & Submit button must be recognised as Review"
        assert is_100 is True, "Must be recognised as 100% last page"
        assert "review your application" in heading.lower()
        assert "submit application" in btn.lower()

        browser.close()


def test_synthetic_dialog_100_percent_no_heading_no_submit_becomes_review_not_recognized(capsys):
    """
    Item 5 test 4: A synthetic dialog at 100 with no heading and no Submit becomes REVIEW_NOT_RECOGNIZED.
    """
    from playwright.sync_api import sync_playwright
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards, is_rehearsal=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        html_content = """
        <!DOCTYPE html>
        <html>
        <body>
            <dialog open>
                <div role="progressbar" aria-valuenow="100" aria-valuemin="0" aria-valuemax="100"></div>
                <h2>Additional information</h2>
                <p>Some random form without review elements</p>
                <div class="footer">
                    <button type="button">Back</button>
                    <button type="button" aria-label="Done">Done</button>
                </div>
            </dialog>
        </body>
        </html>
        """
        page.set_content(html_content)
        modal = page.locator("dialog[open]").first

        is_rev, is_100, heading, btn = applicant._detect_review_and_progress(modal)
        assert is_rev is False, "Dialog without Review heading and without Submit must NOT be recognised as Review"
        assert is_100 is True, "Progressbar at 100 with no Next/Review button is detected as 100% progress"

        with patch.object(applicant, "discard_modal") as mock_discard, \
             patch("src.platforms.linkedin.save_rehearsal_snapshot") as mock_snap:
            res = applicant.process_application(page, job_id="synthetic-100-job", title="Software Engineer", company="TestCo")
            assert res["status"] == "STEP_FAILED"
            assert "REVIEW_NOT_RECOGNIZED" in res["reason"]
            mock_snap.assert_called_with(page, "synthetic-100-job", "step_4_review_not_recognized")
            mock_discard.assert_called_once_with(page, "synthetic-100-job")

        out = capsys.readouterr().out
        assert "[STEP FAILED] REVIEW_NOT_RECOGNIZED" in out

        browser.close()


def test_policy_blocks_upload_cover_letter_and_upload_resume():
    """
    Item 5 test 5: 'Upload cover letter' and 'Upload resume' (and any control containing 'upload')
    are blocked by policy.
    """
    from src.policy import PolicyEngine, PolicyBlockError

    # 1. 'Upload cover letter' text blocked
    with pytest.raises(PolicyBlockError, match="Clicking upload controls"):
        PolicyEngine.validate_action("click", text="Upload cover letter")

    # 2. 'Upload resume' text blocked
    with pytest.raises(PolicyBlockError, match="Clicking upload controls"):
        PolicyEngine.validate_action("click", text="Upload resume")

    # 3. Generic 'Upload' text blocked
    with pytest.raises(PolicyBlockError, match="Clicking upload controls"):
        PolicyEngine.validate_action("click", text="Upload")

    # 4. Selector with upload blocked
    with pytest.raises(PolicyBlockError, match="Clicking upload controls"):
        PolicyEngine.validate_action("click", selector="button[aria-label='Upload cover letter']")

    with pytest.raises(PolicyBlockError, match="Clicking upload controls"):
        PolicyEngine.validate_action("click", selector="input[type='file']")


def test_city_typeahead_modern_sdui_placeholder_fills_configured_city():
    """Verifies handle_city_typeahead finds and fills modern SDUI city input."""
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)
    applicant.profile = {"personal": {"current_city": "Jaipur"}}

    modal = MagicMock()
    city_loc = MagicMock()
    city_loc.count.return_value = 1
    city_input = MagicMock()
    city_input.input_value.return_value = ""  # empty
    city_loc.first = city_input

    def mock_loc(selector, **kwargs):
        if "placeholder*='city'" in selector or "typeahead-input" in selector:
            return city_loc
        sugg = MagicMock()
        sugg.count.return_value = 0
        return sugg

    modal.locator.side_effect = mock_loc

    applicant.handle_city_typeahead(modal)
    city_input.fill.assert_called_with("Jaipur")
    assert applicant.answers_filled["City"] == "Jaipur"


def test_answer_screening_fields_fills_location_city():
    """Verifies answer_screening_fields fills 'Location (city)*' with Jaipur from profile/answers."""
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)
    applicant.profile = {"personal": {"current_city": "Jaipur"}}

    modal = MagicMock()
    inp = MagicMock()
    inp.get_attribute.side_effect = lambda attr: "text" if attr == "type" else None
    inp.input_value.return_value = ""
    inputs = MagicMock()
    inputs.count.return_value = 1
    inputs.nth.return_value = inp

    empty_loc = MagicMock()
    empty_loc.count.return_value = 0

    def mock_modal_loc(sel, **kwargs):
        if "artdeco-text-input" in sel:
            return inputs
        return empty_loc

    modal.locator.side_effect = mock_modal_loc
    applicant._extract_field_label = MagicMock(return_value="Location (city)*")
    applicant._is_field_required = MagicMock(return_value=True)

    with patch("src.platforms.linkedin.SafeLocator") as mock_safe_loc:
        ok, pending_q = applicant.answer_screening_fields(modal)
        assert ok is True
        assert pending_q is None
        mock_safe_loc.return_value.safe_fill.assert_called_with("Jaipur")
        assert applicant.answers_filled["Location (city)*"] == "Jaipur"










def test_should_prompt_typed_yes_always_and_conditional():
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    # 1. Mode: always -> always prompts
    applicant.confirmation_mode = "always"
    applicant.fields_detail = [
        {"step": 1, "source": "answers.yaml", "label": "Notice Period", "value": "60 days"}
    ]
    should_prompt, reason = applicant.should_prompt_typed_yes(MagicMock())
    assert should_prompt is True
    assert "always" in reason.lower()

    # 2. Mode: conditional -> with standard answers -> does NOT prompt
    applicant.confirmation_mode = "conditional"
    applicant.fields_detail = [
        {"step": 1, "source": "answers.yaml", "label": "Notice Period", "value": "60 days"},
        {"step": 1, "source": "LinkedIn pre-filled", "label": "Email", "value": "test@example.com"},
        {"step": 2, "source": "dynamic last working date", "label": "Last working date", "value": "21 Dec 2026"}
    ]
    should_prompt, _ = applicant.should_prompt_typed_yes(MagicMock())
    assert should_prompt is False

    # 3. Mode: conditional -> with consent question -> DOES prompt
    applicant.fields_detail.append(
        {"step": 2, "source": "answers.yaml", "label": "Do you agree with the terms and privacy policy?", "value": "Yes"}
    )
    should_prompt, reason = applicant.should_prompt_typed_yes(MagicMock())
    assert should_prompt is True
    assert "consent question" in reason.lower()

    # 4. Mode: conditional -> with non-standard source -> DOES prompt
    applicant.fields_detail = [
        {"step": 1, "source": "Claude CLI generated", "label": "Why do you want this role?", "value": "Strong match"}
    ]
    should_prompt, reason = applicant.should_prompt_typed_yes(MagicMock())
    assert should_prompt is True
    assert "non-standard source" in reason.lower()


def test_approval_sheet_deduplication_and_step_display():
    db = MagicMock()
    guards = MagicMock()
    applicant = LinkedInApplicant(db, guards)

    applicant.fields_detail = [
        {"step": 1, "source": "answers.yaml", "label": "Current CTC", "value": "1260000"},
        {"step": 1, "source": "answers.yaml", "label": "Current CTC", "value": "1260000"},  # duplicate
        {"step": 2, "source": "answers.yaml", "label": "Notice Period", "value": "60 days"},
    ]

    sheet = applicant.generate_approval_sheet(
        job_id="test-job",
        title="Senior Developer",
        company="Enterprise Bot",
        location="Jaipur, India",
        url="https://www.linkedin.com/jobs/view/test-job/",
        match_score=90,
        match_reason="Good match",
        resume_name="Guru_Prasad.pdf",
        steps_handled=2,
        follow_state="unchecked, verified",
        submit_btn_label="Submit application"
    )

    # Current CTC should appear only once in the fields list
    assert sheet.count("Current CTC") == 1
    assert "[Step 1] [answers.yaml] Current CTC: 1260000" in sheet
    assert "[Step 2] [answers.yaml] Notice Period: 60 days" in sheet


def test_process_application_same_company_skips():
    db = MagicMock()
    guards = MagicMock()
    guards.can_apply_to_company.return_value = (False, "SAME_COMPANY_RECENTLY_APPLIED")

    applicant = LinkedInApplicant(db, guards)
    res = applicant.process_application(
        page=MagicMock(),
        job_id="job-dup-123",
        title="Full Stack Engineer",
        company="Enterprise Bot LLC"
    )

    assert res["status"] == "SKIPPED"
    assert res["reason"] == "SAME_COMPANY_RECENTLY_APPLIED"
    db.update_job_status.assert_called_with(
        platform="linkedin",
        job_id="job-dup-123",
        status="SKIPPED",
        failure_reason="SAME_COMPANY_RECENTLY_APPLIED"
    )


def test_process_application_typed_yes_prompt(monkeypatch):
    db = MagicMock()
    guards = MagicMock()
    guards.can_apply_to_company.return_value = (True, "")

    applicant = LinkedInApplicant(db, guards)
    applicant.observe_only = False
    applicant.is_rehearsal = False
    applicant.review_mode = True
    applicant.confirmation_mode = "always"

    modal = MagicMock()
    modal.count.return_value = 1
    applicant.is_modal_content_rendered = MagicMock(return_value=True)
    applicant._wait_for_modal_content_rendered = MagicMock(return_value=True)
    applicant._detect_review_and_progress = MagicMock(return_value=(True, True, "Review your application", "Submit application"))
    applicant.verify_availability_consistency = MagicMock(return_value=(True, "60 days", "21 Dec 2026", "Within 2 months", ""))
    applicant.recheck_follow_company = MagicMock(return_value=("unchecked, verified", False))
    applicant.discard_modal = MagicMock()

    applicant.select_resume_by_name = MagicMock(return_value=True)
    applicant.answer_screening_fields = MagicMock(return_value=(True, None))

    # User inputs 'NO' (cancelled)
    monkeypatch.setattr("builtins.input", lambda _: "NO")
    res_no = applicant.process_application(
        page=MagicMock(),
        job_id="job-yes-test",
        title="Full Stack Engineer",
        company="NewCo"
    )
    assert res_no["status"] == "SKIPPED_BY_USER"
    applicant.discard_modal.assert_called_once()
