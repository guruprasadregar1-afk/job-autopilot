import re
from datetime import datetime, timezone, timedelta
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
    - Never rounds decimals (e.g. '5.5' -> 'UNKNOWN').
    - Never strips letters from free text (e.g. '5.5 years' -> 'UNKNOWN').
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

def get_kolkata_now() -> datetime:
    """Returns current datetime in Asia/Kolkata timezone (UTC+05:30)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        kolkata_tz = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
        return datetime.now(kolkata_tz)

def compute_last_working_date(base_date: Optional[datetime] = None, format_hint: str = "") -> str:
    """
    Computes last working date as base_date (or TODAY in Asia/Kolkata) + 60 days.
    Inspects format_hint (from helper text, aria-describedby, or placeholder) to determine format.
    Defaults to 'DD Mon YYYY'.
    """
    if base_date is None:
        base_date = get_kolkata_now()

    target_date = base_date + timedelta(days=60)
    hint_lower = (format_hint or "").lower().strip()

    if "dd/mm/yyyy" in hint_lower or "d/m/y" in hint_lower or "dd/mm/yy" in hint_lower:
        return target_date.strftime("%d/%m/%Y")
    elif "yyyy-mm-dd" in hint_lower or "y-m-d" in hint_lower:
        return target_date.strftime("%Y-%m-%d")
    elif "mm/dd/yyyy" in hint_lower or "m/d/y" in hint_lower:
        return target_date.strftime("%m/%d/%Y")
    elif "dd-mm-yyyy" in hint_lower or "d-m-y" in hint_lower:
        return target_date.strftime("%d-%m-%Y")
    elif "mon dd, yyyy" in hint_lower or "month dd, yyyy" in hint_lower:
        return target_date.strftime("%b %d, %Y")
    elif "dd month yyyy" in hint_lower:
        return target_date.strftime("%d %B %Y")
    else:
        # Default format when no format is stated
        return target_date.strftime("%d %b %Y")


def normalize_exact_option(text: str) -> str:
    """
    Normalizes option text for exact matching:
    - Case-insensitive
    - Strips surrounding whitespace
    - Strips trailing period and surrounding whitespace
    """
    if not text:
        return ""
    s = str(text).strip()
    s = s.rstrip(".").strip()
    return s.lower()


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
        self.approved_skill_years = self._load_yaml(self.answers_path).get("approved_skill_years", {})
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
        self.approved_skill_years = self._load_yaml(self.answers_path).get("approved_skill_years", {})

    def normalize(self, text: str) -> str:
        cleaned = re.sub(r"[^\w\s]", "", text.lower())
        return re.sub(r"\s+", " ", cleaned).strip()

    def is_inr_or_notice_field(self, question: str) -> bool:
        """Identifies fields representing INR compensation or notice period in days."""
        norm = self.normalize(question)
        return any(k in norm for k in ["ctc", "salary", "compensation", "inr", "notice period", "notice", "days to join"])

    def is_consent_question(self, question: str, options: Optional[List[str]] = None) -> bool:
        """
        Returns True if the question or any offered option contains any consent-related keyword:
        agree, consent, terms, conditions, privacy, policy, acknowledge, authorize,
        authorise, declaration, certify, GDPR, newsletter, marketing, contact me (case-insensitive).
        """
        consent_keywords = [
            "agree", "consent", "terms", "conditions", "privacy", "policy",
            "acknowledge", "authorize", "authorise", "declaration",
            "certify", "gdpr", "newsletter", "marketing", "contact me"
        ]
        def _has_kw(text: str) -> bool:
            if not text:
                return False
            norm = self.normalize(text)
            for kw in consent_keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", norm):
                    return True
            return False

        if _has_kw(question):
            return True
        if options:
            for opt in options:
                if _has_kw(opt):
                    return True
        return False

    def find_direct_answer(self, question: str, field_type: str = "text", options: Optional[List[str]] = None) -> Optional[str]:
        """
        Checks answers.yaml first for a normalized pattern match.
        Saves Claude CLI calls.
        """
        norm_q = self.normalize(question)
        is_consent = self.is_consent_question(question, options=options)

        # Special rule for control labelled just "Bachelor's degree" / "Bachelors degree":
        # Answered ONLY when its options are exactly Yes and No (case-insensitive); otherwise NEEDS_INPUT.
        if norm_q in ("bachelors degree", "bachelor degree"):
            if options and field_type in ("radio", "dropdown", "select", "checkbox"):
                opt_set = {normalize_exact_option(o) for o in options if normalize_exact_option(o) not in ("select an option", "select", "please select", "choose an option", "")}
                if opt_set == {"yes", "no"}:
                    for opt in options:
                        if normalize_exact_option(opt) == "yes":
                            return opt
            return None

        # Special rule for "years of work experience with <skill>":
        # Sourced exclusively from user confirmations.
        # Approved skills and years: [React.js: __, Node.js: __, JavaScript: __, TypeScript: __, Next.js: __, NestJS: __, MongoDB: __, PostgreSQL: __, AWS: __, or "none approved"]
        # Match the skill name exactly (case-insensitive) in questions of the form "how many years of work experience do you have with <skill>";
        # fill only text or number inputs with the digits, or select the exact option text in a dropdown.
        # Any other skill, tool or domain (IPython, Data Engineering, Back-End Web Development, etc.) -> None -> NEEDS_INPUT.
        skill_years_match = re.search(
            r"^(?:how many )?years of (?:work )?experience (?:do you have )?(?:with|in) (.+)$",
            norm_q
        )
        if skill_years_match:
            skill_candidate = skill_years_match.group(1).strip()
            matched_years = None
            for approved_skill, years_val in (self.approved_skill_years or {}).items():
                if self.normalize(approved_skill) == self.normalize(skill_candidate):
                    matched_years = str(years_val)
                    break

            if matched_years is not None:
                digits_only = re.sub(r"\D", "", matched_years)
                if field_type in ("text", "number") and not options:
                    return digits_only
                if options:
                    for opt in options:
                        norm_opt = normalize_exact_option(opt)
                        if norm_opt in (normalize_exact_option(matched_years), digits_only, f"{digits_only} years", f"{digits_only} yrs"):
                            return opt
                    return None
            return None

        for entry in self.approved_answers:
            # Enforce experience rule:
            # "total/overall/professional experience" phrasing may return 5.
            # Any question naming a specific skill, technology or domain returns UNKNOWN -> NEEDS_INPUT,
            # UNLESS an explicit approved entry exists for that specific skill (e.g. back-end web development).
            is_general_experience_entry = (
                str(entry.get("value")) in ("5", "5.0")
                and any("total" in p or "overall" in p for p in entry.get("patterns", []))
                and not any("back-end" in p or "backend" in p for p in entry.get("patterns", []))
            )
            if is_general_experience_entry:
                has_specific_qualifier = bool(re.search(r"\b(with|using)\b", norm_q))
                has_specific_tech = bool(re.search(r"\b(java|aws|react|node|full\s*stack|fullstack|python|angular|vue|devops|cloud|backend|frontend|golang|git|docker|kubernetes|sql)\b", norm_q))
                if has_specific_qualifier or has_specific_tech:
                    continue

            # Skill entries must NOT apply to questions about years or duration
            is_explicit_years_pattern = any(
                re.search(r"\b(year|years|month|months|duration|how long|exp|experience)\b", p.lower())
                for p in entry.get("patterns", [])
            )
            is_skill_entry = ("textarea_value" in entry or entry.get("exact_match", False)) and not is_explicit_years_pattern and "numeric_value" not in entry
            if is_skill_entry:
                is_years_or_duration = bool(re.search(r"\b(year|years|month|months|duration|how long|exp|experience)\b", norm_q))
                if is_years_or_duration or field_type == "number":
                    continue

            # URL entries (LinkedIn, Website, Portfolio): fill only text/URL inputs, never radio/dropdown/checkbox
            is_url_entry = str(entry.get("value", "")).startswith("http://") or str(entry.get("value", "")).startswith("https://")
            if is_url_entry:
                if field_type not in ("text", "url", "textarea") or options:
                    continue

            # Last working date: text inputs only, computed at fill time
            is_lwd_entry = any(
                p in ("what is your last working date", "last working date") for p in entry.get("patterns", [])
            )
            if is_lwd_entry:
                if field_type not in ("text", "url", "textarea") or options:
                    continue

            # Relocation rule: only applies to questions that do NOT name a country outside India
            is_relocation_entry = any("relocat" in p for p in entry.get("patterns", []))
            if is_relocation_entry:
                foreign_country_named = bool(re.search(
                    r"\b(us|usa|u\.s\.|united states|uk|u\.k\.|united kingdom|germany|canada|uae|dubai|australia|europe|singapore)\b",
                    norm_q
                ))
                if foreign_country_named:
                    continue

            # Work authorization in India rule: only applies to questions that do NOT name a country outside India
            is_india_work_auth_entry = any("authorized to work" in p or "work authorization" in p for p in entry.get("patterns", []))
            if is_india_work_auth_entry:
                foreign_country_named = bool(re.search(
                    r"\b(us|usa|u\.s\.|united states|uk|u\.k\.|united kingdom|germany|canada|uae|dubai|australia|europe|singapore)\b",
                    norm_q
                ))
                if foreign_country_named:
                    continue

            # Field type constraint: e.g. select/dropdown only
            allowed_field_types = entry.get("allowed_field_types") or entry.get("field_types")
            if allowed_field_types and field_type not in allowed_field_types:
                continue

            # Require exact options if specified in entry (e.g. Yes and No)
            require_options = entry.get("require_options")
            if require_options:
                if not options:
                    if field_type != "checkbox":
                        continue
                else:
                    req_set = {normalize_exact_option(ro) for ro in require_options}
                    opt_set = {normalize_exact_option(o) for o in options if normalize_exact_option(o) not in ("select an option", "select", "please select", "choose an option", "")}
                    if opt_set != req_set:
                        continue

            # Consent Guard: If question or options contain consent keywords,
            # this entry must NOT match UNLESS it has user_approved_consent: true,
            # user_approved_date (date of approval), and exact_match: true.
            if is_consent:
                if not entry.get("user_approved_consent"):
                    continue
                if not (entry.get("user_approved_date") or entry.get("date")):
                    continue
                if not entry.get("exact_match", False):
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
                        val = str(entry.get("text_value", entry.get("textarea_value", entry.get("value", ""))))

                    if val == "DYNAMIC_LAST_WORKING_DATE":
                        val = compute_last_working_date()

                    # If options are present, candidate MUST match one of the options
                    if options:
                        accepted = entry.get("accepted_options")
                        if accepted:
                            for accepted_opt in accepted:
                                norm_acc = normalize_exact_option(accepted_opt)
                                for opt in options:
                                    if normalize_exact_option(opt) == norm_acc:
                                        return opt
                            return None

                        if exact_match or entry.get("exact_option_match", False):
                            # Only exact normalized option match allowed (no nearest, rounding or partial)
                            norm_val = self.normalize(val)
                            norm_exact_val = normalize_exact_option(val)
                            for opt in options:
                                if self.normalize(opt) == norm_val or normalize_exact_option(opt) == norm_exact_val:
                                    return opt
                            return None
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
        # Any question asking about years or experience that was not directly matched in answers.yaml
        # returns strictly UNKNOWN -> NEEDS_INPUT (no per-skill years are approved).
        if any(w in norm_q for w in ["experience", "years", "year", "duration", "how long"]):
            return "UNKNOWN"

        # Gate specific skill/technology/domain questions: per-skill years are not claimed in profile.yaml.
        # Any question naming a specific skill, technology, or domain returns "UNKNOWN" -> NEEDS_INPUT.
        is_specific_skill = (
            bool(re.search(r"\b(with|using)\b", norm_q))
            or bool(re.search(r"\b(java|javascript|typescript|js|ts|aws|react|node|full\s*stack|fullstack|python|angular|vue|devops|cloud|backend|frontend|golang|go|git|docker|kubernetes|sql|mongodb|postgres|postgresql)\b", norm_q))
        )
        if is_specific_skill:
            return "UNKNOWN"

        # Education guards: Master's degree, highest level of education, field of study, university, grade, graduation year strictly UNKNOWN -> NEEDS_INPUT
        if any(k in norm_q for k in [
            "master", "highest level of education", "highest education",
            "field of study", "university", "college", "school",
            "gpa", "grade", "percentage", "graduation year", "year of graduation"
        ]):
            return "UNKNOWN"

        # Relevant work experience: only allowed as dropdown/select with "5-6 years". Never round. If text, number, or not matched, strictly UNKNOWN -> NEEDS_INPUT.
        if "relevant work experience" in norm_q:
            return "UNKNOWN"

        # English proficiency & degree options: if direct answer did not match options, strictly UNKNOWN -> NEEDS_INPUT
        if any(k in norm_q for k in ["english proficiency", "english language proficiency", "level of english", "english level", "proficiency in english"]):
            return "UNKNOWN"

        # Consent Guard: Any question or option containing consent keywords
        # that was not matched above with user_approved_consent: true strictly returns UNKNOWN -> NEEDS_INPUT
        if self.is_consent_question(question, options=options):
            return "UNKNOWN"

        if any(k in norm_q for k in ["which bachelor", "bachelor degree", "bachelors degree", "degree name"]):
            return "UNKNOWN"

        # Availability / start / join questions: strictly governed by answers.yaml
        if any(k in norm_q for k in [
            "available to start", "when can you start", "when can you join",
            "how soon can you join", "start working"
        ]):
            return "UNKNOWN"

        # Work authorization questions: strictly governed by answers.yaml
        if any(k in norm_q for k in [
            "work authorization", "authorized to work", "visa sponsorship", "require sponsorship"
        ]):
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
