"""partyline server: conversations over REST + WebSocket, adapters as members.

Routing model (MVP):
  * Every message is broadcast to all humans watching the conversation.
  * Agents are woken ONLY by an explicit @mention of their attachment name.
  * A wake delivers every message the agent hasn't seen yet (its cursor),
    excluding its own, formatted as `[sender]: text` lines.
"""

import asyncio
import logging
import os
import re
import signal
import subprocess
import sys
import uuid
from collections.abc import Sequence
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from . import __version__
from .attachment_commands import validated_attachment_command
from .attachment_resume import resume_adapter
from .bind import BindConfig, apply_server_config, load_bind_config, load_dotenv, parse_bind_args
from .adapters import (
    ADAPTERS,
    ADAPTER_METADATA,
    import_repository,
    make_adapter,
    reload_adapters,
)
from .contracts import (
    AdapterImportIn,
    AdapterImportResponse,
    AdapterMetadataResponse,
    AdapterRemoveResponse,
    ArchiveResponse,
    AttachIn,
    AttachmentCommandRequest,
    AttachmentEvent,
    AttachmentResponse,
    AttentionEvent,
    ConvIn,
    ConversationDetailResponse,
    ConversationArchivedEvent,
    ConversationDeletedEvent,
    ConversationEvent,
    ConversationResponse,
    HookEventRequest,
    KeyIn,
    LoadedResponse,
    MessageEvent,
    MessageResponse,
    OkResponse,
    PresetIn,
    PresetResponse,
    PurgeResponse,
    RestartPlanRequest,
    RestartPlanResponse,
    RenameIn,
    RunningProcessResponse,
    ScreenResponse,
    ShutdownEvent,
    ShutdownRequest,
    ShutdownResponse,
    TopicIn,
    VersionResponse,
)
from .db import Db
from .frontend_build import current_frontend_build
from .presence import Presence
from .media import MediaStore, media_root
from .claim_routes import claims_router, purge_claims
from .media_routes import media_router
from .task_routes import wire_tasks
from .reattach import (
    ReattachCoordinator,
    RestartPlanError,
    create_restart_plan,
)
from .runtime import NAME_RE, RESERVED_NAMES, ChatRuntime
from .terminal_stream import register_terminal_route

STATIC_DIR = Path(__file__).parent / "static"
ASSETS_DIR = STATIC_DIR / "assets"
logger = logging.getLogger(__name__)


# The .env merge has to happen before anything reads the environment.
# `runtime`, `media`, and the router below all bind at import, so loading
# it later — as `main()` used to — meant a .env-only PARTYLINE_MEDIA_DIR or
# PARTYLINE_DB was read after the values it sets had already been used, and
# was silently ignored. A configured NAS path that quietly writes somewhere
# else is the silent-fallback failure `docs/lessons.md` keeps recording.
load_dotenv()
runtime = ChatRuntime(Db(os.environ.get("PARTYLINE_DB", os.path.expanduser("~/.partyline.db"))))
media = MediaStore(runtime.db, media_root(os.environ, runtime.db.path))
presence = Presence(runtime)


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
app.state.bind = BindConfig()
register_terminal_route(app, runtime)
app.include_router(media_router(runtime, media))
app.include_router(claims_router(runtime))
tasks = wire_tasks(app, runtime)

# -- REST ------------------------------------------------------------------
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
    return {"version": __version__, "build": current_frontend_build(),
            "instance_name": getattr(app.state, "instance_name", None)}


LOOPBACK = {"127.0.0.1", "::1", "localhost"}
# Set by main(). None when partyline runs under someone else's ASGI server, in
# which case there is no server object to ask politely and we signal instead.
_uvicorn_server = None


def require_loopback(request: Request) -> None:
    """Keep process-control endpoints local even when the server binds widely."""
    client = request.client.host if request.client else None
    # Dual-stack sockets can represent an IPv4 loopback peer in IPv4-mapped
    # IPv6 form. Normalize it so local shutdown remains usable on those hosts.
    if client and client.lower().startswith("::ffff:"):
        client = client[7:]
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
        "messages": media.attach(runtime.db.list_messages(conv_id)),
        "attachments": runtime.db.list_attachments(conv_id),
        "working": presence.working_ids(conv_id),
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
    media.delete_conversation(conv_id)  # a purge takes the pictures with it
    purge_claims(runtime.db, conv_id)
    tasks.purge(conv_id)
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
    for existing in runtime.db.list_attachments(conv_id):
        if existing["name"].lower() == body.name.lower() and existing["status"] in ("starting", "running"):
            raise HTTPException(409, f"'{body.name}' is already attached")

    try:
        command = validated_attachment_command(
            body.adapter, body.command, ADAPTERS, ADAPTER_METADATA
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

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
    att["hook_url"] = _hook_url(att_id, app.state.bind)
    att["digest_rider"] = lambda: tasks.rider(conv_id)

    adapter = make_adapter(
        body.adapter,
        att,
        presence.posting(conv_id, att_id, runtime.post_callback(att_id, conv_id, runtime_owner)),
        presence.statusing(conv_id, att_id, runtime.status_callback(att_id, conv_id, runtime_owner)),
        on_cli_session=lambda s: runtime.db.set_cli_session(att_id, s, runtime_owner),
    )
    try:
        await adapter.start()
    except Exception as exc:
        await runtime.db.set_attachment_status_async(
            att_id, "exited", runtime_owner
        )
        raise HTTPException(500, f"failed to spawn: {exc}") from exc
    runtime.live[att_id] = presence.watch(adapter, conv_id, att_id)

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
):
    return await resume_adapter(
        att_id, startup_messages, runtime=runtime,
        adapter_metadata=ADAPTER_METADATA, make_adapter=make_adapter,
        presence=presence, tasks=tasks,
        hook_url=lambda ident: _hook_url(ident, app.state.bind),
    )


@app.patch("/api/attachments/{att_id}", response_model=AttachmentResponse)
async def edit_attachment_command(
    request: Request, att_id: str, body: AttachmentCommandRequest
):
    require_loopback(request)
    att = runtime.db.get_attachment(att_id)
    if not att:
        raise HTTPException(404)
    if att_id in runtime.live or att["status"] not in ("exited", "detached"):
        raise HTTPException(409, f"'{att['name']}' must be stopped before editing its command")
    try:
        command = validated_attachment_command(
            att["adapter"], body.command, ADAPTERS, ADAPTER_METADATA
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    updated = await runtime.db.update_inactive_attachment_command(att_id, command)
    if updated is None:
        raise HTTPException(409, f"'{att['name']}' became live; refresh and try again")
    await runtime.broadcast(
        att["conv_id"],
        AttachmentEvent(attachment=AttachmentResponse.model_validate(updated)),
    )
    return updated


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
def _hook_url(att_id: str, bind: BindConfig | None = None) -> str:
    bind = bind or app.state.bind
    host = f"[{bind.host}]" if ":" in bind.host else bind.host
    return f"http://{host}:{bind.port}/api/hooks/{att_id}"


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
        frontend_build=current_frontend_build(), server_version=__version__,
        instance_name=getattr(app.state, "instance_name", None),
        reattacher=ReattachCoordinator(runtime, _resume_adapter),
    )


def main(argv: Sequence[str] | None = None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    parsed = parse_bind_args(arguments)
    config = load_bind_config(parsed.config)
    host, port = apply_server_config(app.state, parsed, os.environ, config)
    global _uvicorn_server
    # Hold the server object so /api/shutdown can ask it to stop rather than
    # signalling blindly.
    _uvicorn_server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    _uvicorn_server.run()


if __name__ == "__main__":
    main()
