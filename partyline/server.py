"""partyline server: conversations over REST + WebSocket, adapters as members.

Routing model (MVP):
  * Every message is broadcast to all humans watching the conversation.
  * Agents are woken ONLY by an explicit @mention of their attachment name.
  * A wake delivers every message the agent hasn't seen yet (its cursor),
    excluding its own, formatted as `[sender]: text` lines.
"""

import asyncio
import json
import logging
import os
import re
import signal
import shlex
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import __version__
from .adapters import (
    ADAPTERS,
    ADAPTER_METADATA,
    import_repository,
    make_adapter,
    reload_adapters,
)
from .contracts import (
    AdapterImportResponse,
    AdapterMetadataResponse,
    AdapterRemoveResponse,
    ArchiveResponse,
    AttachmentResponse,
    AttentionEvent,
    ConversationDetailResponse,
    ConversationArchivedEvent,
    ConversationDeletedEvent,
    ConversationEvent,
    ConversationResponse,
    HookEventRequest,
    LoadedResponse,
    MessageEvent,
    MessageResponse,
    OkResponse,
    PresetResponse,
    PurgeResponse,
    RestartPlanRequest,
    RestartPlanResponse,
    RunningProcessResponse,
    ScreenResponse,
    ShutdownEvent,
    ShutdownRequest,
    ShutdownResponse,
    VersionResponse,
)
from .db import Db
from .reattach import (
    ReattachCoordinator,
    ResumedAttachment,
    RestartPlanError,
    adapter_can_resume,
    create_restart_plan,
)
from .runtime import NAME_RE, RESERVED_NAMES, ChatRuntime

STATIC_DIR = Path(__file__).parent / "static"
ASSETS_DIR = STATIC_DIR / "assets"
BUILD_MANIFEST = STATIC_DIR / "build.json"
logger = logging.getLogger(__name__)


def load_frontend_build(path: Path = BUILD_MANIFEST) -> str:
    """Read the deterministic id emitted into both the bundle and its manifest."""
    try:
        build = json.loads(path.read_text(encoding="utf-8"))["build"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"no valid frontend build manifest at {path}. "
            "Run `npm install && npm run build` in frontend/."
        ) from exc
    if not isinstance(build, str) or not re.fullmatch(r"[0-9a-f]{16}", build):
        raise RuntimeError(f"invalid frontend build id in {path}: {build!r}")
    return build

FRONTEND_BUILD = load_frontend_build()
runtime = ChatRuntime(Db(os.environ.get("PARTYLINE_DB", os.path.expanduser("~/.partyline.db"))))


async def _run_automatic_reattachment() -> None:
    """Run a trusted cockpit plan at startup without depending on a browser."""
    try:
        await ReattachCoordinator(runtime, _resume_adapter).run_automatic()
    except Exception:
        logger.exception(
            "automatic reattachment stopped unexpectedly; the durable plan was preserved "
            "and will retry on the next restart"
        )


@asynccontextmanager
async def lifespan(app):
    runtime.db.mark_stale_attachments()
    automatic_task = asyncio.create_task(_run_automatic_reattachment())
    app.state.automatic_reattach_task = automatic_task
    try:
        yield
    finally:
        automatic_task.cancel()
        with suppress(asyncio.CancelledError):
            await automatic_task
        await runtime.shutdown()


app = FastAPI(lifespan=lifespan)


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


# The frontend is built by Vite into `static/`, which emits content-hashed
# bundles under `assets/`. Hashed names are why these can be cached hard: a new
# build is a new filename, so nothing served from here is ever stale.
#
# The directory is committed, so it is present in a fresh clone and in a wheel
# without Node ever running. It can still be missing if someone has cleaned it,
# and `StaticFiles` would answer that with an opaque traceback at import time —
# so say what actually needs doing instead.
if not ASSETS_DIR.is_dir():  # pragma: no cover - only reachable with a cleaned tree
    raise RuntimeError(
        f"no built frontend at {ASSETS_DIR}. Run `npm install && npm run build` in frontend/."
    )
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.get("/api/version", response_model=VersionResponse)
async def version():
    return {"version": __version__, "build": FRONTEND_BUILD}


LOOPBACK = {"127.0.0.1", "::1", "localhost"}
# Set by main(). None when partyline runs under someone else's ASGI server, in
# which case there is no server object to ask politely and we signal instead.
_uvicorn_server = None


