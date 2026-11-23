"""fetch_api.py — server API helper via `opencode api` (shell=False; auth delegated to the CLI).

Direct HTTP returns UnauthorizedError, so going through the CLI is required (measured).
PowerShell console re-encoding breaks JSON, so capture_output + utf-8 decoding happens in python.
"""

import json
import os
import shutil
import subprocess

# Same discipline as the JS bridge (CLI_ENV in src/undo-server.js): the env var wins.
OPENCODE = os.environ.get("QUESTION_UNDO_CLI") or shutil.which("opencode")


class ApiError(RuntimeError):
    def __init__(self, method, path, returncode, stdout, stderr):
        super().__init__(f"{method} {path} -> exit {returncode}: {(stderr or stdout or '').strip()[:400]}")
        self.method = method
        self.path = path
        self.returncode = returncode
        self.stdout = stdout or ""
        self.stderr = stderr or ""


def api(method, path, data=None, timeout=180):
    """Call and return the data field on success (or the whole body if absent). ApiError on failure."""
    if not OPENCODE:
        raise RuntimeError("the opencode CLI is not on PATH. Set the QUESTION_UNDO_CLI environment variable to point at it directly")
    args = [OPENCODE, "api", method, path]
    if data is not None:
        args += ["--data", json.dumps(data, ensure_ascii=False)]
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError:
        # A QUESTION_UNDO_CLI pointing at a nonexistent path must not surface as a raw traceback (review finding L1).
        raise ApiError(method, path, -1, "", f"the configured CLI cannot be executed (missing or not an executable): {OPENCODE}")
    except subprocess.TimeoutExpired:
        raise ApiError(method, path, -1, "", f"the CLI stopped responding after {timeout}s")
    raw = (r.stdout or "").strip()
    body = None
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        pass
    if r.returncode != 0:
        raise ApiError(method, path, r.returncode, raw, r.stderr)
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body
