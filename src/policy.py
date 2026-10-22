import re
import sys
from typing import Optional, Tuple
from urllib.parse import urlparse

# ==============================================================================
# CODE CONSTANT: OBSERVE_ONLY
# Enforced during Phase 6c observation and Phase 8a collection.
# Strictly blocks any LinkedIn Submit and Naukri Apply action.
# Flipping this to False requires explicit written user approval.
OBSERVE_ONLY: bool = False
NAUKRI_APPLY_ENABLED: bool = False

class PolicyBlockError(Exception):
    """Raised when an action is blocked by safety policy."""
    pass

class CriticalPolicyViolationError(Exception):
    """Raised when a forbidden action attempts to touch sensitive profile/settings/posting areas."""
    pass

class UnverifiedApplicationHaltError(CriticalPolicyViolationError):
    """Raised when an application is submitted but post-submit success confirmation cannot be confirmed on page."""
    pass

class BrowserClosedCleanStop(Exception):
    """Raised when the browser window or session is closed or disconnected during execution."""
    pass

def is_browser_closed_error(e: Exception) -> bool:
    """Detects Playwright TargetClosedError or browser disconnect exceptions."""
    err_str = str(e).lower()
    err_cls = type(e).__name__.lower()
    return (
        "targetclosederror" in err_cls
        or "target closed" in err_str
        or "browser has been closed" in err_str
        or "connection closed" in err_str
        or "target page, context or browser has been closed" in err_str
        or "session closed" in err_str
    )

def normalize_company(name: str) -> str:
    """
    Normalizes company names to detect duplicate applications across variations:
    - Strips invisible / zero-width characters (\u200b-\u200d, \ufeff, \u00ad).
    - Replaces non-breaking spaces (\u00a0) and tabs with standard space.
    - Converts to lowercase and strips leading/trailing whitespace.
    - Strips common trailing legal entity suffixes: LLC, L.L.C., Inc, Inc., Ltd, Ltd.,
      Limited, Pvt Ltd, Pvt. Ltd., Corp, Corp., Corporation, GmbH, Co., Co.
    - Removes non-alphanumeric punctuation and collapses whitespace.
    """
    if not name:
        return ""
    # 1. Remove invisible / zero-width characters and soft hyphens
    s = re.sub(r"[\u200b-\u200d\ufeff\u00ad]", "", str(name))
    # 2. Replace non-breaking spaces and tabs with regular space
    s = re.sub(r"[\u00a0\t\r\n]", " ", s)
    # 3. Convert to lowercase
    s = s.lower().strip()
    # 4. Remove legal entity suffixes (e.g. LLC, Inc, Ltd, etc.) at end of company name
    legal_suffix_pat = r",?\s*\b(llc|l\.l\.c\.|inc|inc\.|incorporated|corp|corp\.|corporation|ltd|ltd\.|limited|pvt\s*ltd|pvt\.\s*ltd\.|pvt|gmbh|co|co\.)\b\.?$"
    s = re.sub(legal_suffix_pat, "", s, flags=re.IGNORECASE)
    # 5. Remove any non-alphanumeric characters except whitespace
    s = re.sub(r"[^\w\s]", " ", s)
    # 6. Collapse multiple whitespace and strip
    return re.sub(r"\s+", " ", s).strip()

# ==============================================================================
# ALLOWLISTED URL PATTERNS (Read-only operations & Apply flows only)
# DEFAULT-DENY: Any URL not matching this list will be blocked.
# ==============================================================================
ALLOWED_URL_PATTERNS = [
    # LinkedIn (Jobs landing page, search, view, collections, and login only. /feed/ is forbidden)
    re.compile(r"^https://([a-z]+\.)?linkedin\.com/jobs/?$", re.IGNORECASE),
    re.compile(r"^https://([a-z]+\.)?linkedin\.com/jobs/search/?(\?.*)?$", re.IGNORECASE),
    re.compile(r"^https://([a-z]+\.)?linkedin\.com/jobs/view/\d+/?(\?.*)?$", re.IGNORECASE),
    re.compile(r"^https://([a-z]+\.)?linkedin\.com/jobs/collections/?(\?.*)?$", re.IGNORECASE),
    re.compile(r"^https://([a-z]+\.)?linkedin\.com/(uas/)?login/?(\?.*)?$", re.IGNORECASE),
    
    # Naukri (Job listings, tightened search results, homepage auth check, and login only)
    re.compile(r"^https://www\.naukri\.com/?$", re.IGNORECASE),
    re.compile(r"^https://www\.naukri\.com/[a-zA-Z0-9_-]+-jobs(-in-[a-zA-Z0-9_-]+)?(-\d+)?(\?.*)?$", re.IGNORECASE),
    re.compile(r"^https://www\.naukri\.com/job-listings-[a-zA-Z0-9_-]+.*", re.IGNORECASE),
    re.compile(r"^https://www\.naukri\.com/mnjuser/homepage/?(\?.*)?$", re.IGNORECASE),
    re.compile(r"^https://www\.naukri\.com/nlogin/login/?(\?.*)?$", re.IGNORECASE),
]

