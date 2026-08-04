"""Adapter for the Hermes interactive terminal application."""

from partyline.adapters.bundled.raw.adapter import RawAdapter


class PartylineAdapter(RawAdapter):
    kind = "hermes"

    def build_command(self) -> list[str]:
        return list(self.att["command"]) or list(self.att["adapter_metadata"]["command"])
