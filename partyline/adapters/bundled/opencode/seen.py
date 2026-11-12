"""Which pending messages an OpenCode v2 session already holds, read from its own store.

A resumed process keeps its session, and the session keeps every digest that was ever
pasted into it. The cursor only advances on a proven paste, so a paste whose proof was
lost (the process died first) leaves messages "unseen" that the session in fact contains.
Replaying them costs the process its context again for nothing.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path


def store_path(att: dict) -> Path | None:
    """The shared store's path, as the adapter finds it: a diagnostic that prints a path only."""
    executable = (att.get("command") or ["opencode2"])[0]
    try:
        out = subprocess.run([executable, "debug", "paths", "db"], check=True, capture_output=True,
                             text=True, timeout=15, cwd=att.get("cwd") or None, env=dict(os.environ))
    except (OSError, subprocess.SubprocessError):
        return None
    path = Path(out.stdout.strip())
    return path if path.is_absolute() else None


def _line(message: dict) -> str:
    return f"[{message['sender']}]: {str(message['body']).splitlines()[0] if message['body'] else ''}"


def seen_ids(att: dict, messages: list[dict], path: Path | None = None) -> set[int]:
    """Ids of ``messages`` whose digest line is in the kept session's user records.

    A line seen once in the session accounts for one pending message, so a repeated
    "[captain]: continue" does not hide a new one. Any failure answers "none seen":
    replaying is the safe direction.
    """
    session = str(att.get("cli_session") or "")
    if not session or not messages:
        return set()
    path = path or store_path(att)
    if path is None:
        return set()
    try:
        db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            rows = db.execute("SELECT data FROM session_message WHERE session_id = ? AND type = 'user'",
                              (session,)).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return set()
    text = "\n".join(str(row[0]) for row in rows).replace("\\n", "\n")
    budget: dict[str, int] = {}
    seen = set()
    for message in sorted(messages, key=lambda item: item["id"]):
        line = _line(message)
        budget.setdefault(line, text.count(line))
        if budget[line] > 0:
            budget[line] -= 1
            seen.add(message["id"])
    return seen
