"""Identify CLI service processes using the attachment's effective MCP commands."""
import json
import os
import shutil
import tomllib
from pathlib import Path


def _merge(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value


def commands(adapter):
    att = getattr(adapter, 'att', {})
    args = getattr(adapter, 'spawn_argv', None) or att.get('command', [])
    configs = [att['mcp_config']] if att.get('mcp_config') else []
    overrides = {}
    for index, arg in enumerate(args):
        if arg == '--mcp-config':
            for value in args[index + 1:]:
                if value.startswith('-'):
                    break
                configs.append(value)
        elif arg.startswith('--mcp-config='):
            configs.append(arg.split('=', 1)[1])
        value = (args[index + 1] if arg in ('-c', '--config') and index + 1 < len(args)
                 else arg.removeprefix('--config=') if arg.startswith('--config=') else '')
        if value.startswith('mcp_servers.'):
            try:
                _merge(overrides, tomllib.loads(value).get('mcp_servers', {}))
            except tomllib.TOMLDecodeError:
                pass
    servers = []
    for config in configs:
        try:
            path = Path(config)
            if not path.is_absolute():
                path = Path(att.get('cwd', '.')) / path
            payload = json.loads(config if config.lstrip().startswith('{') else path.read_text())
            servers.extend(payload.get('mcpServers', {}).values())
        except (OSError, ValueError, AttributeError):
            continue
    home = getattr(adapter, '_home', None)
    effective = {}
    if home:
        try:
            effective = tomllib.loads((Path(home) / 'config.toml').read_text()).get('mcp_servers', {})
        except (OSError, ValueError):
            pass
    if isinstance(effective, dict):
        _merge(effective, overrides)
        servers.extend(effective.values())
    return [[entry['command'], *entry.get('args', [])] for entry in servers
            if isinstance(entry, dict) and isinstance(entry.get('command'), str)
            and isinstance(entry.get('args', []), list) and entry.get('enabled') is not False]


def matches(parts, configured):
    if not parts:
        return False
    def executable(value):
        return os.path.realpath(shutil.which(value) or value)
    return any(parts[1:] == command[1:] and executable(parts[0]) == executable(command[0])
               for command in configured)
