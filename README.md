# job-autopilot

Automated job discovery, fit scoring, and application assistant for LinkedIn and Naukri, built with safety policies and human-in-the-loop controls.

---

> [!WARNING]
> **LinkedIn and Naukri terms prohibit automation; use at your own risk; never commit browser_profile, configs, resumes, data or snapshots.**

---

## Tech Stack & Architecture Lock

- **Language**: Python 3.11
- **Browser Automation**: Playwright (Microsoft Edge channel)
- **Database**: SQLite3 (`data/jobs.db`) via standard library
- **Configuration**: PyYAML (`pyyaml`)
- **Testing**: `pytest`
- **LLM Reasoning**: Local `claude -p` CLI (`claude.cmd -p` on Windows)

---

## Setup & Installation

1. **Clone repository & set up Python virtual environment**:
   ```bash
   python -m venv .venv
   # Windows PowerShell
   .venv\Scripts\Activate.ps1
   # Linux / macOS
   source .venv/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Playwright browsers**:
   ```bash
   playwright install
   ```

4. **Copy example configuration files and fill in your details**:
   ```bash
   cp config/profile.example.yaml config/profile.yaml
   cp config/answers.example.yaml config/answers.yaml
   cp config/settings.example.yaml config/settings.yaml
   ```
   *Note: Edit `config/profile.yaml`, `config/answers.yaml`, and `config/settings.yaml` with your personal information, approved answers, and resume filename. Never commit these files.*

---

## Usage

### 1. Interactive Manual Login
Launch a persistent browser session for manual login and 2FA authentication (credentials are never handled or stored by the automation):
```bash
python -m src.main login
```

### 2. Rehearsal Mode (Dry-Run Navigation)
Rehearse search and modal progression safely without submitting any applications:
```bash
python -m src.main run --rehearse
```

### 3. Application History Dashboard
Generate the standalone, zero-external-dependency HTML dashboard directly from SQLite using read-only mode (`mode=ro`):
```bash
python -m src.main dashboard
```
To serve locally on `127.0.0.1`:
```bash
python -m src.main dashboard --serve
# Custom port:
python -m src.main dashboard --serve --port 8080
```

### 4. Review Unanswered Screening Questions
List all pending screening questions flagged during execution that require user input:
```bash
python -m src.main needs-input
```

---

## Safety Rules & Guardrails

- **`OBSERVE_ONLY` Policy Constant**: Defined as `True` in `src/policy.py`. When active, it strictly blocks any application submission (`submit` button clicks on LinkedIn and Apply clicks on Naukri).
- **`NAUKRI_APPLY_ENABLED` Constant**: Defined as `False` in `src/policy.py`. Naukri Quick Apply clicks are strictly gated and cannot be triggered unless explicitly authorized.
- **Forbidden Actions**:
  - Zero "Open to Work" modifications or toggles.
  - Zero profile viewing, profile editing, or resume upload actions.
  - Zero post creation, feed interactions, comments, likes, reactions, or shares.
  - Zero network connection requests, recruiter messages, or InMail sending.
  - Third-party company website application links are logged as `EXTERNAL_SITE` and never navigated automatically.
- **No Stealth / Anti-Detection Hacks**: Does not use bypass techniques, patched binaries, or bot-masking exploits.
- **Hard Application Caps**:
  - LinkedIn daily cap: 25 applications
  - Naukri daily cap: 40 applications
  - Combined attempts per day cap: 25 attempts
  - Search pagination limit: 1 page per run (max 10 jobs per platform)
  - Working hours enforcement: operations restricted to configured hours with randomized human-like delays.

---

## Testing

Run the test suite using `pytest`:
```bash
pytest -q
```
