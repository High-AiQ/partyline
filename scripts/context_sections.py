"""The measured sections of ``context_budget``; each returns {label: characters}."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

from partyline.adapters.briefing import format_digest, safe_rider
from partyline.adapters.base import Adapter
from partyline.mcp.server import MCPServer
from partyline.resume_backlog import addressed_backlog
from partyline.role_delivery import bind_role_delivery

ROLES = {"root captain": "cap", "sub-captain": "subcap", "task implementer": "impl-task1",
         "task reviewer": "rev-task1", "participant": "worker"}
FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "notice_hour.json"
DYNAMIC = {"claude", "opencode-v2"}


class _Client:
    def __init__(self, state):
        self.home = state["conv_id"]
        self.connection = {"api": "http://127.0.0.1:8643", "handle": "h", "attachment_id": "a"}
        self._state = state

    def capabilities(self, conv_id=None):
        return self._state


def listed(state) -> list[dict]:
    """The tools/list reply a process is given for ``state``."""
    out = io.StringIO()
    MCPServer(_Client(state), output=out).handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    return json.loads(out.getvalue())["result"]["tools"]


def catalog(world, adapter, per_tool=False) -> dict:
    result = {}
    for role, att_id in ROLES.items():
        state = {**world.state(att_id), "dynamic_screen_tools": adapter in DYNAMIC}
        tools = listed(state)
        sizes = {tool["name"]: len(json.dumps(tool, separators=(",", ":"))) for tool in tools}
        if adapter == "claude":  # tool schemas load on demand there: the standing cost is the names
            sizes = {name: len(name) + 8 for name in sizes}
        result[role] = {"chars": sum(sizes.values()), "count": len(sizes),
                        "per_tool": sizes if per_tool else {}}
    return result


def attachment(world, att_id, adapter) -> dict:
    row = dict(world.db.get_attachment(att_id))
    row.update(adapter=adapter, conv_name=world.db.get_conversation(row["conv_id"])["name"],
               topic="", digest_rider=lambda: "", agent_command="/venv/bin/python /x/agent_client.py "
               "--connection /home/u/.db.agent-connections/c.json", agent_shell="")
    bind_role_delivery(world.db, row, None)
    return row


def briefing_text(row) -> str:
    fake = SimpleNamespace(att=row, _with_claim=lambda text: text)
    return Adapter.briefing(fake)


def startup(world, adapter) -> dict:
    result = {}
    for role, att_id in ROLES.items():
        row = attachment(world, att_id, adapter)
        result[f"{role}: whole briefing"] = len(briefing_text(row))
        result[f"{role}:   its role/captain pack part"] = len(row.get("role_briefing") or "")
    return result


def resume(world, adapter, backlog=30, size=800) -> dict:
    """What is pasted when a process comes back with its own session and a lagging cursor."""
    row = attachment(world, "impl-task1", adapter)
    world.db._exec("UPDATE attachments SET last_seen=0 WHERE id='impl-task1'")
    row["last_seen"] = 0
    for _ in range(backlog):
        world.db.add_message("task1", "fable-api-oc", "agent", f"@{row['name']} " + "update " * (size // 7))
    runtime = SimpleNamespace(db=world.db)
    pending = addressed_backlog(runtime, row)
    digest = format_digest(pending, safe_rider(row), cwd="", api="http://127.0.0.1:8643")
    check = "Partyline resume check. Reply READY, then wait for the next instruction."
    prompt = check if adapter == "opencode-v2" else ""
    return {f"backlog of {backlog} unseen addressed messages": len(digest),
            "resume check prompt": len(prompt), "messages replayed": len(pending)}


def suffix(world, adapter) -> dict:
    """Everything a delivery adds around the messages themselves, per delivery."""
    result = {}
    message = [{"sender": "fable-api-oc", "body": "@x go", "sender_type": "agent"}]
    base = len("[fable-api-oc]: @x go")
    for role in ("task implementer", "root captain"):
        row = attachment(world, ROLES[role], adapter)
        row["cwd"] = world.repo
        sizes = [len(format_digest(message, safe_rider(row), world.repo, api="")) - base for _ in range(6)]
        result[f"{role}: delivery 1"] = sizes[0]
        result[f"{role}: delivery 2"] = sizes[1]
        result[f"{role}: 6 deliveries"] = sum(sizes)
    return result


def _load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def notices(world) -> dict:
    """System notices pasted into the implementer over one fixture hour of eight wakes."""
    try:
        from partyline.notice_policy import digest_candidates as select
    except ImportError:
        def select(db, att):
            return db.messages_after(att["conv_id"], att["last_seen"], att["name"], att["id"])
    data = _load()
    row = attachment(world, "impl-task1", "claude")
    events = sorted(data["events"], key=lambda e: e["minute"])
    total = shown = 0
    count = shown_count = 0
    world.db._exec("UPDATE attachments SET name=?,last_seen=? WHERE id=?",
                   (data["agent"], world.db._exec("SELECT MAX(id) FROM messages").fetchone()[0] or 0,
                    row["id"]))
    wakes = data["wakes"]
    queue = [("w", m) for m in wakes] + [("e", e) for e in events]
    queue.sort(key=lambda item: (item[1] if item[0] == "w" else item[1]["minute"], item[0] == "w"))
    for kind, item in queue:
        if kind == "e":
            msg = world.db.add_message("task1", item["sender"], "system", item["body"])
            if item.get("to"):
                world.db._exec("UPDATE messages SET audience_attachment_id=? WHERE id=?",
                               (row["id"] if item["to"] == data["agent"] else "cap", msg["id"]))
            total += len(item["body"])
            count += 1
            continue
        world.db.add_message("task1", "fable-api-oc", "agent", f"@{data['agent']} please continue; gates?")
        current = world.db.get_attachment(row["id"])
        pending = select(world.db, current)
        for message in pending:
            if message["sender_type"] == "system":
                shown += len(message["body"])
                shown_count += 1
        world.db._exec("UPDATE attachments SET last_seen=? WHERE id=?",
                       (world.db._exec("SELECT MAX(id) FROM messages").fetchone()[0], row["id"]))
    return {f"posted on the line ({count} notices)": total,
            f"pasted into the process ({shown_count} notices)": shown}


def listings(world) -> dict:
    """What a captain's listing calls return on a tree with 14 retired task lines."""
    from partyline.mcp.tools_tasks import RETIRED_PAGE, _board
    from partyline.orchestrator_store import tasks
    from partyline.process_overview import process_overview
    from partyline.staffing import staffing_line, staffing_report

    runtime = SimpleNamespace(db=world.db, live={}, memory_usage={}, presence=None)
    out = {"staffing rider (every captain wake)": len(staffing_line(world.db, "root"))}
    out["staffing op"] = len(json.dumps(staffing_report(world.db, "root"), default=str))
    overview = process_overview(runtime, "root", include_retired=False)  # what the MCP op asks for
    out["process_overview op"] = len(overview.model_dump_json())
    live = tasks(world.db, "root", retired=False)
    out["tasks board (live lines)"] = len(json.dumps(_board(live), default=str))
    page = tasks(world.db, "root", only_retired=(RETIRED_PAGE + 1, 0))[:RETIRED_PAGE]  # first page
    board = _board(live) + _board(page, retired=True)
    out["tasks board (include_retired)"] = len(json.dumps(board, default=str))
    return out
