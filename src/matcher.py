import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
import yaml
from src.llm import ask_json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = PROJECT_ROOT / "config" / "profile.yaml"
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"

@dataclass
class MatchResult:
    should_apply: bool
    score: int
    reason: str
    hard_rejected: bool = False

class JobMatcher:
    def __init__(
        self,
        profile_path: Optional[Path] = None,
        settings_path: Optional[Path] = None,
        cli_command: str = "claude.cmd"
    ):
        self.profile_path = profile_path or PROFILE_PATH
        self.settings_path = settings_path or SETTINGS_PATH
        self.cli_command = cli_command
        self.profile = self._load_yaml(self.profile_path)
        self.settings = self._load_yaml(self.settings_path)

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            example_path = path.parent / (path.stem + ".example.yaml")
            if example_path.exists():
                path = example_path
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def evaluate_hard_filters(self, title: str, company: str, location: str, description: str = "") -> Tuple[bool, str]:
        """
        Runs inexpensive Python hard-filters BEFORE calling Claude.
        Returns (is_rejected: bool, reason: str).
        """
        title_lower = title.lower()
        company_lower = company.lower()
        loc_lower = location.lower()
        desc_lower = description.lower()
        prefs = self.profile.get("preferences", {})

        # 1. Company Blacklist Check
        blacklist = prefs.get("company_blacklist", [])
        for bl_company in blacklist:
            if bl_company.lower() in company_lower:
                return True, f"Hard-rejected: Company '{company}' is blacklisted ({bl_company})."

        # 2. Excluded Titles Check
        exclude_titles = prefs.get("target_titles_exclude", [])
        for ex_title in exclude_titles:
            pattern = rf"\b{re.escape(ex_title.lower())}\b"
            if re.search(pattern, title_lower):
                return True, f"Hard-rejected: Job title contains excluded keyword '{ex_title}'."

        # 3. Regional / Work Authorization Restrictions Check (Outside India)
        combined_text = f"{title_lower} {loc_lower} {desc_lower}"
        outside_restrictions = [
            r"\bus only\b",
            r"\bu\.s\. only\b",
            r"\bus residents? only\b",
            r"\bu\.s\. residents? only\b",
            r"\beu residents? only\b",
            r"\buk residents? only\b",
            r"\bcanada only\b",
            r"\bcanadian residents? only\b",
            r"\bmust be authorized to work in the us\b",
            r"\bmust be authorized to work in the u\.s\b",
            r"\bmust be authorized to work in the united states\b",
            r"\bmust be legally authorized to work in the us\b",
            r"\bmust be legally authorized to work in the united states\b",
            r"\bmust be legally authorized to work in the u\.s\b",
            r"\bwork authorization in the us required\b",
            r"\bus citizenship required\b",
            r"\bu\.s\. citizenship required\b",
            r"\bus citizens? only\b",
            r"\bgreen card or us citizen\b",
            r"\bno c2c or visa sponsorship\b",
            r"\bmust be located in the us\b",
            r"\bmust reside in the us\b",
            r"\bmust be based in the us\b",
            r"\bapplicants must be legally authorized to work in the us\b",
        ]
        for pat in outside_restrictions:
            m = re.search(pat, combined_text)
            if m:
                matched_kw = m.group(0)
                return True, f"Hard-rejected: Job restricts candidates to regions outside India ('{matched_kw}')."

        # 4. Location Check (if location is provided)
        if loc_lower:
            allowed_locations = [loc.lower() for loc in prefs.get("target_locations_india", [])]
            allowed_locations.extend([loc.lower() for loc in prefs.get("target_locations_international", [])])
            work_modes = [wm.lower() for wm in prefs.get("work_modes", [])]
            if "remote" in work_modes:
                allowed_locations.append("remote")
            
            # Check if any allowed location keyword is in the job location string
            matches_location = any(al in loc_lower for al in allowed_locations)
            # If location string is specified and does not match any preference or remote/India
            if not matches_location and len(loc_lower.strip()) > 2:
                # We do not strictly hard reject if it says remote in title
                if "remote" not in title_lower:
                    return True, f"Hard-rejected: Location '{location}' is outside target regions."

        return False, ""

    def evaluate_fit(self, title: str, company: str, location: str, description: str) -> MatchResult:
        """
        Evaluates a job against candidate profile.
        Hard-rejects in Python first to save Claude calls.
        Calls Claude only if hard filters pass.
        """
        # Hard-filters first (including regional / authorization restrictions)
        rejected, reason = self.evaluate_hard_filters(title, company, location, description)
        if rejected:
            return MatchResult(should_apply=False, score=0, reason=reason, hard_rejected=True)

        # Build prompt for Claude
        model = self.settings.get("llm", {}).get("models", {}).get("matcher", "claude-haiku-4-5")
        threshold = self.settings.get("llm", {}).get("match_score_threshold", 65)

        # Condensed profile representation (no personal PII like phone or email passed; summary omitted)
        condensed_profile = {
            "role": self.profile.get("experience", {}).get("current_role"),
            "total_experience_years": self.profile.get("experience", {}).get("total_years"),
            "primary_skills": self.profile.get("skills", {}),
            "used_in_projects": self.profile.get("used_in_projects", []),
            "projects": [
                {
                    "name": p.get("name"),
                    "role": p.get("role"),
                    "stack": p.get("stack"),
                    "description": p.get("description"),
                }
                for p in self.profile.get("projects", [])
            ],
            "target_titles": self.profile.get("preferences", {}).get("target_titles_include", []),
        }

        prompt = f"""You are evaluating whether a candidate should apply to this job.
Base your evaluation ONLY on the provided candidate facts and the job description. Do not assume or hallucinate any skills.

CANDIDATE FACTS:
{condensed_profile}

JOB DETAILS:
Title: {title}
Company: {company}
Location: {location}
Description:
{description[:3000]}

INSTRUCTIONS:
1. Score the match from 0 to 100 based on required tech stack and experience.
2. If score >= {threshold}, set apply = true, otherwise false.
3. Provide a one-sentence reason explaining the decision.
4. Output ONLY a valid JSON object matching this schema:
{{"apply": boolean, "score": integer, "reason": "one sentence"}}"""

        try:
            res = ask_json(prompt, model=model, cli_command=self.cli_command)
            score = int(res.get("score", 0))
            apply_val = bool(res.get("apply", False)) and (score >= threshold)
            reason_str = str(res.get("reason", "Scored by matcher.")).strip()
            return MatchResult(should_apply=apply_val, score=score, reason=reason_str)
        except Exception as e:
            return MatchResult(should_apply=False, score=0, reason=f"Matcher evaluation failed: {e}")
