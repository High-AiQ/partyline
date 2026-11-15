"""A one-off tray notice after the helper has been replaced by a newer version."""
import json

from .config import config_path, save_config
from .version import helper_version


def path():
    return config_path().parent / "announced-version.json"


def parse(value):
    try:
        parts = tuple(int(part) for part in value.split("."))
        return parts if parts and len(parts) <= 4 else None
    except (AttributeError, ValueError):
        return None


def announced():
    try:
        value = json.loads(path().read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return value if parse(value) else None


def announce_update(status, version=None):
    """Notify once when the running version is newer than the last one this helper recorded.

    A missing record is a first install (or the first run of a helper that predates this notice): it
    is seeded silently. A restart at the same version, or an older one, never notifies.
    """
    version = version or helper_version()
    previous = announced()
    if previous != version:
        save_config({"version": version}, path())
    if previous and parse(version) and parse(previous) < parse(version):
        status.attention(f"Partyline Helper updated to {version}")
        return True
    return False
