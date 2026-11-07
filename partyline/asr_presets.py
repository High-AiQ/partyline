"""Named speech-recognition presets: config-file ``[[asr]]`` tables merged with database rows.

Config-file presets load at startup and are read-only; with none, one local
faster-whisper preset is built from the ``PARTYLINE_TRANSCRIBE_*`` variables.
Database presets are edited in settings and applied live by rebuilding the
shared registry. A database preset with the same name as a config-file one
wins. Order: database presets in their stored order, then the remaining
config-file presets in file order. The default is the flagged database preset,
else the first config-file preset, else the first preset. Secrets are only
ever named (``api_key_env``), never stored.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .asr_backends import Command, OpenAICompatible
from .transcriber import DEFAULT_MAX_BYTES, TranscribeSettings, Transcriber

logger = logging.getLogger(__name__)
KINDS = ("faster-whisper", "openai-compatible", "command")
FIELDS = {
    "faster-whisper": ("model", "device", "compute_type", "model_dir"),
    "openai-compatible": ("base_url", "model", "api_key_env", "timeout", "response_format", "language",
                          "prompt"),
    "command": ("argv", "timeout"),
}
RESPONSE_FORMATS = ("verbose_json", "json")
# An environment variable NAME. Upper case only, so a pasted key (sk-…, gsk_…) never fits.
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
BUILTIN = "faster-whisper"


def _text(entry: Mapping[str, Any], key: str, required: bool = False) -> str | None:
    value = entry.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"[[asr]] {entry.get('name', '?')!r}: {key} must be a non-empty string")
    return value.strip()


def _openai(entry: Mapping[str, Any], extra: dict[str, float]) -> OpenAICompatible:
    label = f"[[asr]] {entry.get('name', '?')!r}"
    base_url = _text(entry, "base_url", True) or ""
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"{label}: base_url must be an http(s) URL")
    if parts.username or parts.password or parts.query:
        raise ValueError(f"{label}: base_url must not carry credentials or a query; name a key variable")
    key_env = _text(entry, "api_key_env")
    if key_env is not None and not ENV_NAME.match(key_env):
        raise ValueError(f"{label}: api_key_env is the NAME of an environment variable (e.g. "
                         "OPENAI_API_KEY), never the key itself")
    response_format = _text(entry, "response_format") or "verbose_json"
    if response_format not in RESPONSE_FORMATS:
        raise ValueError(f"{label}: response_format must be one of {', '.join(RESPONSE_FORMATS)}")
    return OpenAICompatible(base_url, _text(entry, "model", True) or "", key_env, **extra,
                            response_format=response_format, language=_text(entry, "language"),
                            prompt=_text(entry, "prompt"))


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
        return _openai(entry, extra)
    if kind == "command":
        argv = entry.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
            raise ValueError(f"[[asr]] {entry.get('name', '?')!r}: argv must be a non-empty list of strings")
        return Command(argv, **extra)
    raise ValueError(f"[[asr]] {entry.get('name', '?')!r}: kind must be one of {', '.join(KINDS)}")


def spec_of(entry: Mapping[str, Any]) -> dict[str, Any]:
    """The kind plus only that kind's fields that are set: what a preset *is*."""
    kind = entry.get("kind")
    keys = FIELDS.get(kind, ()) if isinstance(kind, str) else ()
    return {"kind": kind, **{key: entry[key] for key in keys if entry.get(key) not in (None, "")}}


class Broken:
    """A stored preset that no longer builds: listed, unavailable, never run."""

    def __init__(self, kind: str, reason: str):
        self.kind = kind
        self._reason = reason

    def status(self) -> dict[str, Any]:
        return {"available": False, "reason": self._reason, "model": None}


@dataclass(frozen=True)
class PresetMeta:
    source: str           # "config" | "builtin" | "database"
    spec: dict[str, Any]
    overrides_config: bool = False
    is_default_flag: bool = False


class AsrRegistry:
    def __init__(self, entries: list[tuple[str, Any]], max_bytes: int = DEFAULT_MAX_BYTES,
                 meta: Mapping[str, PresetMeta] | None = None, default: str | None = None,
                 config_default: str | None = None):
        self.entries = dict(entries)
        self.default = default or entries[0][0]
        self.max_bytes = max_bytes
        self.meta = dict(meta or {})
        # The preset that is default when no database row is flagged.
        self.config_default = config_default or self.default

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


