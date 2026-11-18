"""Bounded, line-scoped evidence for explicitly recorded demonstrations."""

import json
import re
import time
import uuid

from fastapi import HTTPException

RETENTION = 30 * 24 * 60 * 60
MAX_CALLS = 300
MAX_CALL_BYTES = 20_000
HISTORY_MATCH_TOLERANCE = 10


def prune(db, now=None):
    db._exec("DELETE FROM screen_workflow_demonstrations WHERE expires_at<=?",
             (time.time() if now is None else now,))


def start(db, conv_id, grant_id, owner_id, grant_owner_id, grant_line_id=None, now=None):
    now = time.time() if now is None else now
    prune(db, now)
    active = db._exec("SELECT id FROM screen_workflow_demonstrations WHERE conv_id=? AND state='recording'",
                      (conv_id,)).fetchone()
    if active:
        raise HTTPException(409, "a demonstration is already recording on this window")
    ident = str(uuid.uuid4())
    db._exec("INSERT INTO screen_workflow_demonstrations("
             "id,conv_id,grant_id,owner_id,grant_owner_id,grant_line_id,"
             "started_at,expires_at,state) VALUES(?,?,?,?,?,?,?,?, 'recording')",
             (ident, conv_id, grant_id, owner_id, grant_owner_id, grant_line_id or conv_id,
              now, now + RETENTION))
    return ident


def stop(db, ident, now=None):
    now = time.time() if now is None else now
    cursor = db._exec("UPDATE screen_workflow_demonstrations SET state='stopped',stopped_at=? "
                      "WHERE id=? AND state IN ('recording','limit_reached') AND expires_at>?",
                      (now, ident, now))
    if cursor.rowcount != 1:
        raise HTTPException(404, "demonstration not found")
    return read_row(db, ident, now)


def record_call(db, grant_id, operation, arguments, outcome, observation=None, now=None):
    now = time.time() if now is None else now
    row = db._exec("SELECT id,calls,started_at FROM screen_workflow_demonstrations "
                   "WHERE grant_id=? AND state='recording' AND expires_at>? ORDER BY started_at DESC LIMIT 1",
                   (grant_id, now)).fetchone()
    if row is None:
        return
    calls = json.loads(row["calls"])
    if len(calls) >= MAX_CALLS:
        calls[-1]["unresolved"] = "recording reached its call limit; later calls are absent"
        db._exec("UPDATE screen_workflow_demonstrations "
                 "SET state='limit_reached',stopped_at=?,calls=? WHERE id=?",
                 (now, json.dumps(calls, separators=(",", ":")), row["id"]))
        return
    encoded_arguments = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
    unresolved = []
    if len(encoded_arguments.encode()) > MAX_CALL_BYTES:
        arguments = {"unresolved": "arguments exceeded recording size limit"}
        unresolved.append("arguments exceeded recording size limit")
    safe_observation = compact_observation(observation)
    if safe_observation is None:
        unresolved.append("semantic observation was unavailable")
    calls.append({"index": len(calls), "at": now, "operation": operation,
                  "arguments": arguments, "outcome": outcome,
                  "observation": safe_observation, "narration": None,
                  **({"unresolved": "; ".join(unresolved)} if unresolved else {})})
    db._exec("UPDATE screen_workflow_demonstrations SET calls=? WHERE id=?",
             (json.dumps(calls, separators=(",", ":")), row["id"]))


def compact_observation(value):
    """Keep only semantic target facts, never complete trees or page text."""
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("point_observation"), dict):
        value = value["point_observation"]
    if isinstance(value.get("after"), dict):
        value = value["after"]
    if isinstance(value.get("targets"), list):
        candidates = value["targets"]
    else:
        candidates = value.get("elements")
    if not isinstance(candidates, list):
        return None
    targets = []
    for item in candidates[:50]:
        if not isinstance(item, dict):
            continue
        role = item.get("role") or item.get("semantic_role") or item.get("control_type")
        target = {"role": role[:200]} if isinstance(role, str) and role else {}
        for key in ("name", "scope"):
            candidate = item.get(key) or (item.get("path") if key == "scope" else None)
            if isinstance(candidate, str) and candidate:
                target[key] = candidate[:200]
        if target:
            targets.append(target)
    return {"targets": targets} if targets else None


