"""Durable identity for transcript speech relayed outside normal order."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptDeliveryRecord:
    """One out-of-order transcript relay, linked to its durable chat body."""

    fingerprint: bytes
    body: str