def require_loopback(request: Request) -> None:
    """Keep process-control endpoints local even when the server binds widely."""
    client = request.client.host if request.client else None
    if client not in LOOPBACK:
        raise HTTPException(403, "process control may only be requested from this machine")


def save_restart_plan(body: RestartPlanRequest) -> RestartPlanResponse:
    try:
        return create_restart_plan(runtime, ADAPTER_METADATA, body)
    except RestartPlanError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


def request_exit():
    """Ask the process to come down gracefully, running lifespan teardown.

    Never os._exit(): that skips `ChatRuntime.shutdown()`, which is what stops
    the ptys. Orphaned processes would outlive the server that owns them.
    """
    if _uvicorn_server is not None:
        _uvicorn_server.should_exit = True
    else:
        os.kill(os.getpid(), signal.SIGTERM)


@app.get("/api/running", response_model=list[RunningProcessResponse])
async def running():
    return runtime.running_processes()


@app.post("/api/restart-plan", response_model=RestartPlanResponse)
async def plan_restart(request: Request, body: RestartPlanRequest):
    """Persist the only line allowed to offer reattachment after a restart."""
    require_loopback(request)
    return save_restart_plan(body)


@app.post("/api/shutdown", response_model=ShutdownResponse)
async def shutdown(request: Request, body: ShutdownRequest | None = None):
    """Stop partyline. Deliberately reachable only from this machine.

    The bind address is configurable, so "it only listens on localhost" is not
    something to assume — check the caller.
    """
    require_loopback(request)
    planned = save_restart_plan(body.reattach) if body and body.reattach else None
    stopping = runtime.running_processes()
    # Tell every open tab before going, so they show a stopped state instead of
    # reconnecting forever at a socket that is never coming back.
    for conv_id in list(runtime.sockets):
        await runtime.broadcast(conv_id, ShutdownEvent())
    # The exit runs *after* this response is flushed; stopping first would drop
    # the connection before the caller ever learned it had worked.
    payload = ShutdownResponse(
        ok=True,
        stopping=[process["name"] for process in stopping],
        reattach=planned,
    )
    return JSONResponse(
        payload.model_dump(exclude_none=True),
        background=BackgroundTask(request_exit),
    )


@app.get("/api/adapters", response_model=list[AdapterMetadataResponse])
async def adapters():
    return [ADAPTER_METADATA[name] for name in sorted(ADAPTERS)]


class AdapterImportIn(BaseModel):
    repository: str
    ref: str | None = None


@app.post("/api/adapters/import", response_model=AdapterImportResponse)
async def import_adapters(body: AdapterImportIn):
    try:
        loaded = import_repository(body.repository, body.ref)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise HTTPException(400, f"could not import adapter repository: {exc}") from exc
    return {"loaded": loaded, "adapters": [ADAPTER_METADATA[name] for name in loaded]}


@app.post("/api/adapters/reload", response_model=LoadedResponse)
async def reload_adapter_definitions():
    try:
        loaded = reload_adapters()
    except (ValueError, OSError) as exc:
        raise HTTPException(400, f"could not reload adapters: {exc}") from exc
    return {"loaded": loaded}


@app.delete("/api/adapters/{adapter_name}", response_model=AdapterRemoveResponse)
async def remove_adapter(adapter_name: str):
    # Removing source is intentionally not automatic: an imported checkout may
    # contain several packages. Reloading is sufficient to disable stale code.
    if adapter_name not in ADAPTERS:
        raise HTTPException(404)
    return {"ok": True, "message": "adapter source remains installed; remove its checkout then reload"}


@app.get("/api/conversations", response_model=list[ConversationResponse])
async def conversations(archived: bool = False):
    return runtime.db.list_conversations(archived=archived)


@app.post("/api/conversations", response_model=ConversationResponse)
async def create_conversation(body: ConvIn):
    name = body.name.strip() or "untitled"
    return runtime.db.create_conversation(str(uuid.uuid4()), name)


@app.get("/api/conversations/{conv_id}", response_model=ConversationDetailResponse)
async def conversation_detail(conv_id: str):
    conv = runtime.db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404)
    return {
        "conversation": conv,
        "messages": runtime.db.list_messages(conv_id),
        "attachments": runtime.db.list_attachments(conv_id),
    }


