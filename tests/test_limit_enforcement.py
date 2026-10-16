import pytest
from unittest.mock import MagicMock
from src.platforms.linkedin import LinkedInCollector
from src.platforms.naukri import NaukriCollector
from src.matcher import MatchResult

def test_linkedin_limit_enforcement():
    db = MagicMock()
    db.job_exists.return_value = False
    db.is_job_blocked.return_value = False
    guards = MagicMock()
    matcher = MagicMock()
    matcher.evaluate_hard_filters.return_value = (False, "")
    matcher.evaluate_fit.return_value = MatchResult(should_apply=True, score=85, reason="Good match")

    collector = LinkedInCollector(db, guards, matcher)

    page = MagicMock()
    page.url = "https://www.linkedin.com/jobs/search/"
    
    # Mock 25 job cards available on page
    mock_cards = MagicMock()
    mock_cards.count.return_value = 25
    
    def nth_card(idx):
        card = MagicMock()
        card.get_attribute.side_effect = lambda attr: f"job-{idx}" if attr == "data-job-id" else None
        
        title_el = MagicMock()
        title_el.count.return_value = 1
        title_el.inner_text.return_value = f"Senior React Developer {idx}"
        
        comp_el = MagicMock()
        comp_el.count.return_value = 1
        comp_el.inner_text.return_value = "Acme Labs"
        
        loc_el = MagicMock()
        loc_el.count.return_value = 1
        loc_el.inner_text.return_value = "Bengaluru, Karnataka, India"

        def card_locator(sel, **kwargs):
            if "job-card-list__title--link" in sel:
                return MagicMock(first=title_el)
            if "company" in sel or "subtitle" in sel:
                return MagicMock(first=comp_el)
            if "metadata" in sel or "caption" in sel:
                return MagicMock(first=loc_el)
            m = MagicMock()
            m.count.return_value = 0
            m.first = m
            return m
            
        card.locator.side_effect = card_locator
        card.inner_text.return_value = f"Senior React Developer {idx}"
        return card

    mock_cards.nth.side_effect = nth_card
    
    easy_apply_btn = MagicMock()
    easy_apply_btn.count.return_value = 1
    
    desc_el = MagicMock()
    desc_el.count.return_value = 1
    desc_el.first.inner_text.return_value = "React, Node.js, AWS job description"
    
    def page_locator_side_effect(sel, **kwargs):
        if "jobs-search-results__list-item" in sel or "job-card-container" in sel:
            return mock_cards
        if "jobs-apply-button-id" in sel:
            return easy_apply_btn
        if "jobs-description" in sel:
            return desc_el
        mock = MagicMock()
        mock.count.return_value = 0
        return mock
        
    page.locator.side_effect = page_locator_side_effect

    # Run with max_jobs = 10
    results = collector.run_phase8a_search(
        page=page,
        search_query={"keywords": "React", "location": "Bengaluru"},
        max_jobs=10,
        dry_run=True
    )

    # Must inspect at most 10 jobs despite 25 being on the page
    assert len(results) == 10
    assert db.record_job.call_count == 10

def test_naukri_limit_enforcement():
    db = MagicMock()
    db.job_exists.return_value = False
    db.is_job_blocked.return_value = False
    guards = MagicMock()
    matcher = MagicMock()
    matcher.evaluate_hard_filters.return_value = (False, "")
    matcher.evaluate_fit.return_value = MatchResult(should_apply=True, score=80, reason="Fit")

    collector = NaukriCollector(db, guards, matcher)

    page = MagicMock()
    page.url = "https://www.naukri.com/senior-full-stack-developer-jobs-in-bengaluru"

    # Mock 40 tuples available on page
    mock_tuples = MagicMock()
    mock_tuples.count.return_value = 40

    def nth_tuple(idx):
        t = MagicMock()
        t.get_attribute.side_effect = lambda attr: f"98765432{idx:04d}" if attr == "data-job-id" else None
        
        title_el = MagicMock()
        title_el.count.return_value = 1
        title_el.inner_text.return_value = f"Full Stack Engineer {idx}"
        title_el.get_attribute.return_value = f"https://www.naukri.com/job-listings-98765432{idx:04d}"

        comp_el = MagicMock()
        comp_el.count.return_value = 1
        comp_el.inner_text.return_value = "Tech Corp"

        loc_el = MagicMock()
        loc_el.count.return_value = 1
        loc_el.inner_text.return_value = "Bengaluru"

        def tuple_loc(sel, **kwargs):
            if "a.title" in sel:
                return MagicMock(first=title_el)
            if "comp-name" in sel:
                return MagicMock(first=comp_el)
            if "loc" in sel:
                return MagicMock(first=loc_el)
            m = MagicMock()
            m.count.return_value = 0
            m.first = m
            return m
            
        t.locator.side_effect = tuple_loc
        return t

    mock_tuples.nth.side_effect = nth_tuple

    # Detail page mock
    mock_detail_page = MagicMock()
    mock_detail_page.url = "https://www.naukri.com/job-listings-987654320000"
    
    comp_site_btn = MagicMock()
    comp_site_btn.count.return_value = 0
    
    plain_apply_btn = MagicMock()
    plain_apply_btn.count.return_value = 1
    
    desc_el = MagicMock()
    desc_el.count.return_value = 1
    desc_el.first.inner_text.return_value = "Naukri Job Description"

    def detail_locator_side_effect(sel, **kwargs):
        if "company-site-button" in sel:
            return comp_site_btn
        if "apply-button" in sel:
            return plain_apply_btn
        if "job-desc-wrap" in sel:
            return desc_el
        m = MagicMock()
        m.count.return_value = 0
        return m

    mock_detail_page.locator.side_effect = detail_locator_side_effect
    page.context.new_page.return_value = mock_detail_page

    def page_locator_side_effect(sel, **kwargs):
        if "srp-jobtuple-wrapper" in sel:
            return mock_tuples
        m = MagicMock()
        m.count.return_value = 0
        return m

    page.locator.side_effect = page_locator_side_effect

    # Run with max_jobs = 10
    results = collector.run_phase8a_search(
        page=page,
        search_query={"keywords": "Full Stack", "locations": ["Bengaluru"]},
        max_jobs=10,
        dry_run=True
    )

    # Must inspect and record at most 10 jobs despite 40 being on the page
    assert db.record_job.call_count == 10
