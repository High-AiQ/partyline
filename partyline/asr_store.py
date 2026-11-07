"""Database speech presets: one row each, its fields as JSON. Never holds a key, only its variable's name."""

from __future__ import annotations

import json
import time
from typing import Any


def list_presets(db) -> list[dict[str, Any]]:
    with db.lock:
        rows = db.conn.execute(
            "SELECT name, kind, config, is_default, position FROM asr_presets ORDER BY position, name"
        ).fetchall()
    return [{"name": row["name"], "kind": row["kind"], "config": json.loads(row["config"] or "{}"),
             "is_default": bool(row["is_default"]), "position": row["position"]} for row in rows]


def get_preset(db, name: str) -> dict[str, Any] | None:
    return next((row for row in list_presets(db) if row["name"] == name), None)


def save_preset(db, name: str, spec: dict[str, Any], *, create: bool) -> None:
    """Insert at the end (``create``) or replace the fields of an existing row."""
    config = json.dumps({key: value for key, value in spec.items() if key != "kind"}, sort_keys=True)
    with db.lock, db.conn:
        if create:
            (last,) = db.conn.execute("SELECT COALESCE(MAX(position), -1) FROM asr_presets").fetchone()
            db.conn.execute(
                "INSERT INTO asr_presets(name, kind, config, is_default, position, updated_at) "
                "VALUES(?,?,?,0,?,?)", (name, spec["kind"], config, last + 1, time.time()))
        else:
            db.conn.execute("UPDATE asr_presets SET kind=?, config=?, updated_at=? WHERE name=?",
                            (spec["kind"], config, time.time(), name))


def delete_preset(db, name: str) -> bool:
    with db.lock, db.conn:
        return db.conn.execute("DELETE FROM asr_presets WHERE name=?", (name,)).rowcount > 0


def set_default(db, name: str | None) -> None:
    """Flag one database preset as the default, or clear the flag (``None``)."""
    with db.lock, db.conn:
        db.conn.execute("UPDATE asr_presets SET is_default=0 WHERE is_default=1")
        if name is not None:
            db.conn.execute("UPDATE asr_presets SET is_default=1 WHERE name=?", (name,))


def reorder(db, names: list[str]) -> None:
    with db.lock, db.conn:
        db.conn.executemany("UPDATE asr_presets SET position=? WHERE name=?",
                            [(index, name) for index, name in enumerate(names)])
