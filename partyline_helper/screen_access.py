"""The paired helper's authoritative, restart-persistent window permission."""
import json

from .config import config_path, save_config


def enabled(path=None):
    try:
        return json.loads((path or config_path()).read_text(encoding="utf-8")).get(
            "window_access_enabled") is True
    except (OSError, ValueError, AttributeError):
        return False


def set_enabled(value, path=None):
    path = path or config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data["window_access_enabled"] = bool(value)
    save_config(data, path)
    return bool(value)