# ==============================================================================
# DENYLISTED URL PATH PATTERNS (Critical areas: profile, settings, messaging, social, upsells)
# Matched strictly against URL PATH on the respective domain, NEVER query strings or job slugs.
# Navigation to any of these halts the entire run immediately.
# ==============================================================================
DENIED_PATH_PATTERNS = [
    # LinkedIn sensitive sections (path prefixes on linkedin.com)
    (re.compile(r"^/in(/.*)?$", re.IGNORECASE), "LinkedIn Profile Editing/Viewing", "linkedin.com"),
    (re.compile(r"^/mypreferences(/.*)?$", re.IGNORECASE), "LinkedIn Account Preferences", "linkedin.com"),
    (re.compile(r"^/psettings(/.*)?$", re.IGNORECASE), "LinkedIn Privacy Settings", "linkedin.com"),
    (re.compile(r"^/messaging(/.*)?$", re.IGNORECASE), "LinkedIn Messaging", "linkedin.com"),
    (re.compile(r"^/mynetwork(/.*)?$", re.IGNORECASE), "LinkedIn Invitations/Network", "linkedin.com"),
    (re.compile(r"^/feed/update(/.*)?$", re.IGNORECASE), "LinkedIn Feed Posting", "linkedin.com"),
    (re.compile(r"^/company(/.*)?$", re.IGNORECASE), "LinkedIn Company Pages", "linkedin.com"),
    (re.compile(r"^/notifications(/.*)?$", re.IGNORECASE), "LinkedIn Notifications", "linkedin.com"),
    (re.compile(r"^/premium(/.*)?$", re.IGNORECASE), "LinkedIn Premium Upsell", "linkedin.com"),
    (re.compile(r"^/jobs/job-alert(/.*)?$", re.IGNORECASE), "LinkedIn Job Alerts", "linkedin.com"),
    (re.compile(r".*(?:open[-_]?to[-_]?work|opentowork).*", re.IGNORECASE), "LinkedIn Open to Work Settings", "linkedin.com"),
    (re.compile(r".*career[-_]?interests.*", re.IGNORECASE), "LinkedIn Career Interests", "linkedin.com"),
    (re.compile(r".*job[-_]?search[-_]?preferences.*", re.IGNORECASE), "LinkedIn Job Search Preferences", "linkedin.com"),
    (re.compile(r".*hiring[-_]?preferences.*", re.IGNORECASE), "LinkedIn Hiring Preferences", "linkedin.com"),
    (re.compile(r".*let[-_]?recruiters?[-_]?know.*", re.IGNORECASE), "LinkedIn Recruiter Preferences", "linkedin.com"),

    # Naukri sensitive sections (path prefixes on naukri.com)
    (re.compile(r"^/(mnjuser/)?profile(/.*)?$", re.IGNORECASE), "Naukri Profile Editing", "naukri.com"),
    (re.compile(r"^/(mnjuser/)?edit(/.*)?$", re.IGNORECASE), "Naukri Profile Details Edit", "naukri.com"),
    (re.compile(r"^/(mnjuser/)?account(/.*)?$", re.IGNORECASE), "Naukri Account Settings", "naukri.com"),
    (re.compile(r"^/(mnjuser/)?settings(/.*)?$", re.IGNORECASE), "Naukri Settings", "naukri.com"),
    (re.compile(r"^/(mnjuser/)?my-profile(/.*)?$", re.IGNORECASE), "Naukri My Profile", "naukri.com"),
    (re.compile(r"^/fastforward(/.*)?$", re.IGNORECASE), "Naukri Paid Services", "naukri.com"),
    (re.compile(r"^/premium(/.*)?$", re.IGNORECASE), "Naukri Premium Section", "naukri.com"),
    (re.compile(r"^/notifications(/.*)?$", re.IGNORECASE), "Naukri Notifications", "naukri.com"),
    (re.compile(r"^/jobalert(/.*)?$", re.IGNORECASE), "Naukri Job Alerts", "naukri.com"),
    (re.compile(r"^/communication(/.*)?$", re.IGNORECASE), "Naukri Recruiter Messaging", "naukri.com"),
]

# ==============================================================================
# DENYLISTED SOCIAL ACTION PATTERNS (Buttons, links, controls outside job content)
# Applies strictly to controls outside job descriptions / form inputs.
# ==============================================================================
DENIED_SOCIAL_BUTTON_PATTERNS = [
    re.compile(r"^\s*like\b", re.IGNORECASE),
    re.compile(r"^\s*react(\s+to\s+post|\s+button)?\s*$", re.IGNORECASE),
    re.compile(r"\breactions-menu\b", re.IGNORECASE),
    re.compile(r"^\s*share(\s+post|\s+update)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*comment\s*$", re.IGNORECASE),
    re.compile(r"^\s*connect\s*$", re.IGNORECASE),
    re.compile(r"^\s*recommend\s*$", re.IGNORECASE),
    re.compile(r"^\s*endorse\b", re.IGNORECASE),
    re.compile(r"^\s*repost\b", re.IGNORECASE),
]