def _config_entries(config: Mapping[str, Any]) -> list[tuple[str, dict[str, Any], str]]:
    tables = config.get("asr", [])
    if not isinstance(tables, list):
        raise ValueError("[[asr]] configuration must be an array of tables")
    if not tables:
        return [(BUILTIN, {"kind": "faster-whisper"}, "builtin")]
    entries: list[tuple[str, dict[str, Any], str]] = []
    for entry in tables:
        if not isinstance(entry, dict):
            raise ValueError("[[asr]] entries must be tables")
        name = _text(entry, "name", True) or ""
        if any(name == existing for existing, _, _ in entries):
            raise ValueError(f"[[asr]] name {name!r} is used twice")
        entries.append((name, entry, "config"))
    return entries


def build_registry(config: Mapping[str, Any], env: Mapping[str, str], rows: Iterable[Mapping[str, Any]] = (),
                   previous: AsrRegistry | None = None) -> AsrRegistry:
    """Merge config-file presets with database ``rows``; reuse unchanged backends from ``previous``."""
    configured = _config_entries(config)
    config_names = {name for name, _, _ in configured}
    stored = sorted(rows, key=lambda row: (row["position"], row["name"]))

    def backend(name: str, entry: Mapping[str, Any], spec: dict[str, Any], strict: bool):
        old = previous.meta.get(name) if previous else None
        if previous and old and old.spec == spec and name in previous.entries:
            return previous.entries[name]
        try:
            return _build({**entry, "name": name}, env)
        except ValueError as exc:
            if strict:
                raise
            logger.warning("speech preset %r no longer builds; listing it as unavailable", name)
            return Broken(str(entry.get("kind")), str(exc))

    entries: list[tuple[str, Any]] = []
    meta: dict[str, PresetMeta] = {}
    flagged = None
    for row in stored:
        spec = spec_of({**row["config"], "kind": row["kind"]})
        entries.append((row["name"], backend(row["name"], spec, spec, strict=False)))
        meta[row["name"]] = PresetMeta("database", spec, row["name"] in config_names, bool(row["is_default"]))
        flagged = row["name"] if row["is_default"] else flagged
    for name, entry, source in configured:
        if name in meta:
            continue
        spec = spec_of(entry)
        entries.append((name, backend(name, entry, spec, strict=True)))
        meta[name] = PresetMeta(source, spec)
    config_default = configured[0][0]
    max_bytes = TranscribeSettings.from_env(dict(env)).max_bytes
    return AsrRegistry(entries, max_bytes, meta, flagged or config_default, config_default)


def validate(name: str, kind: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    """The stored spec for a new or edited database preset; ``ValueError`` explains a refusal."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    spec = spec_of({**fields, "kind": kind})
    _build({**spec, "name": name}, os.environ)
    return spec


_lock = threading.Lock()
_config: Mapping[str, Any] = {}
_env: Mapping[str, str] | None = None
_installed: AsrRegistry | None = None
_merged_db = False


def install(config: Mapping[str, Any], env: Mapping[str, str] | None = None) -> None:
    """Startup: validate and remember the config file's presets; database rows merge on first use."""
    global _installed, _config, _env, _merged_db
    with _lock:
        _config, _env = dict(config), env
        _installed = build_registry(_config, os.environ if env is None else env)
        _merged_db = False


def rebuild(db) -> AsrRegistry:
    """Re-merge the database rows into a fresh registry and swap it in (live; no restart)."""
    global _installed, _merged_db
    from .asr_store import list_presets

    with _lock:
        previous = _installed
        fresh = build_registry(_config, os.environ if _env is None else _env, list_presets(db), previous)
        _installed, _merged_db = fresh, True
    kept = {id(backend) for backend in fresh.entries.values()}
    for backend in (previous.entries.values() if previous else ()):
        if id(backend) not in kept:
            # A take may still be running on it: let the idle timer drop its model.
            getattr(backend, "unload_if_idle", lambda: None)()
    return fresh


def shared_registry(db=None) -> AsrRegistry:
    global _installed
    if db is not None and not _merged_db:
        return rebuild(db)
    with _lock:
        if _installed is None:
            _installed = build_registry(_config, os.environ if _env is None else _env)
        return _installed
