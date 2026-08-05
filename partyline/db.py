"""SQLite persistence for partyline. Small, synchronous, lock-guarded."""

import json
import sqlite3
import threading
import time
from typing import TypedDict

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conv_id TEXT NOT NULL,
  sender TEXT NOT NULL,
  sender_type TEXT NOT NULL,          -- human | agent | system
  body TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id, id);
CREATE TABLE IF NOT EXISTS attachments(
  id TEXT PRIMARY KEY,                -- also used as the agent session UUID
  conv_id TEXT NOT NULL,
  name TEXT NOT NULL,
  adapter TEXT NOT NULL,              -- adapter identifier
  command TEXT NOT NULL,              -- JSON argv list
  cwd TEXT NOT NULL,
  status TEXT NOT NULL,               -- starting | running | exited | detached
  last_seen INTEGER NOT NULL DEFAULT 0,  -- id of last message delivered to this agent
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS presets(
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  name TEXT NOT NULL,                 -- default @handle
  adapter TEXT NOT NULL,
  command TEXT NOT NULL,              -- shell-style string (no cwd: that's per-attach)
  created_at REAL NOT NULL
);
"""

MIGRATIONS = [
    # cli_session: optional process session id, for adapters that support resume
    "ALTER TABLE attachments ADD COLUMN cli_session TEXT",
    # topic: free-text line topic, relayed to agents in briefings and digests
    "ALTER TABLE conversations ADD COLUMN topic TEXT NOT NULL DEFAULT ''",
    # archived_at: when a line was archived, NULL while it is live. Archiving
    # hides a line and stops its processes; the history stays until a purge.
    "ALTER TABLE conversations ADD COLUMN archived_at REAL",
    # A deliberately singleton restart intent. It is saved before shutdown and
    # only consumed after the requesting line accepts reattachment on startup.
    """CREATE TABLE IF NOT EXISTS restart_plan(
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        conversation_id TEXT NOT NULL,
        attachment_ids TEXT NOT NULL,
        debrief TEXT NOT NULL,
        created_at REAL NOT NULL
    )""",
]


class RestartPlan(TypedDict):
    """The one line allowed to offer sequential process reattachment."""

    conversation_id: str
    attachment_ids: list[str]
    debrief: str
    created_at: float


def _att_row(row):
    d = dict(row)
    d["command"] = json.loads(d["command"])
    return d


def _restart_plan_row(row) -> RestartPlan:
    return RestartPlan(
        conversation_id=row["conversation_id"],
        attachment_ids=json.loads(row["attachment_ids"]),
        debrief=row["debrief"],
        created_at=row["created_at"],
    )


class Db:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            for mig in MIGRATIONS:
                try:
                    self.conn.execute(mig)
                except sqlite3.OperationalError:
                    pass  # already applied
            self.conn.commit()

    def close(self):
        """Release the connection. The server holds one for its whole life, so
        this exists for tests and for anything that opens a second database."""
        with self.lock:
            self.conn.close()

    def _exec(self, q, args=()):
        with self.lock:
            cur = self.conn.execute(q, args)
            self.conn.commit()
            return cur

    # -- conversations -----------------------------------------------------
    def create_conversation(self, conv_id, name):
        ts = time.time()
        self._exec("INSERT INTO conversations(id,name,created_at) VALUES(?,?,?)", (conv_id, name, ts))
        return self.get_conversation(conv_id)

    def list_conversations(self, archived=False):
        if archived:
            cur = self._exec(
                "SELECT * FROM conversations WHERE archived_at IS NOT NULL ORDER BY archived_at DESC")
        else:
            cur = self._exec(
                "SELECT * FROM conversations WHERE archived_at IS NULL ORDER BY created_at DESC")
        return [dict(r) for r in cur.fetchall()]

    def get_conversation(self, conv_id):
        cur = self._exec("SELECT * FROM conversations WHERE id=?", (conv_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def set_topic(self, conv_id, topic):
        self._exec("UPDATE conversations SET topic=? WHERE id=?", (topic, conv_id))
        return self.get_conversation(conv_id)

    def rename_conversation(self, conv_id, name):
        self._exec("UPDATE conversations SET name=? WHERE id=?", (name, conv_id))
        return self.get_conversation(conv_id)

    def archive_conversation(self, conv_id):
        self._exec("UPDATE conversations SET archived_at=? WHERE id=?", (time.time(), conv_id))
        return self.get_conversation(conv_id)

    def restore_conversation(self, conv_id):
        self._exec("UPDATE conversations SET archived_at=NULL WHERE id=?", (conv_id,))
        return self.get_conversation(conv_id)

    def delete_conversation(self, conv_id):
        """Drop a line and everything hanging off it, in one transaction.

        Callers must stop live adapters first: this only removes rows, and an
        orphaned pty whose attachment row is gone can never be detached again.
        """
        with self.lock:
            self.conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
            self.conn.execute("DELETE FROM attachments WHERE conv_id=?", (conv_id,))
            self.conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
            self.conn.execute("DELETE FROM restart_plan WHERE conversation_id=?", (conv_id,))
            self.conn.commit()

    # -- messages ----------------------------------------------------------
    def add_message(self, conv_id, sender, sender_type, body):
        ts = time.time()
        cur = self._exec(
            "INSERT INTO messages(conv_id,sender,sender_type,body,created_at) VALUES(?,?,?,?,?)",
            (conv_id, sender, sender_type, body, ts),
        )
        return {"id": cur.lastrowid, "conv_id": conv_id, "sender": sender,
                "sender_type": sender_type, "body": body, "created_at": ts}

    def list_messages(self, conv_id, limit=500):
        cur = self._exec(
            "SELECT * FROM (SELECT * FROM messages WHERE conv_id=? ORDER BY id DESC LIMIT ?) ORDER BY id",
            (conv_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def messages_after(self, conv_id, after_id, exclude_sender=None):
        q = "SELECT * FROM messages WHERE conv_id=? AND id>?"
        args = [conv_id, after_id]
        if exclude_sender is not None:
            q += " AND sender != ?"
            args.append(exclude_sender)
        cur = self._exec(q + " ORDER BY id", args)
        return [dict(r) for r in cur.fetchall()]

    # -- attachments -------------------------------------------------------
    def add_attachment(self, att_id, conv_id, name, adapter, command, cwd):
        ts = time.time()
        self._exec(
            "INSERT INTO attachments(id,conv_id,name,adapter,command,cwd,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (att_id, conv_id, name, adapter, json.dumps(command), cwd, "starting", ts),
        )
        return self.get_attachment(att_id)

    def get_attachment(self, att_id):
        cur = self._exec("SELECT * FROM attachments WHERE id=?", (att_id,))
        row = cur.fetchone()
        return _att_row(row) if row else None

    def list_attachments(self, conv_id):
        cur = self._exec("SELECT * FROM attachments WHERE conv_id=? ORDER BY created_at", (conv_id,))
        return [_att_row(r) for r in cur.fetchall()]

    def set_attachment_status(self, att_id, status):
        self._exec("UPDATE attachments SET status=? WHERE id=?", (status, att_id))

    def set_last_seen(self, att_id, msg_id):
        self._exec("UPDATE attachments SET last_seen=? WHERE id=? AND last_seen<?", (msg_id, att_id, msg_id))

    def set_cli_session(self, att_id, cli_session):
        self._exec("UPDATE attachments SET cli_session=? WHERE id=?", (cli_session, att_id))

    def mark_stale_attachments(self):
        """On server boot, anything still marked live belongs to a dead process."""
        self._exec("UPDATE attachments SET status='exited' WHERE status IN ('starting','running')")

    # -- restart plans -----------------------------------------------------
    def save_restart_plan(self, conversation_id: str, attachment_ids: list[str], debrief: str) -> RestartPlan:
        """Replace the sole pending restart intent, preserving attachment order."""
        created_at = time.time()
        self._exec(
            "INSERT INTO restart_plan(singleton,conversation_id,attachment_ids,debrief,created_at)"
            " VALUES(1,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET"
            " conversation_id=excluded.conversation_id,"
            " attachment_ids=excluded.attachment_ids,"
            " debrief=excluded.debrief,"
            " created_at=excluded.created_at",
            (conversation_id, json.dumps(attachment_ids), debrief, created_at),
        )
        plan = self.get_restart_plan()
        if plan is None:  # pragma: no cover - a committed INSERT is immediately readable
            raise RuntimeError("restart plan was not saved")
        return plan

    def get_restart_plan(self) -> RestartPlan | None:
        """Read the pending plan without consuming the requesting line's choice."""
        cur = self._exec("SELECT * FROM restart_plan WHERE singleton=1")
        row = cur.fetchone()
        return _restart_plan_row(row) if row else None

    def take_restart_plan(self) -> RestartPlan | None:
        """Consume the pending plan atomically after the line accepts reattachment."""
        with self.lock:
            row = self.conn.execute("SELECT * FROM restart_plan WHERE singleton=1").fetchone()
            if row:
                self.conn.execute("DELETE FROM restart_plan WHERE singleton=1")
                self.conn.commit()
            return _restart_plan_row(row) if row else None

    # -- presets -----------------------------------------------------------
    def list_presets(self):
        cur = self._exec("SELECT * FROM presets ORDER BY title COLLATE NOCASE")
        return [dict(r) for r in cur.fetchall()]

    def get_preset(self, preset_id):
        cur = self._exec("SELECT * FROM presets WHERE id=?", (preset_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def save_preset(self, preset_id, title, name, adapter, command):
        ts = time.time()
        self._exec(
            "INSERT INTO presets(id,title,name,adapter,command,created_at) VALUES(?,?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET title=excluded.title, name=excluded.name,"
            " adapter=excluded.adapter, command=excluded.command",
            (preset_id, title, name, adapter, command, ts),
        )
        return self.get_preset(preset_id)

    def delete_preset(self, preset_id):
        self._exec("DELETE FROM presets WHERE id=?", (preset_id,))
