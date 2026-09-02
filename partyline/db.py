"""SQLite persistence for partyline. Small, synchronous, lock-guarded."""

import asyncio
from contextlib import asynccontextmanager, contextmanager
import fcntl
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from typing import Literal, TypedDict

from .db_schema import MIGRATIONS, SCHEMA
from .conversation_queries import ACTIVE_CONVERSATIONS, ARCHIVED_CONVERSATIONS, CONVERSATION_BY_ID
from .message_queries import select_message_page


RestartPlanMode = Literal["offer", "automatic"]


class MessageRow(TypedDict):
    id: int
    conv_id: str
    sender: str
    sender_type: str
    body: str
    created_at: float


class RestartPlan(TypedDict):
    """The one line allowed to offer sequential process reattachment."""

    conversation_id: str
    token: str
    # The failure-report capability. Only the planner (reading its own
    # database) and the restart trigger ever see it; it is deliberately not
    # part of any API response or browser offer event.
    report_token: str | None
    mode: RestartPlanMode
    claim_owner: str | None
    claim_until: float | None
    attempt_count: int
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
        token=row["token"],
        report_token=row["report_token"],
        mode=row["mode"],
        claim_owner=row["claim_owner"],
        claim_until=row["claim_until"],
        attempt_count=row["attempt_count"],
        attachment_ids=json.loads(row["attachment_ids"]),
        debrief=row["debrief"],
        created_at=row["created_at"],
    )


