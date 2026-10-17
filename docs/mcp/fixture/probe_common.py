"""Runtime setup shared by host-specific CLI probes; paths need local adaptation."""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def probe_attachment():
    """Find this process's connection by token without displaying the token."""
    from partyline.agent_connection import connection_directory

    token = os.environ.get("PARTYLINE_TOKEN", "")
    if not token:
        raise RuntimeError("Partyline attachment token is unavailable")
    db_path = os.path.expanduser(os.environ.get("PARTYLINE_DB", "~/.partyline.db"))
    found = []
    for path in connection_directory(db_path).glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if hmac.compare_digest(str(data.get("token", "")), token):
            found.append((path, data))
    if len(found) != 1:
        raise RuntimeError("Partyline connection lookup was not unique")
    connection_path, data = found[0]
    attachment = {
        "id": data["attachment_id"], "name": data["handle"],
        "_agent_connection_file": str(connection_path),
    }
    from partyline.mcp_attach import write_config

    scratch = os.environ.get("PARTYLINE_PROBE_SCRATCH")
    if scratch:
        scratch_dir = Path(scratch).expanduser()
        scratch_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        config_db = str(scratch_dir / "partyline-mcp-probe")
        connection_directory(config_db).mkdir(mode=0o700, exist_ok=True)
    else:
        config_db = db_path
    attachment["mcp_config"] = str(write_config(config_db, attachment))
    return attachment


def codex_command(attachment, forwarded):
    """Build the Codex preset argv and apply the branch adapter hook once."""
    from partyline.adapters.bundled.codex.adapter import PartylineAdapter

    adapter = PartylineAdapter.__new__(PartylineAdapter)
    adapter.att = attachment
    bypass = "--dangerously-bypass-approvals-and-sandbox"
    forwarded = [argument for argument in forwarded if argument != bypass]
    command = ["codex", "--model", "gpt-6-luna", "--config",
               'model_reasoning_effort="high"', bypass, *forwarded]
    return adapter.mcp_argv(command)
