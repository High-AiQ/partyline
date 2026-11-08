"""The helper's own audit of every local-tool script: a hash-chained file the server cannot edit."""
import hashlib
import json
import threading
import time

from .config import config_path

MAX_CODE = 65536


def entry(op, args, code=None):
    """One audit line per call: a script by size (its hash is its own field), anything else by arguments."""
    if code is not None:
        return f"{op} {len(code.encode())} bytes"
    shown = json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"{op} {shown[:200]}" if args else op


class ToolAudit:
    """Appended before a script is sent; an unwritable log refuses the call (fail closed)."""

    def __init__(self, path=None, clock=time.time):
        self.path, self.clock = path, clock
        self.lock = threading.Lock()
        self.last = None

    def _file(self):
        path = self.path or config_path().parent / "tools-audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_writable(self):
        with self.lock:
            with self._file().open("a", encoding="utf-8"):
                pass

    def _tail(self, path):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            return json.loads(lines[-1])["hash"] if lines else ""
        except (OSError, ValueError, KeyError, IndexError):
            return ""

    def append(self, kind, session_id, agent, op, entry, code=None):
        row = {"time": round(self.clock(), 3), "session": session_id, "agent": agent, "kind": kind,
               "op": op, "entry": entry}
        if code is not None:
            row["code_sha256"] = hashlib.sha256(code.encode()).hexdigest()
            row["code_bytes"] = len(code.encode())
            row["code"] = code[:MAX_CODE]
        with self.lock:
            path = self._file()
            row["prev"] = self.last if self.last is not None else self._tail(path)
            row["hash"] = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                                    separators=(",", ":")).encode()).hexdigest()
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.last = row["hash"]
        return row["hash"]
