"""Named speech-recognition presets: the first is the default.

Configured as ``[[asr]]`` tables in the server config file; with none, one
local faster-whisper preset is built from the ``PARTYLINE_TRANSCRIBE_*``
variables. Like process presets, a preset is a name plus a kind and its
settings; secrets are only ever named (``api_key_env``), never stored.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .asr_backends import Command, OpenAICompatible
from .transcriber import DEFAULT_MAX_BYTES, TranscribeSettings, Transcriber

KINDS = ("faster-whisper", "openai-compatible", "command")


def _text(entry: Mapping[str, Any], key: str, required: bool = False) -> str | None:
    value = entry.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"[[asr]] {entry.get('name', '?')!r}: {key} must be a non-empty string")
    return value.strip()


def _build(entry: Mapping[str, Any], env: Mapping[str, str]):
    kind = entry.get("kind")
    if kind == "faster-whisper":
        base = TranscribeSettings.from_env(dict(env))
        return Transcriber(TranscribeSettings(
            model=_text(entry, "model") or base.model,
            device=(_text(entry, "device") or base.device).lower(),
            compute_type=_text(entry, "compute_type"),
            model_dir=_text(entry, "model_dir") or base.model_dir,
            idle_seconds=base.idle_seconds, max_bytes=base.max_bytes))
    timeout = entry.get("timeout")
    bad = isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0
    if timeout is not None and bad:
        raise ValueError(f"[[asr]] {entry.get('name', '?')!r}: timeout must be a positive number")
    extra = {} if timeout is None else {"timeout": float(timeout)}
    if kind == "openai-compatible":
        return OpenAICompatible(_text(entry, "base_url", True), _text(entry, "model", True),
                                _text(entry, "api_key_env"), **extra)
    if kind == "command":
        argv = entry.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
            raise ValueError(f"[[asr]] {entry.get('name', '?')!r}: argv must be a non-empty list of strings")
        return Command(argv, **extra)
    raise ValueError(f"[[asr]] {entry.get('name', '?')!r}: kind must be one of {', '.join(KINDS)}")


class AsrRegistry:
    def __init__(self, entries: list[tuple[str, Any]], max_bytes: int = DEFAULT_MAX_BYTES):
        self.entries = dict(entries)
        self.default = entries[0][0]
        self.max_bytes = max_bytes

    def get(self, name: str | None):
        """The preset's backend; ``KeyError`` for a name that is not configured."""
        return self.entries[name or self.default]

    def listing(self) -> dict[str, Any]:
        return {"default": self.default, "presets": [
            {"name": name, "kind": backend.kind, **backend.status()}
            for name, backend in self.entries.items()]}

    def release(self) -> None:
        for backend in self.entries.values():
            getattr(backend, "unload_if_idle", lambda: None)()


def build_registry(config: Mapping[str, Any], env: Mapping[str, str]) -> AsrRegistry:
    tables = config.get("asr", [])
    if not isinstance(tables, list):
        raise ValueError("[[asr]] configuration must be an array of tables")
    base = TranscribeSettings.from_env(dict(env))
    max_bytes = base.max_bytes
    if not tables:
        return AsrRegistry([("faster-whisper", Transcriber(base))], max_bytes)
    entries: list[tuple[str, Any]] = []
    for entry in tables:
        if not isinstance(entry, dict):
            raise ValueError("[[asr]] entries must be tables")
        name = _text(entry, "name", True)
        if any(name == existing for existing, _ in entries):
            raise ValueError(f"[[asr]] name {name!r} is used twice")
        entries.append((name, _build(entry, env)))
    return AsrRegistry(entries, max_bytes)


_installed: AsrRegistry | None = None


def install(config: Mapping[str, Any], env: Mapping[str, str] | None = None) -> None:
    global _installed
    _installed = build_registry(config, os.environ if env is None else env)


def shared_registry() -> AsrRegistry:
    global _installed
    if _installed is None:
        _installed = build_registry({}, os.environ)
    return _installed
