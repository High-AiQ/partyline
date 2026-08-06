"""Live chat state and behavior underneath the HTTP/WebSocket routes."""

import re

from fastapi import WebSocket, WebSocketDisconnect

from .adapters import Adapter
from .contracts import (
    AttachmentEvent,
    AttachmentResponse,
    Event,
    ErrorEvent,
    HelloEvent,
    MessageEvent,
    MessageResponse,
)
from .db import Db
from .reattach import ReattachCoordinator

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")
MENTION_RE = re.compile(r"@([A-Za-z0-9][A-Za-z0-9_.-]*)")
RESERVED_NAMES = {"all", "system"}  # @all rings everyone; system is the notice sender


def handle_error(handle: str) -> str | None:
    """Return a user-facing validation error, or ``None`` for a valid handle."""
    if not NAME_RE.match(handle):
        return "handle must be alphanumeric ([A-Za-z0-9_.-], max 32)"
    if handle.lower() in RESERVED_NAMES:
        return f"'{handle}' is a reserved handle"
    return None


class ChatRuntime:
    """Own process-local chat state and the behavior that operates on it."""

    def __init__(self, db: Db):
        self.db = db
        self.sockets: dict[str, set] = {}
        self.human_handles: dict[str, dict[WebSocket, tuple[str, str]]] = {}
        self.live: dict[str, Adapter] = {}
        # A planned process is queued behind its durable cursor, not unreachable.
        self.reattaching: set[str] = set()

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

    async def post_message(self, conv_id: str, sender: str, sender_type: str, body: str):
        msg = self.db.add_message(conv_id, sender, sender_type, body)
        await self.broadcast(conv_id, MessageEvent(message=MessageResponse.model_validate(msg)))
        await self.route_mentions(conv_id, msg)
        return msg

    async def route_mentions(self, conv_id: str, msg: dict):
        if msg["sender_type"] == "system":
            return  # join/exit notices mention names but must never wake agents
        # Accept both a punctuation-bearing handle and its sentence-ending reading.
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
        queued: set[str] = set()
        for att in self.db.list_attachments(conv_id):
            addressed = ring_all or att["name"].lower() in names
            if not addressed or att["name"].lower() == msg["sender"].lower():
                continue  # not for them, or no self-pings
            adapter = self.live.get(att["id"]) if att["status"] == "running" else None
            if adapter is not None and not self.activation_matches(adapter, att):
                # Another server generation owns the running row. This runtime
                # must neither wake its obsolete local process nor report the
                # handle as unavailable; the current owner is authoritative.
                queued.add(att["name"].lower())
                continue
            if adapter is None:
                if att["id"] in self.reattaching:
                    queued.add(att["name"].lower())
                    continue
                # The process is gone but the mention looked like it landed. Say so:
                # a silently dropped mention is indistinguishable from an agent that
                # simply chose not to answer, and can go unnoticed for hours.
                if not ring_all and att["name"] not in unreachable:
                    unreachable.append(att["name"])
                continue
            pending = self.db.messages_after(conv_id, att["last_seen"], exclude_sender=att["name"])
            if pending:
                runtime_owner = adapter.att.get("runtime_owner")
                async with self.db.reserve_attachment_delivery(
                    att["id"], runtime_owner
                ) as reserved:
                    if not reserved:
                        # Ownership changed after the attachment snapshot was
                        # read. The current generation will route from the
                        # durable cursor; never paste into this stale pty.
                        queued.add(att["name"].lower())
                        continue
                    delivered.add(att["name"].lower())
                    await adapter.deliver(pending)
                    if not self.db.set_last_seen(
                        att["id"], pending[-1]["id"], runtime_owner
                    ):
                        raise RuntimeError(
                            "attachment ownership changed during mention delivery"
                        )

        # A handle can have several rows — old detached ones alongside a live one.
        # Only warn about handles that got no delivery at all.
        unavailable = [name for name in unreachable
                       if name.lower() not in delivered and name.lower() not in queued]
        for name in unavailable:
            # A system notice never wakes anyone, so this cannot loop.
            await self.post_message(
                conv_id,
                "system",
                "system",
                f"⚠ @{name} was mentioned but is not attached — nothing was delivered",
            )

    def status_callback(self, att_id: str, conv_id: str, runtime_owner: str):
        async def on_status(status: str):
            if not await self.db.set_attachment_status_async(
                att_id, status, runtime_owner
            ):
                return
            att = self.db.get_attachment(att_id)
            await self.broadcast(
                conv_id, AttachmentEvent(attachment=AttachmentResponse.model_validate(att)))

        return on_status

    def post_callback(
        self, att_id: str, conv_id: str, runtime_owner: str
    ):
        async def post(sender: str, sender_type: str, body: str):
            msg = self.db.add_owned_message(
                att_id, runtime_owner, conv_id, sender, sender_type, body
            )
            if msg is None:
                return
            await self.broadcast(
                conv_id, MessageEvent(message=MessageResponse.model_validate(msg))
            )
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

    def attachment_handle_taken(self, conv_id: str, handle: str) -> bool:
        """Whether a live process already owns ``handle`` on this line."""
        return any(
            att["name"].lower() == handle.lower() and att["status"] in ("starting", "running")
            for att in self.db.list_attachments(conv_id)
        )

    async def websocket(
        self,
        ws: WebSocket,
        conv_id: str,
        frontend_build: str,
        server_version: str,
        reattacher: ReattachCoordinator | None = None,
    ):
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
                    handle = str(data.get("handle", "")).strip()
                    client_id = str(data.get("client_id", "")).strip()
                    conv = self.db.get_conversation(conv_id)
                    error = handle_error(handle)
                    if conv is None or conv["archived_at"]:
                        error = "this line is archived — restore it to talk here"
                    elif not error and self.attachment_handle_taken(conv_id, handle):
                        error = "that handle is taken by a running process on this line"
                    elif not error and any(
                        other is not ws and name.lower() == handle.lower()
                        and (not client_id or client != client_id)
                        for other, (name, client) in self.human_handles.get(conv_id, {}).items()
                    ):
                        error = "that handle is taken by another human on this line"
                    if error:
                        await ws.send_json(
                            ErrorEvent(conversation_id=conv_id, message=error).model_dump())
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
                    await ws.send_json(
                        HelloEvent(
                            conversation_id=conv_id,
                            handle=handle,
                            build=frontend_build or None,
                            version=server_version,
                        ).model_dump(exclude_none=True)
                    )
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
                            message="choose a handle before sending messages",
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
                sender = str(data.get("sender", "")).strip()
                if sender != claimed_handle:
                    await ws.send_json(
                        ErrorEvent(
                            conversation_id=conv_id,
                            message="messages must use your claimed handle",
                        ).model_dump()
                    )
                    continue
                body = str(data.get("body", "")).strip()
                if not body:
                    continue
                await self.post_message(conv_id, sender, "human", body)
        except WebSocketDisconnect:
            pass
        finally:
            self.sockets.get(conv_id, set()).discard(ws)
            self.human_handles.get(conv_id, {}).pop(ws, None)
            if not self.human_handles.get(conv_id):
                self.human_handles.pop(conv_id, None)
