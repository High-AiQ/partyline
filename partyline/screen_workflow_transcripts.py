"""Read native adapter transcripts on demand for a person's history import."""

import glob
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .adapters.transcript_scan import scan_lines


def _stamp(record):
    from .turn_usage_parse import stamp

    return stamp(record.get("timestamp"))


def _operation(name, arguments):
    """Return a fixed screen operation and its native arguments, when recognized."""
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return None, None
    name = name.rsplit("__", 1)[-1]
    if name in ("extras", "captain"):
        operation = arguments.get("op")
        args = arguments.get("args")
    else:
        operation, args = name, arguments
    from .mcp.telemetry import operation_names

    if operation not in operation_names() or not operation.startswith("screen_"):
        return None, None
    return operation, args if isinstance(args, dict) else None


def _result(value):
    """Decode only an unambiguous JSON tool result; do not infer from prose."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        texts = [part.get("text") for part in value if isinstance(part, dict)
                 and isinstance(part.get("text"), str)]
        if len(texts) == 1:
            value = texts[0]
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def _observation(result):
    if not isinstance(result, dict):
        return None
    source = result.get("point_observation") or result.get("after") or result
    if isinstance(source, dict) and isinstance(source.get("after"), dict):
        source = source["after"]
    nodes = source.get("elements", source.get("targets")) if isinstance(source, dict) else None
    if not isinstance(nodes, list):
        return None
    targets = []
    for node in nodes[:50]:
        if not isinstance(node, dict):
            continue
        target = {}
        role = node.get("role") or node.get("semantic_role") or node.get("control_type")
        name = node.get("name")
        scope = node.get("scope") or node.get("path")
        for key, value in (("role", role), ("name", name), ("scope", scope)):
            if isinstance(value, str) and value:
                target[key] = value[:200]
        if target:
            targets.append(target)
    return {"targets": targets} if targets else None


def _native_calls(records):
    """Normalize Claude and Codex call/result pairs from their native JSONL records."""
    pending, results, calls = {}, {}, []
    for record in records:
        if not isinstance(record, dict):
            continue
        stamp = _stamp(record)
        kind = record.get("type")
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        if kind == "assistant":
            for block in message.get("content") or ():
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                op, args = _operation(block.get("name"), block.get("input"))
                if op:
                    pending[block.get("id")] = (op, args, stamp)
        elif kind == "user":
            for block in message.get("content") or ():
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    results[block.get("tool_use_id")] = (block.get("content"), stamp)
        elif kind == "response_item" and payload.get("type") == "function_call":
            try:
                args = json.loads(payload.get("arguments", ""))
            except (ValueError, TypeError):
                args = None
            op, args = _operation(payload.get("name"), args)
            if op:
                pending[payload.get("call_id") or payload.get("id")] = (op, args, stamp)
        elif kind == "response_item" and payload.get("type") == "function_call_output":
            results[payload.get("call_id") or payload.get("id")] = (payload.get("output"), stamp)
    for ident, (operation, arguments, at) in pending.items():
        raw_result, completed_at = results.get(ident, (None, None))
        result = _result(raw_result)
        status = result.get("status") if result else None
        if status not in ("completed", "no_effect", "failed", "unconfirmed"):
            status = "unknown"
        calls.append({"at": at, "completed_at": completed_at,
                      "operation": operation, "arguments": arguments,
                      "window": arguments.get("window") if isinstance(arguments, dict) else None,
                      "outcome": status, "observation": _observation(result)})
    return sorted((call for call in calls if call["at"] is not None), key=lambda item: item["at"])


def _opencode_calls(attachment, start, end):
    """Read the selected OpenCode v2 session rows from its existing read-only store."""
    session = attachment.get("cli_session")
    if not session:
        return []
    configured = os.environ.get("OPENCODE_DB")
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            return []  # The adapter resolves relative overrides; the server cannot verify that path.
    else:
        data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        if not data_home.is_absolute():
            return []
        path = data_home / "opencode" / "opencode-v2.db"
    if not path.is_file():
        return []
    try:
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
            rows = db.execute(
                "SELECT data FROM session_message WHERE session_id=? AND type='assistant' "
                "ORDER BY seq", (session,)).fetchall()
    except sqlite3.Error:
        return []
    calls = []
    for (raw,) in rows:
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            continue
        created = (message.get("time") or {}).get("created")
        at = created / 1000 if isinstance(created, (int, float)) else None
        if at is None or not start <= at <= end:
            continue
        for part in message.get("content") or ():
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            operation, arguments = _operation(part.get("name"), state.get("input"))
            if not operation:
                continue
            result = _result(state.get("output"))
            part_time = state.get("time") if isinstance(state.get("time"), dict) else {}
            completed = part_time.get("completed") or (message.get("time") or {}).get("completed")
            completed_at = completed / 1000 if isinstance(completed, (int, float)) else None
            status = state.get("status")
            status = status if status in ("completed", "no_effect", "failed", "unconfirmed") else (
                result.get("status") if result else "unknown")
            if status not in ("completed", "no_effect", "failed", "unconfirmed"):
                status = "unknown"
            calls.append({"at": at, "completed_at": completed_at,
                          "operation": operation, "arguments": arguments,
                          "window": arguments.get("window") if isinstance(arguments, dict) else None,
                          "outcome": status, "observation": _observation(result)})
    return calls


def _jsonl(path, start, end):
    records = []
    try:
        for line in scan_lines(path):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            at = _stamp(record) if isinstance(record, dict) else None
            if at is not None and start <= at <= end:
                records.append(record)
    except OSError:
        return []
    return records


def read_attachment_calls(attachment, start, end):
    """Read only a selected attachment's existing transcript; unsupported evidence is absent."""
    if not attachment:
        return []
    kind = attachment.get("adapter", "").lower()
    if kind == "claude":
        from .adapters.bundled.claude.session import pinned_transcript_glob

        paths = glob.glob(pinned_transcript_glob(attachment))
    elif kind == "codex":
        home = Path.home() / ".partyline" / "sessions" / "codex" / attachment["id"] / "sessions"
        paths = glob.glob(str(home / "**" / "rollout-*.jsonl"), recursive=True)
    elif kind == "opencode-v2":
        return _opencode_calls(attachment, start, end)
    else:
        return []
    records = []
    for path in paths[:16]:
        # The native reader is bounded to selected timestamps, and parsing happens only at import.
        records.extend(_jsonl(path, start, end))
    return _native_calls(records)
