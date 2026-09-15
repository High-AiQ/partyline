"""partyline server: REST, WebSocket, and adapters as members of the line."""

import asyncio
import logging
import os
import signal
import shlex
import subprocess
import sys
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
from .attachment_start import start_attachment
from .attachment_lifecycle_routes import register_attachment_lifecycle_routes
from .attachment_view import attachment_response
from .auth_guard import (
    WS_FORBIDDEN,
    UserSocketRegistry,
    install_auth_guard,
    request_principal,
    websocket_principal,
)
from .auth_routes import auth_router
from .machine_scope import (
    allows_restart_plan,
    deny_unless_attachment,
    visible_conversation_ids,
)
from .bind import (BindConfig, apply_server_config, load_bind_config, load_dotenv,
                   parse_bind_args, uvicorn_config)
from .compact_routes import register_compact_route
from . import features
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
    AttachmentEvent,
    AttachmentPatchRequest,
    AttachmentResponse,
    FeatureFlagResponse,
    KeyIn,
    LoadedResponse,
    OkResponse,
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
from .frontend_build import current_frontend_build
from .hook_routes import hook_url, hooks_router
from .line_process_routes import detach_attachment, register_line_process_routes
from .message_routes import message_router
from .reaction_routes import reaction_router
from .goal import register_goal_route
from .presence import Presence
from .media import MediaStore, media_root
from .conversation_routes import register_conversation_routes
from . import heartbeat_scheduler
from .heartbeat_routes import heartbeat_router
from .hierarchy_routes import hierarchy_router
from .media_routes import media_router
from .preset_routes import presets_router
from .staffing_routes import staffing_router
from .restart_report import restart_report_router
from .static_cache import install_static_cache
from .resume_continuation import resume_with_backlog
from .restart_requests import register_restart_request_routes
from .reattach import (
    ReattachCoordinator,
    RestartPlanError,
    create_restart_plan,
)
from .runtime import ChatRuntime
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
    # The monitor's state is in the database, so a restart resumes whatever the
    # lead had configured — including an unsettled wake, which stays unsettled.
    # Behind the `heartbeat` flag (off by default since 1.23.0): a switched-off
    # server neither ticks nor answers the routes.
    tasks = [automatic_task]
    if features.enabled("heartbeat"):
        tasks.append(asyncio.create_task(heartbeat_scheduler.run(runtime)))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await runtime.shutdown()


app = FastAPI(lifespan=lifespan)
app.state.bind = BindConfig()
user_sockets = UserSocketRegistry()
install_auth_guard(app, runtime.db)
install_static_cache(app)
register_terminal_route(app, runtime)
register_compact_route(app, runtime, presence)
register_line_process_routes(app, runtime)
register_goal_route(app, runtime)
register_restart_request_routes(app, runtime, ADAPTER_METADATA, lambda: request_exit())
app.include_router(auth_router(runtime.db, on_handle_change=user_sockets.close_all))
app.include_router(media_router(runtime, media))
app.include_router(message_router(runtime, media))
app.include_router(reaction_router(runtime))
app.include_router(hierarchy_router(runtime))
app.include_router(heartbeat_router(runtime))
app.include_router(hooks_router(runtime, presence))
app.include_router(presets_router(runtime, ADAPTERS))
app.include_router(staffing_router(runtime))
app.include_router(restart_report_router(runtime, lambda r: require_loopback(r)))

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
async def running(request: Request):
    processes = runtime.running_processes()
    allowed = visible_conversation_ids(runtime.db, request_principal(request))
    if allowed is None:
        return processes
    names = {
        row["name"] for row in runtime.db.list_conversations() if row["id"] in allowed
    }
    return [process for process in processes if process["conversation"] in names]


@app.post("/api/restart-plan", response_model=RestartPlanResponse)
async def plan_restart(request: Request, body: RestartPlanRequest):
    """Persist a restart plan. Loopback, and machines only for their home line.

    The cockpit planner uses ``PARTYLINE_TOKEN`` against the line that owns
    the plan. A machine on another line is 403. ``allows()`` still governs
    conversation, attachment, and report routes; this is not one of them.
    """
    require_loopback(request)
    if not allows_restart_plan(
        request_principal(request), body.conversation_id, db=runtime.db, scope=body.scope
    ):
        raise HTTPException(403, "this credential cannot plan a restart for that line")
    return save_restart_plan(body)


@app.post("/api/shutdown", response_model=ShutdownResponse)
async def shutdown(request: Request, body: ShutdownRequest | None = None):
    """Stop partyline. Deliberately reachable only from this machine.

    The bind address is configurable, so "it only listens on localhost" is not
    something to assume — check the caller.
    """
    require_loopback(request)
    if request_principal(request).kind != "user":
        raise HTTPException(403, "only a human operator may shut down the instance")
    if body and body.reattach and not allows_restart_plan(
        request_principal(request), body.reattach.conversation_id,
        db=runtime.db, scope=body.reattach.scope
    ):
        raise HTTPException(403, "this credential cannot plan a restart for that line")
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


@app.get("/api/features", response_model=list[FeatureFlagResponse])
def list_features():
    """Which flags this server runs with, so a client or a captain can tell."""
    return features.current().describe()


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


