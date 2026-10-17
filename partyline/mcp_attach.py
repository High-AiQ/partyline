"""Attach-time MCP wiring: per-invocation config for the Partyline stdio server.

Each attachment gets one private config file, written beside its connection
file when the attachment is provisioned and removed on detach. Adapters add
that file to the CLI command for this invocation only, so no user, project, or
preset configuration changes. The config names the connection file's path and
never holds the credential itself.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import tomllib
from pathlib import Path

SERVER_NAME = "partyline"
CONFIG_SUFFIX = ".mcp.json"
CONNECTION_ENV = "PARTYLINE_MCP_CONNECTION"
# Codex keys we own under mcp_servers.partyline; a user-set key wins.
CODEX_KEYS = ("command", "args", "env")


def _ident(att_id: str) -> str:
    ident = str(att_id)
    if not ident or Path(ident).name != ident or ident in (".", ".."):
        raise ValueError("invalid attachment ID")
    return ident


def config_path(db_path: str, att_id: str) -> Path:
    from .agent_connection import connection_directory  # lazy: adapters import this module

    return connection_directory(db_path) / (_ident(att_id) + CONFIG_SUFFIX)


def server_entry(connection_file: str) -> dict:
    """The stdio server, imported from the service checkout despite cwd shadows."""
    root = str(Path(__file__).resolve().parent.parent)
    return {
        "command": sys.executable,
        "args": ["-P", "-m", "partyline.mcp"],
        "env": {CONNECTION_ENV: connection_file, "PYTHONPATH": root},
    }


def server_for(att: dict) -> dict | None:
    """The stdio server for this attachment, or None before it is provisioned."""
    connection = att.get("_agent_connection_file")
    return server_entry(connection) if connection else None


def write_config(db_path: str, att: dict) -> Path:
    """Publish the attachment's MCP config atomically, mode 0600.

    Called from provisioning, which runs on both start and resume, so the
    file is regenerated whenever the attachment is spawned again.
    """
    target = config_path(db_path, att["id"])
    payload = {"mcpServers": {SERVER_NAME: server_entry(att["_agent_connection_file"])}}
    fd, scratch = tempfile.mkstemp(dir=target.parent, prefix=".mcp-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(payload, stream)
        os.replace(scratch, target)
    finally:
        if os.path.exists(scratch):
            os.unlink(scratch)
    att["mcp_config"] = str(target)
    return target


def remove_config(db_path: str, att_id: str) -> None:
    config_path(db_path, att_id).unlink(missing_ok=True)


def claude_command(cmd: list[str], att: dict) -> list[str]:
    """Add the Partyline config to a Claude command, keeping the user's own.

    Non-strict on purpose: user MCP servers stay loaded. A user's
    ``--mcp-config`` values keep their order and gain ours at the end of
    their run, so the Partyline entry is added, never substituted.
    """
    config = att.get("mcp_config")
    if not config or config in cmd:
        return cmd
    merged = list(cmd)
    for index, arg in enumerate(merged):
        if arg == "--mcp-config":
            end = index + 1
            while end < len(merged) and not merged[end].startswith("-"):
                end += 1
            merged.insert(end, config)
            return merged
    return [*merged, "--mcp-config", config]


def _codex_user_keys(cmd: list[str], config_file: str | None = None) -> set[str]:
    """Keys the user already set under mcp_servers.partyline via -c/--config."""
    prefix = f"mcp_servers.{SERVER_NAME}."
    keys: set[str] = set()
    values = []
    for index, arg in enumerate(cmd):
        if arg in ("-c", "--config") and index + 1 < len(cmd):
            values.append(cmd[index + 1])
        elif arg.startswith("--config="):
            values.append(arg.split("=", 1)[1])
    for value in values:
        name = value.split("=", 1)[0].strip()
        if name.startswith(prefix):
            keys.add(name[len(prefix):].split(".", 1)[0])
    if config_file:
        keys.update(_codex_config_server(config_file))
    return keys


def codex_overrides(cmd: list[str], att: dict, config_file: str | None = None) -> list[str]:
    """Per-invocation ``-c`` overrides for the Partyline server.

    Existing server keys in the effective config and user ``-c`` arguments
    win per key. An explicit ``enabled = false`` or ``url`` keeps the user's
    server entry intact and disables local injection. Values are rendered
    using TOML syntax because Codex parses each override as an assignment.
    """
    def toml_key(value: str) -> str:
        if value and all(char.isalnum() or char in "_-" for char in value):
            return value
        return json.dumps(value, ensure_ascii=False)

    def toml_value(value) -> str:
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, (int, float)):
            return repr(value)
        if isinstance(value, list):
            return "[" + ", ".join(toml_value(item) for item in value) + "]"
        if isinstance(value, dict):
            pairs = (f"{toml_key(key)} = {toml_value(item)}"
                     for key, item in value.items())
            return "{ " + ", ".join(pairs) + " }"
        raise ValueError("unsupported Codex TOML override value")

    entry = server_for(att)
    if entry is None:
        return []
    user = _codex_user_keys(cmd, config_file)
    if "url" in user or "enabled" in user and _codex_disabled(cmd, config_file):
        return []
    overrides: list[str] = []
    for key in CODEX_KEYS:
        if key in user:
            continue
        overrides += ["-c", f"mcp_servers.{SERVER_NAME}.{key}={toml_value(entry[key])}"]
    return overrides


def _codex_disabled(cmd: list[str], config_file: str | None) -> bool:
    """Whether the user explicitly disabled this server in any config layer."""
    prefix = f"mcp_servers.{SERVER_NAME}.enabled="
    for index, arg in enumerate(cmd):
        value = cmd[index + 1] if arg in ("-c", "--config") and index + 1 < len(cmd) else arg
        if value.startswith(prefix):
            return value[len(prefix):].strip().lower() == "false"
        if value.startswith("--config="):
            value = value.split("=", 1)[1]
            if value.startswith(prefix):
                return value[len(prefix):].strip().lower() == "false"
    if config_file:
        server = _codex_config_server(config_file)
        return isinstance(server, dict) and server.get("enabled") is False
    return False


def _codex_config_server(config_file: str) -> dict:
    try:
        with open(config_file, "rb") as stream:
            servers = tomllib.load(stream).get("mcp_servers", {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    if not isinstance(servers, dict):
        return {}
    server = servers.get(SERVER_NAME, {})
    return server if isinstance(server, dict) else {}


def opencode_config_content(existing: str, server: dict) -> str | None:
    """``OPENCODE_CONFIG_CONTENT`` with the Partyline server merged in.

    Every other key and server passes through unchanged; ``mcp.partyline`` is
    the only entry this sets. Unparseable or unexpectedly shaped input yields
    None, so the caller leaves the user's value alone and adds nothing.
    """
    try:
        config = json.loads(existing) if existing else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(config, dict):
        return None
    mcp = config.setdefault("mcp", {})
    if not isinstance(mcp, dict):
        return None
    mcp[SERVER_NAME] = {
        "type": "local",
        "command": [server["command"], *server["args"]],
        "environment": server["env"],
    }
    return json.dumps(config)
