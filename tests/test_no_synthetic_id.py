import pytest
from unittest.mock import MagicMock
from src.platforms.linkedin import LinkedInCollector
from src.platforms.naukri import NaukriCollector

def test_linkedin_skips_card_without_job_id_no_synthetic_id(capsys):
    db = MagicMock()
    guards = MagicMock()
    matcher = MagicMock()

    collector = LinkedInCollector(db, guards, matcher)

    page = MagicMock()
    page.url = "https://www.linkedin.com/jobs/search/"

    mock_cards = MagicMock()
    mock_cards.count.return_value = 3

    def nth_card(idx):
        card = MagicMock()
        # Returns None for all job id attributes
        card.get_attribute.return_value = None
        inner_container = MagicMock()
        inner_container.count.return_value = 0
        card.locator.return_value = inner_container
        return card

    mock_cards.nth.side_effect = nth_card
    page.locator.return_value = mock_cards

    jobs = collector.run_phase8a_search(
        page=page,
        search_query={"keywords": "React", "location": "Bengaluru"},
        max_jobs=3,
        dry_run=True
    )

    captured = capsys.readouterr()
    assert "Logged NO_JOB_ID" in captured.out
    assert len(jobs) == 0
    # Crucial: DB is never touched with a synthetic ID
    assert db.record_job.call_count == 0
    assert db.upsert_job.call_count == 0

def test_naukri_skips_tuple_without_job_id_no_synthetic_id(capsys):
    db = MagicMock()
    guards = MagicMock()
    matcher = MagicMock()

    collector = NaukriCollector(db, guards, matcher)

    page = MagicMock()
    page.url = "https://www.naukri.com/react-jobs-in-bengaluru"

    mock_tuples = MagicMock()
    mock_tuples.count.return_value = 2

    def nth_tuple(idx):
        t = MagicMock()
        # Title link exists but href has no job id pattern
        title_el = MagicMock()
        title_el.count.return_value = 1
        title_el.inner_text.return_value = f"Developer {idx}"
        title_el.get_attribute.return_value = "https://www.naukri.com/some-random-page-no-id"

        comp_el = MagicMock()
        comp_el.count.return_value = 1
        comp_el.inner_text.return_value = "Acme Corp"

        def tuple_locator(sel):
            if "title" in sel:
                return MagicMock(first=title_el)
            if "comp-name" in sel:
                return MagicMock(first=comp_el)
            m = MagicMock()
            m.count.return_value = 0
            m.first = m
            return m

        t.locator.side_effect = tuple_locator
        t.get_attribute.return_value = None  # No data-job-id attribute
        return t

    mock_tuples.nth.side_effect = nth_tuple
    page.locator.return_value = mock_tuples

    jobs = collector.run_phase8a_search(
        page=page,
        search_query={"keywords": "React", "location": "Bengaluru"},
        max_jobs=2,
        dry_run=True
    )

    captured = capsys.readouterr()
    assert "Logged NO_JOB_ID" in captured.out
    assert len(jobs) == 0
    assert db.record_job.call_count == 0
    assert db.upsert_job.call_count == 0
