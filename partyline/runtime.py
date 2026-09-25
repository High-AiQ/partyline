"""Live chat state and behavior underneath the HTTP/WebSocket routes."""

import asyncio
import re

from fastapi import WebSocket, WebSocketDisconnect

from .adapter_capabilities import claims_transcript, transcript_claimed
from .adapters import Adapter
from .attachment_broadcast import broadcast_attachment_state
from .contracts import ErrorEvent, Event, MessageEvent, MessageResponse
from .handshake import hello_payload
from .db import Db
from .delivery_hooks import delivery_hooks
from .message_routing import post_human_message, route_message
from .reattach import ReattachCoordinator
from .runtime_delivery_credit import DeliveryCreditMixin

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")
RESERVED_NAMES = {"all", "system"}  # @all rings everyone; system is the notice sender


def handle_error(handle: str) -> str | None:
    """Return a user-facing validation error, or ``None`` for a valid handle."""
    if not NAME_RE.match(handle):
        return "handle must be alphanumeric ([A-Za-z0-9_.-], max 32)"
    if handle.lower() in RESERVED_NAMES:
        return f"'{handle}' is a reserved handle"
    return None


class ChatRuntime(DeliveryCreditMixin):
    """Own process-local chat state and the behavior that operates on it."""

    def __init__(self, db: Db):
        self.db = db
        self.sockets: dict[str, set] = {}
        self.human_handles: dict[str, dict[WebSocket, tuple[str, str]]] = {}
        self.live: dict[str, Adapter] = {}
        # Manual and restart-plan resumes must never start the same attachment
        # concurrently. Locks are process-local and keyed by durable id.
        self.resume_locks: dict[str, asyncio.Lock] = {}
        # A planned process is queued behind its durable cursor, not unreachable.
        self.reattaching: set[str] = set()
        # Pasted-but-unproved message ids, keyed per activation. Transcript
        # identity releases these for retry; only a paste-specific receipt
        # may advance the durable cursor.
        self.uncredited: dict[str, dict] = {}
        self.unclaimed_noticed: set[str] = set()

    @staticmethod
    def activation_matches(adapter: Adapter, attachment: dict) -> bool:
        """Whether this process-local adapter owns the shared attachment row."""
        return adapter.att.get("runtime_owner") == attachment.get("runtime_owner")

    def running_processes(self) -> list[dict]:
        """Every live attachment, across every line, newest line first.

        Stopping the server stops all of these, so whoever asks for that has to
        be shown the whole list — not just the line they happen to be looking at.
        """
        found = []
        for conv in self.db.list_conversations():
            for att in self.db.list_attachments(conv["id"]):
                adapter = self.live.get(att["id"])
                if (
                    adapter is not None
                    and self.activation_matches(adapter, att)
                    and att["status"] in ("starting", "running")
                ):
                    found.append({"name": att["name"], "adapter": att["adapter"],
                                  "conversation": conv["name"]})
        return found

    async def shutdown(self):
        for adapter in list(self.live.values()):
            try:
                await adapter.stop()
            except Exception:
                pass

    async def broadcast(self, conv_id: str, event: Event):
        payload = event.model_dump(exclude_none=True)
        for ws in list(self.sockets.get(conv_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:
                self.sockets.get(conv_id, set()).discard(ws)
                self.human_handles.get(conv_id, {}).pop(ws, None)
                if not self.human_handles.get(conv_id):
                    self.human_handles.pop(conv_id, None)

    async def broadcast_all(self, event: Event) -> None:
        for conv_id in list(self.sockets):
            await self.broadcast(conv_id, event)

    async def post_message(self, conv_id: str, sender: str, sender_type: str, body: str):
        msg = self.db.add_message(conv_id, sender, sender_type, body)
        await self.broadcast(conv_id, MessageEvent(message=MessageResponse.model_validate(msg)))
        await self.route_mentions(conv_id, msg)
        return msg


    async def broadcast_attachment(self, conv_id: str, att_id: str) -> None:
        """Broadcast live attachment presentation without blocking the event loop."""
        await broadcast_attachment_state(self, conv_id, att_id)

    async def deliver_pending(self, conv_id: str, att: dict, adapter: Adapter) -> bool:
        """Deliver from the durable cursor, advancing it only after a paste.

        An unclaimed transcript adapter may paste to claim its session, but
        that proves identity only. An unadvanced ``last_seen`` is the durable
        record of any paste that has not received its own ingestion proof.
        """
        await self._credit_claimed(att, adapter)
        runtime_owner = adapter.att.get("runtime_owner")
        async with self.db.reserve_attachment_delivery(att["id"], runtime_owner) as reserved:
            if not reserved:
                return False
            current = self.db.get_attachment(att["id"])
            if current is None or current.get("runtime_owner") != runtime_owner:
                return False
            att = current
            pending = self.db.messages_after(
                conv_id, att["last_seen"], att["name"], att["id"]
            )
            ours = self._live_uncredited(att["id"], runtime_owner)
            pending = [m for m in pending if m["id"] not in (ours or ())]
            if not pending:
                return not bool(ours)
            pasted = await adapter.deliver(pending)
            if pasted is False:
                if claims_transcript(adapter.att):
                    self._record_unproved(att, adapter, pending)
                    if not transcript_claimed(adapter):
                        await self._hold_credit(conv_id, att, adapter, pending)
                return False
            if claims_transcript(adapter.att) and not transcript_claimed(adapter):
                await self._hold_credit(conv_id, att, adapter, pending)
                return True
            if not self.db.set_last_seen(att["id"], pending[-1]["id"], runtime_owner):
                raise RuntimeError("attachment ownership changed during mention delivery")
            self.db.clear_queued_delivery_ids(att["id"], [m["id"] for m in pending])
        return True

    def held_wake_hooks(self, conv_id: str, att_id: str, name: str):
        """Persist and flush exact held batches without re-running mention routing."""
        return delivery_hooks(self, conv_id, att_id)

    async def route_mentions(self, conv_id: str, msg: dict, *, force: bool = False):
        await route_message(self, conv_id, msg, force=force)

    def status_callback(self, att_id: str, conv_id: str, runtime_owner: str):
        async def on_status(status: str):
            if not await self.db.set_attachment_status_async(
                att_id, status, runtime_owner
            ):
                return
            if status in ("exited", "detached"):
                adapter = self.live.get(att_id)
                if (
                    adapter is not None
                    and adapter.att.get("runtime_owner") == runtime_owner
                ):
                    self.live.pop(att_id, None)
            await self.broadcast_attachment(conv_id, att_id)

        return on_status

    def post_callback(self, att_id: str, conv_id: str, runtime_owner: str, *, route: bool = True):
        async def post(sender: str, sender_type: str, body: str):
            msg = self.db.add_owned_message(
                att_id, runtime_owner, conv_id, sender, sender_type, body
            )
            if msg is None:
                return
            await self.broadcast(
                conv_id, MessageEvent(message=MessageResponse.model_validate(msg))
            )
            if route:
                await self.route_mentions(conv_id, msg)

        return post

    async def stop_attachments(self, conv_id: str) -> list[str]:
        """Kill every live process on a line. Returns the handles actually stopped."""
        stopped: list[str] = []
        for att in self.db.list_attachments(conv_id):
            adapter = self.live.pop(att["id"], None)
            if adapter is None:
                continue
            stopped.append(att["name"])
            try:
                await adapter.stop()
            except Exception:
                # A pty that refuses to die must not strand the archive: the row is
                # already out of `live`, so nothing can route to it either way.
                await self.db.set_attachment_status_async(
                    att["id"], "exited", adapter.att.get("runtime_owner")
                )
        return stopped

    async def websocket(
        self,
        ws: WebSocket,
        conv_id: str,
        handle: str,
        frontend_build: str,
        server_version: str,
        instance_name: str | None = None,
        reattacher: ReattachCoordinator | None = None,
    ):
        """Serve one authenticated socket. ``handle`` comes from the caller's
        credential, so it is never validated or collision-checked here — two
        sockets with one handle are the same account in two tabs."""
        await ws.accept()
        self.sockets.setdefault(conv_id, set()).add(ws)
        claimed_handle = None
        claimed_client = None
        try:
            while True:
                data = await ws.receive_json()
                if not isinstance(data, dict):
                    await ws.send_json(
                        ErrorEvent(
                            conversation_id=conv_id,
                            message="WebSocket commands must be JSON objects",
                        ).model_dump()
                    )
                    continue
                if data.get("type") == "hello":
                    client_id = str(data.get("client_id", "")).strip()
                    conv = self.db.get_conversation(conv_id)
                    if conv is None or conv["archived_at"]:
                        await ws.send_json(ErrorEvent(
                            conversation_id=conv_id,
                            message="this line is archived — restore it to talk here",
                        ).model_dump())
                        continue
                    # A reconnect can arrive before a half-open old socket times
                    # out. Its durable client id proves it is the same browser, so
                    claims = self.human_handles.setdefault(conv_id, {})
                    if client_id:
                        for other, (_, client) in list(claims.items()):
                            if other is not ws and client == client_id:
                                claims.pop(other)
                                self.sockets.get(conv_id, set()).discard(other)
                                try:
                                    await other.close(code=1000, reason="superseded by reconnect")
                                except Exception:
                                    pass  # a half-open socket cannot be closed cleanly
                    claims[ws] = (handle, client_id)
                    claimed_handle, claimed_client = handle, client_id
                    await ws.send_json(hello_payload(
                        conv_id, handle, frontend_build, server_version, instance_name
                    ))
                    if reattacher is not None and (offer := reattacher.offer(conv_id)):
                        await ws.send_json(offer.model_dump())
                    continue

                # Preserve the useful archived-line error even for an old client
                # which has not yet learned the hello handshake.
                conv = self.db.get_conversation(conv_id)
                if conv is None or conv["archived_at"]:
                    await ws.send_json(
                        ErrorEvent(
                            conversation_id=conv_id,
                            message="this line is archived — restore it to talk here",
                        ).model_dump()
                    )
                    continue
                if claimed_handle is None:
                    await ws.send_json(
                        ErrorEvent(
                            conversation_id=conv_id,
                            message="say hello before sending messages",
                        ).model_dump()
                    )
                    continue
                if self.human_handles.get(conv_id, {}).get(ws) != (claimed_handle, claimed_client):
                    await ws.send_json(
                        ErrorEvent(
                            conversation_id=conv_id,
                            message="this connection was superseded; reconnect to continue",
                        ).model_dump()
                    )
                    continue
                if data.get("type") == "reattach":
                    if reattacher is None:
                        await ws.send_json(
                            ErrorEvent(
                                conversation_id=conv_id,
                                message="reattachment is not available on this server",
                            ).model_dump()
                        )
                        continue
                    error = await reattacher.choose(conv_id, data, claimed_handle)
                    if error is not None:
                        await ws.send_json(
                            ErrorEvent(
                                conversation_id=conv_id,
                                message=error,
                            ).model_dump()
                        )
                    continue
                body = str(data.get("body", "")).strip()
                if not body:
                    continue
                # The sender is the credential's handle; any client-supplied
                # sender field is ignored, so impersonation cannot happen.
                await post_human_message(self, conv_id, claimed_handle, body)
        except WebSocketDisconnect:
            pass
        finally:
            self.sockets.get(conv_id, set()).discard(ws)
            self.human_handles.get(conv_id, {}).pop(ws, None)
            if not self.human_handles.get(conv_id):
                self.human_handles.pop(conv_id, None)