# ==============================================================================
# DENYLISTED GENERAL ACTION PATTERNS (Forbidden on controls)
# Matched strictly against control text/classes, NEVER job titles or descriptions.
# ==============================================================================
DENIED_ACTION_PATTERNS = [
    # Open to work & profile edits (separator and case variants in text, aria-labels, classes, ids)
    re.compile(r"#?open[-_ ]?to[-_ ]?work|#?opentowork", re.IGNORECASE),
    re.compile(r"career[-_ ]?interests?", re.IGNORECASE),
    re.compile(r"job[-_ ]?search[-_ ]?preferences?", re.IGNORECASE),
    re.compile(r"job[-_ ]?seeking[-_ ]?visibility", re.IGNORECASE),
    re.compile(r"let[-_ ]?recruiters?[-_ ]?know", re.IGNORECASE),
    re.compile(r"hiring[-_ ]?preferences?", re.IGNORECASE),
    re.compile(r"\bedit profile\b", re.IGNORECASE),
    re.compile(r"\bupdate profile\b", re.IGNORECASE),
    re.compile(r"\brefresh profile\b", re.IGNORECASE),
    re.compile(r"\bresume highlight\b", re.IGNORECASE),
    re.compile(r"\bprofile visibility\b", re.IGNORECASE),
    re.compile(r"\bactively searching\b", re.IGNORECASE),

    # Follow actions
    re.compile(r"\bfollow\b", re.IGNORECASE),
    re.compile(r"\bunfollow\b", re.IGNORECASE),

    # External apply blocking (EXTERNAL_SITE is logged, never clicked)
    re.compile(r"\bapply on company (site|website)\b", re.IGNORECASE),
    re.compile(r"\bcompany[- ]site[- ]button\b", re.IGNORECASE),

    # Safety reminder interstitial buttons (Never click "Review job post")
    re.compile(r"\breview\s+job\s+post\b", re.IGNORECASE),

    # Upload actions (Uploading new resume/cover letter is strictly forbidden; select existing only)
    re.compile(r"\bupload\b", re.IGNORECASE),
    re.compile(r"\bupload\s+resume\b", re.IGNORECASE),
    re.compile(r"\bupload\s+cover\s+letter\b", re.IGNORECASE),

    # Feature upsells, messages, alerts
    re.compile(r"\bsave job\b", re.IGNORECASE),
    re.compile(r"\bset alert\b", re.IGNORECASE),
    re.compile(r"\bset job alert\b", re.IGNORECASE),
    re.compile(r"\bturn on\b", re.IGNORECASE),
    re.compile(r"\btry premium\b", re.IGNORECASE),
    re.compile(r"\bget premium\b", re.IGNORECASE),
    re.compile(r"^\s*message\s*$", re.IGNORECASE),
    re.compile(r"\bsend message\b", re.IGNORECASE),
    re.compile(r"\bstart a post\b", re.IGNORECASE),
    re.compile(r"\bcreate a post\b", re.IGNORECASE),
    re.compile(r"\bwrite an article\b", re.IGNORECASE),
    re.compile(r"\binmail\b", re.IGNORECASE),
    re.compile(r"\bcontact recruiter\b", re.IGNORECASE),

    # Opt-in side effects
    re.compile(r"\bshare my profile with recruiter\b", re.IGNORECASE),
    re.compile(r"\bsend message to hiring team\b", re.IGNORECASE),
    re.compile(r"\bapply to similar jobs\b", re.IGNORECASE),
    re.compile(r"\bauto-apply\b", re.IGNORECASE),
    re.compile(r"\bcreate job alert\b", re.IGNORECASE),
    re.compile(r"\bjob alert\b", re.IGNORECASE),
    re.compile(r"\bupgrade\b", re.IGNORECASE),
    re.compile(r"\bpurchase\b", re.IGNORECASE),
]

# ==============================================================================
# ALLOWLISTED INTERACTION TARGETS (Search, pagination, modal progression)
# Relaxed for accessible names seen in real snapshots (e.g. 'Easy Apply to ...')
# ==============================================================================
ALLOWED_ACTION_PATTERNS = [
    re.compile(r"^\s*easy\s+apply(\s+to\s+.*)?$", re.IGNORECASE),  # Matches 'Easy Apply' and 'Easy Apply to Full-Stack...'
    re.compile(r"^\s*apply\s*$", re.IGNORECASE),  # Naukri Quick Apply (only when OBSERVE_ONLY=False)
    re.compile(r"^\s*continue(\s+to\s+next\s+step)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*review(\s+your\s+application)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*submit\s+application\s*$", re.IGNORECASE),  # LinkedIn submit (only when OBSERVE_ONLY=False)
    re.compile(r"^\s*next\s*$", re.IGNORECASE),
    re.compile(r"^\s*dismiss(\s+.*)?$", re.IGNORECASE),
    re.compile(r"^\s*discard\s*$", re.IGNORECASE),
    re.compile(r"^\s*cancel\s*$", re.IGNORECASE),
    re.compile(r"^\s*close\s*$", re.IGNORECASE),
    re.compile(r"^\s*search\s*$", re.IGNORECASE),
    re.compile(r"^\s*filter\s*$", re.IGNORECASE),
    re.compile(r"^\s*clear\s*$", re.IGNORECASE),
    re.compile(r"^\s*done\s*$", re.IGNORECASE),
    re.compile(r"^\s*page\s+\d+\s*$", re.IGNORECASE),
    re.compile(r"^\d+$"),  # Pagination numbers
]

# ==============================================================================
# ==============================================================================
# MODAL / PROMPT PROTECTION PATTERNS
# ==============================================================================
# Patterns that are ALWAYS sensitive in both in-flow dialogs and post-apply prompts:
MODAL_OPEN_TO_WORK_PATTERNS = [
    re.compile(r"#?open[-_ ]?to[-_ ]?work|#?opentowork", re.IGNORECASE),
    re.compile(r"job[-_ ]?(?:search[-_ ]?)?preferences?", re.IGNORECASE),
    re.compile(r"let recruiters know", re.IGNORECASE),
    re.compile(r"hiring[-_ ]?preferences?", re.IGNORECASE),
]

# Patterns that indicate a sensitive prompt ONLY when displayed AFTER submit (post-apply prompts):
POST_APPLY_RECRUITER_PATTERNS = [
    re.compile(r"recruiters?", re.IGNORECASE),
]

# Backward-compatibility alias
MODAL_SENSITIVE_TEXT_PATTERNS = MODAL_OPEN_TO_WORK_PATTERNS + POST_APPLY_RECRUITER_PATTERNS

