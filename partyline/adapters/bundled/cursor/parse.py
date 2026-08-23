"""Pure transcript parsing and path calculation for the Cursor adapter."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

from partyline.adapters.receipts import BEGAN, ENDED


def cwd_md5(cwd: str) -> str:
    """Return MD5 hash of canonical realpath for the working directory."""
    real = os.path.realpath(cwd)
    return hashlib.md5(real.encode("utf-8")).hexdigest()


def cwd_slug(cwd: str) -> str:
    """Convert directory path into Cursor's project slug format."""
    return re.sub(r"[^a-zA-Z0-9]+", "-", cwd).strip("-")


def chat_dir(cwd: str) -> Path:
    """Return directory where Cursor stores chat metadata for this cwd."""
    return Path.home() / ".cursor" / "chats" / cwd_md5(cwd)


def transcript_path(cwd: str, session_id: str) -> Path:
    """Return full path to the primary agent JSONL transcript for a session."""
    slug = cwd_slug(cwd)
    return (
        Path.home()
        / ".cursor"
        / "projects"
        / slug
        / "agent-transcripts"
        / session_id
        / f"{session_id}.jsonl"
    )


def fingerprint(record: dict | str) -> str:
    """Compute deterministic SHA-256 fingerprint for a transcript record or line."""
    if isinstance(record, dict):
        canonical = json.dumps(record, sort_keys=True, ensure_ascii=False)
    else:
        try:
            parsed = json.loads(record)
            if isinstance(parsed, dict):
                canonical = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
            else:
                canonical = record.strip()
        except Exception:
            canonical = record.strip()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_record(record: dict) -> tuple[str | None, str | None]:
    """Parse one JSONL record into turn receipts and assistant chat speech.

    Returns ``(event, text)`` where:
    - ``event`` is ``BEGAN``, ``ENDED``, or ``None``
    - ``text`` is assistant reply string or ``None``
    """
    if record.get("type") == "turn_ended":
        return ENDED, None

    msg = record.get("message")
    role = record.get("role")
    if isinstance(msg, dict):
        role = role or msg.get("role")

    if role == "user":
        return BEGAN, None

    if role == "assistant":
        content = (msg.get("content") if isinstance(msg, dict) else None) or record.get("content")
        if isinstance(content, list):
            # Do not post assistant text if the record also contains tool_use
            if any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content):
                return None, None
            texts = [
                block.get("text", "").replace("[REDACTED]", "").strip()
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            body = "\n\n".join(t for t in texts if t)
            return None, body.strip() if body.strip() else None
        if isinstance(content, str):
            cleaned = content.replace("[REDACTED]", "").strip()
            return None, cleaned if cleaned else None
        if record.get("type") == "text" and isinstance(record.get("text"), str):
            cleaned = record["text"].replace("[REDACTED]", "").strip()
            return None, cleaned if cleaned else None
        return None, None

    if record.get("type") == "text" and not role:
        text = record.get("text")
        if isinstance(text, str):
            cleaned = text.replace("[REDACTED]", "").strip()
            if cleaned:
                return None, cleaned

    return None, None


def resync_fingerprints(
    path: Path, seen_fps: list[str], incoming_fps: list[str] | None = None
) -> list[str]:
    """Re-anchor watermark after file truncation, rewrite, or compaction.

    Invariant: The returned watermark may only ever cover records this process
    actually delivered. Candidate watermarks are validated against the seen
    multiset (per-fingerprint counts) and never extend past records that would
    exceed those counts.

    If no candidate validates, we hold the watermark by position
    (incoming[:len(seen_fps)]) rather than returning empty, preventing resume
    rewrites from replaying history.

    Known trade-off: A rewritten file containing a byte-identical duplicate turn
    is genuinely ambiguous for any positional scheme. On ambiguity, we bias
    toward emitting (receipts must fire; badge safety beats speech dedup).
    Any boundary ENDED emitted by positional hold cleanly flushes server-held
    wakes on turn-end, which is safe and badge-conservative.
    """
    if incoming_fps is None:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                incoming = [fingerprint(line) for line in fh if line.endswith("\n")]
        except OSError:
            return seen_fps
    else:
        incoming = incoming_fps
    if not seen_fps or not incoming:
        return seen_fps if seen_fps else []

    seen_counts = Counter(seen_fps)

    def is_valid(cand: list[str]) -> bool:
        cand_counts = Counter(cand)
        for fp, count in cand_counts.items():
            # A shared stop sentinel is not enough to cover new speech.
            if fp not in seen_counts or count > seen_counts[fp]:
                return False
        return True

    # 1. Exact prefix match
    high = min(len(seen_fps), len(incoming))
    for k in range(high, 0, -1):
        if seen_fps[-k:] == incoming[:k]:
            cand = incoming[:k]
            if is_valid(cand):
                return cand

    # 2. Subsegment match: find longest suffix of seen_fps in incoming
    for k in range(len(seen_fps), 0, -1):
        target = seen_fps[-k:]
        target_len = len(target)
        for i in range(len(incoming) - target_len + 1):
            if incoming[i : i + target_len] == target:
                cand = incoming[: i + target_len]
                if is_valid(cand):
                    return cand

    # 3. Fallback: preserve seen_fps unchanged rather than dropping history
    return seen_fps


def resync_positional(
    path: Path, seen_fps: list[str], incoming_fps: list[str] | None = None
) -> list[str]:
    """Positional fallback when semantic re-anchoring fails."""
    if incoming_fps is None:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                incoming = [fingerprint(line) for line in fh if line.endswith("\n")]
        except OSError:
            return seen_fps
    else:
        incoming = incoming_fps
    return incoming[: len(seen_fps)]
