"""Helper-owned opt-in, shared with the native host; setting changes are locally audited."""
import json

from .config import config_path, save_config
from .screen_access_audit import ScreenAccessAudit


def read(path=None):
    try:
        data = json.loads((path or config_path()).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def enabled():
    return read().get("auto_update") is True


def set_enabled(value):
    data = read()
    value = bool(value)
    if data.get("auto_update", False) != value:
        ScreenAccessAudit().append("", "local", "auto_update", "helper", "", str(value))
        data["auto_update"] = value
        save_config(data, config_path())
    return value


def failed_version(version):
    data = read()
    data["failed_update"] = version
    save_config(data, config_path())
