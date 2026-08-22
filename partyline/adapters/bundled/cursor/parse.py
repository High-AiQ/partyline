"""Pure transcript parsing and path calculation for the Cursor adapter."""

from __future__ import annotations

import hashlib
import json
import os
import re
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


def resync_fingerprints(path: Path, seen_fps: set[str] | list[str]) -> set[str]:
    """Re-anchor watermark after file truncation, rewrite, or compaction."""
    res = set(seen_fps)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.endswith("\n"):
                    res.add(fingerprint(line))
    except OSError:
        pass
    return res
