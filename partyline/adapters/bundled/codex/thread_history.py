"""Codex paginated thread history: where a resumed turn is recorded.

Verified against codex-cli 0.156 on this host: interactive ``codex resume``
creates **no new rollout file**. The resumed turn is appended to the prior
rollout in place and projected into ``thread_history_1.sqlite`` under
``CODEX_HOME`` (``thread_items`` / ``thread_turns``). A private
``CODEX_HOME`` therefore holds this attachment's copy of both, and this
module reads that store the way the opencode adapter reads its session db:
read-only, WAL-safe, never a write.

Only ``agentMessage`` rows are chat. 0.156 writes these ``item_type`` values
into ``thread_items`` (counts from a live ``~/.codex`` store, 2026-09-23):
``reasoning``, ``commandExecution``, ``agentMessage``, ``fileChange``,
``userMessage``, ``imageView``, ``contextCompaction``, ``sleep``,
``collabAgentToolCall``. Several of those carry text of their own —
``reasoning`` summaries, ``commandExecution.command`` / ``aggregatedOutput``,
``fileChange`` diffs — and none of it is the process speaking. The relay is
therefore an allowlist on ``item_type == "agentMessage"``; a new row kind the
vendor invents must not become speech by merely having a ``text`` field.

The claim-marker gate is unchanged: a ``userMessage`` row is the structured
record of a pasted digest, so it is what proves this activation's nonce.
Speech still flows only through ``adapter.post``, which holds it until that
proof lands.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path

from partyline.adapters.receipts import BEGAN, ENDED, receipt
from partyline.adapters.store_wake import StoreWake

STORE_NAME = "thread_history_1.sqlite"


def store_path(home: str) -> Path:
    return Path(home) / STORE_NAME


def connect(home: str) -> sqlite3.Connection:
    """Open the CLI-owned database read-only for the lifetime of the tail."""
    return sqlite3.connect(f"{store_path(home).as_uri()}?mode=ro", uri=True)


def user_text(item: dict) -> str:
    parts = item.get("content") or []
    return "".join(part.get("text") or "" for part in parts if isinstance(part, dict))


def agent_text(item: dict) -> str:
    text = item.get("text") or ""
    return text if isinstance(text, str) else ""


def parse_item(item_type: str, raw: str) -> dict | None:
    if item_type == "contextCompaction":
        return None  # a summary, never speech
    try:
        item = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return item if isinstance(item, dict) else None


def fetch_items(conn, thread_id: str, after_ms: int, seen=()) -> list[tuple[str, str, int, str]]:
    ids = [row[0] for row in conn.execute(
        "SELECT item_id FROM thread_items WHERE thread_id = ? AND created_at_ms >= ?",
        (thread_id, after_ms)) if row[0] not in seen]
    rows = []
    for start in range(0, len(ids), 400):
        chunk = ids[start:start + 400]
        rows.extend(conn.execute(
            "SELECT item_id, item_type, created_at_ms, item_json FROM thread_items "
            f"WHERE thread_id = ? AND created_at_ms >= ? AND item_id IN ({','.join('?' * len(chunk))})",
            (thread_id, after_ms, *chunk)).fetchall())
    return sorted(rows, key=lambda row: (row[2], row[0]))


def fetch_turns(conn, thread_id: str) -> list[tuple[str, str, int | None]]:
    return conn.execute(
        "SELECT turn_id, status, started_at FROM thread_turns "
        "WHERE thread_id = ? ORDER BY started_at, turn_id",
        (thread_id,),
    ).fetchall()


async def _emit_turn(adapter, turn_id: str, status: str, seen: dict[str, str],
                     open_turn: str | None) -> str | None:
    prior = seen.get(turn_id)
    if prior == status:
        return open_turn
    seen[turn_id] = status
    if prior is None:
        if open_turn and open_turn != turn_id:
            # A superseding turn is the abandoned one's only death signal.
            seen[open_turn] = "completed"
            await receipt(adapter.att, ENDED)
            open_turn = None
        if status == "inProgress":
            await receipt(adapter.att, BEGAN)
            return turn_id
        await receipt(adapter.att, BEGAN)
        await receipt(adapter.att, ENDED)
        return None
    if status == "completed":
        await receipt(adapter.att, ENDED)
        return None if open_turn == turn_id else open_turn
    await receipt(adapter.att, BEGAN)
    return turn_id


async def tail_thread_history(adapter, home: str, thread_id: str, *, timeout: float = 45.0) -> bool:
    """Relay this thread from CODEX_HOME's paginated store.

    Returns False when the store never appears, so the caller can fall back
    to the rollout tail. Returns True once a store has been claimed — even
    if the process then exits — so a resume is never double-tailed.
    """
    with contextlib.ExitStack() as stack:
        return await _tail_open(adapter, home, thread_id, timeout, stack)


async def _tail_open(adapter, home, thread_id, timeout, stack):
    after_ms = int((adapter.spawned_at - 5) * 1000)
    seen_items: set[str] = set()
    seen_turns: dict[str, str] = {}
    open_turn: str | None = None
    deadline = adapter.event_time() + timeout
    waited = 0.0
    opened = False
    conn = None
    version = None
    wake = StoreWake(adapter)
    while adapter.alive():
        path = store_path(home)
        if not path.exists():
            if waited >= timeout:
                return False
            await adapter.wait_for_change(max(0, deadline - adapter.event_time()))
            waited = timeout - max(0, deadline - adapter.event_time())
            continue
        observed = wake.observed()
        try:
            if conn is None:
                conn = stack.enter_context(contextlib.closing(connect(home)))
            current = conn.execute("PRAGMA data_version").fetchone()[0]
            changed = current != version
            if changed:
                rows = fetch_items(conn, thread_id, after_ms, seen_items)
                turns = fetch_turns(conn, thread_id)
                version = current
            else:
                rows, turns = [], []
        except sqlite3.Error:
            wake.read(observed, False, error=True)
            await adapter.wait_for_change()
            continue
        found = bool(rows) or any(seen_turns.get(ident) != status
                                  for ident, status, _ in turns)
        wake.read(observed, found)
        opening = not opened
        if opening:
            opened = True
        # Claims first: a batch may carry this activation's nonce and its
        # speech, and proof must not depend on row order inside that batch.
        speech: list[str] = []
        for item_id, item_type, _created_ms, raw in rows:
            if item_id in seen_items:
                continue
            seen_items.add(item_id)
            if item_type == "userMessage":
                adapter.observe_claim(raw)
                item = parse_item(item_type, raw) or {}
                await adapter.observe_paste_text(user_text(item))
                prompt = getattr(adapter, "_startup_prompt", "")
                if prompt and prompt in user_text(item):
                    adapter.mark_startup_delivery_received()
                continue
            if item_type != "agentMessage":
                continue  # reasoning, commands, diffs: never the process talking
            item = parse_item(item_type, raw)
            if not item:
                continue
            body = agent_text(item).strip()
            if body:
                speech.append(body)
        # Input receipts in this snapshot must settle before a Stop hook can
        # flush the same assignment from the pre-claim retry queue.
        for turn_id, status, started_at in turns:
            if started_at is not None and started_at < (adapter.spawned_at - 5):
                seen_turns[turn_id] = status
                continue
            open_turn = await _emit_turn(adapter, turn_id, status, seen_turns, open_turn)
        if opening:
            adapter.mark_ready()
        for body in speech:
            await adapter.post(adapter.att["name"], "agent", body)
        await adapter.wait_for_change(wake.delay())
    return opened
