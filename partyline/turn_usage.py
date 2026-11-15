"""Per-response model token usage: storage, retention and the adapter-side callback."""

import json
import time

RETENTION_SECONDS = 30 * 86400
COLUMNS = ("input", "cache_read", "cache_write", "output", "reasoning")


def prune(db, now=None):
    with db.lock:
        db.conn.execute("DELETE FROM turn_usage WHERE timestamp < ?",
                        ((time.time() if now is None else now) - RETENTION_SECONDS,))
        db.conn.commit()


def store(db, att: dict, turn: dict) -> bool:
    """Upsert one response; a repeat of it merges (largest counts, union of tool calls)."""
    now = time.time()
    when = min(now, turn["timestamp"])
    if when < now - RETENTION_SECONDS:
        return False
    with db.lock:
        row = db.conn.execute(
            "SELECT input_tokens, cache_read_tokens, cache_write_tokens, output_tokens, reasoning_tokens,"
            " calls, model, timestamp, model_ms FROM turn_usage WHERE attachment_id=? AND response_id=?",
            (att["id"], turn["response_id"])).fetchone()
        numbers = [turn[key] for key in COLUMNS]
        calls, model, took = turn["calls"], turn["model"], turn.get("model_ms")
        if row is not None:
            took = max((ms for ms in (took, row[8]) if ms is not None), default=None)
            numbers = [max(new, old) for new, old in zip(numbers, row[:5], strict=True)]
            calls = list(dict.fromkeys([*json.loads(row[5]), *calls]))
            model, when = model or row[6], min(when, row[7])
        reasoning = min(numbers[4], numbers[3])
        total = sum(numbers[:4])
        db.conn.execute(
            "INSERT INTO turn_usage(conv_id, attachment_id, adapter, response_id, model, input_tokens,"
            " cache_read_tokens, cache_write_tokens, output_tokens, reasoning_tokens, total_tokens,"
            " context_tokens, context_window, calls, timestamp, model_ms)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(attachment_id, response_id) DO UPDATE SET model=excluded.model,"
            " input_tokens=excluded.input_tokens, cache_read_tokens=excluded.cache_read_tokens,"
            " cache_write_tokens=excluded.cache_write_tokens, output_tokens=excluded.output_tokens,"
            " reasoning_tokens=excluded.reasoning_tokens, total_tokens=excluded.total_tokens,"
            " context_tokens=excluded.context_tokens, context_window=excluded.context_window,"
            " calls=excluded.calls, timestamp=excluded.timestamp, model_ms=excluded.model_ms",
            (att["conv_id"], att["id"], att["adapter"], turn["response_id"], model, *numbers[:4], reasoning,
             total, turn["context"], turn["window"], json.dumps(calls, separators=(",", ":")), when, took))
        db.conn.commit()
    if row is None:
        prune(db, now)
    return True


def turn_usage_callback(runtime, att: dict):
    """The adapter-side door: a transcript tail hands each parsed response to this."""
    async def noted(turn: dict) -> bool:
        import asyncio
        return await asyncio.to_thread(store, runtime.db, att, turn)
    return noted
