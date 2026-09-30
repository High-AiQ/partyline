"""Persistence helpers for per-line pins."""

import time


def _pin_row(row) -> dict:
    item = dict(row)
    body = item.pop("body", None)
    item["message_available"] = body is not None
    item["message_text"] = body
    return item


def list_pins(db, conv_id: str) -> list[dict]:
    rows = db._exec(
        "SELECT p.conv_id AS conversation_id, p.message_id, p.alias, p.created_at, m.body, "
        "(SELECT count(*) FROM images i WHERE i.message_id=p.message_id "
        "AND i.conv_id=p.conv_id) AS file_count "
        "FROM message_pins p LEFT JOIN messages m "
        "ON m.id=p.message_id AND m.conv_id=p.conv_id "
        "WHERE p.conv_id=? ORDER BY p.created_at, p.message_id",
        (conv_id,),
    )
    return [_pin_row(row) for row in rows.fetchall()]


def create_pin(db, conv_id: str, message_id: int) -> dict:
    db._exec(
        "INSERT INTO message_pins(conv_id,message_id,created_at) VALUES(?,?,?) "
        "ON CONFLICT(conv_id,message_id) DO NOTHING",
        (conv_id, message_id, time.time()),
    )
    return next(pin for pin in list_pins(db, conv_id) if pin["message_id"] == message_id)


def set_alias(db, conv_id: str, message_id: int, alias: str | None) -> bool:
    result = db._exec(
        "UPDATE message_pins SET alias=? WHERE conv_id=? AND message_id=?",
        (alias, conv_id, message_id),
    )
    return result.rowcount > 0


def remove_pin(db, conv_id: str, message_id: int) -> bool:
    result = db._exec(
        "DELETE FROM message_pins WHERE conv_id=? AND message_id=?", (conv_id, message_id)
    )
    return result.rowcount > 0