@app.put("/api/conversations/{conv_id}/topic", response_model=ConversationResponse)
async def set_topic(conv_id: str, body: TopicIn):
    conv = runtime.db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404)
    topic = body.topic.strip()
    if len(topic) > 3000:
        raise HTTPException(400, "topic is capped at 3000 characters")
    if topic == conv["topic"]:
        return conv
    conv = runtime.db.set_topic(conv_id, topic)
    who = f" by @{body.sender.strip()}" if body.sender.strip() else ""
    # A system message never wakes agents, but it rides along in the digest at
    # their next wake — so every agent picks up the new topic lazily, for free.
    notice = f"☏ topic set{who}: {topic}" if topic else f"☏ topic cleared{who}"
    await runtime.post_message(conv_id, "system", "system", notice)
    await runtime.broadcast(conv_id, ConversationEvent(conversation=conv))
    return conv


@app.put("/api/conversations/{conv_id}/name", response_model=ConversationResponse)
async def rename_conversation(conv_id: str, body: RenameIn):
    conv = runtime.db.get_conversation(conv_id)
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
    conv = runtime.db.rename_conversation(conv_id, name)
    who = f" by @{body.sender.strip()}" if body.sender.strip() else ""
    # Like a topic change: never wakes anyone, but rides along in the next
    # digest, so agents learn the line's new name without costing a turn.
    await runtime.post_message(
        conv_id, "system", "system", f"☏ line renamed{who}: {was} → {name}")
    await runtime.broadcast(conv_id, ConversationEvent(conversation=conv))
    return conv


@app.delete("/api/conversations/{conv_id}", response_model=ArchiveResponse)
async def archive_conversation(conv_id: str):
    """Archive a line: stop its processes, hide it, keep the history."""
    conv = runtime.db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404)
    if conv["archived_at"]:
        raise HTTPException(409, "line is already archived")
    # Tell watchers before tearing down: a tab sitting on this line should leave
    # under its own power rather than discover the archive by a failing fetch.
    event = ConversationArchivedEvent(conversation_id=conv_id)
    await runtime.broadcast(conv_id, event)
    # Alias kept for one version so clients written against the first cut of
    # this route keep working. Remove in 0.17.
    await runtime.broadcast(conv_id, ConversationDeletedEvent(conversation_id=conv_id))
    stopped = await runtime.stop_attachments(conv_id)
    conv = runtime.db.archive_conversation(conv_id)
    runtime.sockets.pop(conv_id, None)
    return {"ok": True, "archived": True, "stopped": stopped, "conversation": conv}


@app.post("/api/conversations/{conv_id}/restore", response_model=ConversationResponse)
async def restore_conversation(conv_id: str):
    """Bring an archived line back. Its processes stay stopped — a restored
    attachment is resumed one at a time, through the usual resume route."""
    conv = runtime.db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404)
    if not conv["archived_at"]:
        raise HTTPException(409, "line is not archived")
    conv = runtime.db.restore_conversation(conv_id)
    await runtime.post_message(
        conv_id, "system", "system", "☏ line restored from the archive")
    return conv


@app.delete("/api/conversations/{conv_id}/purge", response_model=PurgeResponse)
async def purge_conversation(conv_id: str):
    """Destroy an archived line for good. Archiving first is mandatory: it is
    the step that stops the processes, and it makes this irreversible act
    something you have to ask for twice."""
    conv = runtime.db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404)
    if not conv["archived_at"]:
        raise HTTPException(409, "archive the line before purging it")
    await runtime.stop_attachments(conv_id)  # belt and braces: nothing should be live
    runtime.db.delete_conversation(conv_id)
    runtime.sockets.pop(conv_id, None)
    return {"ok": True, "purged": True}


