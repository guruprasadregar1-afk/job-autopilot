# Naukri Flow & DOM Observation Notes (Phase 6 & 6b)

Recorded from live DOM observation on persistent authenticated session.
Snapshots referenced: `docs/snapshots/naukri_01_search_results.*`, `naukri_02_job_detail.*`, `naukri_03_pagination.*`.

---

> **Definition:** **PROVEN** strictly means: appears in a saved snapshot under `docs/snapshots/`.
> **UNPROVEN** means: not yet captured in a saved snapshot; pending Phase 6c read-only observation.

## 1. Proven Role/Text/Aria Locators vs Unproven Fallbacks

| Purpose | Primary Locator (Role/Text/Aria) | Fallback Selector | Proof Status in `docs/snapshots/` |
| :--- | :--- | :--- | :--- |
| **Search Tuple** | `locator("div.srp-jobtuple-wrapper")` | `locator("article.jobTuple, div.cust-job-tuple")` | **PROVEN** (`naukri_01_search_results.html:156`) |
| **Job ID** | `tuple.getAttribute("data-job-id")` | URL regex `\d{10,14}$` on `a.title[href]` | **PROVEN** (`naukri_01_search_results.html:156`) |
| **Job Title** | `tuple.locator("a.title").innerText()` | `tuple.locator("a[title]").innerText()` | **PROVEN** (`naukri_01_search_results.html:156`) |
| **Company** | `tuple.locator("span.comp-name").innerText()` | `tuple.locator("a.comp-name")` | **PROVEN** (`naukri_01_search_results.html:166`) |
| **External Apply** | `page.getByRole("button", name="Apply on company site")`| `button#company-site-button.company-site-button` | **PROVEN (Mark EXTERNAL_SITE)** (`naukri_02_job_detail.html:155`) |
| **Quick Apply Btn**| `page.getByRole("button", name="Apply")` | `button.apply-button:not(.company-site-button)` | **UNPROVEN** (`naukri_02_job_detail.html` had external site button only) |
| **Pagination Next**| `page.getByRole("link", name="Next")` | `a > span:has-text("Next")` | **PROVEN** (`naukri_03_pagination.html:172`) |
| **Pagination Page**| `page.locator("a.styles_page__...")` | `div.styles_pages__... a` | **PROVEN** (`naukri_03_pagination.html:172`) |
| **Already Applied**| `page.locator(".already-applied, [class*='applied-banner']")`| `span:has-text("Already Applied")` | **UNPROVEN** (Pending Phase 6c snapshot) |

---

## 2. Critical Naukri Behavior: Immediate Submit Warning

> [!WARNING]
> **Clicking "Apply" on Naukri can submit immediately without a multi-step modal!**
> Unlike LinkedIn, where Easy Apply always opens a review modal, Naukri's direct "Apply" button often triggers instantaneous application submission using the profile's stored resume.
> - **In `--review` mode:** The automation engine MUST pause and ask for your terminal confirmation **BEFORE** clicking the initial "Apply" button.
> - **In `--dry-run` mode:** The automation engine MUST log the match and stop before clicking the "Apply" button.

---

## 3. Mandatory Opt-in Traps (Uncheck & Verify)
- Naukri sometimes presents post-click or inline checkboxes:
  - `"Apply to similar jobs"`
  - `"Auto-apply to matching roles"`
- **Enforcement:**
  Any checkbox matching opt-in patterns must be inspected, unchecked, and verified via `is_checked() == False` before completion.
