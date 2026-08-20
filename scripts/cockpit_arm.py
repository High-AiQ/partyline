"""Pure helpers for constructing and verifying the cockpit restart trigger."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from partyline.bind import load_bind_config, parse_bind_args, resolve_bind, resolve_instance_name


@dataclass(frozen=True)
class ServerConfigProof:
    path: Path
    host: str
    port: int
    instance_name: str | None


def websocket_url(base_url: str, conversation_id: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, f"/ws/{conversation_id}", "", "", ""))


def parse_systemd_exec_start(value: str) -> list[str] | None:
    """Extract the ordered argv from ``systemctl show -p ExecStart``."""
    marker = "argv[]="
    if marker not in value:
        return None
    encoded = value.partition(marker)[2].partition(" ; ignore_errors=")[0]
    try:
        return shlex.split(encoded)
    except ValueError:
        return None


def resolve_server_config(
    path: Path,
    arguments: Sequence[str],
    environment: Mapping[str, str],
) -> ServerConfigProof:
    """Resolve an explicit config with the replacement process's real inputs."""
    resolved = path.expanduser().resolve()
    parsed = parse_bind_args(arguments)
    config = load_bind_config(parsed.config)
    host, port = resolve_bind(parsed, environment, config)
    name = resolve_instance_name(parsed, environment, config)
    return ServerConfigProof(resolved, host, port, name)


def preflight_server_config(path: Path) -> ServerConfigProof:
    """Resolve the explicit config without any higher-precedence overrides."""
    resolved = path.expanduser().resolve()
    return resolve_server_config(resolved, ["--config", str(resolved)], {})


BIND_FLAGS = ("--host", "--port", "--instance-name")


def _without_bind_flags(arguments: list[str]) -> list[str]:
    """Drop preserved bind/identity flags an explicit config supersedes."""
    kept: list[str] = []
    skip_value = False
    for value in arguments:
        if skip_value:
            skip_value = False
            continue
        if value in BIND_FLAGS:
            skip_value = True
            continue
        if value.startswith(tuple(f"{flag}=" for flag in BIND_FLAGS)):
            continue
        kept.append(value)
    return kept


def with_server_config(arguments: list[str], config: Path) -> list[str]:
    """Rewrite the preserved argv so the explicit config owns the bind.

    An explicit ``--server-config`` is the operator's declared address: the
    outgoing server's ``--host``/``--port``/``--instance-name`` flags are
    dropped, not preserved — a cockpit stuck on loopback could otherwise
    never be moved, because the preserved CLI flags outrank any config. The
    ``effective == expected`` guard downstream still refuses environment
    overrides the config cannot beat.
    """
    rewritten = _without_bind_flags(list(arguments))
    positions = [
        index for index, value in enumerate(rewritten)
        if value == "--config" or value.startswith("--config=")
    ]
    if len(positions) > 1:
        raise ValueError("server command has several --config arguments")
    if not positions:
        return [*rewritten, "--config", str(config)]
    index = positions[0]
    if rewritten[index] == "--config":
        if index + 1 >= len(rewritten) or rewritten[index + 1].startswith("--"):
            raise ValueError("server command has --config without a path")
        rewritten[index + 1] = str(config)
    else:
        rewritten[index] = f"--config={config}"
    return rewritten
