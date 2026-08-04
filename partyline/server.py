"""partyline server: conversations over REST + WebSocket, adapters as members.

Routing model (MVP):
  * Every message is broadcast to all humans watching the conversation.
  * Agents are woken ONLY by an explicit @mention of their attachment name.
  * A wake delivers every message the agent hasn't seen yet (its cursor),
    excluding its own, formatted as `[sender]: text` lines.
"""

import asyncio
import os
import re
import shlex
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import __version__
from .adapters import ADAPTERS, ADAPTER_METADATA, Adapter, import_repository, make_adapter, reload_adapters
from .db import Db

STATIC_DIR = Path(__file__).parent / "static"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")
MENTION_RE = re.compile(r"@([A-Za-z0-9][A-Za-z0-9_.-]*)")
RESERVED_NAMES = {"all", "system"}  # @all rings everyone; system is the notice sender

db = Db(os.environ.get("PARTYLINE_DB", os.path.expanduser("~/.partyline.db")))
sockets: dict[str, set] = {}          # conv_id -> live websockets
live: dict[str, Adapter] = {}         # attachment_id -> adapter


@asynccontextmanager
async def lifespan(app):
    db.mark_stale_attachments()
    yield
    for adapter in list(live.values()):
        try:
            await adapter.stop()
        except Exception:
            pass


app = FastAPI(lifespan=lifespan)


# -- fan-out ---------------------------------------------------------------
async def broadcast(conv_id: str, event: dict):
    for ws in list(sockets.get(conv_id, ())):
        try:
            await ws.send_json(event)
        except Exception:
            sockets.get(conv_id, set()).discard(ws)


async def post_message(conv_id: str, sender: str, sender_type: str, body: str):
    msg = db.add_message(conv_id, sender, sender_type, body)
    await broadcast(conv_id, {"type": "message", "message": msg})
    await route_mentions(conv_id, msg)
    return msg


async def route_mentions(conv_id: str, msg: dict):
    if msg["sender_type"] == "system":
        return  # join/exit notices mention names but must never wake agents
    # A handle may legitimately contain "." or "-", but a mention that ends a
    # sentence picks up its punctuation: "thanks @opus." must still ring opus.
    # Both readings are accepted rather than guessing which one was meant.
    names = set()
    for found in MENTION_RE.findall(msg["body"]):
        names.add(found.lower())
        names.add(found.rstrip(".-_").lower())
    names.discard("")
    if not names:
        return
    ring_all = "all" in names  # reserved handle: rings every running agent
    unreachable: list[str] = []
    delivered: set[str] = set()
    for att in db.list_attachments(conv_id):
        addressed = ring_all or att["name"].lower() in names
        if not addressed or att["name"].lower() == msg["sender"].lower():
            continue  # not for them, or no self-pings
        adapter = live.get(att["id"]) if att["status"] == "running" else None
        if adapter is None:
            # The process is gone but the mention looked like it landed. Say so:
            # a silently dropped mention is indistinguishable from an agent that
            # simply chose not to answer, and can go unnoticed for hours.
            if not ring_all and att["name"] not in unreachable:
                unreachable.append(att["name"])
            continue
        delivered.add(att["name"].lower())
        pending = db.messages_after(conv_id, att["last_seen"], exclude_sender=att["name"])
        db.set_last_seen(att["id"], msg["id"])
        if pending:
            await adapter.deliver(pending)

    # A handle can have several rows — old detached ones alongside a live one.
    # Only warn about handles that got no delivery at all.
    for name in [n for n in unreachable if n.lower() not in delivered]:
        # A system notice never wakes anyone, so this cannot loop.
        await post_message(conv_id, "system", "system",
                           f"⚠ @{name} was mentioned but is not attached — nothing was delivered")


def _status_cb(att_id: str, conv_id: str):
    async def on_status(status: str):
        db.set_attachment_status(att_id, status)
        att = db.get_attachment(att_id)
        await broadcast(conv_id, {"type": "attachment", "attachment": att})
    return on_status


def _post_cb(conv_id: str):
    async def post(sender: str, sender_type: str, body: str):
        await post_message(conv_id, sender, sender_type, body)
    return post


# -- REST ------------------------------------------------------------------
class ConvIn(BaseModel):
    name: str


class AttachIn(BaseModel):
    name: str
    adapter: str = "opencode"
    command: str = ""
    cwd: str = ""


