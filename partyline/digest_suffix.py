"""The lines a delivery appends to the messages, sent when they changed, not every time.

``(cwd git: ...)``, the ``(reminder: ...)`` footer and the ``(captain pack: ...)`` pointer
used to ride every delivered digest: a few hundred characters per wake, for the life of a
process that already holds them. A line now rides when it is new or different, when the
digest that last carried it was never proven delivered, and every ``EVERY``-th delivery
so a long session is still reminded.
"""

from __future__ import annotations

EVERY = 8


class SuffixGate:
    def __init__(self, every: int = EVERY):
        self.every = every
        self.deliveries = 0
        self.through = 0
        self.credited = 0
        self.last: dict[str, tuple[str, int, int]] = {}  # key -> text, delivery number, carrier's top id

    def begin(self, messages: list[dict], credited: int) -> None:
        """One delivery is starting: its top message id, and how far the host has proof of."""
        self.deliveries += 1
        self.through = max((int(m.get("id") or 0) for m in messages), default=0)
        self.credited = credited

    def keep(self, key: str, text: str) -> str:
        """``text`` if this delivery should carry it, else nothing."""
        if not text:
            return ""
        seen = self.last.get(key)
        due = (seen is None or seen[0] != text or self.deliveries - seen[1] >= self.every
               or seen[2] == 0 or seen[2] > self.credited)  # carrier unproven, or unnumbered
        if due:
            self.last[key] = (text, self.deliveries, self.through)
            return text
        return ""


def begin_gate(att: dict, messages: list[dict]):
    """The attachment's gate, started for this delivery; None when it has none (always send)."""
    gate = att.get("suffix_gate")
    if gate is not None:
        gate.begin(messages, att["credited_through"]())
    return gate
