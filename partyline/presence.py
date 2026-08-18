"""Who is working right now, told by the server rather than by the process.

A mentioned process is working from the moment it is woken, but nothing it
writes reaches the line until its turn ends. For most of an evening's worst
failures — a lead reassigning work from a process that was mid-build, two
agents writing the same files, findings re-reported long after they closed —
the room could not tell a thinking participant from a dead one.

The receipt is emitted by the server at the two moments it already knows
about: a digest was delivered into a pty, and that attachment's next message
was persisted. **A process can never post its own liveness**, which is the
whole point: a signal the subject can forge is not evidence, and this
codebase has been burned by exactly that before (`docs/lessons.md`).

Nothing here reaches into ``ChatRuntime``: presence wraps the callbacks and
the adapter that the server already builds, so the runtime keeps its shape
and its line count.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from .contracts import WorkingEvent


class Presence:
    """Which attachments are mid-turn, and the broadcasts that say so."""

    def __init__(self, runtime):
        self.runtime = runtime
        # attachment id -> (its line, when the turn started). The line is part
        # of the state because presence is asked per-conversation: a tab open
        # on one line must never light a jack that belongs to another.
        self.working: dict[str, tuple[str, float]] = {}

    def is_working(self, att_id: str) -> bool:
        return att_id in self.working

    def working_ids(self, conv_id: str) -> list[str]:
        """Which attachments are mid-turn *on this line*."""
        return sorted(
            att_id for att_id, (line, _) in self.working.items() if line == conv_id
        )

    async def _announce(self, conv_id: str, att_id: str, working: bool) -> None:
        await self.runtime.broadcast(
            conv_id, WorkingEvent(attachment_id=att_id, working=working)
        )

    async def started(self, conv_id: str, att_id: str) -> None:
        """A wake was delivered into this attachment's terminal."""
        if att_id in self.working:
            return  # already mid-turn; a second delivery is not a new turn
        self.working[att_id] = (conv_id, time.time())
        await self._announce(conv_id, att_id, True)

    async def finished(self, conv_id: str, att_id: str) -> None:
        """The turn produced something, or the process is no longer live."""
        if self.working.pop(att_id, None) is None:
            return  # not working: say nothing rather than announce a non-event
        await self._announce(conv_id, att_id, False)

    def forget(self, att_id: str) -> None:
        """Drop state without broadcasting — for a line that is going away."""
        self.working.pop(att_id, None)

    def watch(self, adapter, conv_id: str, att_id: str):
        """Return the adapter, with its wake delivery reporting presence.

        Wrapping ``deliver`` rather than editing the runtime keeps the report
        exactly where the fact is: the receipt is emitted only once the digest
        has actually been written into the pty, so a delivery that raises
        never claims a turn started.
        """
        deliver = adapter.deliver

        async def delivering(messages):
            await deliver(messages)
            await self.started(conv_id, att_id)

        adapter.deliver = delivering
        return adapter

    def posting(
        self, conv_id: str, att_id: str, post: Callable[..., Awaitable[None]]
    ):
        """Wrap the runtime's post callback so speech ends the turn."""

        async def posted(sender: str, sender_type: str, body: str):
            await post(sender, sender_type, body)
            await self.finished(conv_id, att_id)

        return posted

    def statusing(
        self, conv_id: str, att_id: str, on_status: Callable[[str], Awaitable[None]]
    ):
        """Wrap the status callback so a stopped process stops looking busy.

        A process that dies mid-turn would otherwise pulse forever, which is a
        worse lie than no indicator at all.
        """

        async def status(value: str):
            await on_status(value)
            if value in ("exited", "detached"):
                await self.finished(conv_id, att_id)

        return status
