import pytest
from src.matcher import JobMatcher

def test_hard_reject_blacklisted_company():
    matcher = JobMatcher()
    matcher.profile.setdefault("preferences", {})["company_blacklist"] = ["Blacklisted Corp"]
    rejected, reason = matcher.evaluate_hard_filters(
        title="Senior Full Stack Developer",
        company="Blacklisted Corp Pvt Ltd",
        location="Bengaluru"
    )
    assert rejected is True
    assert "blacklisted" in reason.lower()

def test_hard_reject_excluded_title():
    matcher = JobMatcher()
    matcher.profile["preferences"]["target_titles_exclude"] = ["Junior", "QA", "WordPress", "PHP"]
    for bad_title in ["Junior React Developer", "QA Automation Tester", "WordPress Developer", "PHP Developer"]:
        rejected, reason = matcher.evaluate_hard_filters(
            title=bad_title,
            company="Some Tech Corp",
            location="Bengaluru"
        )
        assert rejected is True
        assert "excluded keyword" in reason.lower()

def test_hard_filter_allows_valid_job():
    matcher = JobMatcher()
    rejected, reason = matcher.evaluate_hard_filters(
        title="Senior Full Stack Developer",
        company="Top Tier Cloud Solutions",
        location="Bengaluru"
    )
    assert rejected is False
    assert reason == ""

def test_hard_reject_outside_india_restrictions():
    matcher = JobMatcher()
    restricted_cases = [
        ("Full Stack Engineer (US Only)", "Top Tech", "Remote", "Great role for candidates."),
        ("Senior React Developer", "Global Corp", "United States", "US residents only apply."),
        ("Lead Node.js Engineer", "Euro Systems", "Remote", "Role open to EU residents only."),
        ("Backend Developer", "Cloud Inc", "Remote", "Candidate must be authorized to work in the US."),
        ("Senior Full Stack Developer", "American Tech", "Remote", "Applicants must be legally authorized to work in the United States without sponsorship."),
        ("Full Stack Engineer", "Defense Tech", "Remote", "US citizenship required.")
    ]
    for title, comp, loc, desc in restricted_cases:
        # Test direct hard filter
        rejected, reason = matcher.evaluate_hard_filters(title, comp, loc, desc)
        assert rejected is True, f"Failed to reject restricted job: {title} | {desc}"
        assert "outside india" in reason.lower()

        # Test evaluate_fit returns score 0 and should_apply False without calling Claude
        fit_res = matcher.evaluate_fit(title, comp, loc, desc)
        assert fit_res.score == 0
        assert fit_res.should_apply is False
        assert "outside india" in fit_res.reason.lower()

