"""REST command for detaching every live process from one line."""

import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request

from .adapters.process_shutdown import process_group_alive
from .contracts import MessageEvent, MessageResponse
from .auth_guard import request_principal
from .attachment_lifecycle import expire_unowned_attachment
from .hierarchy import descendants
from .line_process_contracts import CloseProcessesResponse
from .machine_scope import deny_unless

LIVE = ("starting", "running")
DETACH_STOP_TIMEOUT = 2.5
DETACH_LOCK_TIMEOUT = 0.5
DETACH_DB_TIMEOUT = 0.5
DETACH_BROADCAST_TIMEOUT = 0.5
logger = logging.getLogger(__name__)


def live_attachments(db, conv_id: str, include_children: bool) -> list[dict]:
    """Return live attachments on a line and, optionally, its descendants."""
    line_ids = [conv_id, *descendants(db, conv_id)] if include_children else [conv_id]
    return [
        att
        for line_id in line_ids
        for att in db.list_attachments(line_id)
        if att["status"] in LIVE
    ]


def mid_turn_blocker(live: list[dict], presence) -> dict | None:
    """Describe a live process that cannot be stopped without interrupting work."""
    if presence is None:
        return None
    working = [att for att in live if presence.is_working(att["id"])]
    if not working:
        return None
    names = ", ".join("@" + att["name"] for att in working)
    return {
        "code": "process_mid_turn",
        "message": f"processes mid-turn: {names}; wait for them to finish before "
        "using stop_processes=true",
    }


async def detach_attachment(runtime, att_id: str) -> dict:
    """Run the one-jack detach transaction used by both REST commands."""
    lock = runtime.resume_locks.setdefault(att_id, asyncio.Lock())
    try:
        await asyncio.wait_for(lock.acquire(), timeout=DETACH_LOCK_TIMEOUT)
    except TimeoutError as exc:
        raise HTTPException(409, "attachment lifecycle is busy; retry detach") from exc
    try:
        att = runtime.db.get_attachment(att_id)
        if not att:
            raise HTTPException(404)
        adapter = runtime.live.get(att_id)
        runtime_owner = adapter.att.get("runtime_owner") if adapter else att.get("runtime_owner")
        if adapter is None and att["status"] in LIVE:
            body = (
                f"@{att['name']} detach failed: no local adapter owns the running record; "
                "process stop is unconfirmed"
            )
            try:
                message = await asyncio.wait_for(
                    expire_unowned_attachment(runtime.db, att_id, runtime_owner, body),
                    timeout=DETACH_DB_TIMEOUT,
                )
            except TimeoutError as exc:
                raise HTTPException(503, "attachment ownership is busy; retry detach") from exc
            if message is None:
                raise HTTPException(409, "attachment ownership changed; refresh and retry")
            await _bounded_broadcast(runtime.broadcast_attachment(att["conv_id"], att_id))
            await _broadcast_message(runtime, att["conv_id"], message)
            raise HTTPException(500, "no local adapter owns the running record; stop unconfirmed")
        stop_error = None
        if adapter:
            try:
                await asyncio.wait_for(adapter.stop(), timeout=DETACH_STOP_TIMEOUT)
            except (Exception, asyncio.CancelledError) as exc:
                stop_error = exc
        if stop_error is not None and not _process_group_stopped(adapter):
            await _report_stop_failure(
                runtime, att, adapter, "process stop was not confirmed",
                stop_confirmed=False,
            )
            raise HTTPException(500, "process stop was not confirmed; attachment remains live")
        if stop_error is not None:
            # stop may have killed the process but timed out in its status
            # callback; make the row inactive before the atomic notice.
            try:
                await asyncio.wait_for(
                    runtime.db.set_attachment_status_async(att_id, "exited", runtime_owner),
                    timeout=DETACH_DB_TIMEOUT,
                )
            except TimeoutError as exc:
                await _report_stop_failure(
                    runtime, att, adapter, "process stopped but status update was busy",
                    stop_confirmed=True,
                )
                raise HTTPException(
                    503, "attachment status update is busy; retry detach"
                ) from exc
        try:
            message = await asyncio.wait_for(
                runtime.db.detach_attachment_with_message_async(
                    att_id, runtime_owner, f"@{att['name']} detached"
                ),
                timeout=DETACH_DB_TIMEOUT,
            )
        except TimeoutError as exc:
            if adapter:
                stop_confirmed = stop_error is None or _process_group_stopped(adapter)
                detail = (
                    "process stopped but detach transaction was busy"
                    if stop_confirmed
                    else "process stop was not confirmed"
                )
                await _report_stop_failure(
                    runtime, att, adapter, detail, stop_confirmed=stop_confirmed
                )
            raise HTTPException(503, "detach transaction is busy; retry detach") from exc
        if message is None:
            raise HTTPException(
                409,
                "the attachment became live in another server generation; refresh and try again",
            )
        await _bounded_broadcast(runtime.broadcast(
            att["conv_id"], MessageEvent(message=MessageResponse.model_validate(message))
        ))
        if adapter is not None and runtime.live.get(att_id) is adapter:
            runtime.live.pop(att_id, None)
        return {"ok": True}
    finally:
        lock.release()


