"""Installer coordinates shared by the server and the independently frozen helper."""
import re

from . import __version__

RELEASES_URL = "https://github.com/High-AiQ/partyline/releases"
PLAIN = re.compile(r"[0-9]{1,9}(\.[0-9]{1,9}){0,2}")


def parse(value):
    if not isinstance(value, str) or not PLAIN.fullmatch(value.strip()):
        return None
    parts = [int(part) for part in value.strip().split(".")]
    return (*parts, *([0] * (3 - len(parts))))


def installer_info(version=None):
    version = version or __version__
    filename = f"PartylineHelper-Setup-{version}.exe"
    return {"version": version, "filename": filename, "releases_url": RELEASES_URL,
            "url": f"{RELEASES_URL}/download/helper-v{version}/{filename}"}
