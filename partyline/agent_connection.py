"""Private, per-attachment API coordinates for tools that filter their environment."""

import json
import os
from pathlib import Path
import shlex
import stat
import sys
import subprocess
import tempfile

from .adapters.briefing import child_env


def connection_directory(db_path: str) -> Path:
    return Path(str(db_path) + ".agent-connections")


def provision_connection(db_path: str, att: dict) -> None:
    """Publish atomically; never include a credential in a prompt or command."""
    if not att.get("api_token"):
        raise ValueError("attachment has no machine credential")
    directory = connection_directory(db_path)
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if os.name == 'nt':
        from .windows_private import secure_directory
        secure_directory(directory)
    elif not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("unsafe agent connection directory")
    if os.name != 'nt' and stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("agent connection directory must have mode 0700")
    coordinates = child_env({}, att)
    payload = {"api": coordinates["PARTYLINE_API"], "token": att["api_token"],
               "conversation_id": att["conv_id"], "attachment_id": att["id"],
               "handle": att["name"]}
    # Attachment IDs originate in the server, but reject path traversal at this boundary.
    ident = str(att["id"])
    if not ident or Path(ident).name != ident or ident in (".", ".."):
        raise ValueError("invalid attachment ID")
    target = directory / (ident + ".json")
    fd, scratch = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(payload, stream)
        if os.name == 'nt':
            secure_directory(scratch, directory=False)
        os.replace(scratch, target)
    finally:
        if os.path.exists(scratch):
            os.unlink(scratch)
    client = Path(__file__).with_name("agent_client.py")
    att['_agent_connection_file'] = str(target)
    quote = subprocess.list2cmdline if os.name == 'nt' else shlex.join
    att["agent_command"] = quote([sys.executable, str(client), "--connection", str(target)])


def remove_connection(db_path: str, att_id: str) -> None:
    if Path(att_id).name != att_id or att_id in (".", ".."):
        raise ValueError("invalid attachment ID")
    (connection_directory(db_path) / (att_id + ".json")).unlink(missing_ok=True)


def connection_hint(att: dict) -> str:
    """Resumed contexts did not receive a new joining briefing."""
    return ("Partyline API helper (works without inherited environment): `"
            + att["agent_command"] + "`; use `context` or `request METHOD /api/... --json-file PATH`.")


def bind_connection_hint(att: dict) -> None:
    """Deliver resumed connection instructions once, alongside the existing rider."""
    original = att["digest_rider"]
    pending = True

    def rider() -> str:
        nonlocal pending
        text = original()
        if pending:
            pending = False
            return "\n".join(part for part in (text, connection_hint(att)) if part)
        return text

    att["digest_rider"] = rider