async def _report_stop_failure(
    runtime, att: dict, adapter, detail: str, *, stop_confirmed: bool | None = None
) -> None:
    """Reconcile memory with the current owner and confirmed process state."""
    runtime_owner = adapter.att.get("runtime_owner")
    current = runtime.db.get_attachment(att["id"])
    owned = current is not None and current.get("runtime_owner") == runtime_owner
    stopped = _process_group_stopped(adapter) if stop_confirmed is None else stop_confirmed
    if owned:
        desired = (
            "exited" if stopped and current["status"] in LIVE
            else "running" if not stopped
            else current["status"]
        )
        if current["status"] != desired:
            try:
                await asyncio.wait_for(
                    runtime.db.set_attachment_status_async(
                        att["id"], desired, runtime_owner
                    ),
                    timeout=DETACH_DB_TIMEOUT,
                )
            except TimeoutError:
                pass
            current = runtime.db.get_attachment(att["id"])
            owned = current is not None and current.get("runtime_owner") == runtime_owner
        if owned and (not stopped or current["status"] in LIVE):
            runtime.live[att["id"]] = adapter
        elif runtime.live.get(att["id"]) is adapter:
            runtime.live.pop(att["id"], None)
        await _bounded_broadcast(runtime.broadcast_attachment(att["conv_id"], att["id"]))
    elif runtime.live.get(att["id"]) is adapter:
        runtime.live.pop(att["id"], None)
    await _post_detach_failure(
        runtime, att,
        f"@{att['name']} detach failed: {detail}",
    )


async def _post_detach_failure(runtime, att: dict, body: str) -> None:
    notice = runtime.db.add_message(att["conv_id"], "system", "system", body)
    await _broadcast_message(runtime, att["conv_id"], notice)


async def _broadcast_message(runtime, conv_id: str, message: dict) -> None:
    await _bounded_broadcast(runtime.broadcast(
        conv_id, MessageEvent(message=MessageResponse.model_validate(message))
    ))


async def _bounded_broadcast(awaitable) -> None:
    """Do not let a slow websocket hold the durable detach response open."""
    try:
        await asyncio.wait_for(awaitable, timeout=DETACH_BROADCAST_TIMEOUT)
    except TimeoutError:
        logger.warning("detach broadcast timed out after its DB change committed")
    except Exception:
        logger.exception("detach broadcast failed after its DB change committed")


def _process_group_stopped(adapter) -> bool:
    """Confirm the adapter's owned session ended even if stop raised or timed out."""
    proc = getattr(adapter, "proc", None)
    if proc is None:
        return False
    return not process_group_alive(proc.pid)


def register_line_process_routes(app: FastAPI, runtime) -> None:
    @app.post(
        "/api/conversations/{conv_id}/attachments/close",
        response_model=CloseProcessesResponse,
    )
    async def close_line_processes(
        request: Request, conv_id: str, include_children: bool = True
    ):
        conversation = runtime.db.get_conversation(conv_id)
        if conversation is None:
            raise HTTPException(404)
        deny_unless(runtime.db, request_principal(request), conv_id, "close")
        if conversation["archived_at"] is not None:
            raise HTTPException(409, "restore the line before closing its processes")
        live = live_attachments(runtime.db, conv_id, include_children)
        for attachment in live:
            await detach_attachment(runtime, attachment["id"])
        return {"ok": True, "stopped": [attachment["name"] for attachment in live]}
