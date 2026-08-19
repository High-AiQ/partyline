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