def read_observation(tree, result):
    """Keep only nodes actually returned by the read route, never the cached full tree."""
    if not tree or not isinstance(result, dict):
        return None
    lines = result.get("lines")
    if isinstance(lines, str):
        lines = lines.splitlines()
    if not isinstance(lines, list):
        return None
    targets = []
    for line in lines:
        if not isinstance(line, str):
            continue
        first = line.splitlines()[0].strip().split(" ", 1)[0]
        node = tree.nodes.get(first)
        if node is None:
            continue
        item = {"role": node.cached.get("semantic_role") or node.type.lower(), "name": node.name}
        if scope := tree.path(node.id):
            item["scope"] = scope
        targets.append({key: str(item[key])[:200] for key in ("role", "name", "scope")
                        if item.get(key)})
    return {"targets": targets[:50]} if targets else None


def narrate(db, ident, owner_id, text, at=None, now=None):
    now = time.time() if now is None else now
    row = db._exec("SELECT narration,started_at FROM screen_workflow_demonstrations "
                   "WHERE id=? AND owner_id=? AND state IN ('recording','stopped','limit_reached') "
                   "AND expires_at>?",
                   (ident, owner_id, now)).fetchone()
    if row is None:
        raise HTTPException(404, "demonstration not found")
    at = time.time() if at is None else at
    if at < row["started_at"] or at - row["started_at"] > RETENTION:
        raise HTTPException(422, "narration timestamp is outside the demonstration")
    lines = json.loads(row["narration"])
    lines.append({"index": len(lines), "at": at, "text": text[:2000]})
    db._exec("UPDATE screen_workflow_demonstrations SET narration=? WHERE id=?",
             (json.dumps(lines, separators=(",", ":")), ident))


def read_row(db, ident, now=None):
    now = time.time() if now is None else now
    prune(db, now)
    row = db._exec("SELECT * FROM screen_workflow_demonstrations WHERE id=? AND expires_at>?",
                   (ident, now)).fetchone()
    if row is None:
        raise HTTPException(404, "demonstration not found")
    return {"id": row["id"], "line": row["conv_id"], "window": row["grant_id"],
            "started_at": row["started_at"], "stopped_at": row["stopped_at"],
            "state": row["state"], "calls": json.loads(row["calls"]),
            "narration": json.loads(row["narration"]), "expires_at": row["expires_at"]}