class TopicIn(BaseModel):
    topic: str = ""
    sender: str = ""      # who set it, for the system notice


class RenameIn(BaseModel):
    name: str
    sender: str = ""      # who renamed it, for the system notice


class PresetIn(BaseModel):
    title: str
    name: str
    adapter: str = "opencode"
    command: str = ""


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/version")
async def version():
    return {"version": __version__}


@app.get("/api/adapters")
async def adapters():
    return [ADAPTER_METADATA[name] for name in sorted(ADAPTERS)]


class AdapterImportIn(BaseModel):
    repository: str
    ref: str | None = None


@app.post("/api/adapters/import")
async def import_adapters(body: AdapterImportIn):
    try:
        loaded = import_repository(body.repository, body.ref)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise HTTPException(400, f"could not import adapter repository: {exc}") from exc
    return {"loaded": loaded, "adapters": [ADAPTER_METADATA[name] for name in loaded]}


@app.post("/api/adapters/reload")
async def reload_adapter_definitions():
    try:
        loaded = reload_adapters()
    except (ValueError, OSError) as exc:
        raise HTTPException(400, f"could not reload adapters: {exc}") from exc
    return {"loaded": loaded}


@app.delete("/api/adapters/{adapter_name}")
async def remove_adapter(adapter_name: str):
    # Removing source is intentionally not automatic: an imported checkout may
    # contain several packages. Reloading is sufficient to disable stale code.
    if adapter_name not in ADAPTERS:
        raise HTTPException(404)
    return {"ok": True, "message": "adapter source remains installed; remove its checkout then reload"}


@app.get("/api/conversations")
async def conversations():
    return db.list_conversations()


@app.post("/api/conversations")
async def create_conversation(body: ConvIn):
    name = body.name.strip() or "untitled"
    return db.create_conversation(str(uuid.uuid4()), name)


@app.get("/api/conversations/{conv_id}")
async def conversation_detail(conv_id: str):
    conv = db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404)
    return {
        "conversation": conv,
        "messages": db.list_messages(conv_id),
        "attachments": db.list_attachments(conv_id),
    }


@app.put("/api/conversations/{conv_id}/topic")
async def set_topic(conv_id: str, body: TopicIn):
    conv = db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404)
    topic = body.topic.strip()
    if len(topic) > 3000:
        raise HTTPException(400, "topic is capped at 3000 characters")
    if topic == conv["topic"]:
        return conv
    conv = db.set_topic(conv_id, topic)
    who = f" by @{body.sender.strip()}" if body.sender.strip() else ""
    # A system message never wakes agents, but it rides along in the digest at
    # their next wake — so every agent picks up the new topic lazily, for free.
    notice = f"☏ topic set{who}: {topic}" if topic else f"☏ topic cleared{who}"
    await post_message(conv_id, "system", "system", notice)
    await broadcast(conv_id, {"type": "conversation", "conversation": conv})
    return conv


@app.put("/api/conversations/{conv_id}/name")
async def rename_conversation(conv_id: str, body: RenameIn):
    conv = db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404)
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "a line needs a name")
    if len(name) > 120:
        raise HTTPException(400, "name is capped at 120 characters")
    if name == conv["name"]:
        return conv
    was = conv["name"]
    conv = db.rename_conversation(conv_id, name)
    who = f" by @{body.sender.strip()}" if body.sender.strip() else ""
    # Like a topic change: never wakes anyone, but rides along in the next
    # digest, so agents learn the line's new name without costing a turn.
    await post_message(conv_id, "system", "system", f"☏ line renamed{who}: {was} → {name}")
    await broadcast(conv_id, {"type": "conversation", "conversation": conv})
    return conv


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    conv = db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404)
    # Tell watchers before anything is torn down: once the rows are gone a tab
    # sitting on this line can only discover it by a 404 on its next fetch.
    await broadcast(conv_id, {"type": "conversation_deleted", "conversation_id": conv_id})
    stopped: list[str] = []
    for att in db.list_attachments(conv_id):
        adapter = live.pop(att["id"], None)
        if adapter is None:
            continue
        stopped.append(att["name"])
        try:
            await adapter.stop()
        except Exception:
            pass  # a pty that will not die must not strand the delete
    db.delete_conversation(conv_id)
    sockets.pop(conv_id, None)
    return {"ok": True, "stopped": stopped}


