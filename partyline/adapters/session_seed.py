"""Seed private CLI state without requiring Windows symlink privileges."""

import os
import shutil
import sys
import tempfile


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


def seed_private_file(source, target):
    """Copy a shared config into the attachment home, replacing old links."""
    if not os.path.isfile(source):
        if os.path.islink(target):
            os.unlink(target)
        return
    if os.path.lexists(target) and not os.path.islink(target):
        os.chmod(target, 0o600)
        return
    directory = os.path.dirname(target)
    fd, scratch = tempfile.mkstemp(prefix=".partyline-config-", dir=directory)
    os.close(fd)
    try:
        shutil.copy2(source, scratch)
        os.chmod(scratch, 0o600)
        os.replace(scratch, target)
    finally:
        if os.path.exists(scratch):
            os.unlink(scratch)


def seed_claude_home():
    """Seed and return Claude Code's private config dir on Windows; '' elsewhere."""
    if sys.platform != 'win32':
        return ""
    home = os.path.expanduser(os.environ.get('CLAUDE_CONFIG_DIR', '~/.claude'))
    os.makedirs(home, exist_ok=True)
    seed(os.path.expanduser('~/.claude.json'), os.path.join(home, '.claude.json'))
    return home