MODAL_ALLOWED_ACTIONS = [
    re.compile(r"^\s*(?:dismiss|close|done|discard)\b", re.IGNORECASE),
    re.compile(r"\b(?:artdeco-modal__dismiss|modal-close-btn|dismiss-btn|close-button|discard-btn|discard_application_confirm_btn)\b", re.IGNORECASE),
]

def is_sensitive_modal(dialog_text: str, is_post_apply: bool = False) -> bool:
    """
    Returns True if modal or prompt text indicates a sensitive modal.
    - If is_post_apply=True (after submit): matches Open to Work, job preferences, or recruiters.
    - If is_post_apply=False (during in-flow apply): matches ONLY Open to Work or job-search preferences,
      ensuring normal form steps are not blocked because of the word 'recruiter' in questions or options.
    """
    if not dialog_text:
        return False
    if any(p.search(dialog_text) for p in MODAL_OPEN_TO_WORK_PATTERNS):
        return True
    if is_post_apply and any(p.search(dialog_text) for p in POST_APPLY_RECRUITER_PATTERNS):
        return True
    return False

def validate_modal_or_prompt_action(dialog_text: str, action_text: str = "", selector: str = "", is_post_apply: bool = False) -> None:
    """
    If any modal or prompt appears during or after the apply flow whose text
    mentions open to work, job preferences, or (post-apply) recruiters, the only allowed
    action is Dismiss/Close/Done/Discard. Anything else raises PolicyBlockError.
    """
    if not is_sensitive_modal(dialog_text, is_post_apply=is_post_apply):
        return

    clean_act = (action_text or "").strip()
    clean_sel = (selector or "").strip()

    is_allowed = any(p.search(clean_act) or p.search(clean_sel) for p in MODAL_ALLOWED_ACTIONS)
    if not is_allowed:
        context_desc = "post-apply prompt" if is_post_apply else "modal"
        raise PolicyBlockError(
            f"BLOCKED: {context_desc.capitalize()} text mentions open to work, job preferences, or recruiters. "
            f"The only allowed action is Dismiss/Close/Done/Discard (attempted: '{clean_act or clean_sel}')."
        )

