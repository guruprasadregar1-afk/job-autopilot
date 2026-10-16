import re
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml
from src.llm import ask_json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = PROJECT_ROOT / "config" / "profile.yaml"
ANSWERS_PATH = PROJECT_ROOT / "config" / "answers.yaml"
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"

def format_numeric_digits_only(value: Any) -> str:
    """
    Formats numeric answers strictly to digits only for fields identified as
    INR compensation or notice period in days.
    - Succeeded values return integer string (e.g. '1500000', '60').
    - Never rounds decimals (e.g. '4.5' -> 'UNKNOWN').
    - Never strips letters from free text (e.g. '4.5 years' -> 'UNKNOWN').
    - Ambiguous inputs return 'UNKNOWN'.
    """
    if value is None:
        return "UNKNOWN"
    val_str = str(value).strip()
    if not val_str:
        return "UNKNOWN"

    # Explicit check: If string contains decimals outside LPA/Lakh notation, return UNKNOWN
    if re.search(r"\d+\.\d+", val_str) and not re.search(r"(?:lpa|lakh|lac|lacs|lakhs)", val_str, re.IGNORECASE):
        return "UNKNOWN"

    # If string contains words like years, months, exp, etc. return UNKNOWN
    if re.search(r"\b(?:year|years|month|months|exp|experience)\b", val_str, re.IGNORECASE):
        return "UNKNOWN"

    # Handle LPA / Lakh notation (e.g. '15 LPA' -> 1500000, '25 LPA' -> 2500000)
    lpa_match = re.search(r"^₹?\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakh|lac|lacs|lakhs)(?:\s*/-)?$", val_str, re.IGNORECASE)
    if lpa_match:
        num = float(lpa_match.group(1))
        computed = num * 100000
        if computed.is_integer():
            return str(int(computed))
        return "UNKNOWN"

    # Handle notice period in days (e.g. "60 days", "60 Days", "60")
    days_match = re.search(r"^(\d+)\s*(?:days?)?$", val_str, re.IGNORECASE)
    if days_match:
        return days_match.group(1)

    # Handle currency formatted with commas / currency symbols (e.g. "15,00,000", "₹ 15,00,000 /-", "INR 1500000")
    curr_match = re.search(r"^(?:(?:INR|Rs\.?|₹)\s*)?([\d,]+)(?:\s*/-)?$", val_str, re.IGNORECASE)
    if curr_match:
        digits = curr_match.group(1).replace(",", "").strip()
        if digits.isdigit():
            return digits

    return "UNKNOWN"


