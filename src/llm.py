import os
import sys
import json
import subprocess
import time
import re
from pathlib import Path
from typing import Any, Dict, Optional

class UsageLimitReached(Exception):
    """Raised when Claude CLI reports rate/usage limits reached."""
    pass

class LLMError(Exception):
    """General LLM execution error."""
    pass

# Hard security startup check
if os.environ.get("ANTHROPIC_API_KEY"):
    sys.stderr.write(
        "[CRITICAL SECURITY ERROR] ANTHROPIC_API_KEY is detected in environment!\n"
        "This project is strictly configured to use local headless Claude CLI ('claude -p').\n"
        "Please remove ANTHROPIC_API_KEY from your environment before running.\n"
    )
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SANDBOX_DIR = PROJECT_ROOT / "llm_sandbox"
SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

USAGE_LIMIT_PATTERNS = [
    re.compile(r"usage limit", re.IGNORECASE),
    re.compile(r"rate limit", re.IGNORECASE),
    re.compile(r"resets at", re.IGNORECASE),
    re.compile(r"you have reached your limit", re.IGNORECASE),
    re.compile(r"credit balance is too low", re.IGNORECASE),
    re.compile(r"quota exceeded", re.IGNORECASE),
]

def check_usage_limits(text: str) -> None:
    for pattern in USAGE_LIMIT_PATTERNS:
        if pattern.search(text):
            raise UsageLimitReached(f"Claude usage limit reached: {text.strip()}")

CLAUDE_CALL_COUNT = 0

def get_claude_call_count() -> int:
    global CLAUDE_CALL_COUNT
    return CLAUDE_CALL_COUNT

def reset_claude_call_count() -> None:
    global CLAUDE_CALL_COUNT
    CLAUDE_CALL_COUNT = 0

def ask_claude(
    prompt: str,
    model: Optional[str] = None,
    timeout_seconds: int = 60,
    cli_command: str = "claude.cmd"
) -> str:
    """
    Executes a single non-interactive prompt via claude CLI with stdin.
    Working directory is strictly isolated to llm_sandbox/.
    """
    global CLAUDE_CALL_COUNT
    CLAUDE_CALL_COUNT += 1

    cmd = [cli_command, "-p", "--output-format", "json"]
    if model:
        cmd.extend(["--model", model])

    # Add safe flags to avoid running any file-modifying tools
    cmd.extend(["--tools", ""])

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(SANDBOX_DIR),
            text=True,
            encoding="utf-8"
        )
        stdout, stderr = proc.communicate(input=prompt, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise LLMError(f"Claude CLI timed out after {timeout_seconds} seconds")
    except Exception as e:
        raise LLMError(f"Failed to execute Claude CLI: {e}")

    combined_output = f"{stdout} {stderr}"
    check_usage_limits(combined_output)

    if proc.returncode != 0:
        error_msg = stderr.strip() or stdout.strip() or f"Exit code {proc.returncode}"
        raise LLMError(f"Claude CLI failed ({proc.returncode}): {error_msg}")

    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            if data.get("is_error"):
                err_text = str(data.get("result") or data.get("api_error_status"))
                check_usage_limits(err_text)
                raise LLMError(f"Claude reported error: {err_text}")
            return str(data.get("result", "")).strip()
        return stdout.strip()
    except json.JSONDecodeError:
        return stdout.strip()

def ask_json(
    prompt: str,
    model: Optional[str] = None,
    retries: int = 2,
    timeout_seconds: int = 60,
    cli_command: str = "claude.cmd"
) -> Dict[str, Any]:
    """
    Queries Claude and defensively parses a valid JSON object.
    Never loops if UsageLimitReached is raised.
    """
    last_err: Optional[Exception] = None
    curr_prompt = prompt

    for attempt in range(retries + 1):
        try:
            raw_text = ask_claude(
                prompt=curr_prompt,
                model=model,
                timeout_seconds=timeout_seconds,
                cli_command=cli_command
            )

            # Defensive JSON extraction
            # 1. Direct parse
            try:
                parsed = json.loads(raw_text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

            # 2. Markdown code block
            code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
            if code_block_match:
                parsed = json.loads(code_block_match.group(1))
                if isinstance(parsed, dict):
                    return parsed

            # 3. First '{' to last '}'
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                parsed = json.loads(raw_text[start : end + 1])
                if isinstance(parsed, dict):
                    return parsed

            raise ValueError(f"Could not parse JSON object from output: {raw_text[:200]}")

        except UsageLimitReached:
            raise
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                curr_prompt = f"{prompt}\n\nNOTE: Return ONLY a valid JSON object without markdown or comments."

    raise LLMError(f"Failed to extract valid JSON after {retries + 1} attempts: {last_err}")
