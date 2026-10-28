"""Optional, bounded health checks for named line resources."""

import json
import math
import os
import subprocess

from fastapi import HTTPException

SETTING = 'PARTYLINE_RESOURCE_PROBES'
TIMEOUT = 2
POWER_SETTING = 'PARTYLINE_GPU_MAX_POWER_W'


def probe(name):
    try:
        configured = json.loads(os.environ.get(SETTING, '{}'))
        if not isinstance(configured, dict):
            raise ValueError('expected an object')
        command = configured.get(name, ['nvidia-smi', '-L'] if name == 'gpu' else None)
        if command is not None and (not isinstance(command, list) or not command or not all(
                isinstance(arg, str) and arg for arg in command)):
            raise ValueError('expected a nonempty array of command arguments or null')
    except (ValueError, TypeError) as exc:
        raise HTTPException(503, f'Invalid {SETTING} configuration: {exc}; '
                            'fix the setting and retry') from exc
    if command is not None:
        _run(name, command)
    if name == 'gpu' and POWER_SETTING in os.environ:
        _check_power()


def _run(name, command):
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
    return result.stdout


def _check_power():
    try:
        maximum = float(os.environ[POWER_SETTING])
        if not math.isfinite(maximum) or maximum <= 0:
            raise ValueError('expected a positive finite number')
    except ValueError as exc:
        raise HTTPException(503, f'Invalid {POWER_SETTING} configuration: {exc}; '
                            'fix the setting and retry') from exc
    output = _run('gpu', ['nvidia-smi', '--query-gpu=power.limit',
                          '--format=csv,noheader,nounits'])
    if output is None:  # nvidia-smi is not installed
        return
    try:
        limits = [float(line) for line in output.splitlines()]
        if not limits or any(not math.isfinite(limit) or limit <= 0 for limit in limits):
            raise ValueError('expected positive finite power limits')
    except ValueError as exc:
        raise HTTPException(503, 'GPU power limit probe returned unparseable output; '
                            'check the resource and retry') from exc
    for limit in limits:
        if limit > maximum:
            raise HTTPException(503, f'GPU power limit {limit:g} W exceeds maximum {maximum:g} W; '
                                'a person must lower it (e.g. nvidia-smi -pl) and retry')
