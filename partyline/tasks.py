"""A shared task board for a line.

Tasks are the room's durable to-do list: any participant can add one, claim
one, or mark one done, and the open set rides every wake digest, so a process
that was asleep when work was handed out still sees it the moment it is next
mentioned. The store stays small on purpose — the decisions about *what* a
task means live in the routes and the digest rider, not here.
"""

from __future__ import annotations

import time

from .db import Db
from .task_contracts import MAX_TASK_BODY, MAX_TASK_OWNER

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conv_id TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','done')),
  owner TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_conv ON tasks(conv_id, status, id);
"""

STATUSES = ("open", "done")
# Sentinel distinguishing "field absent from the PATCH" from "explicit null".
UNSET = object()


class TaskError(Exception):
    """A task operation refused, with the HTTP shape the route should answer."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _valid_body(body: str) -> str:
    body = body.strip()
    if not body or len(body) > MAX_TASK_BODY:
        raise TaskError(400, f"body must be 1-{MAX_TASK_BODY} characters")
    return body


def _valid_owner(owner: str | None) -> str | None:
    if owner is None:
        return None
    owner = owner.strip().lstrip("@")
    if len(owner) > MAX_TASK_OWNER:
        raise TaskError(400, f"owner must be at most {MAX_TASK_OWNER} characters")
    return owner or None


def _row_to_task(row) -> dict:
    keys = ("id", "conv_id", "body", "status", "owner", "created_at", "updated_at")
    return {key: row[key] for key in keys}


def task_rider(tasks: list[dict]) -> str:
    """The open-tasks line of a wake digest; empty when nothing is open."""
    if not tasks:
        return ""
    items = "; ".join(
        f"#{task['id']} {task['body']}"
        + (f" (@{task['owner']})" if task["owner"] else "")
        for task in tasks
    )
    return f"(open tasks: {items})"


class TaskStore:
    """Task rows in SQLite, addressed by line. Validation lives at the edges."""

    def __init__(self, db: Db):
        self.db = db
        with db.lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    def _query(self, sql: str, args=()):
        with self.db.lock:
            return self.db.conn.execute(sql, args).fetchall()

    def _exec(self, sql: str, args=()):
        with self.db.lock:
            cursor = self.db.conn.execute(sql, args)
            self.db.conn.commit()
            return cursor

    def add(self, conv_id: str, body: str, owner: str | None = None) -> dict:
        now = time.time()
        cursor = self._exec(
            "INSERT INTO tasks(conv_id, body, owner, created_at, updated_at)"
            " VALUES(?, ?, ?, ?, ?)",
            (conv_id, _valid_body(body), _valid_owner(owner), now, now),
        )
        return self.get(cursor.lastrowid)

    def get(self, task_id: int) -> dict:
        rows = self._query("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not rows:
            raise TaskError(404, f"no task #{task_id}")
        return _row_to_task(rows[0])

    def list(self, conv_id: str, status: str | None = None) -> list[dict]:
        if status is not None and status not in STATUSES:
            raise TaskError(400, f"status must be one of {', '.join(STATUSES)}")
        if status is None:
            rows = self._query(
                "SELECT * FROM tasks WHERE conv_id = ? ORDER BY id", (conv_id,))
        else:
            rows = self._query(
                "SELECT * FROM tasks WHERE conv_id = ? AND status = ? ORDER BY id",
                (conv_id, status))
        return [_row_to_task(row) for row in rows]

    def open_tasks(self, conv_id: str) -> list[dict]:
        return self.list(conv_id, status="open")

    def update(self, task_id: int, *, body=UNSET, status=UNSET, owner=UNSET) -> dict:
        task = self.get(task_id)
        if body is not UNSET:
            task["body"] = _valid_body(body)
        if status is not UNSET:
            if status not in STATUSES:
                raise TaskError(400, f"status must be one of {', '.join(STATUSES)}")
            task["status"] = status
        if owner is not UNSET:
            task["owner"] = _valid_owner(owner)
        task["updated_at"] = time.time()
        self._exec(
            "UPDATE tasks SET body = ?, status = ?, owner = ?, updated_at = ?"
            " WHERE id = ?",
            (task["body"], task["status"], task["owner"],
             task["updated_at"], task_id),
        )
        return task

    def delete(self, task_id: int) -> None:
        self.get(task_id)
        self._exec("DELETE FROM tasks WHERE id = ?", (task_id,))

    def rider(self, conv_id: str) -> str:
        """The digest rider for a line, as the adapters' hook expects it."""
        return task_rider(self.open_tasks(conv_id))
