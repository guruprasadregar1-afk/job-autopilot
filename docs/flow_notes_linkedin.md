# LinkedIn Flow & DOM Observation Notes (Phase 6 & 6b)

Recorded from live DOM observation on persistent authenticated session.
Snapshots referenced: `docs/snapshots/linkedin_01_search_results.*`, `linkedin_02_job_detail.*`, `linkedin_03_modal_step1.*`, `linkedin_04_modal_step2.*`, `linkedin_05_modal_review.*`, `linkedin_06_discard_prompt.*`, `linkedin_07_no_draft_confirmed.*`, `linkedin_08_pagination_page2.*`.

---

> **Definition:** **PROVEN** strictly means: appears in a saved snapshot under `docs/snapshots/`.
> **UNPROVEN** means: not yet captured in a saved snapshot; pending user-provided applied job URL.

## 1. Proven Role/Text/Aria Locators vs Unproven Fallbacks

| Purpose | Primary Locator (Role/Text/Aria) | Fallback Selector | Proof Status in `docs/snapshots/` |
| :--- | :--- | :--- | :--- |
| **Search Card** | `locator("div.job-card-container")` | `locator("li.jobs-search-results__list-item")` | **PROVEN** (`linkedin_01_search_results.html:1850`) |
| **Job ID** | `card.locator("div[data-job-id]").getAttribute("data-job-id")` | `card.getAttribute("data-occludable-job-id")` | **PROVEN** (`linkedin_01_search_results.html:1850`) |
| **Job Title** | `card.locator("a.job-card-list__title--link").innerText()` | `card.locator("span[aria-hidden='true']").first` | **PROVEN** (`linkedin_01_search_results.html:1877`) |
| **Company** | `card.locator(".artdeco-entity-lockup__subtitle").innerText()` | `card.locator(".job-card-container__company-name")` | **PROVEN** (`linkedin_01_search_results.html:1882`) |
| **Easy Apply Btn** | `page.getByRole("button", name="Easy Apply")` | `button#jobs-apply-button-id` | **PROVEN** (`linkedin_02_job_detail.html:3027`) |
| **Modal Dismiss** | `page.getByRole("button", name="Dismiss")` | `button[aria-label="Dismiss"]` | **PROVEN** (`linkedin_03_modal_step1.html:249`) |
| **Modal Next** | `page.getByRole("button", name="Continue to next step")` | `button:has-text("Next")` | **PROVEN** (`linkedin_03_modal_step1.html:1146`) |
| **Modal Review** | `page.getByRole("button", name="Review your application")`| `button:has-text("Review")` | **PROVEN** (`linkedin_04_modal_step2.html:432`) |
| **Resume Upload** | `page.locator("input[type='file'][id*='upload-resume']")` | `input[name='file']` | **FORBIDDEN** (Uploading new resume files blocked by policy; select stored resume only) |
| **Resume Radio** | `page.locator("input[type='radio'][id*='jobsDocumentCardToggle']")`| `input[type='radio']` | **PROVEN** (`linkedin_04_modal_step2.html:326`) |
| **Modal Submit** | `page.getByRole("button", name="Submit application")` | `button[aria-label="Submit application"]` | **PROVEN** (`linkedin_05_modal_review.html:464`) |
| **Follow Checkbox**| `input#follow-company-checkbox` | `label[for='follow-company-checkbox']` | **PROVEN** (`linkedin_05_modal_review.html:444`) |
| **Discard Confirm**| `page.getByRole("button", name="Discard")` | `button[data-control-name="discard_application_confirm_btn"]` | **PROVEN** (`linkedin_06_discard_prompt.html:503`) |
| **Pagination Page 2**| `page.getByRole("button", name="Page 2")` | `button[aria-label='Page 2']` | **PROVEN** (`linkedin_08_pagination_page2.html:2807`) |
| **Already Applied**| `page.locator(".artdeco-inline-feedback__message:has-text('Applied')")` | `button:has-text('Applied')` | **UNPROVEN** (No applied job card found in live search) |

---

## 2. Modal Step Progression & Field Types

1. **Contact Information Step (Step 1):**
   - Text input: `input.artdeco-text-input--input`, `input[id*="single-line-text"]`
   - Phone code select: `select[id*="countryCode"]`
   - Action: `page.getByRole("button", name="Continue to next step").click()`
2. **Resume Step (Step 2):**
   - Existing resume radio toggle: `input[type="radio"][id*="jobsDocumentCardToggle"]`
   - Upload new resume PDF: `input[type="file"][id*="upload-resume"]`
   - Action: `page.getByRole("button", name="Review your application").click()`
3. **Screening Questions / Custom Fields (Step 3+ when present):**
   - Text inputs: `div.fb-single-line-text input`
   - Dropdown selects: `div.fb-dropdown select`
   - Radio groups: `fieldset[data-test-form-builder-radio-button-form-component]`
   - Number fields: `input[type="number"], input[inputmode="numeric"]`
4. **Review Step:**
   - Shows summary of submitted answers and candidate resume.
   - Contains Submit button: `page.getByRole("button", name="Submit application")`
   - Contains mandatory Opt-In checkbox: `"Follow <Company> to stay up to date..."`

---

## 3. Mandatory Pre-Checked Opt-in Rule (Follow Company)
- **Detected Opt-in:**
  `label:has-text("Follow") input[type="checkbox"]`
- **Enforcement:**
  Before clicking Review or Submit, the engine MUST:
  1. Inspect `checkbox.is_checked()`
  2. If `True`, click to uncheck.
  3. Re-read `checkbox.is_checked()`
  4. If STILL `True`, **BLOCK THE APPLICATION** and halt the flow.