@app.post("/api/conversations/{conv_id}/attachments")
async def attach(conv_id: str, body: AttachIn):
    conv = db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404)
    if not NAME_RE.match(body.name):
        raise HTTPException(400, "name must be alphanumeric ([A-Za-z0-9_.-], max 32)")
    if body.name.lower() in RESERVED_NAMES:
        raise HTTPException(400, f"'{body.name}' is a reserved handle")
    if body.adapter not in ADAPTERS:
        raise HTTPException(400, f"adapter must be one of {sorted(ADAPTERS)}")
    for existing in db.list_attachments(conv_id):
        if existing["name"].lower() == body.name.lower() and existing["status"] in ("starting", "running"):
            raise HTTPException(409, f"'{body.name}' is already attached")

    metadata = ADAPTER_METADATA[body.adapter]
    command = shlex.split(body.command) if body.command.strip() else []
    if not command:
        default_command = metadata.get("command") or []
        if not default_command:
            raise HTTPException(400, f"the {body.adapter} adapter needs an explicit command")
        command = list(default_command)
    # Fail here with something readable rather than as a spawn traceback later.
    for executable in metadata.get("requires") or []:
        if shutil.which(executable) is None:
            raise HTTPException(400, f"{executable!r} is not on PATH — install it, or attach with a full path")

    cwd = os.path.abspath(os.path.expanduser(body.cwd.strip() or os.getcwd()))
    if not os.path.isdir(cwd):
        raise HTTPException(400, f"cwd does not exist: {cwd}")

    att_id = str(uuid.uuid4())
    att = db.add_attachment(att_id, conv_id, body.name, body.adapter, command, cwd)
    att["conv_name"] = conv["name"]
    att["topic"] = conv["topic"]
    att["hook_url"] = _hook_url(att_id)

    adapter = make_adapter(body.adapter, att, _post_cb(conv_id), _status_cb(att_id, conv_id),
                           on_cli_session=lambda s: db.set_cli_session(att_id, s))
    try:
        await adapter.start()
    except Exception as exc:
        db.set_attachment_status(att_id, "exited")
        raise HTTPException(500, f"failed to spawn: {exc}")
    live[att_id] = adapter

    await post_message(
        conv_id, "system", "system",
        f"@{body.name} joined · `{ ' '.join(command) }` · {cwd} · session {att_id}",
    )
    return db.get_attachment(att_id)


@app.post("/api/attachments/{att_id}/resume")
async def resume_attachment(att_id: str):
    att = db.get_attachment(att_id)
    if not att:
        raise HTTPException(404)
    if att["status"] in ("starting", "running") or att_id in live:
        raise HTTPException(409, f"'{att['name']}' is already live")
    metadata = ADAPTER_METADATA.get(att["adapter"], {})
    capabilities = metadata.get("capabilities") or {}
    can_resume = capabilities.get("resume", False) if isinstance(capabilities, dict) else "resume" in capabilities
    if not can_resume:
        raise HTTPException(400, f"the {att['adapter']} adapter has no session to resume")
    for other in db.list_attachments(att["conv_id"]):
        if other["name"].lower() == att["name"].lower() and other["status"] in ("starting", "running"):
            raise HTTPException(409, f"'{att['name']}' is already attached")

    conv = db.get_conversation(att["conv_id"])
    att["conv_name"] = conv["name"]
    att["resume"] = True
    att["hook_url"] = _hook_url(att_id)

    adapter = make_adapter(att["adapter"], att, _post_cb(att["conv_id"]),
                           _status_cb(att_id, att["conv_id"]),
                           on_cli_session=lambda s: db.set_cli_session(att_id, s))
    try:
        await adapter.start()
    except Exception as exc:
        db.set_attachment_status(att_id, "exited")
        raise HTTPException(500, f"failed to resume: {exc}")
    live[att_id] = adapter

    await post_message(
        att["conv_id"], "system", "system",
        f"@{att['name']} resumed with full context · session {att.get('cli_session') or att_id}",
    )
    return db.get_attachment(att_id)


@app.delete("/api/attachments/{att_id}")
async def detach(att_id: str):
    att = db.get_attachment(att_id)
    if not att:
        raise HTTPException(404)
    adapter = live.pop(att_id, None)
    if adapter:
        await adapter.stop()
    else:
        db.set_attachment_status(att_id, "detached")
    await post_message(att["conv_id"], "system", "system", f"@{att['name']} detached")
    return {"ok": True}