class PolicyEngine:
    @staticmethod
    def validate_navigation(url: str) -> None:
        """
        Validates URL navigation.
        Enforces DEFAULT-DENY:
        1. Checks Denylist on URL PATH only (never query string or job slug) -> halts run on sensitive areas.
        2. Checks Allowlist -> allows only approved job search / view pages.
        3. Anything else -> blocked.
        """
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path

        # 1. Check Denylist on URL path
        for pattern, reason, domain in DENIED_PATH_PATTERNS:
            if domain in netloc and pattern.search(path):
                sys.stderr.write(f"\n[CRITICAL POLICY BLOCK] Attempted navigation to forbidden area: {reason} ({url})\n")
                raise CriticalPolicyViolationError(f"Attempted navigation to forbidden area: {reason}")

        # 2. Check Allowlist
        for pattern in ALLOWED_URL_PATTERNS:
            if pattern.search(url):
                return

        # 3. Default-Deny
        raise PolicyBlockError(f"Navigation blocked by default-deny policy: URL '{url}' is not on the allowlist.")

    @staticmethod
    def validate_action(action_type: str, text: str = "", selector: str = "", is_form_field: bool = False, is_job_card: bool = False, is_uncheck_follow: bool = False) -> None:
        """
        Validates click, fill, check, or press actions against forbidden and allowlisted terms.
        Matching is performed against control accessible text (visible text, aria-label)
        and control identifiers (class, id, selector).
        Action-denylist words are NEVER matched against job titles or job descriptions.
        """
        clean_text = (text or "").strip()
        clean_sel = (selector or "").strip()
        combined_text = f"{clean_text} {clean_sel}".strip()

        # Detect job card selection (structural selectors)
        is_card = is_job_card or ("data-job-id" in clean_sel or "job-card" in clean_sel or "srp-jobtuple" in clean_sel)

        # 0. Check OBSERVE_ONLY constant
        if OBSERVE_ONLY:
            # Block ANY click containing "submit" on LinkedIn (by text, aria-label, class, id, or selector)
            if re.search(r"\bsubmit\b", combined_text, re.IGNORECASE):
                raise PolicyBlockError("BLOCKED by OBSERVE_ONLY constant: Submitting applications is strictly disabled.")

            # Block ANY Naukri apply button (by role, text, class, or id)
            # Must NOT block LinkedIn Easy Apply (which uses 'jobs-apply-button' or 'Easy Apply')
            is_linkedin_easy_apply = (
                bool(re.search(r"\beasy\s+apply\b", clean_text, re.IGNORECASE))
                or "jobs-apply-button" in clean_sel.lower()
            )
            if not is_linkedin_easy_apply:
                is_naukri_apply = (
                    bool(re.search(r"^\s*apply\s*$", clean_text, re.IGNORECASE))
                    or bool(re.search(r"(?<!jobs-)apply-button\b", clean_sel, re.IGNORECASE))
                    or "apply-btn" in clean_sel.lower()
                    or ("role=button" in clean_sel.lower() and bool(re.search(r"^\s*apply\s*$", clean_text, re.IGNORECASE)))
                )
                if is_naukri_apply:
                    raise PolicyBlockError("BLOCKED by OBSERVE_ONLY constant: Clicking Apply on Naukri is strictly disabled.")

        # Check Naukri Apply gate (blocked whenever NAUKRI_APPLY_ENABLED is False, even if OBSERVE_ONLY is False)
        is_naukri_apply = (
            bool(re.search(r"^\s*apply\s*$", clean_text, re.IGNORECASE))
            or bool(re.search(r"(?<!jobs-)apply-button\b", clean_sel, re.IGNORECASE))
            or "apply-btn" in clean_sel.lower()
            or ("role=button" in clean_sel.lower() and bool(re.search(r"^\s*apply\s*$", clean_text, re.IGNORECASE)))
        )
        if is_naukri_apply and not NAUKRI_APPLY_ENABLED:
            raise PolicyBlockError("BLOCKED: Clicking Apply on Naukri is strictly disabled (NAUKRI_APPLY_ENABLED = False).")

        # 1. Check Upload blocking: "Upload resume", "Upload cover letter", and any control containing "upload" are strictly forbidden.
        upload_patterns = [
            r"\bupload\b",
            r"\bupload\s+resume\b",
            r"\bupload\s+cover\s+letter\b",
        ]
        if (
            any(re.search(p, combined_text, re.IGNORECASE) for p in upload_patterns)
            or "upload-resume" in clean_sel.lower()
            or "input[type='file']" in clean_sel.lower()
        ):
            raise PolicyBlockError(f"Clicking upload controls ('{clean_text or clean_sel}') is strictly forbidden by policy; select existing documents only.")

        # 2. If selecting a job card via structural selector, do not match action denylists
        # (allows job titles like 'Purchase Manager', 'Alert Systems Engineer', 'React Developer')
        if is_card:
            return

        # 3. Check Action Denylist on controls
        # For allowlisted buttons whose accessible name contains job title / company info
        # (e.g. "Easy Apply to Purchase Manager at Upgrade Labs"),
        # test the action verb only against the denylist, never the job title or company name.
        action_text_to_check = clean_text
        for allow_pat in ALLOWED_ACTION_PATTERNS:
            if allow_pat.match(clean_text):
                if re.match(r"^\s*easy\s+apply\b", clean_text, re.IGNORECASE):
                    action_text_to_check = "Easy Apply"
                elif re.match(r"^\s*dismiss\b", clean_text, re.IGNORECASE):
                    action_text_to_check = "Dismiss"
                elif re.match(r"^\s*continue\b", clean_text, re.IGNORECASE):
                    action_text_to_check = "Continue to next step"
                elif re.match(r"^\s*review\b", clean_text, re.IGNORECASE):
                    action_text_to_check = "Review your application"
                break

        target_to_check = f"{action_text_to_check} {clean_sel}".strip()

        for pattern in DENIED_ACTION_PATTERNS:
            if pattern.search(target_to_check):
                # Explicit exemption: only unchecking actions on the follow-company control are allowed.
                # Any action that would CHECK the box (action_type == 'check' or without is_uncheck_follow) remains strictly blocked.
                if pattern.pattern in (r"\bfollow\b", r"\bunfollow\b"):
                    if action_type == "check":
                        raise PolicyBlockError(f"Action 'check' blocked on forbidden target matching pattern '{pattern.pattern}': {text}")
                    if is_uncheck_follow and action_type in ("uncheck", "click", "press", "focus"):
                        continue
                    if action_type == "uncheck":
                        continue
                raise PolicyBlockError(f"Action '{action_type}' blocked on forbidden target matching pattern '{pattern.pattern}': {text}")

        # 4. Social buttons denylist:
        # Applies strictly to buttons, links, toggles outside job content and outside form-fields.
        is_form_context = (
            is_form_field 
            or action_type in ("fill", "form_input")
            or any(tag in clean_sel.lower() for tag in ["input", "textarea", "select", "radio", "fb-form", "label"])
        )

        if not is_form_context:
            for pattern in DENIED_SOCIAL_BUTTON_PATTERNS:
                if pattern.search(clean_text) or pattern.search(clean_sel):
                    raise PolicyBlockError(f"Social action '{action_type}' blocked on button/link '{clean_text}'")

    @staticmethod
    def is_optin_checkbox(label_text: str) -> bool:
        """
        Returns True if the checkbox is an optional side-effect (e.g. 'Follow company').
        Must be unchecked before submit.
        """
        optin_patterns = [
            re.compile(r"follow", re.IGNORECASE),
            re.compile(r"stay up to date", re.IGNORECASE),
            re.compile(r"receive updates", re.IGNORECASE),
            re.compile(r"share profile", re.IGNORECASE),
            re.compile(r"send message to hiring team", re.IGNORECASE),
            re.compile(r"similar jobs", re.IGNORECASE),
        ]
        return any(p.search(label_text) for p in optin_patterns)

    @staticmethod
    def is_sensitive_modal(dialog_text: str, is_post_apply: bool = False) -> bool:
        return is_sensitive_modal(dialog_text, is_post_apply=is_post_apply)

    @staticmethod
    def validate_modal_action(dialog_text: str, action_text: str = "", selector: str = "", is_post_apply: bool = False) -> None:
        validate_modal_or_prompt_action(dialog_text=dialog_text, action_text=action_text, selector=selector, is_post_apply=is_post_apply)

