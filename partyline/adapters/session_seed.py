"""Seed private CLI state without requiring Windows symlink privileges."""

import os
import shutil
import sys


def seed(source, target):
    if os.path.lexists(target):
        return
    if sys.platform == 'win32':
        # Normal PowerShell/CMD users need neither elevation nor Developer Mode.
        # Missing optional state is fine; a failed copy of existing auth is not.
        if os.path.isdir(source):
            shutil.copytree(source, target)
        elif os.path.isfile(source):
            shutil.copy2(source, target)
    else:
        try:
            os.symlink(source, target)
        except OSError:
            pass


def seed_claude_home():
    """Seed and return Claude Code's private config dir on Windows; '' elsewhere."""
    if sys.platform != 'win32':
        return ""
    home = os.path.expanduser(os.environ.get('CLAUDE_CONFIG_DIR', '~/.claude'))
    os.makedirs(home, exist_ok=True)
    seed(os.path.expanduser('~/.claude.json'), os.path.join(home, '.claude.json'))
    return home
