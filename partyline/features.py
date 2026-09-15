"""Feature flags: what this server has switched on, decided once at startup.

A flag is a named boolean with a registered default. The registry is the
whole list — a name that is not here is a typo, and a typo that silently
enabled nothing is how a "disabled" feature stays on. Resolution follows the
same layers as the bind address: environment (``PARTYLINE_FEATURE_<NAME>``)
over the config file's ``[features]`` table over the default. No command-line
option: a flag is a deployment decision written down, not a run's mood.

The first flag is the root captain's heartbeat. The return path and the goal
riders (1.4–1.21) made the tree ring its captain on every event that
matters, and the timer stopped earning its wake-ups; it is deprecated and
off by default, kept whole behind this flag in case a fleet shows a gap the
return path does not cover.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from fastapi import HTTPException

logger = logging.getLogger(__name__)

ENV_PREFIX = "PARTYLINE_FEATURE_"
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class Flag:
    name: str
    default: bool
    status: str      # "stable" | "experimental" | "deprecated"
    summary: str


REGISTRY: dict[str, Flag] = {
    flag.name: flag for flag in (
        Flag("heartbeat", default=False, status="deprecated",
             summary="the root captain's self-timer (POST /api/heartbeat); superseded by "
                     "the return path and goal riders, off since 1.23.0"),
    )
}


@dataclass(frozen=True)
class Features:
    enabled: frozenset[str]

    def on(self, name: str) -> bool:
        if name not in REGISTRY:
            raise KeyError(f"unknown feature flag {name!r}")
        return name in self.enabled

    def describe(self) -> list[dict]:
        return [{"name": flag.name, "enabled": flag.name in self.enabled,
                 "default": flag.default, "status": flag.status, "summary": flag.summary}
                for flag in REGISTRY.values()]


def _as_bool(value: object, source: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in _TRUE | _FALSE:
        return value.strip().lower() in _TRUE
    raise ValueError(f"{source} must be true or false, not {value!r}")


def resolve(env: Mapping[str, str], config_dict: Mapping[str, object]) -> Features:
    """Environment over ``[features]`` over the registered default; unknown names refused."""
    table = config_dict.get("features", {})
    if not isinstance(table, Mapping):
        raise ValueError("[features] configuration must be a table")
    unknown = sorted(set(table) - set(REGISTRY))
    if unknown:
        raise ValueError(f"[features] names no such flag: {', '.join(unknown)}; "
                         f"known flags: {', '.join(sorted(REGISTRY))}")
    states = {name: flag.default for name, flag in REGISTRY.items()}
    for name, value in table.items():
        states[name] = _as_bool(value, f"[features] {name}")
    for key, value in env.items():
        if not key.startswith(ENV_PREFIX):
            continue
        name = key[len(ENV_PREFIX):].lower()
        if name not in REGISTRY:
            raise ValueError(f"{key} names no such flag; known flags: {', '.join(sorted(REGISTRY))}")
        states[name] = _as_bool(value, key)
    return Features(frozenset(name for name, on in states.items() if on))


# The environment alone until main() has read the config file; routers bind at
# import, so anything they gate consults `current()` per request, not at import.
_current: Features = resolve(os.environ, {})


def install(features: Features) -> None:
    global _current
    _current = features
    on = sorted(features.enabled)
    logger.info("feature flags on: %s", ", ".join(on) if on else "none")


def current() -> Features:
    return _current


def enabled(name: str) -> bool:
    return _current.on(name)


def require(name: str) -> None:
    """Gate a route on a flag: a 404 that says how to switch it on."""
    if not enabled(name):
        raise HTTPException(
            404, f"feature '{name}' is off on this server; enable it with [features] "
                 f"{name} = true in the config file or {ENV_PREFIX}{name.upper()}=1")


@contextlib.contextmanager
def overridden(**flags: bool) -> Iterator[Features]:
    """Tests switch flags for one block; the process-wide state comes back after."""
    global _current
    before = _current
    states = set(before.enabled)
    for name, on in flags.items():
        if name not in REGISTRY:
            raise KeyError(f"unknown feature flag {name!r}")
        (states.add if on else states.discard)(name)
    _current = Features(frozenset(states))
    try:
        yield _current
    finally:
        _current = before
