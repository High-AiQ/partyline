"""Is a connected screen helper older than this server?

Both ship from the same release, so the server's own version is the newest helper there is. A helper that
cannot say what it is (`unknown`) is never flagged."""
import re

from . import __version__

PLAIN = re.compile(r"[0-9]{1,9}(\.[0-9]{1,9}){0,2}")  # bounded: a hostile version cannot overflow int()


def parse(value) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or not PLAIN.fullmatch(value.strip()):
        return None
    parts = [int(part) for part in value.strip().split(".")]
    return (*parts, *([0] * (3 - len(parts))))


def update_available(helper_version, server_version=None) -> bool:
    helper, server = parse(helper_version), parse(server_version or __version__)
    return helper is not None and server is not None and helper < server
