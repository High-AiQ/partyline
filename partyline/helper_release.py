"""Is a connected screen helper older than this server? Where is the matching Windows installer?

The checkout ships the current helper version. Unknown versions are not flagged."""
import re

from partyline_helper import __version__

RELEASES_URL = "https://github.com/High-AiQ/partyline/releases"

PLAIN = re.compile(r"[0-9]{1,9}(\.[0-9]{1,9}){0,2}")  # bounded: a hostile version cannot overflow int()


def parse(value) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or not PLAIN.fullmatch(value.strip()):
        return None
    parts = [int(part) for part in value.strip().split(".")]
    return (*parts, *([0] * (3 - len(parts))))


def update_available(helper_version, server_version=None) -> bool:
    helper, server = parse(helper_version), parse(server_version or __version__)
    return helper is not None and server is not None and (helper[0] >= 2 or helper < server)


def installer_info(version: str | None = None) -> dict:
    """The one place that names the Windows installer: its file, its release tag and its exact download URL.

    The workflow names the file PartylineHelper-Setup-<version>.exe and attaches it to release
    helper-v<version>."""
    version = version or __version__
    filename = f"PartylineHelper-Setup-{version}.exe"
    return {"version": version, "filename": filename, "releases_url": RELEASES_URL,
            "url": f"{RELEASES_URL}/download/helper-v{version}/{filename}"}
