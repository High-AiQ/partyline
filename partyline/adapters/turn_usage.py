"""Adapter side of model usage telemetry: parse a transcript record, hand it to the runtime.

Only the Claude Code, Codex and OpenCode v2 adapters mix this in. The runtime sets
``att["on_turn_usage"]``; without it (plain test attachments, other adapters) nothing happens,
and a telemetry failure can never reach speech.
"""

import logging

logger = logging.getLogger(__name__)


class TurnUsage:
    """Mixin: ``turn_parser`` is the transcript parser class; ``note_turn_usage`` feeds it."""

    turn_parser = None

    async def note_turn_usage(self, record, parser=None) -> None:
        noted = self.att.get("on_turn_usage")
        if noted is None or self.turn_parser is None:
            return
        try:
            parser = parser or self.__dict__.get("_turn_parser") or self.__dict__.setdefault(
                "_turn_parser", self.turn_parser())
            turn = parser.feed(record)
            # A resumed CLI can show an older session's history; only this process's responses count.
            if turn is not None and turn["timestamp"] >= self.spawned_at - 5:
                await noted(turn)
        except Exception:
            logger.debug("turn usage not recorded", exc_info=True)
