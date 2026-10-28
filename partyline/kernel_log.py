"""Bounded, redacted access to the host kernel journal."""

import ipaddress
import re
import subprocess
from typing import Literal

from fastapi import HTTPException, Query, Request

from .auth_guard import request_principal

MARKER = "[REDACTED]"
_SECRETS = re.compile(r'(?i)\b(token|password|secret|key)\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s,;]+)')
_BEARER = re.compile(r'(?i)\bbearer\s+[^\s,;]+')
_JWT = re.compile(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b')
_MAC = re.compile(r'(?i)(?<![\da-f])(?:[\da-f]{2}[:-]){5}[\da-f]{2}(?![\da-f])')
_IP = re.compile(r'(?<![\w:])(?:[0-9a-fA-F:.]*:[0-9a-fA-F:.]+|(?:\d{1,3}\.){3}\d{1,3})(?![\w:])')


def redact(line: str) -> str:
    line = _SECRETS.sub(lambda m: m.group(1) + '=' + MARKER, line)
    line = _BEARER.sub('Bearer ' + MARKER, line)
    line = _JWT.sub(MARKER, line)
    line = _MAC.sub(MARKER, line)

    def address(match):
        try:
            ipaddress.ip_address(match.group())
        except ValueError:
            return match.group()
        return MARKER

    return _IP.sub(address, line)


def read_kernel_log(boot: str, lines: int) -> list[str]:
    command = ['journalctl', '-k', '-b', '-1' if boot == 'previous' else '0',
               '-n', str(lines), '--no-pager', '-o', 'short-iso']
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors='replace',
                                timeout=5, check=False)
    except FileNotFoundError as exc:
        raise HTTPException(503, 'journalctl is missing; install systemd journal utilities') from exc
    except PermissionError as exc:
        raise HTTPException(503, 'journal access denied; add the service user to systemd-journal') from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(503, 'journalctl timed out; check the system journal service') from exc
    except OSError as exc:
        raise HTTPException(503, 'cannot run journalctl; check the service installation') from exc
    if 'insufficient permissions' in result.stderr.lower() or 'permission denied' in result.stderr.lower():
        raise HTTPException(503, 'journal access denied; add the service user to systemd-journal')
    if result.returncode:
        raise HTTPException(503, 'journalctl failed; check journal access and add the service user '
                            'to systemd-journal if permission is denied')
    return [redact(line) for line in result.stdout.splitlines()[-lines:]]


def register_kernel_log_route(app, runtime):
    @app.get('/api/host/kernel-log')
    def kernel_log(request: Request, boot: Literal['previous', 'current'] = 'previous',
                   lines: int = Query(default=100, ge=1, le=300)):
        principal = request_principal(request)
        home = runtime.db.get_conversation(principal.conv_id) if principal.conv_id else None
        if principal.kind != 'user' and not (principal.kind == 'machine' and principal.is_lead
                                             and home and home['parent_id'] is None):
            raise HTTPException(403, 'only people and root captains may read the kernel log')
        return read_kernel_log(boot, lines)
