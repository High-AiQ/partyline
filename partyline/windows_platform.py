"""Native Windows runtime requirements without importing Windows APIs on Unix."""

import importlib.util
import sys


def available():
    version = getattr(sys, 'getwindowsversion', lambda: None)()
    if version is None or version.major < 10 or version.build < 17763:
        return False, 'Partyline requires Windows 10 build 17763 or newer for ConPTY'
    if importlib.util.find_spec('win32security') is None:
        return False, 'Windows permission support is missing; run uv sync --locked'
    return True, ''