def history_evidence(db, conv_id, start, end, selected_window, selected_title=None):
    """Join content-free call timing to native adapter transcript evidence without guessing."""
    from .screen_workflow_transcripts import read_attachment_calls

    rows = db._exec(
        "SELECT id,timestamp,attachment_id,metrics FROM tool_calls "
        "WHERE conv_id=? AND timestamp>=? AND timestamp<=? "
        "ORDER BY timestamp,id LIMIT 1000",
        (conv_id, start, end),
    ).fetchall()
    native = {}
    for attachment_id in dict.fromkeys(row["attachment_id"] for row in rows):
        native[attachment_id] = read_attachment_calls(db.get_attachment(attachment_id), start, end)
    screen_rows = []
    groups = {}
    for row in rows:
        metrics = json.loads(row["metrics"])
        if metrics.get("media_source") != "screen" and not metrics.get("tool", "").startswith("screen_"):
            continue
        operation = (metrics.get("sub_op") if metrics.get("tool") in ("extras", "captain")
                     else metrics.get("tool", "unknown"))
        screen_rows.append((row, operation))
        groups.setdefault((row["attachment_id"], operation), []).append(row)

    evidence_by_call = {}
    for (attachment_id, operation), grouped_rows in groups.items():
        transcript_calls = [item for item in native.get(attachment_id, [])
                            if item["operation"] == operation]
        ordered_rows = sorted(grouped_rows, key=lambda row: (row["timestamp"], row["id"]))
        transcript_calls.sort(key=lambda item: item["at"])
        if len(ordered_rows) != len(transcript_calls):
            continue
        pairs = list(zip(ordered_rows, transcript_calls, strict=True))
        completions = [item["completed_at"] for item in transcript_calls]
        if (any(item["completed_at"] is None or item["at"] > item["completed_at"]
               or abs(row["timestamp"] - item["completed_at"]) > HISTORY_MATCH_TOLERANCE
               for row, item in pairs)
                or any(previous > current for previous, current in
                       zip(completions, completions[1:], strict=False))):
            continue
        evidence_by_call.update({row["id"]: item for row, item in pairs})

    calls = []
    for row, operation in screen_rows:
        transcript = evidence_by_call.get(row["id"])
        window = transcript.get("window") if transcript else None
        attributed = isinstance(window, str) and window in {selected_window, selected_title}
        # Do not expose evidence from a different grant merely because it appeared
        # in the same line's interval.
        arguments = transcript["arguments"] if transcript and attributed else None
        if (not isinstance(arguments, dict)
                or len(json.dumps(arguments, ensure_ascii=False, separators=(",", ":")).encode())
                > MAX_CALL_BYTES):
            arguments = None
        observation = compact_observation(transcript["observation"]) if transcript and attributed else None
        unresolved = []
        if arguments is None:
            unresolved.append("structured transcript arguments are unavailable")
        if observation is None:
            unresolved.append("semantic observation is unavailable")
        outcome = transcript["outcome"] if transcript and attributed else "unknown"
        if outcome == "unknown":
            unresolved.append("call outcome is unknown")
        if not attributed:
            unresolved.append("call cannot be attributed to the selected window")
        calls.append({
            "index": len(calls), "at": row["timestamp"],
            "operation": operation,
            "arguments": arguments, "outcome": outcome, "observation": observation,
            "narration": None, **({"unresolved": "; ".join(unresolved)} if unresolved else {}),
        })
    messages = db._exec(
        "SELECT created_at,body FROM messages WHERE conv_id=? AND created_at>=? "
        "AND created_at<=? AND sender_type='human' ORDER BY created_at,id LIMIT 500",
        (conv_id, start, end),
    ).fetchall()
    narration = []
    for message in messages:
        if not message["body"].startswith("Walkthrough ·"):
            continue
        header = re.match(r"^Walkthrough · (\d+):(\d{2}) ·", message["body"])
        take_started = None
        if header:
            duration = int(header.group(1)) * 60 + int(header.group(2))
            take_started = message["created_at"] - duration
        for line in message["body"].splitlines():
            match = re.fullmatch(r'\[(\d+):(\d+)\] "(.{1,2000})"', line)
            if match:
                at = (take_started + int(match.group(1)) * 60 + int(match.group(2))
                      if take_started is not None else None)
                item = {"index": len(narration), "at": at, "text": match.group(3)}
                if at is None:
                    item["unresolved"] = "walkthrough timing is unavailable"
                narration.append(item)
    return calls, narration


def walkthrough_narration(db, conv_id, owner_id, started_epoch, segments, now=None):
    """Attach timestamped transcript segments only to the unique active line recording."""
    now = time.time() if now is None else now
    rows = db._exec(
        "SELECT id,owner_id,started_at FROM screen_workflow_demonstrations "
        "WHERE conv_id=? AND state='recording' AND expires_at>? AND started_at<=?",
        (conv_id, now, now),
    ).fetchall()
    rows = [row for row in rows if row["owner_id"] == owner_id]
    if len(rows) != 1 or started_epoch is None:
        return False
    demo = rows[0]
    for segment in segments:
        text = segment.get("text", "").strip()
        if not text:
            continue
        at = started_epoch + segment.get("start", 0)
        if at < demo["started_at"] or at > now:
            continue
        narrate(db, demo["id"], owner_id, text, at=at, now=now)
    return True