@app.post("/api/conversations/{conv_id}/attachments", response_model=AttachmentResponse)
async def attach(conv_id: str, body: AttachIn):
    conv = runtime.db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404)
    if conv["archived_at"]:
        raise HTTPException(409, "restore the line before attaching to it")
    if not NAME_RE.match(body.name):
        raise HTTPException(400, "name must be alphanumeric ([A-Za-z0-9_.-], max 32)")
    if body.name.lower() in RESERVED_NAMES:
        raise HTTPException(400, f"'{body.name}' is a reserved handle")
    if body.name.lower() in {
            name.lower() for name, _ in runtime.human_handles.get(conv_id, {}).values()}:
        raise HTTPException(409, f"'{body.name}' is already in use by a human on this line")
    if body.adapter not in ADAPTERS:
        raise HTTPException(400, f"adapter must be one of {sorted(ADAPTERS)}")
    for existing in runtime.db.list_attachments(conv_id):
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
            raise HTTPException(
                400, f"{executable!r} is not on PATH — install it, or attach with a full path")

    cwd = os.path.abspath(os.path.expanduser(body.cwd.strip() or os.getcwd()))
    if not os.path.isdir(cwd):
        raise HTTPException(400, f"cwd does not exist: {cwd}")

    att_id = str(uuid.uuid4())
    runtime_owner = str(uuid.uuid4())
    att = runtime.db.add_attachment(
        att_id, conv_id, body.name, body.adapter, command, cwd, runtime_owner
    )
    att["runtime_owner"] = runtime_owner
    att["conv_name"] = conv["name"]
    att["topic"] = conv["topic"]
    att["hook_url"] = _hook_url(att_id)

    adapter = make_adapter(
        body.adapter,
        att,
        runtime.post_callback(att_id, conv_id, runtime_owner),
        runtime.status_callback(att_id, conv_id, runtime_owner),
        on_cli_session=lambda s: runtime.db.set_cli_session(att_id, s, runtime_owner),
    )
    try:
        await adapter.start()
    except Exception as exc:
        await runtime.db.set_attachment_status_async(
            att_id, "exited", runtime_owner
        )
        raise HTTPException(500, f"failed to spawn: {exc}") from exc
    runtime.live[att_id] = adapter

    await runtime.post_message(
        conv_id, "system", "system",
        f"@{body.name} joined · `{ ' '.join(command) }` · {cwd} · session {att_id}",
    )
    return runtime.db.get_attachment(att_id)


@app.post("/api/attachments/{att_id}/resume", response_model=AttachmentResponse)
async def resume_attachment(att_id: str):
    await _resume_adapter(att_id)
    return runtime.db.get_attachment(att_id)


async def _resume_adapter(
    att_id: str, startup_messages: list[dict] | None = None
) -> ResumedAttachment:
    att = runtime.db.get_attachment(att_id)
    if not att:
        raise HTTPException(404)
    if att["status"] in ("starting", "running") or att_id in runtime.live:
        raise HTTPException(409, f"'{att['name']}' is already live")
    capabilities = ADAPTER_METADATA.get(att["adapter"], {})
    if not adapter_can_resume(capabilities):
        raise HTTPException(400, f"the {att['adapter']} adapter has no session to resume")
    for other in runtime.db.list_attachments(att["conv_id"]):
        if other["name"].lower() == att["name"].lower() and other["status"] in ("starting", "running"):
            raise HTTPException(409, f"'{att['name']}' is already attached")

    conv = runtime.db.get_conversation(att["conv_id"])
    if conv["archived_at"]:
        raise HTTPException(409, "restore the line before resuming its processes")
    att["conv_name"] = conv["name"]
    att["resume"] = True
    att["hook_url"] = _hook_url(att_id)
    runtime_owner = str(uuid.uuid4())
    att["runtime_owner"] = runtime_owner

    adapter = make_adapter(
        att["adapter"],
        att,
        runtime.post_callback(att_id, att["conv_id"], runtime_owner),
        runtime.status_callback(att_id, att["conv_id"], runtime_owner),
        on_cli_session=lambda s: runtime.db.set_cli_session(att_id, s, runtime_owner),
    )
    startup_delivery_staged = adapter.stage_startup_delivery(startup_messages or [])
    if not await runtime.db.claim_attachment_async(att_id, runtime_owner):
        raise HTTPException(409, f"'{att['name']}' is already live")
    try:
        await adapter.start()
    except Exception as exc:
        await runtime.db.set_attachment_status_async(
            att_id, "exited", runtime_owner
        )
        raise HTTPException(500, f"failed to resume: {exc}") from exc
    runtime.live[att_id] = adapter

    await runtime.post_message(
        att["conv_id"], "system", "system",
        f"@{att['name']} resumed with full context · session {att.get('cli_session') or att_id}",
    )
    return ResumedAttachment(adapter, startup_delivery_staged)


