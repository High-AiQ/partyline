"""Bounded cleanup on update events; retain the running and rollback binaries, never follow links."""
import contextlib
import shutil
from pathlib import Path

from .config import config_path
from .update_release import parse


def installer(path):
    if path is None:
        return
    root = config_path().parent / "updates"
    path = Path(path)
    if (root.is_symlink() or path.parent.is_symlink() or path.parent == root
            or not path.parent.resolve().is_relative_to(root.resolve())):
        return
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def host_version():
    from .native_host import discover, running_pid
    if running_pid() is None:
        return None
    endpoint = discover()
    return endpoint.get("version", "unknown") if endpoint else "unknown"


def versions(previous, current, active=host_version):
    if len(previous) != 1:
        return  # Python/source launchers have no installer-owned versions directory.
    old = Path(previous[0]).parent
    root = old.parent
    if root.name != "versions" or not parse(old.name) or not parse(current):
        return
    host = active()
    if host is not None and not parse(host):
        return  # Do not partially remove a folder while an older, unidentifiable native host still uses it.
    with contextlib.suppress(OSError):
        for folder in root.iterdir():
            if (folder.name not in (old.name, current, host) and parse(folder.name)
                    and parse(folder.name) < parse(current) and folder.is_dir() and not folder.is_symlink()):
                with contextlib.suppress(OSError):
                    # Windows retains a folder whose native host still holds files open.
                    shutil.rmtree(folder)
