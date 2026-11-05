"""Conservative Linux cwd/fd inventory for temporary-directory lifetime."""
import os
import sys
from pathlib import Path


def under(value, root):
    value = value.removesuffix(' (deleted)')
    root = os.path.realpath(root)
    return value == root or value.startswith(root + os.sep)


def references(pid, root):
    """Return cwd, matching paths, and whether inspection was complete."""
    cwd, paths, certain = '?', set(), True
    try:
        cwd = os.readlink(f'/proc/{pid}/cwd')
        if under(cwd, root):
            paths.add(cwd)
        for fd in Path(f'/proc/{pid}/fd').iterdir():
            try:
                value = os.readlink(fd)
                if under(value, root):
                    paths.add(value)
            except FileNotFoundError:
                continue  # fd closed during the scan
    except FileNotFoundError:
        # Zombies have neither a cwd nor live file descriptors.
        try:
            stat = Path(f'/proc/{pid}/stat').read_text()
            certain = stat.rsplit(')', 1)[1].split()[0] == 'Z'
        except FileNotFoundError:
            pass  # process exited
        except OSError:
            certain = False
    except OSError:
        certain = False
    return cwd, sorted(paths), certain


def in_use(root, owned=()):
    """Readable holders protect any directory; denial protects only owned processes."""
    if not sys.platform.startswith('linux'):
        return True
    try:
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                if entry.stat().st_uid != os.getuid():
                    continue
            except FileNotFoundError:
                continue
            pid = int(entry.name)
            _, paths, certain = references(pid, root)
            if paths or (not certain and pid in owned):
                return True
    except OSError:
        return True
    return False