@app.delete("/api/attachments/{att_id}", response_model=OkResponse)
async def detach(att_id: str):
    att = runtime.db.get_attachment(att_id)
    if not att:
        raise HTTPException(404)
    adapter = runtime.live.pop(att_id, None)
    if adapter:
        await adapter.stop()
        runtime_owner = adapter.att.get("runtime_owner")
    else:
        runtime_owner = att.get("runtime_owner")
    message = await runtime.db.detach_attachment_with_message_async(
        att_id, runtime_owner, f"@{att['name']} detached"
    )
    if message is None:
        raise HTTPException(
            409,
            "the attachment became live in another server generation; refresh and try again",
        )
    await runtime.broadcast(
        att["conv_id"], MessageEvent(message=MessageResponse.model_validate(message))
    )
    return {"ok": True}


# -- attachment introspection ----------------------------------------------
def _hook_url(att_id: str) -> str:
    host = os.environ.get("PARTYLINE_HOST", "127.0.0.1")
    port = os.environ.get("PARTYLINE_PORT", "8642")
    return f"http://{host}:{port}/api/hooks/{att_id}"


ATTENTION_RE = re.compile(r"permission|approv|trust|login|auth", re.IGNORECASE)


@app.post("/api/hooks/{att_id}", response_model=OkResponse)
async def hook_event(att_id: str, request: Request):
    """Receiver for optional process-side attention hooks."""
    att = runtime.db.get_attachment(att_id)
    if not att:
        raise HTTPException(404)
    try:
        payload = HookEventRequest.model_validate(await request.json())
    except Exception:
        payload = HookEventRequest()
    message = (payload.message or payload.title or "").strip()
    # Only surface events that mean "a human must look at me" — idle chatter
    # from an agent waiting between mentions would spam the conversation.
    if message and ATTENTION_RE.search(message):
        await runtime.post_message(
            att["conv_id"], "system", "system",
            f"⏸ @{att['name']} needs attention: {message} — use peek to view/answer the dialog",
        )
        await runtime.broadcast(
            att["conv_id"], AttentionEvent(attachment_id=att_id))
    return {"ok": True}


@app.get("/api/attachments/{att_id}/screen", response_model=ScreenResponse)
async def attachment_screen(att_id: str):
    adapter = runtime.live.get(att_id)
    if adapter is None:
        raise HTTPException(404, "attachment is not live")
    return {"screen": adapter.screen_text()}


class KeyIn(BaseModel):
    key: str


@app.post("/api/attachments/{att_id}/keys", response_model=OkResponse)
async def attachment_key(att_id: str, body: KeyIn):
    adapter = runtime.live.get(att_id)
    if adapter is None:
        raise HTTPException(404, "attachment is not live")
    try:
        adapter.send_key(body.key)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


# -- presets ---------------------------------------------------------------
@app.get("/api/presets", response_model=list[PresetResponse])
async def presets():
    return runtime.db.list_presets()


@app.post("/api/presets", response_model=PresetResponse)
async def create_preset(body: PresetIn):
    return _save_preset(str(uuid.uuid4()), body)


@app.put("/api/presets/{preset_id}", response_model=PresetResponse)
async def update_preset(preset_id: str, body: PresetIn):
    if not runtime.db.get_preset(preset_id):
        raise HTTPException(404)
    return _save_preset(preset_id, body)


@app.delete("/api/presets/{preset_id}", response_model=OkResponse)
async def delete_preset(preset_id: str):
    runtime.db.delete_preset(preset_id)
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
    return runtime.db.save_preset(
        preset_id, body.title.strip(), body.name, body.adapter, body.command.strip())


@app.websocket("/ws/{conv_id}")
async def ws_endpoint(ws: WebSocket, conv_id: str):
    await runtime.websocket(
        ws,
        conv_id,
        FRONTEND_BUILD,
        ReattachCoordinator(runtime, _resume_adapter),
    )


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
    global _uvicorn_server
    # Hold the server object so /api/shutdown can ask it to stop rather than
    # signalling blindly.
    _uvicorn_server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    _uvicorn_server.run()


if __name__ == "__main__":
    main()
