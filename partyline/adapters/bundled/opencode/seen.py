"""Which pending messages an OpenCode v2 session already holds, read from its own store.

A resumed process keeps its session, and the session keeps every digest that was ever
pasted into it. The cursor only advances on a proven paste, so a paste whose proof was
lost (the process died first) leaves messages "unseen" that the session in fact contains.
Replaying them costs the process its context again for nothing.

A message counts as seen only when its whole digest line (speaker and the full body) sits on
its own lines in a user record pasted *after* the last paste the cursor already credits:
a short reply ("yes") must not be hidden by a longer line that starts the same, nor by the
same words pasted long ago.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

from partyline.adapters.briefing import _speaker


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


def line(message: dict) -> str:
    return f"[{_speaker(message)}]: {message['body'] or ''}"


def _text(data: str) -> str:
    try:
        record = json.loads(data)
    except ValueError:
        return str(data)
    return str(record.get("text", "")) if isinstance(record, dict) else str(record)


def _count(text: str, wanted: str) -> int:
    return len(re.findall(r"(?:^|\n)" + re.escape(wanted) + r"(?=\n|$)", text))


def seen_ids(att: dict, messages: list[dict], path: Path | None = None,
             credited: list[dict] | None = None) -> set[int]:
    """Ids of ``messages`` whose whole digest line is in the kept session's later user records.

    ``credited`` are the newest messages the cursor already counts as pasted; records up to the
    last one holding any of them are skipped. When it is non-empty but none is found, nothing
    is vouched for. A line seen once accounts for one pending message, so a repeated
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
            rows = db.execute("SELECT data FROM session_message WHERE session_id = ? AND type = 'user'"
                              " ORDER BY seq", (session,)).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return set()
    records = [_text(str(row[0])) for row in rows]
    if credited:
        anchors = [line(message) for message in credited]
        holding = [index for index, record in enumerate(records)
                   if any(_count(record, anchor) for anchor in anchors)]
        if not holding:
            return set()
        records = records[holding[-1] + 1:]
    text = "\n".join(records)
    budget: dict[str, int] = {}
    seen = set()
    for message in sorted(messages, key=lambda item: item["id"]):
        wanted = line(message)
        budget.setdefault(wanted, _count(text, wanted))
        if budget[wanted] > 0:
            budget[wanted] -= 1
            seen.add(message["id"])
    return seen