# -- attachment introspection ----------------------------------------------
def _hook_url(att_id: str) -> str:
    host = os.environ.get("PARTYLINE_HOST", "127.0.0.1")
    port = os.environ.get("PARTYLINE_PORT", "8642")
    return f"http://{host}:{port}/api/hooks/{att_id}"


ATTENTION_RE = re.compile(r"permission|approv|trust|login|auth", re.IGNORECASE)


@app.post("/api/hooks/{att_id}")
async def hook_event(att_id: str, request: Request):
    """Receiver for optional process-side attention hooks."""
    att = db.get_attachment(att_id)
    if not att:
        raise HTTPException(404)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    message = str(payload.get("message") or payload.get("title") or "").strip()
    # Only surface events that mean "a human must look at me" — idle chatter
    # from an agent waiting between mentions would spam the conversation.
    if message and ATTENTION_RE.search(message):
        await post_message(
            att["conv_id"], "system", "system",
            f"⏸ @{att['name']} needs attention: {message} — use peek to view/answer the dialog",
        )
        await broadcast(att["conv_id"], {"type": "attention", "attachment_id": att_id})
    return {"ok": True}


@app.get("/api/attachments/{att_id}/screen")
async def attachment_screen(att_id: str):
    adapter = live.get(att_id)
    if adapter is None:
        raise HTTPException(404, "attachment is not live")
    return {"screen": adapter.screen_text()}


class KeyIn(BaseModel):
    key: str


@app.post("/api/attachments/{att_id}/keys")
async def attachment_key(att_id: str, body: KeyIn):
    adapter = live.get(att_id)
    if adapter is None:
        raise HTTPException(404, "attachment is not live")
    try:
        adapter.send_key(body.key)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


# -- presets ---------------------------------------------------------------
@app.get("/api/presets")
async def presets():
    return db.list_presets()


@app.post("/api/presets")
async def create_preset(body: PresetIn):
    return _save_preset(str(uuid.uuid4()), body)


@app.put("/api/presets/{preset_id}")
async def update_preset(preset_id: str, body: PresetIn):
    if not db.get_preset(preset_id):
        raise HTTPException(404)
    return _save_preset(preset_id, body)


@app.delete("/api/presets/{preset_id}")
async def delete_preset(preset_id: str):
    db.delete_preset(preset_id)
    return {"ok": True}


def _save_preset(preset_id: str, body: PresetIn):
    if not body.title.strip():
        raise HTTPException(400, "preset needs a title")
    if not NAME_RE.match(body.name):
        raise HTTPException(400, "name must be alphanumeric ([A-Za-z0-9_.-], max 32)")
    if body.name.lower() in RESERVED_NAMES:
        raise HTTPException(400, f"'{body.name}' is a reserved handle")
    if body.adapter not in ADAPTERS:
        raise HTTPException(400, f"adapter must be one of {sorted(ADAPTERS)}")
    return db.save_preset(preset_id, body.title.strip(), body.name, body.adapter, body.command.strip())


# -- WebSocket -------------------------------------------------------------
@app.websocket("/ws/{conv_id}")
async def ws_endpoint(ws: WebSocket, conv_id: str):
    await ws.accept()
    sockets.setdefault(conv_id, set()).add(ws)
    try:
        while True:
            data = await ws.receive_json()
            sender = str(data.get("sender", "")).strip()[:32] or "anon"
            body = str(data.get("body", "")).strip()
            if body:
                await post_message(conv_id, sender, "human", body)
    except WebSocketDisconnect:
        pass
    finally:
        sockets.get(conv_id, set()).discard(ws)


def load_dotenv(path: str = ".env"):
    """Merge a local .env into the environment attached processes inherit.

    Credentials for an attached CLI have to reach it somehow, and the two bad
    answers are baking them into a stored command or exporting them from a shell
    profile. A gitignored .env next to the server is the third option. Variables
    already set in the real environment always win, so an inline
    `KEY=... uv run partyline` still overrides the file.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def main():
    load_dotenv()
    host = os.environ.get("PARTYLINE_HOST", "127.0.0.1")
    port = int(os.environ.get("PARTYLINE_PORT", "8642"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
