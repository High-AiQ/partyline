"""Resume-hatch markers for speech relayed out of transcript order."""

from __future__ import annotations

from collections import Counter

from partyline.transcript_delivery import TranscriptDeliveryRecord

from .transcript import AssistantRecord

MAX_RESUME_BACKLOG = 10
MIN_RATIO_TRANSCRIPT = 20
MAX_RESUME_RATIO = 0.25


def unsafe_resume_backlog(backlog: int, transcript_records: int) -> bool:
    """Whether a hatch flush is too large to trust as an aligned history tail."""
    return backlog > MAX_RESUME_BACKLOG or (
        transcript_records >= MIN_RATIO_TRANSCRIPT
        and backlog / transcript_records > MAX_RESUME_RATIO
    )


def match_marked_records(
    records: list[AssistantRecord],
    already: set[int],
    deliveries: list[TranscriptDeliveryRecord],
    legacy_bodies: list[str],
) -> set[int]:
    """Locate hatch-relayed records without affecting the live transcript tail.

    Raw-line fingerprints identify exact records first. Grok may compact and
    re-serialize a retained record, so markers with no remaining fingerprint
    match fall back to occurrence-aware bodies. That fallback cannot tell a
    re-serialized record from identical hatch history; its scope must remain
    this resume snapshot and must never become general speech deduplication.
    """
    matched: set[int] = set()
    fingerprint_counts = Counter(item.fingerprint for item in deliveries)
    for index, record in enumerate(records, start=1):
        if record.body is None or not fingerprint_counts[record.fingerprint]:
            continue
        fingerprint_counts[record.fingerprint] -= 1
        if index not in already:
            matched.add(index)

    unmatched_bodies: list[str] = []
    remaining = fingerprint_counts.copy()
    for item in deliveries:
        if remaining[item.fingerprint]:
            unmatched_bodies.append(item.body)
            remaining[item.fingerprint] -= 1

    body_counts = Counter([*legacy_bodies, *unmatched_bodies])
    for index, record in enumerate(records, start=1):
        if index in already or index in matched or record.body is None:
            continue
        if body_counts[record.body]:
            matched.add(index)
            body_counts[record.body] -= 1
    return matched