async def _start_attachment(att, *, checkpoint="", fresh=False):
    return await start_attachment(
        att, runtime=runtime, presence=presence, make_adapter=make_adapter,
        hook_url=lambda ident, owner: _hook_url(ident, app.state.bind, owner),
        checkpoint=checkpoint, fresh=fresh,
    )


register_conversation_routes(
    app,
    runtime,
    media,
    presence,
    ADAPTERS,
    ADAPTER_METADATA,
    _start_attachment,
)
from . import conversation_routes as _conversation_routes  # noqa: E402
from .contracts import AttachIn, RenameIn, TopicIn  # noqa: F401,E402

archive_conversation = _conversation_routes.archive_conversation
restore_conversation = _conversation_routes.restore_conversation
purge_conversation = _conversation_routes.purge_conversation
attach = _conversation_routes.attach
set_topic = _conversation_routes.set_topic
rename_conversation = _conversation_routes.rename_conversation
conversation_detail = _conversation_routes.conversation_detail
register_attachment_lifecycle_routes(
    app, runtime, start=lambda att, **kwargs: _start_attachment(att, **kwargs),
    require_loopback=require_loopback,
    validate=lambda att: validated_attachment_command(
        att["adapter"], shlex.join(att["command"]), ADAPTERS, ADAPTER_METADATA
    ),
)


@app.post("/api/attachments/{att_id}/resume", response_model=AttachmentResponse)
async def resume_attachment(request: Request, att_id: str):
    deny_unless_attachment(runtime.db, request_principal(request), att_id, "attach")
    await resume_with_backlog(runtime, att_id, _resume_adapter)
    # An explicit resume is the operator saying "this one is back". Automatic
    # recovery leaves an unconfirmed attachment in `reattaching`, which routing
    # consults *only when no live adapter exists*: it never blocks delivery to
    # a running process, but once that process exits it swallows the "not
    # attached" warning and the room hears nothing. Nothing else cleared it, so
    # the flag outlived the recovery it belonged to.
    runtime.reattaching.discard(att_id)
    return await attachment_response(runtime.db.get_attachment(att_id))


async def _resume_adapter(
    att_id: str, startup_messages: list[dict] | None = None
):
    return await resume_adapter(
        att_id, startup_messages, runtime=runtime,
        adapter_metadata=ADAPTER_METADATA, make_adapter=make_adapter,
        presence=presence,
        hook_url=lambda ident, token: _hook_url(ident, app.state.bind, token),
    )


@app.patch("/api/attachments/{att_id}", response_model=AttachmentResponse)
async def edit_attachment(
    request: Request, att_id: str, body: AttachmentPatchRequest
):
    att = runtime.db.get_attachment(att_id)
    if not att:
        raise HTTPException(404)
    deny_unless_attachment(runtime.db, request_principal(request), att_id, "attach")
    require_loopback(request)
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
    response = await attachment_response(updated)
    await runtime.broadcast(att["conv_id"], AttachmentEvent(attachment=response))
    return response


@app.delete("/api/attachments/{att_id}", response_model=OkResponse)
async def detach(request: Request, att_id: str):
    deny_unless_attachment(runtime.db, request_principal(request), att_id, "close")
    return await detach_attachment(runtime, att_id)


# -- attachment introspection ----------------------------------------------
def _hook_url(att_id: str, bind: BindConfig | None = None, token: str = "") -> str:
    return hook_url(att_id, bind or app.state.bind, token)

@app.get("/api/attachments/{att_id}/screen", response_model=ScreenResponse)
async def attachment_screen(request: Request, att_id: str):
    deny_unless_attachment(runtime.db, request_principal(request), att_id, "read")
    adapter = runtime.live.get(att_id)
    if adapter is None:
        raise HTTPException(404, "attachment is not live")
    return {"screen": adapter.screen_text()}


@app.post("/api/attachments/{att_id}/keys", response_model=OkResponse)
async def attachment_key(request: Request, att_id: str, body: KeyIn):
    deny_unless_attachment(runtime.db, request_principal(request), att_id, "attach")
    adapter = runtime.live.get(att_id)
    if adapter is None:
        raise HTTPException(404, "attachment is not live")
    try:
        adapter.send_key(body.key)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@app.websocket("/ws/{conv_id}")
async def ws_endpoint(ws: WebSocket, conv_id: str):
    principal = await websocket_principal(runtime.db, ws)
    if principal is None:
        return
    if principal.user_id is None:
        # An attachment has no business on the human chat socket: it speaks
        # through its harness. Letting it in would relabel agent speech as
        # human and hand it a seat in human_handles.
        await ws.accept()
        await ws.close(code=WS_FORBIDDEN, reason="machine tokens cannot join the chat socket")
        return
    # A handle is fixed for the socket's lifetime: when it changes, every one
    # of the user's sockets is force-closed (below) and each tab reconnects
    # and re-authenticates under the new name — deterministic for every tab,
    # with no per-message database lookup.
    user_sockets.add(principal.user_id, ws)
    try:
        await _serve_socket(ws, conv_id, principal.name)
    finally:
        user_sockets.discard(principal.user_id, ws)


async def _serve_socket(ws: WebSocket, conv_id: str, handle: str):
    await runtime.websocket(
        ws,
        conv_id,
        handle=handle,
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
    _uvicorn_server = uvicorn.Server(uvicorn_config(app, host, port, os.environ))
    _uvicorn_server.run()


if __name__ == "__main__":
    main()
