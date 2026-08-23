"""Vendor-specific structured records that are context summaries, not speech."""

from __future__ import annotations


def is_compaction_record(adapter: str, record: object) -> bool:
    """Recognize only shapes observed in the named CLI's structured transcript."""
    if not isinstance(record, dict):
        return False
    if adapter == "claude":
        return record.get("type") == "system" and record.get("subtype") == "compact_boundary"
    if adapter == "codex":
        return record.get("type") == "compacted"
    if adapter == "grok":
        return record.get("synthetic_reason") == "compaction_meta"
    if adapter == "muse":
        event = (record.get("payload") or {}).get("event") or {}
        return event.get("kind") in {
            "context_compaction_candidate",
            "context_compaction_installed",
        }
    if adapter == "pi":
        return record.get("type") == "compaction"
    return False
