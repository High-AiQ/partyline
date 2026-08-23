"""Resume one attachment, including its server-owned delivery history.

The server used to hold this orchestration inline while ``server.py`` sat on
its grandfathered line cap.  Keeping it here both removes that debt and makes
the replay boundary explicit: a resumable adapter receives the ordered bodies
this exact attachment actually delivered, not an inferred position in a file
owned by its CLI.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException

from .adapter_capabilities import adapter_completion
from .auth_store import ensure_api_token
from .reattach import ResumedAttachment, adapter_can_resume


def delivered_bodies(db, attachment: dict) -> list[str]:
    """Agent speech persisted for this attachment's name and lifetime."""
    with db.lock:
        rows = db.conn.execute(
            "SELECT body FROM messages WHERE conv_id=? AND sender=? "
            "AND sender_type='agent' AND created_at>=? ORDER BY id",
            (
                attachment["conv_id"],
                attachment["name"],
                attachment["created_at"],
            ),
        ).fetchall()
    return [row["body"] for row in rows]


async def resume_adapter(
    att_id: str,
    startup_messages: list[dict] | None,
    *,
    runtime,
    adapter_metadata,
    make_adapter,
    presence,
    tasks,
    hook_url,
) -> ResumedAttachment:
    att = runtime.db.get_attachment(att_id)
    if not att:
        raise HTTPException(404)
    if att["status"] in ("starting", "running") or att_id in runtime.live:
        raise HTTPException(409, f"'{att['name']}' is already live")
    capabilities = adapter_metadata.get(att["adapter"], {})
    if not adapter_can_resume(capabilities):
        raise HTTPException(400, f"the {att['adapter']} adapter has no session to resume")
    for other in runtime.db.list_attachments(att["conv_id"]):
        if (
            other["name"].lower() == att["name"].lower()
            and other["status"] in ("starting", "running")
        ):
            raise HTTPException(409, f"'{att['name']}' is already attached")

    conv = runtime.db.get_conversation(att["conv_id"])
    if conv["archived_at"]:
        raise HTTPException(409, "restore the line before resuming its processes")
    att["conv_name"] = conv["name"]
    att["resume"] = True
    # The activation is minted before the hook URL because the URL carries it
    # as a capability: a resumed process must get this generation's token, not
    # the one the previous activation's harness was configured with.
    runtime_owner = str(uuid.uuid4())
    att["runtime_owner"] = runtime_owner
    # The machine token, unlike the activation owner, is stable on purpose:
    # a resumed process keeps the PARTYLINE_TOKEN its briefing already named.
    att["api_token"] = ensure_api_token(runtime.db, att_id)
    att["hook_url"] = hook_url(att_id, runtime_owner)
    att["digest_rider"] = lambda: tasks.rider(att["conv_id"])
    att["delivered_bodies"] = delivered_bodies(runtime.db, att)

    adapter = make_adapter(
        att["adapter"],
        att,
        presence.posting(
            conv["id"],
            att_id,
            runtime.post_callback(att_id, conv["id"], runtime_owner),
        ),
        presence.statusing(
            conv["id"],
            att_id,
            runtime.status_callback(att_id, conv["id"], runtime_owner),
            name=att.get("name", ""),
        ),
        on_cli_session=lambda session: runtime.db.set_cli_session(
            att_id, session, runtime_owner
        ),
    )
    startup_staged = adapter.stage_startup_delivery(startup_messages or [])
    if not await runtime.db.claim_attachment_async(att_id, runtime_owner):
        raise HTTPException(409, f"'{att['name']}' is already live")
    try:
        await adapter.start()
    except Exception as exc:
        await runtime.db.set_attachment_status_async(att_id, "exited", runtime_owner)
        raise HTTPException(500, f"failed to resume: {exc}") from exc
    async def flush_held() -> bool:
        current = runtime.db.get_attachment(att_id)
        live = runtime.live.get(att_id)
        return bool(current and live and await runtime.deliver_pending(att["conv_id"], current, live))

    def pending_count() -> int:
        current = runtime.db.get_attachment(att_id)
        if current is None:
            return 0
        return len(
            runtime.db.messages_after(
                att["conv_id"], current["last_seen"], exclude_sender=att["name"]
            )
        )

    runtime.live[att_id] = presence.watch(
        adapter, att["conv_id"], att_id, adapter_completion(att["adapter"]), flush_held, pending_count
    )

    await runtime.post_message(
        att["conv_id"],
        "system",
        "system",
        f"@{att['name']} resumed with full context · "
        f"session {att.get('cli_session') or att_id}",
    )
    return ResumedAttachment(adapter, startup_staged)
