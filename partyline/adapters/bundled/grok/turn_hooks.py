"""Process-scoped Grok turn receipts that never touch a repo or config.toml.

Grok has no argv for hooks. Extra hook JSON is loaded from absolute paths
listed in ``~/.grok/hooks-paths``. The JSON itself lives under
``~/.partyline/hooks/`` so we do not write ``~/.grok/hooks`` or any project's
``.grok/hooks``. The command no-ops unless stdin ``sessionId`` (or
``GROK_SESSION_ID``) matches this attachment's UUID, so other Grok sessions
that also load the file cannot POST to this jack.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

DEFAULT_HOOKS_DIR = "~/.partyline/hooks"
DEFAULT_HOOKS_PATHS = "~/.grok/hooks-paths"

# Canonical names after stripping underscores. Grok's payload uses `stop` /
# `user_prompt_submit`; Claude-style hooks use `Stop` / `UserPromptSubmit`.
# `StopFailure` and `StopCancelled` replace `Stop` when a turn errors or is
# interrupted — without them a HOLD that cancels the previous turn never
# clears the badge.
_TURN_EVENTS = frozenset({
    "stop", "userpromptsubmit", "stopfailure", "stopcancelled",
})


def hooks_dir(att: dict | None = None) -> Path:
    raw = (att or {}).get("grok_hooks_dir") or os.environ.get(
        "PARTYLINE_GROK_HOOKS_DIR", DEFAULT_HOOKS_DIR
    )
    return Path(str(raw)).expanduser()


def hooks_paths_file(att: dict | None = None) -> Path:
    raw = (att or {}).get("grok_hooks_paths") or os.environ.get(
        "PARTYLINE_GROK_HOOKS_PATHS", DEFAULT_HOOKS_PATHS
    )
    return Path(str(raw)).expanduser()


def hook_file(session_id: str, att: dict | None = None) -> Path:
    return hooks_dir(att) / f"grok-turn-{session_id}.json"


def filter_command(hook_url: str, session_id: str) -> str:
    """Shell-out that POSTs only this session's UserPromptSubmit/Stop JSON."""
    script = (
        "import json,os,sys,urllib.request\n"
        f"SID={session_id!r}; URL={hook_url!r}\n"
        "ev=json.load(sys.stdin)\n"
        "got=ev.get('sessionId') or os.environ.get('GROK_SESSION_ID')\n"
        "name=(ev.get('hookEventName') or os.environ.get('GROK_HOOK_EVENT') or '')\n"
        "name=name.replace('_','').lower()\n"
        "if got!=SID: raise SystemExit(0)\n"
        f"if name not in {tuple(sorted(_TURN_EVENTS))!r}: raise SystemExit(0)\n"
        "urllib.request.urlopen(urllib.request.Request("
        "URL,data=json.dumps(ev).encode(),method='POST',"
        "headers={'Content-Type':'application/json'}),timeout=5)\n"
    )
    return "python3 -c " + shlex.quote(script)


def payload(hook_url: str, session_id: str) -> dict:
    handler = [{"hooks": [{"type": "command", "command": filter_command(hook_url, session_id)}]}]
    return {"hooks": {
        "UserPromptSubmit": handler,
        "Stop": handler,
        "StopFailure": handler,
        "StopCancelled": handler,
    }}


def install(hook_url: str, session_id: str, att: dict | None = None) -> Path:
    path = hook_file(session_id, att)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload(hook_url, session_id)), encoding="utf-8")
    _register(path, att)
    return path


def uninstall(session_id: str, att: dict | None = None) -> None:
    path = hook_file(session_id, att)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    _unregister(path, att)


def _register(path: Path, att: dict | None) -> None:
    registry = hooks_paths_file(att)
    registry.parent.mkdir(parents=True, exist_ok=True)
    line = str(path.resolve())
    existing = registry.read_text(encoding="utf-8") if registry.is_file() else ""
    lines = [row for row in existing.splitlines() if row.strip()]
    if line not in lines:
        lines.append(line)
        registry.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _unregister(path: Path, att: dict | None) -> None:
    registry = hooks_paths_file(att)
    if not registry.is_file():
        return
    line = str(path.resolve())
    lines = [row for row in registry.read_text(encoding="utf-8").splitlines()
             if row.strip() and row.strip() != line]
    if lines:
        registry.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        registry.write_text("", encoding="utf-8")
