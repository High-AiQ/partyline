"""What each accepted hand-off's review caught, kept with the record.

Finding 2.5: the accept event is the natural place to log review findings,
so what reviews catch can be measured rather than argued. The findings ride
the accept call, land in one row per accept, and the ☏ notice counts them.
"""

from __future__ import annotations

import json
import time

from fastapi import Request

from .auth_guard import request_principal
from .machine_scope import deny_unless


def record_accept(db, conv_id: str, sha: str, reviewer: str,
                  findings: list[str]) -> None:
    with db.lock, db.conn:
        db.conn.execute(
            "INSERT INTO accept_history(conv_id,sha,reviewer,findings,created_at) "
            "VALUES(?,?,?,?,?)",
            (conv_id, sha, reviewer, json.dumps(findings), time.time()))


def accept_history(db, conv_id: str) -> list[dict]:
    rows = db._exec(
        "SELECT sha, reviewer, findings, created_at FROM accept_history "
        "WHERE conv_id=? ORDER BY id DESC", (conv_id,)).fetchall()
    return [{"sha": row["sha"], "reviewer": row["reviewer"],
             "findings": json.loads(row["findings"]), "created_at": row["created_at"]}
            for row in rows]


def register_accept_history_route(app, runtime) -> None:
    @app.get("/api/conversations/{conv_id}/accepts")
    async def accepts(request: Request, conv_id: str):
        db = runtime.db
        deny_unless(db, request_principal(request), conv_id, "read")
        return accept_history(db, conv_id)
