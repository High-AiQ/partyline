"""Command line and working directory of a live job, with the reason when either is unknown.

``/proc`` answers on Linux. macOS has no ``/proc``, so ``ps`` and ``lsof`` answer there; Windows
exposes a command line through CIM and no working directory at all. A field that cannot be read
is reported as unknown **with the reason**, never as a bare ``?``."""
import os
import subprocess
import sys

from .top_processes import argv

COMMAND_CHARS = 200
TIMEOUT_SECONDS = 3


def _run(command):
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _clip(text):
    text = text.strip()
    return text if len(text) <= COMMAND_CHARS else text[:COMMAND_CHARS - 1] + '…'


def _linux(pid):
    parts = argv(pid)
    try:
        cwd = os.readlink(f'/proc/{pid}/cwd')
    except OSError:
        cwd = None
    return (_clip(' '.join(parts)) if parts else None, cwd,
            'the process exited or /proc/<pid> is not readable by the server')


def _windows(pid):
    out = _run(['powershell', '-NoProfile', '-Command',
                f'(Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}").CommandLine'])
    return (_clip(out) if out and out.strip() else None, None,
            'Windows does not expose a working directory, or the process exited')


def _posix(pid):
    out = _run(['ps', '-p', str(int(pid)), '-o', 'args='])
    command = _clip(out) if out and out.strip() else None
    cwd = None
    listing = _run(['lsof', '-a', '-p', str(int(pid)), '-d', 'cwd', '-Fn'])
    for line in (listing or '').splitlines():
        if line.startswith('n') and len(line) > 1:
            cwd = line[1:]
    return command, cwd, 'the process exited, or ps/lsof is unavailable or not permitted'


def describe(pid):
    """Return ``(command, cwd, why_unknown)``: ``why_unknown`` is '' when both were read."""
    reader = (_linux if sys.platform.startswith('linux') else
              _windows if sys.platform.startswith('win') else _posix)
    command, cwd, reason = reader(pid)
    return command, cwd, '' if command and cwd else reason
