"""Resolve and audit local file input paths without copying their contents."""
import json
import os
import stat
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from .cdp_transport import CDPError
from .config import config_path
from .cdp_files import NoRedirect


def prepare(paths, media, limits):
    root = config_path().parent.resolve()
    result = []
    total = sum(item['bytes'] for item in media)
    for value in paths:
        try:
            path = Path(value)
            if not path.is_absolute():
                raise CDPError('local file paths must be absolute')
            path = path.resolve(strict=True)
            if path.is_relative_to(root):
                raise CDPError('files in the helper data and config directory are not allowed')
            if not stat.S_ISREG(path.stat().st_mode):
                raise CDPError('local path must name a regular file')
            flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
            with os.fdopen(os.open(path, flags), 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise CDPError('local path must name a regular file')
                stream.read(1)
        except CDPError:
            raise
        except OSError as exc:  # name the OS reason (such as an unreachable network path), never the path
            reason = exc.strerror or type(exc).__name__
            raise CDPError(f'local file is missing, unreadable, or not a regular file: {reason}') from exc
        except (ValueError, RuntimeError) as exc:
            raise CDPError('local file is missing, unreadable, or not a regular file') from exc
        size = info.st_size
        if size > limits['file']:
            raise CDPError('local file exceeds the media per-file limit')
        total += size
        if total > limits['total']:
            raise CDPError('files exceed the 200 MiB per-call limit')
        result.append({'path': str(path), 'bytes': size})
    return result, total


def audit_remote(session, page, ticket, files):
    page.guard()
    request = Request(session.file_server + f'/api/screen/file-input/{ticket}/audit',
                      data=json.dumps({'paths': files}).encode(), method='POST',
                      headers={'Authorization': 'Bearer ' + session.file_token,
                               'Content-Type': 'application/json'})
    try:
        with build_opener(ProxyHandler({}), NoRedirect).open(request, timeout=30) as response:
            if response.status != 200:
                raise CDPError('server could not record local file audit')
    except OSError as exc:
        raise CDPError('server could not record local file audit') from exc
    page.guard()
