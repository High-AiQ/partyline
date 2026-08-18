"""Bind-address configuration for the partyline server."""

import argparse
import logging
import os
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8642
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BindConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT


def _bind_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="serve partyline")
    parser.add_argument("--host", help="address to bind")
    parser.add_argument("--port", type=int, help="port to bind")
    parser.add_argument("--config", type=lambda value: Path(value).expanduser(),
                        help="TOML configuration file")
    return parser


def parse_bind_args(argv: Sequence[str]) -> argparse.Namespace:
    return _bind_parser().parse_args(list(argv))


def _valid_host(value: object, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source} host must be a non-empty string")
    host = value.strip()
    if host.startswith("[") or host.endswith("]"):
        if not (host.startswith("[") and host.endswith("]")):
            raise ValueError(f"{source} host must be a valid address")
        host = host[1:-1].strip()
    if not host or "[" in host or "]" in host:
        raise ValueError(f"{source} host must be a valid address")
    return host


def _valid_port(value: object, source: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{source} port must be an integer from 1 to 65535")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source} port must be an integer from 1 to 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{source} port must be an integer from 1 to 65535")
    return port


def resolve_bind(
    argv: Sequence[str] | argparse.Namespace,
    env: Mapping[str, str],
    config_dict: Mapping[str, object],
) -> tuple[str, int]:
    """Resolve bind settings with CLI, environment, config, and default precedence."""
    args = argv if isinstance(argv, argparse.Namespace) else parse_bind_args(argv)
    server = config_dict.get("server", {})
    if not isinstance(server, Mapping):
        raise ValueError("[server] configuration must be a table")

    host = server.get("host", DEFAULT_HOST)
    port = server.get("port", DEFAULT_PORT)
    if "PARTYLINE_HOST" in env:
        host = env["PARTYLINE_HOST"]
    if "PARTYLINE_PORT" in env:
        port = env["PARTYLINE_PORT"]
    if args.host is not None:
        host = args.host
    if args.port is not None:
        port = args.port
    return _valid_host(host, "bind"), _valid_port(port, "bind")


def load_bind_config(path: Path | None = None) -> dict:
    """Load an explicit config or the first existing default config file."""
    explicit = path is not None
    if path is not None:
        if not path.is_file():
            raise RuntimeError(f"config file does not exist: {path}")
        candidates = [path]
    else:
        candidates = [
            Path.cwd() / "partyline.toml",
            Path.home() / ".config" / "partyline" / "config.toml",
        ]
    for config_path in candidates:
        if not config_path.is_file():
            continue
        try:
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise RuntimeError(f"could not read config file {config_path}") from exc
        if "server" not in config and not explicit:
            continue
        logger.info("using bind config %s", config_path)
        return config
    logger.info("no bind config file found")
    return {}


def load_dotenv(path: str = ".env"):
    """Merge a local .env into the environment attached processes inherit.

    Credentials for an attached CLI have to reach it somehow, and the two bad
    answers are baking them into a stored command or exporting them from a shell
    profile. A gitignored .env next to the server is the third option. Variables
    already set in the real environment always win, so an inline
    `KEY=... uv run partyline` still overrides the file.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)