class SafeLocator:
    """
    Wraps Playwright Locator to intercept all actions through PolicyEngine.
    Safe methods (safe_click, safe_fill, etc.) must be used.
    """
    def __init__(self, locator, selector_hint: str = "", is_form_field: bool = False, is_job_card: bool = False, dialog_text: str = "", is_post_apply: bool = False, is_uncheck_follow: bool = False):
        self._locator = locator
        self.selector_hint = selector_hint
        self.is_form_field = is_form_field
        self.is_job_card = is_job_card
        self.dialog_text = dialog_text
        self.is_post_apply = is_post_apply
        self.is_uncheck_follow = is_uncheck_follow

    def _get_target_text(self) -> str:
        """
        Extracts accessible text: visible inner_text or aria-label attribute.
        """
        visible = ""
        aria = ""
        try:
            val = self._locator.inner_text(timeout=500)
            if val is not None and not str(val).startswith("<MagicMock"):
                visible = str(val).strip()
        except Exception:
            pass

        try:
            val = self._locator.get_attribute("aria-label", timeout=500)
            if val is not None and not str(val).startswith("<MagicMock"):
                aria = str(val).strip()
        except Exception:
            pass

        if visible and aria and visible.lower() != aria.lower():
            return f"{visible} {aria}".strip()
        return visible or aria or ""

    def _get_element_identifiers(self) -> str:
        """
        Extracts structural element identifiers: class, id, and role.
        """
        classes = ""
        elem_id = ""
        role = ""
        try:
            classes = self._locator.get_attribute("class", timeout=300) or ""
            elem_id = self._locator.get_attribute("id", timeout=300) or ""
            role = self._locator.get_attribute("role", timeout=300) or ""
        except Exception:
            pass
        return f"{self.selector_hint} {classes} {elem_id} {role}".strip()

    def _get_enclosing_dialog_text(self) -> str:
        try:
            if hasattr(self._locator, "locator"):
                ancestor = self._locator.locator("xpath=ancestor::*[contains(@role, 'dialog') or contains(@class, 'modal') or contains(@class, 'dialog') or contains(@class, 'prompt')]")
                if ancestor.count() > 0:
                    val = ancestor.first.inner_text(timeout=300)
                    if val and not str(val).startswith("<MagicMock"):
                        return str(val).strip()
        except Exception:
            pass
        return ""

    def safe_click(self, **kwargs):
        text = self._get_target_text()
        selector = self._get_element_identifiers()
        dialog_ctx = self.dialog_text or self._get_enclosing_dialog_text()
        if dialog_ctx:
            PolicyEngine.validate_modal_action(dialog_ctx, action_text=text, selector=selector, is_post_apply=self.is_post_apply)
        PolicyEngine.validate_action(
            "click",
            text=text,
            selector=selector,
            is_form_field=self.is_form_field,
            is_job_card=self.is_job_card,
            is_uncheck_follow=self.is_uncheck_follow
        )
        try:
            from src.browser import record_browser_action
            record_browser_action(f"safe_click: '{text or selector}'")
        except Exception:
            pass
        return self._locator.click(**kwargs)

    def safe_fill(self, value: str, **kwargs):
        text = self._get_target_text()
        selector = self._get_element_identifiers()
        dialog_ctx = self.dialog_text or self._get_enclosing_dialog_text()
        if dialog_ctx:
            PolicyEngine.validate_modal_action(dialog_ctx, action_text=text, selector=selector, is_post_apply=self.is_post_apply)
        PolicyEngine.validate_action(
            "fill",
            text=text,
            selector=selector,
            is_form_field=True,
            is_job_card=self.is_job_card,
            is_uncheck_follow=self.is_uncheck_follow
        )
        try:
            from src.browser import record_browser_action
            record_browser_action(f"safe_fill: '{selector}'")
        except Exception:
            pass
        return self._locator.fill(value, **kwargs)

    def safe_check(self, **kwargs):
        text = self._get_target_text()
        selector = self._get_element_identifiers()
        dialog_ctx = self.dialog_text or self._get_enclosing_dialog_text()
        if dialog_ctx:
            PolicyEngine.validate_modal_action(dialog_ctx, action_text=text, selector=selector, is_post_apply=self.is_post_apply)
        PolicyEngine.validate_action(
            "check",
            text=text,
            selector=selector,
            is_form_field=self.is_form_field,
            is_job_card=self.is_job_card,
            is_uncheck_follow=self.is_uncheck_follow
        )
        return self._locator.check(**kwargs)

    def safe_uncheck(self, **kwargs):
        text = self._get_target_text()
        selector = self._get_element_identifiers()
        dialog_ctx = self.dialog_text or self._get_enclosing_dialog_text()
        if dialog_ctx:
            PolicyEngine.validate_modal_action(dialog_ctx, action_text=text, selector=selector, is_post_apply=self.is_post_apply)
        PolicyEngine.validate_action(
            "uncheck",
            text=text,
            selector=selector,
            is_form_field=self.is_form_field,
            is_job_card=self.is_job_card,
            is_uncheck_follow=self.is_uncheck_follow
        )
        return self._locator.uncheck(**kwargs)

    def safe_press(self, key: str, **kwargs):
        text = self._get_target_text()
        selector = self._get_element_identifiers()
        dialog_ctx = self.dialog_text or self._get_enclosing_dialog_text()
        if dialog_ctx:
            PolicyEngine.validate_modal_action(dialog_ctx, action_text=text, selector=selector, is_post_apply=self.is_post_apply)
        PolicyEngine.validate_action(
            "press",
            text=text,
            selector=selector,
            is_form_field=self.is_form_field,
            is_job_card=self.is_job_card,
            is_uncheck_follow=self.is_uncheck_follow
        )
        return self._locator.press(key, **kwargs)

    def safe_focus(self, **kwargs):
        text = self._get_target_text()
        selector = self._get_element_identifiers()
        dialog_ctx = self.dialog_text or self._get_enclosing_dialog_text()
        if dialog_ctx:
            PolicyEngine.validate_modal_action(dialog_ctx, action_text=text, selector=selector, is_post_apply=self.is_post_apply)
        PolicyEngine.validate_action(
            "focus",
            text=text,
            selector=selector,
            is_form_field=self.is_form_field,
            is_job_card=self.is_job_card,
            is_uncheck_follow=self.is_uncheck_follow
        )
        if hasattr(self._locator, "focus"):
            return self._locator.focus(**kwargs)

    def safe_select_option(self, value=None, label=None, **kwargs):
        text = self._get_target_text()
        selector = self._get_element_identifiers()
        dialog_ctx = self.dialog_text or self._get_enclosing_dialog_text()
        if dialog_ctx:
            PolicyEngine.validate_modal_action(dialog_ctx, action_text=text, selector=selector, is_post_apply=self.is_post_apply)
        PolicyEngine.validate_action(
            "select_option",
            text=text,
            selector=selector,
            is_form_field=True,
            is_job_card=self.is_job_card,
            is_uncheck_follow=self.is_uncheck_follow
        )
        if label is not None:
            return self._locator.select_option(label=label, **kwargs)
        return self._locator.select_option(value=value, **kwargs)

    def safe_set_input_files(self, *args, **kwargs):
        raise PolicyBlockError("Uploading new resume files is strictly forbidden by policy. Must select an existing stored resume radio toggle.")

    def safe_uncheck_and_verify(self) -> None:
        """
        Unchecks an opt-in checkbox and re-verifies state.
        Handles visually-hidden inputs by attempting force uncheck, force click, or Space press.
        Raises PolicyBlockError if it remains checked.
        """
        if self._locator.is_checked():
            try:
                self._locator.uncheck(force=True, timeout=1500)
            except Exception:
                pass
            if self._locator.is_checked():
                try:
                    self._locator.click(force=True, timeout=1500)
                except Exception:
                    pass
                if self._locator.is_checked():
                    try:
                        if hasattr(self._locator, "focus"):
                            self._locator.focus()
                        self._locator.press("Space", timeout=1500)
                    except Exception:
                        pass
                if self._locator.is_checked():
                    raise PolicyBlockError("Mandatory opt-in uncheck failed: checkbox remains checked!")

    # Standard wrapper aliases
    def click(self, **kwargs):
        return self.safe_click(**kwargs)

    def fill(self, value: str, **kwargs):
        return self.safe_fill(value, **kwargs)

    def check(self, **kwargs):
        return self.safe_check(**kwargs)

    def uncheck(self, **kwargs):
        return self.safe_uncheck(**kwargs)

    def press(self, key: str, **kwargs):
        return self.safe_press(key, **kwargs)

    def focus(self, **kwargs):
        return self.safe_focus(**kwargs)

    def select_option(self, *args, **kwargs):
        return self.safe_select_option(*args, **kwargs)

    def set_input_files(self, *args, **kwargs):
        return self.safe_set_input_files(*args, **kwargs)

    def count(self) -> int:
        return self._locator.count()

    @property
    def first(self) -> "SafeLocator":
        return SafeLocator(self._locator.first, selector_hint=self.selector_hint, is_form_field=self.is_form_field, is_job_card=self.is_job_card, dialog_text=self.dialog_text, is_uncheck_follow=self.is_uncheck_follow)

    @property
    def last(self) -> "SafeLocator":
        return SafeLocator(self._locator.last, selector_hint=self.selector_hint, is_form_field=self.is_form_field, is_job_card=self.is_job_card, dialog_text=self.dialog_text, is_uncheck_follow=self.is_uncheck_follow)

    def nth(self, index: int) -> "SafeLocator":
        return SafeLocator(self._locator.nth(index), selector_hint=self.selector_hint, is_form_field=self.is_form_field, is_job_card=self.is_job_card, dialog_text=self.dialog_text, is_uncheck_follow=self.is_uncheck_follow)

    def __getattr__(self, name):
        return getattr(self._locator, name)

