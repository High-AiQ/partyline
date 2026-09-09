"""Which processes a restart plan covers, when that is more than one line.

A plan's ``conversation_id`` is the line that *owns* it: where a manual offer
appears, where a failure report lands, and which tab may accept it. That is
deliberately not the same question as which processes it recovers.

``attachment_ids`` was always an opaque ordered list and every attachment
already records its own ``conv_id``, so a fleet plan needs no schema change —
only the discipline of reading each attachment's line from the attachment
rather than assuming the owner's.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol


class ScopeDb(Protocol):
    """The narrow database edge plan selection needs."""

    def list_conversations(self, archived: bool = False) -> list[dict]: ...

    def list_attachments(self, conv_id: str) -> list[dict]: ...

    def get_attachment(self, att_id: str) -> dict | None: ...


def resumable(
    attachment: Mapping[str, object],
    live: Mapping[str, object],
    can_resume: bool,
) -> bool:
    """Whether one attachment is a candidate for sequential reattachment."""
    return (
        attachment["id"] in live
        and attachment["status"] in ("starting", "running")
        and can_resume
    )


def planned_conversation_ids(
    db: ScopeDb, conversation_id: str, scope: str
) -> list[str]:
    """The lines a plan of this scope covers, owner first and never archived.

    Owner-first ordering is load-bearing: recovery walks the plan in order, so
    the line that asked for the restart gets its processes back first.
    """
    if scope != "all":
        return [conversation_id]
    others = [
        conversation["id"]
        for conversation in db.list_conversations()
        if conversation["id"] != conversation_id
    ]
    return [conversation_id, *others]


def select_attachment_ids(
    db: ScopeDb,
    live: Mapping[str, object],
    resumable_adapter: Callable[[str], bool],
    conversation_ids: Sequence[str],
) -> list[str]:
    """Live, resumable attachment ids across these lines, in line order."""
    selected: list[str] = []
    for conv_id in conversation_ids:
        for attachment in db.list_attachments(conv_id):
            if resumable(attachment, live, resumable_adapter(attachment["adapter"])):
                selected.append(attachment["id"])
    return selected


def covered_conversation_ids(db: ScopeDb, attachment_ids: Sequence[str]) -> list[str]:
    """Every line a plan touches, in first-appearance order.

    Used to address the lines that must hear about a restart they did not
    request. An attachment that has since been deleted contributes nothing;
    recovery reports that separately as a failure.
    """
    covered: list[str] = []
    for attachment_id in attachment_ids:
        attachment = db.get_attachment(attachment_id)
        if attachment is not None and attachment["conv_id"] not in covered:
            covered.append(attachment["conv_id"])
    return covered
