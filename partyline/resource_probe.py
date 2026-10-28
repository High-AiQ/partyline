"""Optional, bounded health checks for named line resources."""

import json
import os
import subprocess

from fastapi import HTTPException

SETTING = 'PARTYLINE_RESOURCE_PROBES'
TIMEOUT = 2


def probe(name):
    try:
        configured = json.loads(os.environ.get(SETTING, '{}'))
        if not isinstance(configured, dict):
            raise ValueError('expected an object')
        command = configured.get(name, ['nvidia-smi', '-L'] if name == 'gpu' else None)
        if command is None:
            return
        if not isinstance(command, list) or not command or not all(
                isinstance(arg, str) and arg for arg in command):
            raise ValueError('expected a nonempty array of command arguments or null')
    except (ValueError, TypeError) as exc:
        raise HTTPException(503, f'Invalid {SETTING} configuration: {exc}; '
                            'fix the setting and retry') from exc
    try:
        result = subprocess.run(command, capture_output=True, timeout=TIMEOUT, check=False)
    except FileNotFoundError:
        return
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(503, f'Resource {name} probe timed out; check the resource and retry') from exc
    except OSError as exc:
        raise HTTPException(503, f'Resource {name} probe could not run: {exc}; check it and retry') from exc
    if result.returncode or not result.stdout.strip():
        raise HTTPException(503, f'Resource {name} probe failed or returned no output; '
                            f'check the resource and {SETTING}, then retry')
