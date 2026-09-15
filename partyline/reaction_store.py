"""SQLite operations and response shaping for emoji reactions."""

from __future__ import annotations

import time

from .auth_guard import Principal
from .message_queries import MESSAGE_SELECT, as_message
from .reaction_contracts import ReactionType

REACTION_EMOJIS = ("👍", "❤️", "🎉", "👀", "✅", "❌")


def valid_emoji(emoji: str) -> bool:
    return emoji in REACTION_EMOJIS


def message(db, message_id: int) -> dict | None:
    row = db._exec(MESSAGE_SELECT + " WHERE m.id=?", (message_id,)).fetchone()
    return as_message(row) if row else None


def _reactor_type(principal: Principal | None) -> ReactionType | None:
    if principal is None:
        return None
    return "agent" if principal.kind == "machine" else "human"


def _rows(db, message_ids: list[int]) -> list[dict]:
    if not message_ids:
        return []
    marks = ",".join("?" for _ in message_ids)
    cursor = db._exec(
        f"SELECT message_id,reactor,reactor_type,emoji FROM reactions "
        f"WHERE message_id IN ({marks}) ORDER BY created_at, rowid",
        message_ids,
    )
    return [dict(row) for row in cursor.fetchall()]


def grouped(db, message_ids: list[int], principal: Principal | None = None) -> dict[int, list[dict]]:
    mine = principal.name if principal else None
    mine_type = _reactor_type(principal)
    rows = _rows(db, message_ids)
    found: dict[int, dict[str, list[str]]] = {
        message_id: {emoji: [] for emoji in REACTION_EMOJIS} for message_id in message_ids
    }
    mine_keys = {
        (row["message_id"], row["emoji"])
        for row in rows
        if row["reactor"] == mine and (mine_type is None or row["reactor_type"] == mine_type)
    }
    for row in rows:
        found.setdefault(row["message_id"], {}).setdefault(row["emoji"], []).append(row["reactor"])
    return {
        message_id: [
            {"emoji": emoji, "reactors": reactors, "mine": (message_id, emoji) in mine_keys}
            for emoji, reactors in emojis.items() if reactors
        ]
        for message_id, emojis in found.items()
    }


def attach(db, messages: list[dict], principal: Principal | None = None) -> list[dict]:
    grouped_reactions = grouped(db, [item["id"] for item in messages], principal)
    return [
        {**item, "reactions": grouped_reactions.get(item["id"], [])}
        for item in messages
    ]


def with_reactions(db, item: dict, principal: Principal | None = None) -> dict:
    return attach(db, [item], principal)[0]


def toggle(db, message_id: int, reactor: str, reactor_type: ReactionType, emoji: str) -> bool:
    with db.lock:
        row = db.conn.execute(
            "SELECT 1 FROM reactions WHERE message_id=? AND reactor=? AND emoji=?",
            (message_id, reactor, emoji),
        ).fetchone()
        if row:
            db.conn.execute(
                "DELETE FROM reactions WHERE message_id=? AND reactor=? AND emoji=?",
                (message_id, reactor, emoji),
            )
            db.conn.commit()
            return False
        db.conn.execute(
            "INSERT INTO reactions(message_id,reactor,reactor_type,emoji,created_at) "
            "VALUES(?,?,?,?,?)",
            (message_id, reactor, reactor_type, emoji, time.time()),
        )
        db.conn.commit()
        return True


def remove(db, message_id: int, reactor: str, emoji: str) -> None:
    with db.lock:
        db.conn.execute(
            "DELETE FROM reactions WHERE message_id=? AND reactor=? AND emoji=?",
            (message_id, reactor, emoji),
        )
        db.conn.commit()
