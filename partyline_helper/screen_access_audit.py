"""Append-only local audit for standing window access; never stores screen contents."""
import json
import os
import threading
import time

from .config import config_path


class ScreenAccessAudit:
    def __init__(self, path=None, clock=time.time):
        self.path = path
        self.clock = clock
        self.lock = threading.Lock()

    def _file(self):
        path = self.path or config_path().parent / "screen-access-audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def append(self, line, agent, call_type, app, title, result):
        row = {"time": round(self.clock(), 3), "line": str(line)[:128], "agent": str(agent)[:120],
               "call_type": str(call_type)[:40], "app": str(app)[:128], "title": str(title)[:256],
               "result": str(result)[:80]}
        with self.lock, self._file().open("a", encoding="utf-8") as stream:
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    def recent(self, limit=8):
        try:
            rows = self._file().read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 20)):]
            return [json.loads(row) for row in reversed(rows)]
        except (OSError, ValueError):
            return []


def audit_window(session, kind, agent, result, line=None):
    """Record metadata for a granted-window call before its answer is sent."""
    ident = getattr(session, "window_grant_id", None)
    parent = getattr(session, "parent", session)
    entry = getattr(getattr(parent, "windows", None), "grants", {}).get(ident, {})
    access = getattr(session, "window_access_audit", None) or getattr(parent, "window_access_audit", None)
    if access is not None:
        target = entry.get("target", {})
        access.append(line or target.get("line_id", ""), agent, kind, entry.get("process", ""),
                      entry.get("title", ""), result)


def append_metadata(message, kind, result):
    """Record a rejected raced call when its grant disappeared before helper dispatch."""
    ScreenAccessAudit().append(message.get("line", ""), message.get("agent", ""), kind,
                               message.get("process", ""), message.get("title", ""), result)


def begin_window_call(session, agent, line=None):
    ident = getattr(session, "window_grant_id", None)
    parent = getattr(session, "parent", session)
    entry = getattr(getattr(parent, "windows", None), "grants", {}).get(ident, {})
    status = getattr(parent, "status", None)
    if status is None or not hasattr(status, "begin_window_call"):
        return None
    target = entry.get("target", {})
    return status, status.begin_window_call(line or target.get("line_name", "line"), agent)


def end_window_call(active):
    if active is None:
        return
    status, ident = active
    status.end_window_call(ident)