class Db:
    def __init__(self, path):
        self.path = os.path.abspath(os.fspath(path))
        # SQLite transactions protect rows, but a pty write is outside SQLite.
        # This cross-process lock makes an ownership transition wait until an
        # already-authorised delivery has finished, closing the read -> pty
        # write race between retiring and replacement server generations.
        self.runtime_lock_path = f"{self.path}.runtime.lock"
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

    def _open_runtime_lock(self) -> int:
        return os.open(self.runtime_lock_path, os.O_CREAT | os.O_RDWR, 0o600)

    @contextmanager
    def _runtime_serialized(self):
        """Serialize ownership transitions with externally visible effects."""
        descriptor = self._open_runtime_lock()
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @asynccontextmanager
    async def _runtime_serialized_async(self):
        """Cancellation-safe async acquisition of the process-shared lock."""
        descriptor = self._open_runtime_lock()
        try:
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.01)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @asynccontextmanager
    async def reserve_attachment_delivery(
        self, att_id: str, runtime_owner: str | None
    ):
        """Hold attachment ownership stable through one pty delivery.

        The lock is deliberately outside SQLite: the protected effect is an
        adapter write, and holding a database transaction across an ``await``
        would let unrelated operations join that transaction. Acquisition is
        non-blocking so another generation cannot freeze this event loop while
        finishing its own short delivery.
        """
        async with self._runtime_serialized_async():
            with self.lock:
                row = self.conn.execute(
                    "SELECT 1 FROM attachments WHERE id=? AND runtime_owner IS ?",
                    (att_id, runtime_owner),
                ).fetchone()
            yield row is not None

    # -- conversations -----------------------------------------------------
    def create_conversation(self, conv_id, name):
        ts = time.time()
        self._exec("INSERT INTO conversations(id,name,created_at) VALUES(?,?,?)", (conv_id, name, ts))
        return self.get_conversation(conv_id)

    def list_conversations(self, archived=False):
        query = ARCHIVED_CONVERSATIONS if archived else ACTIVE_CONVERSATIONS
        cur = self._exec(query)
        return [dict(r) for r in cur.fetchall()]

    def get_conversation(self, conv_id):
        cur = self._exec(CONVERSATION_BY_ID, (conv_id,))
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
            query = "DELETE FROM {} WHERE attachment_id IN (SELECT id FROM attachments WHERE conv_id=?)"
            for table in ("queued_delivery_messages", "transcript_delivery_records"):
                self.conn.execute(query.format(table), (conv_id,))
            self.conn.execute("DELETE FROM review_decisions WHERE conv_id=?", (conv_id,))
            self.conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
            self.conn.execute("DELETE FROM attachments WHERE conv_id=?", (conv_id,))
            self.conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
            self.conn.execute("DELETE FROM restart_plan WHERE conversation_id=?", (conv_id,))
            self.conn.commit()

    # -- messages ----------------------------------------------------------
    def add_message(self, conv_id, sender, sender_type, body) -> MessageRow:
        ts = time.time()
        cur = self._exec(
            "INSERT INTO messages(conv_id,sender,sender_type,body,created_at) VALUES(?,?,?,?,?)",
            (conv_id, sender, sender_type, body, ts),
        )
        return MessageRow(
            id=cur.lastrowid,
            conv_id=conv_id,
            sender=sender,
            sender_type=sender_type,
            body=body,
            created_at=ts,
        )

    def add_owned_message(
        self,
        att_id: str,
        runtime_owner: str | None,
        conv_id: str,
        sender: str,
        sender_type: str,
        body: str,
    ) -> MessageRow | None:
        """Persist adapter output only while that activation owns the row."""
        created_at = time.time()
        with self.lock:
            message = self.conn.execute(
                "INSERT INTO messages(conv_id,sender,sender_type,body,created_at) "
                "SELECT ?,?,?,?,? WHERE EXISTS ("
                "SELECT 1 FROM attachments "
                "WHERE id=? AND conv_id=? AND runtime_owner IS ?)",
                (
                    conv_id,
                    sender,
                    sender_type,
                    body,
                    created_at,
                    att_id,
                    conv_id,
                    runtime_owner,
                ),
            )
            self.conn.commit()
            if message.rowcount != 1 or message.lastrowid is None:
                return None
            return MessageRow(
                id=message.lastrowid,
                conv_id=conv_id,
                sender=sender,
                sender_type=sender_type,
                body=body,
                created_at=created_at,
            )

    def list_messages(self, conv_id, limit=500):
        return self.message_page(conv_id, limit=limit)[0]

    def message_page(self, conv_id, *, before_id=None, after_id=None, limit=20):
        return select_message_page(self._exec, conv_id, before_id, after_id, limit)

    def messages_after(self, conv_id, after_id, exclude_sender=None):
        q = "SELECT * FROM messages WHERE conv_id=? AND id>?"
        args = [conv_id, after_id]
        if exclude_sender is not None:
            q += " AND sender != ?"
            args.append(exclude_sender)
        cur = self._exec(q + " ORDER BY id", args)
        return [dict(r) for r in cur.fetchall()]

    def messages_by_ids(self, conv_id: str, message_ids: list[int]) -> list[dict]:
        """Resolve an exact queued batch in transcript order, without re-routing."""
        if not message_ids:
            return []
        placeholders = ",".join("?" for _ in message_ids)
        cur = self._exec(
            f"SELECT * FROM messages WHERE conv_id=? AND id IN ({placeholders}) ORDER BY id",
            [conv_id, *message_ids],
        )
        return [dict(row) for row in cur.fetchall()]

    def queued_delivery_ids(self, att_id: str) -> list[int]:
        cur = self._exec(
            "SELECT message_id FROM queued_delivery_messages "
            "WHERE attachment_id=? ORDER BY message_id",
            (att_id,),
        )
        return [row["message_id"] for row in cur.fetchall()]

    async def queue_delivery_ids(
        self, att_id: str, message_ids: list[int], runtime_owner: str | None
    ) -> bool:
        """Persist a skipped batch only while its adapter activation owns it."""
        async with self._runtime_serialized_async():
            with self.lock:
                owned = self.conn.execute(
                    "SELECT 1 FROM attachments WHERE id=? AND runtime_owner IS ?",
                    (att_id, runtime_owner),
                ).fetchone()
                if owned is None:
                    return False
                self.conn.executemany(
                    "INSERT OR IGNORE INTO queued_delivery_messages VALUES(?,?)",
                    ((att_id, message_id) for message_id in set(message_ids)),
                )
                self.conn.commit()
        return True

    def clear_queued_delivery_ids(self, att_id: str, message_ids: list[int]) -> None:
        if not message_ids:
            return
        self._exec(
            "DELETE FROM queued_delivery_messages WHERE attachment_id=? AND message_id IN "
            f"({','.join('?' for _ in message_ids)})",
            [att_id, *message_ids],
        )

    # -- attachments -------------------------------------------------------
    def add_attachment(
        self, att_id, conv_id, name, adapter, command, cwd, runtime_owner=None,
        *, start_after_history=False,
    ):
        ts = time.time()
        self._exec(
            "INSERT INTO attachments("
            "id,conv_id,name,adapter,command,cwd,status,runtime_owner,last_seen,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,CASE WHEN ? THEN COALESCE((SELECT MAX(id) "
            "FROM messages WHERE conv_id=?),0) ELSE 0 END,?)",
            (
                att_id,
                conv_id,
                name,
                adapter,
                json.dumps(command),
                cwd,
                "starting",
                runtime_owner,
                start_after_history,
                conv_id,
                ts,
            ),
        )
        return self.get_attachment(att_id)

    def get_attachment(self, att_id):
        cur = self._exec("SELECT * FROM attachments WHERE id=?", (att_id,))
        row = cur.fetchone()
        return _att_row(row) if row else None

    def list_attachments(self, conv_id):
        cur = self._exec("SELECT * FROM attachments WHERE conv_id=? ORDER BY created_at", (conv_id,))
        return [_att_row(r) for r in cur.fetchall()]

    async def update_inactive_attachment_command(self, att_id, command):
        async with self._runtime_serialized_async():
            changed = self._exec("UPDATE attachments SET command=? "
                                 "WHERE id=? AND status IN ('exited','detached')",
                                 (json.dumps(command), att_id))
            return self.get_attachment(att_id) if changed.rowcount == 1 else None

    def claim_attachment(self, att_id: str, runtime_owner: str) -> bool:
        """Claim one inactive row for a new adapter activation atomically."""
        with self._runtime_serialized():
            return self._claim_attachment(att_id, runtime_owner)

    async def claim_attachment_async(self, att_id: str, runtime_owner: str) -> bool:
        async with self._runtime_serialized_async():
            return self._claim_attachment(att_id, runtime_owner)

    def _claim_attachment(self, att_id: str, runtime_owner: str) -> bool:
        cur = self._exec(
            "UPDATE attachments SET status='starting',runtime_owner=? "
            "WHERE id=? AND status NOT IN ('starting','running')",
            (runtime_owner, att_id),
        )
        return cur.rowcount == 1

    def set_attachment_status(self, att_id, status, runtime_owner: str | None) -> bool:
        """Write lifecycle state unless a newer adapter activation owns the row."""
        with self._runtime_serialized():
            return self._set_attachment_status(att_id, status, runtime_owner)

    async def set_attachment_status_async(self, att_id, status, runtime_owner: str | None) -> bool:
        async with self._runtime_serialized_async():
            return self._set_attachment_status(att_id, status, runtime_owner)

    def _set_attachment_status(self, att_id, status, runtime_owner: str | None) -> bool:
        cur = self._exec(
            "UPDATE attachments SET status=? WHERE id=? AND runtime_owner IS ?",
            (status, att_id, runtime_owner),
        )
        return cur.rowcount == 1

    def detach_attachment_with_message(self, att_id, runtime_owner, body) -> MessageRow | None:
        """Detach one inactive activation and persist its notice atomically.

        A replacement may claim the attachment as soon as it is detached. The
        message belongs in the same transaction as the status transition so a
        new ``running`` claim can never precede an obsolete "detached" notice.
        """
        with self._runtime_serialized():
            return self._detach_attachment_with_message(att_id, runtime_owner, body)

    async def detach_attachment_with_message_async(
        self, att_id: str, runtime_owner: str | None, body: str) -> MessageRow | None:
        async with self._runtime_serialized_async():
            return self._detach_attachment_with_message(att_id, runtime_owner, body)

    def _detach_attachment_with_message(
        self, att_id: str, runtime_owner: str | None, body: str
    ) -> MessageRow | None:
        with self.lock:
            try:
                attachment = self.conn.execute(
                    "SELECT conv_id FROM attachments WHERE id=?", (att_id,)
                ).fetchone()
                if attachment is None:
                    return None
                changed = self.conn.execute(
                    "UPDATE attachments SET status='detached' "
                    "WHERE id=? AND status NOT IN ('starting','running') AND runtime_owner IS ?",
                    (att_id, runtime_owner),
                )
                if changed.rowcount != 1:
                    self.conn.commit()
                    return None
                created_at = time.time()
                message = self.conn.execute(
                    "INSERT INTO messages(conv_id,sender,sender_type,body,created_at) "
                    "VALUES(?,?,?,?,?)",
                    (attachment["conv_id"], "system", "system", body, created_at),
                )
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise
            if message.lastrowid is None:  # pragma: no cover - SQLite assigns this on INSERT
                return None
            return MessageRow(
                id=message.lastrowid,
                conv_id=attachment["conv_id"],
                sender="system",
                sender_type="system",
                body=body,
                created_at=created_at,
            )

    def set_last_seen(self, att_id, msg_id, runtime_owner: str | None) -> bool:
        cur = self._exec(
            "UPDATE attachments SET last_seen=MAX(last_seen,?) "
            "WHERE id=? AND runtime_owner IS ?",
            (msg_id, att_id, runtime_owner),
        )
        return cur.rowcount == 1

    def set_cli_session(self, att_id, cli_session, runtime_owner: str | None) -> bool:
        cur = self._exec(
            "UPDATE attachments SET cli_session=? WHERE id=? AND runtime_owner IS ?",
            (cli_session, att_id, runtime_owner),
        )
        return cur.rowcount == 1

    def mark_stale_attachments(self):
        """On server boot, anything still marked live belongs to a dead process."""
        with self._runtime_serialized():
            self._exec(
                "UPDATE attachments SET status='exited',runtime_owner=NULL "
                "WHERE status IN ('starting','running')"
            )

    # -- restart plans -----------------------------------------------------
    def save_restart_plan(
        self,
        conversation_id: str,
        attachment_ids: list[str],
        debrief: str,
        mode: RestartPlanMode = "offer",
    ) -> RestartPlan:
        """Replace the sole pending restart intent, preserving attachment order."""
        created_at = time.time()
        token = str(uuid.uuid4())
        report_token = secrets.token_urlsafe(32)
        self._exec(
            "INSERT INTO restart_plan("
            "singleton,conversation_id,token,report_token,mode,claim_owner,claim_until,attempt_count,attachment_ids,debrief,created_at)"
            " VALUES(1,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET"
            " conversation_id=excluded.conversation_id,"
            " token=excluded.token,"
            " report_token=excluded.report_token,"
            " mode=excluded.mode,"
            " claim_owner=NULL,"
            " claim_until=NULL,"
            " attempt_count=0,"
            " attachment_ids=excluded.attachment_ids,"
            " debrief=excluded.debrief,"
            " created_at=excluded.created_at",
            (conversation_id, token, report_token, mode, None, None, 0,
             json.dumps(attachment_ids), debrief, created_at),
        )
        plan = self.get_restart_plan()
        if plan is None:  # pragma: no cover - a committed INSERT is immediately readable
            raise RuntimeError("restart plan was not saved")
        return plan

    def get_restart_plan(self) -> RestartPlan | None:
        """Read the pending plan without consuming the requesting line's choice."""
        cur = self._exec("SELECT * FROM restart_plan WHERE singleton=1 AND token IS NOT NULL")
        row = cur.fetchone()
        return _restart_plan_row(row) if row else None

    def claim_restart_plan(
        self,
        mode: RestartPlanMode,
        owner: str,
        lease_seconds: float,
    ) -> RestartPlan | None:
        """Atomically lease an unclaimed or expired plan to one server lifespan."""
        now = time.time()
        with self.lock:
            row = self.conn.execute(
                "UPDATE restart_plan SET claim_owner=?, claim_until=?,"
                " attempt_count=attempt_count + CASE WHEN mode='automatic' THEN 1 ELSE 0 END"
                " WHERE singleton=1 AND mode=?"
                " AND (claim_owner IS NULL OR claim_until <= ?)"
                " RETURNING *",
                (owner, now + lease_seconds, mode, now),
            ).fetchone()
            self.conn.commit()
        return _restart_plan_row(row) if row else None

    def renew_restart_plan_claim(self, token: str, owner: str, lease_seconds: float) -> bool:
        """Extend a still-held lease; an expired owner cannot revive a stale claim."""
        now = time.time()
        cur = self._exec(
            "UPDATE restart_plan SET claim_until=?"
            " WHERE singleton=1 AND token=? AND claim_owner=? AND claim_until > ?",
            (now + lease_seconds, token, owner, now),
        )
        return cur.rowcount == 1

    def release_restart_plan_claim(self, token: str, owner: str) -> bool:
        """Give up a held lease without deleting the recovery plan."""
        cur = self._exec(
            "UPDATE restart_plan SET claim_owner=NULL, claim_until=NULL"
            " WHERE singleton=1 AND token=? AND claim_owner=?",
            (token, owner),
        )
        return cur.rowcount == 1

    def complete_restart_plan(self, token: str, owner: str) -> bool:
        """Delete only an automatic plan still held by its exact lease owner."""
        now = time.time()
        cur = self._exec(
            "DELETE FROM restart_plan"
            " WHERE singleton=1 AND token=? AND mode='automatic'"
            " AND claim_owner=? AND claim_until > ?",
            (token, owner, now),
        )
        return cur.rowcount == 1

    def take_restart_plan(
        self,
        conversation_id: str,
        token: str,
        mode: RestartPlanMode,
    ) -> RestartPlan | None:
        """Atomically consume the offer accepted by its original line and tab."""
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM restart_plan WHERE singleton=1 AND conversation_id=? AND token=? AND mode=?",
                (conversation_id, token, mode),
            ).fetchone()
            if row:
                self.conn.execute(
                    "DELETE FROM restart_plan WHERE singleton=1 AND conversation_id=? AND token=? AND mode=?",
                    (conversation_id, token, mode),
                )
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