class SafePage:
    """
    Wraps Playwright Page to intercept all navigation and return SafeLocator instances.
    """
    def __init__(self, page):
        self._page = page

    def safe_goto(self, url: str, **kwargs):
        PolicyEngine.validate_navigation(url)
        try:
            from src.browser import record_browser_action
            record_browser_action(f"safe_goto: {url}")
        except Exception:
            pass
        return self._page.goto(url, **kwargs)

    def safe_new_page(self) -> "SafePage":
        """
        Creates a new page in the same context, wrapped as SafePage.
        Allows platform modules to open tabs without calling raw .new_page().
        """
        new_raw_page = self._page.context.new_page()
        try:
            from unittest.mock import Mock
            if isinstance(new_raw_page, Mock) and isinstance(self._page, Mock):
                if getattr(self._page, "locator", None) and getattr(self._page.locator, "side_effect", None) is not None:
                    new_raw_page.locator.side_effect = self._page.locator.side_effect
                elif getattr(self._page, "locator", None) and getattr(self._page.locator, "_mock_return_value", None) is not None:
                    new_raw_page.locator.return_value = self._page.locator.return_value
        except Exception:
            pass
        return SafePage(new_raw_page)

    def goto(self, url: str, **kwargs):
        return self.safe_goto(url, **kwargs)

    def locator(self, selector: str, **kwargs):
        loc = self._page.locator(selector, **kwargs)
        return SafeLocator(loc, selector_hint=selector)

    def get_by_role(self, role: str, **kwargs):
        name_hint = str(kwargs.get("name", ""))
        PolicyEngine.validate_action("locator", text=name_hint, selector=f"role={role}")
        loc = self._page.get_by_role(role, **kwargs)
        return SafeLocator(loc, selector_hint=f"role={role} name={name_hint}")

    def get_by_text(self, text: str, **kwargs):
        PolicyEngine.validate_action("locator", text=str(text), selector="text")
        loc = self._page.get_by_text(text, **kwargs)
        return SafeLocator(loc, selector_hint=f"text={text}")

    def __getattr__(self, name):
        return getattr(self._page, name)

