"""Reading Grok's JSONL transcript: what counts as speech, and where we are in it.

Split out of ``adapter.py`` at its line cap. These are pure functions over a
file: none of them know about attachments, ptys, or the chat room, which is
what lets every replay rule be tested against a temporary file alone.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from partyline.adapters.compaction import is_compaction_record


@dataclass(frozen=True)
class AssistantRecord:
    """One assistant record in transcript order, whether or not it is speech."""

    fingerprint: bytes
    body: str | None


def assistant_text(record: object) -> str | None:
    if not isinstance(record, dict):
        return None
    if is_compaction_record("grok", record):
        return None
    if record.get("type") != "assistant":
        return None
    # Grok often puts the user-facing sentence on the same record as
    # ``tool_calls``. That text is on the pty (peek sees it). Dropping it
    # because tools were present made acknowledgments vanish from the room.
    # Empty tool-call records stay silent via the content checks below.
    content = record.get("content")
    if isinstance(content, str):
        return content if content.strip() else None
    if not isinstance(content, list):
        return None
    # No captured Grok transcript has used blocks; support them only as a
    # defensive compatibility shape, not as an asserted vendor contract.
    texts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    ]
    body = "\n\n".join(text for text in texts if text.strip())
    return body if body.strip() else None


def is_assistant_record(record: object) -> bool:
    return (
        isinstance(record, dict)
        and not is_compaction_record("grok", record)
        and record.get("type") == "assistant"
    )


def fingerprint(line: str) -> bytes:
    return hashlib.sha256(line.encode("utf-8")).digest()


def assistant_records(path: Path) -> list[AssistantRecord] | None:
    """Read committed assistant records without trusting byte offsets."""
    records: list[AssistantRecord] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if is_assistant_record(record):
                    records.append(AssistantRecord(fingerprint(line), assistant_text(record)))
    except OSError:
        return None
    return records


def assistant_scan(path: Path) -> list[bytes] | None:
    """Fingerprint committed assistant records without trusting byte offsets."""
    records = assistant_records(path)
    return None if records is None else [record.fingerprint for record in records]


def assistant_count(path: Path) -> int | None:
    """Count committed assistant records without trusting byte offsets."""
    scanned = assistant_scan(path)
    return None if scanned is None else len(scanned)
