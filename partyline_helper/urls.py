"""Strict parser for partyline:// links; a web page can trigger them, so nothing is trusted."""
import re
import socket
from urllib.parse import parse_qs, urlsplit

from .config import server_url

CODE = re.compile(r"[0-9A-Fa-f]{8}")
PARAMS = {"pair": {"server", "code", "name"}, "run": set()}
MAX_LINK = 2048


class LinkError(ValueError):
    pass


def clean_name(value):
    """Printable text only: the device name is shown in dialogs and stored by the server."""
    text = "".join(char if char.isprintable() else " " for char in value).strip()
    if not text or len(text) > 120:
        raise LinkError("Link has an invalid computer name")
    return text


def parse_link(url):
    """Return (action, params); raise LinkError for anything that is not exactly a pair/run link."""
    if not isinstance(url, str) or len(url) > MAX_LINK or not url.isascii() or not url.isprintable():
        raise LinkError("Not a Partyline link")
    try:
        parts = urlsplit(url)
        action = (parts.hostname or "").lower()
    except ValueError:
        raise LinkError("Not a Partyline link") from None
    if (parts.scheme.lower() != "partyline" or parts.username or parts.password or parts.fragment
            or parts.path not in ("", "/")):
        raise LinkError("Not a Partyline link")
    if action not in PARAMS:
        raise LinkError("Unknown Partyline link action")
    query = parse_qs(parts.query, keep_blank_values=True, max_num_fields=8)
    if set(query) - PARAMS[action] or any(len(values) != 1 for values in query.values()):
        raise LinkError("Link has unexpected or repeated parameters")
    if action == "run":
        return action, {}
    code = query.get("code", [""])[0]
    if not CODE.fullmatch(code):
        raise LinkError("Link has an invalid pairing code")
    origin = query.get("server", [""])[0]
    if not re.match(r"https?://", origin, re.IGNORECASE):
        raise LinkError("Link server must start with http:// or https://")
    try:
        server = server_url(origin)
    except (ValueError, socket.gaierror, UnicodeError) as exc:
        raise LinkError(f"Link has an invalid server: {exc}") from None
    params = {"server": server, "code": code.upper()}
    if "name" in query:
        params["name"] = clean_name(query["name"][0])
    return action, params