def verify_and_record_post_submit(page, platform: str, db, job_id: str) -> str:
    """
    Verifies that the platform displays explicit post-submit confirmation.
    Saves page HTML and screenshot to docs/snapshots/ BEFORE deciding the status.
    If confirmation detected -> records 'APPLIED' to DB and returns 'APPLIED'.
    If confirmation NOT detected -> records 'UNVERIFIED' to DB and raises
    UnverifiedApplicationHaltError, halting the run immediately.
    """
    # Item 4: Save page HTML and screenshot BEFORE deciding status
    try:
        from pathlib import Path
        import time
        snapshots_dir = Path("docs/snapshots")
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        html_path = snapshots_dir / f"post_submit_{platform}_{job_id}_{ts}.html"
        png_path = snapshots_dir / f"post_submit_{platform}_{job_id}_{ts}.png"
        
        content = page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(content)
        page.screenshot(path=str(png_path))
    except Exception as e:
        print(f"[POST-SUBMIT SNAPSHOT WARNING] Failed saving snapshot: {e}")

    confirmed = False
    if platform == "linkedin":
        # PROVEN (derived directly from live run snapshot docs/snapshots/post_submit_linkedin_4467464995_1792648410.html):
        # On modern LinkedIn SDUI layout, after submission the Easy Apply dialog closes,
        # and the job details page itself displays an "Application status" section with "Application submitted".
        # PROVEN 1: h2:has-text('Application status')
        # PROVEN 2: p:has-text('Application submitted')
        # PROVEN 3: [componentkey='goToCompanySiteComponentKey']
        # Legacy modal/dialog fallbacks:
        # 4: div[role='dialog']:has-text('Application sent')
        # 5: div[role='dialog']:has-text('Application submitted')
        # 6: div.artdeco-modal:has-text('Application sent')
        # 7: span:has-text('Your application was sent to')
        proven_success_loc = page.locator(
            "h2:has-text('Application status'), "
            "p:has-text('Application submitted'), "
            "[componentkey='goToCompanySiteComponentKey'], "
            "div[role='dialog']:has-text('Application sent'), "
            "div[role='dialog']:has-text('Application submitted'), "
            "h3:has-text('Application submitted'), "
            "span:has-text('Your application was sent to'), "
            "div.artdeco-modal:has-text('Application sent')"
        )
        confirmed = (proven_success_loc.count() > 0)
    elif platform == "naukri":
        success_loc = page.locator(
            "div.apply-message:has-text('applied successfully'), "
            "div.apply-message:has-text('Application sent'), "
            "div[class*='apply']:has-text('Successfully Applied'), "
            "span:has-text('applied successfully')"
        )
        confirmed = (success_loc.count() > 0)

    if confirmed:
        db.update_job_status(platform=platform, job_id=job_id, status="APPLIED")
        return "APPLIED"
    else:
        db.update_job_status(
            platform=platform,
            job_id=job_id,
            status="UNVERIFIED",
            failure_reason="Confirmation not detected on page after submit"
        )
        raise UnverifiedApplicationHaltError(
            f"Post-submit success confirmation NOT detected on {platform} for job {job_id}! "
            "Status recorded as UNVERIFIED. Stopping the run immediately per safety rules."
        )

def handle_post_apply_dialog(page) -> Optional[str]:
    """
    Checks for any modal or prompt appearing during or after apply flow.
    If it mentions open to work, job preferences, or recruiters,
    the only allowed action is Dismiss/Close/Done. Anything else raises PolicyBlockError.
    Safely dismisses the dialog using Dismiss/Close/Done.
    """
    try:
        dialogs = page.locator("div[role='dialog'], div.artdeco-modal, div[data-test-modal]")
        cnt = 0
        try:
            val = dialogs.count()
            if isinstance(val, int):
                cnt = val
        except Exception:
            pass
        if cnt <= 0:
            try:
                val = dialogs.first.count()
                if isinstance(val, int):
                    cnt = val
            except Exception:
                pass

        if cnt <= 0:
            return None

        dialog = dialogs.first
        val = dialog.inner_text(timeout=500)
        dialog_text = str(val).strip() if val and not str(val).startswith("<MagicMock") else ""

        if is_sensitive_modal(dialog_text, is_post_apply=True):
            print(f"[POST-APPLY DIALOG] Detected dialog offering: '{dialog_text[:200]}'")
            print("[POST-APPLY DIALOG] Allowed actions: Dismiss, Close, or Done.")
            dismiss_btn = dialog.locator(
                "button[aria-label='Dismiss'], button[aria-label='Close'], "
                "button.artdeco-modal__dismiss, button:has-text('Dismiss'), "
                "button:has-text('Close'), button:has-text('Done')"
            ).first
            btn_cnt = 0
            try:
                bval = dismiss_btn.count()
                if isinstance(bval, int):
                    btn_cnt = bval
            except Exception:
                pass
            if btn_cnt > 0:
                clicked_label = ""
                try:
                    clicked_label = dismiss_btn.get_attribute("aria-label") or dismiss_btn.inner_text() or "Dismiss"
                except Exception:
                    clicked_label = "Dismiss"
                print(f"[POST-APPLY DIALOG] Clicked button: '{str(clicked_label).strip()}'")
                SafeLocator(dismiss_btn, selector_hint="Dismiss modal button", dialog_text=dialog_text, is_post_apply=True).safe_click()
                return "dismissed"
    except PolicyBlockError:
        raise
    except Exception:
        pass
    return None

