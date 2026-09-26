"""Keep the package entrypoint separate from the importable implementation."""

from partyline.adapters.bundled.opencode.v2 import PartylineAdapter

__all__ = ["PartylineAdapter"]