class FormAnswerer:
    def __init__(
        self,
        profile_path: Optional[Path] = None,
        answers_path: Optional[Path] = None,
        settings_path: Optional[Path] = None,
        cli_command: str = "claude.cmd"
    ):
        self.profile_path = profile_path or PROFILE_PATH
        self.answers_path = answers_path or ANSWERS_PATH
        self.settings_path = settings_path or SETTINGS_PATH
        self.cli_command = cli_command
        self.profile = self._load_yaml(self.profile_path)
        self.approved_answers = self._load_yaml(self.answers_path).get("answers", [])
        self.settings = self._load_yaml(self.settings_path)

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            example_path = path.parent / (path.stem + ".example.yaml")
            if example_path.exists():
                path = example_path
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def reload_answers(self) -> None:
        """Reloads approved answers from answers_path."""
        self.approved_answers = self._load_yaml(self.answers_path).get("answers", [])

    def normalize(self, text: str) -> str:
        return re.sub(r"[^\w\s]", "", text.lower()).strip()

    def is_inr_or_notice_field(self, question: str) -> bool:
        """Identifies fields representing INR compensation or notice period in days."""
        norm = self.normalize(question)
        return any(k in norm for k in ["ctc", "salary", "compensation", "inr", "notice period", "notice", "days to join"])

    def find_direct_answer(self, question: str, field_type: str = "text", options: Optional[List[str]] = None) -> Optional[str]:
        """
        Checks answers.yaml first for a normalized pattern match.
        Saves Claude CLI calls.
        """
        norm_q = self.normalize(question)

        for entry in self.approved_answers:
            # Enforce experience rule:
            # "total/overall/professional experience" phrasing may return 4.5.
            # Any question naming a specific skill, technology or domain returns UNKNOWN -> NEEDS_INPUT.
            is_experience_entry = (str(entry.get("value")) == "4.5")
            if is_experience_entry:
                has_specific_qualifier = bool(re.search(r"\b(with|using)\b", norm_q))
                has_specific_tech = bool(re.search(r"\b(java|aws|react|node|full\s*stack|fullstack|python|angular|vue|devops|cloud|backend|frontend|golang|git|docker|kubernetes|sql)\b", norm_q))
                if has_specific_qualifier or has_specific_tech:
                    continue

            # Skill entries must NOT apply to questions about years or duration
            is_skill_entry = entry.get("exact_match", False) or ("textarea_value" in entry)
            if is_skill_entry:
                is_years_or_duration = bool(re.search(r"\b(year|years|month|months|duration|how long|exp|experience)\b", norm_q))
                if is_years_or_duration or field_type == "number":
                    continue

            patterns = entry.get("patterns", [])
            exact_match = entry.get("exact_match", False)
            for pat in patterns:
                norm_pat = self.normalize(pat)
                matched = (norm_pat == norm_q) if exact_match else (norm_pat in norm_q or norm_q in norm_pat)
                if matched:
                    # Match found in answers.yaml
                    if field_type == "number":
                        if self.is_inr_or_notice_field(question):
                            raw_val = entry.get("numeric_value", entry.get("value", ""))
                            val = format_numeric_digits_only(raw_val)
                            if val == "UNKNOWN":
                                return None
                        else:
                            if "numeric_value" in entry:
                                val = str(entry["numeric_value"])
                            else:
                                raw_val = str(entry.get("value", ""))
                                if re.match(r"^\d+(?:\.\d+)?$", raw_val.strip()):
                                    val = raw_val.strip()
                                else:
                                    return None
                    elif field_type == "textarea":
                        val = str(entry.get("textarea_value", entry.get("value", "")))
                    elif field_type in ("radio", "dropdown", "checkbox") or options:
                        val = str(entry.get("value", ""))
                    else:
                        val = str(entry.get("textarea_value", entry.get("value", "")))

                    # If options are present, candidate MUST match one of the options
                    if options:
                        return self._match_option(val, options)
                    return val

        return None

    def _match_option(self, value: str, options: List[str]) -> Optional[str]:
        """Validates that value exists among offered options."""
        norm_val = self.normalize(value)
        
        # 1. Exact normalized match
        for opt in options:
            if self.normalize(opt) == norm_val:
                return opt

        # 2. Whole-word match (e.g. "Yes" in "Yes, I have...")
        for opt in options:
            norm_opt = self.normalize(opt)
            if norm_opt and re.search(r'\b' + re.escape(norm_opt) + r'\b', norm_val):
                return opt

        # 3. Substring match for longer descriptive options
        for opt in options:
            norm_opt = self.normalize(opt)
            if len(norm_opt) > 3 and (norm_val in norm_opt or norm_opt in norm_val):
                return opt

        # 3. Standard duration semantic conversions (e.g. 60 days -> 2 months)
        duration_map = {
            "60 days": ["2 months", "2 month", "60 days", "60"],
            "30 days": ["1 month", "1 months", "30 days", "30"],
            "90 days": ["3 months", "3 month", "90 days", "90"],
            "15 days": ["15 days", "2 weeks"],
        }
        for key, aliases in duration_map.items():
            if norm_val == self.normalize(key):
                for alias in aliases:
                    for opt in options:
                        if alias in self.normalize(opt):
                            return opt

        # If options are offered and none match, must NOT return ungrounded string
        return None

    def answer_question(
        self,
        question: str,
        field_type: str = "text",
        options: Optional[List[str]] = None
    ) -> str:
        """
        Determines the answer for a screening form field.
        1. Checks answers.yaml first.
        2. Queries Claude if no local match.
        3. Strictly validates result in Python.
        Returns the valid answer string, or literal 'UNKNOWN'.
        """
        # Step 1: Check answers.yaml first
        direct_match = self.find_direct_answer(question, field_type=field_type, options=options)
        if direct_match is not None:
            return direct_match

        norm_q = self.normalize(question)
        # Gate specific skill/technology/domain questions: per-skill years are not claimed in profile.yaml.
        # Any question naming a specific skill, technology, or domain returns "UNKNOWN" -> NEEDS_INPUT.
        is_specific_skill = (
            bool(re.search(r"\b(with|using)\b", norm_q))
            or bool(re.search(r"\b(java|aws|react|node|full\s*stack|fullstack|python|angular|vue|devops|cloud|backend|frontend|golang|git|docker|kubernetes|sql)\b", norm_q))
        )
        if is_specific_skill:
            return "UNKNOWN"

        # Step 2: Query Claude if no direct match

        model = self.settings.get("llm", {}).get("models", {}).get("answerer", "claude-sonnet-5-5")
        
        # Grounding facts
        facts = {
            "personal": {
                "name": self.profile.get("personal", {}).get("full_name"),
                "city": self.profile.get("personal", {}).get("current_city"),
                "country": self.profile.get("personal", {}).get("current_country"),
                "postal_code": self.profile.get("personal", {}).get("postal_code"),
            },
            "experience": self.profile.get("experience", {}),
            "compensation": self.profile.get("compensation_and_notice", {}),
            "skills": self.profile.get("skills", {}),
            "education": self.profile.get("education", []),
        }

        prompt = f"""You are answering an application screening question for a candidate.
Answer ONLY if directly supported by the candidate facts below.
If the facts do not contain the exact required answer, answer EXACTLY "UNKNOWN".
Do NOT guess, fabricate, or assume any experience years, visa status, or salary.

CANDIDATE FACTS:
{facts}

QUESTION:
{question}
Field Type: {field_type}
Offered Options: {options if options else "None"}

INSTRUCTIONS:
1. If options are provided, your answer MUST match one of the offered options.
2. If the field is numeric, output only digits/decimal.
3. If unsupported by the facts, return "UNKNOWN".
4. Output ONLY valid JSON:
{{"answer": "..."}}"""

        try:
            res = ask_json(prompt, model=model, cli_command=self.cli_command)
            candidate_answer = str(res.get("answer", "")).strip()

            if not candidate_answer or candidate_answer.upper() == "UNKNOWN":
                return "UNKNOWN"

            # Step 3: Python-side Validation
            if options:
                matched = self._match_option(candidate_answer, options)
                if matched:
                    return matched
                return "UNKNOWN"

            if field_type == "number":
                if self.is_inr_or_notice_field(question):
                    cleaned = format_numeric_digits_only(candidate_answer)
                    if cleaned and cleaned != "UNKNOWN":
                        return cleaned
                    return "UNKNOWN"
                return candidate_answer

            return candidate_answer

        except Exception:
            return "UNKNOWN"
