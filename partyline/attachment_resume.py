"""Resume one attachment, including its server-owned delivery history.

The server used to hold this orchestration inline while ``server.py`` sat on
its grandfathered line cap.  Keeping it here both removes that debt and makes
the replay boundary explicit: a resumable adapter receives the ordered bodies
this exact attachment actually delivered, not an inferred position in a file
owned by its CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import uuid

from fastapi import HTTPException

from .adapter_capabilities import adapter_completion
from .auth_store import ensure_api_token
from .reattach import ResumedAttachment, adapter_can_resume
from .transcript_delivery import TranscriptDeliveryRecord


@dataclass(frozen=True)
class DeliveryHistory:
    """Normal speech order plus resume records delivered out of that order."""

    bodies: list[str]
    transcript_records: list[TranscriptDeliveryRecord]
    legacy_relayed_bodies: list[str]


def delivered_history(db, attachment: dict) -> DeliveryHistory:
    """Delivery evidence for one attachment lifetime.

    Resume backlog is deliberately excluded from ``bodies``: it reaches chat
    later than its position in the transcript, so mixing it into that ordered
    sequence makes the next alignment replay the same record. New deliveries
    carry an exact fingerprint. The notice parser recovers markers written by
    older Partyline versions so an already-looping attachment heals on upgrade.
    """
    with db.lock:
        rows = db.conn.execute(
            "SELECT m.sender,m.sender_type,m.body,t.fingerprint "
            "FROM messages m LEFT JOIN transcript_delivery_records t "
            "ON t.attachment_id=? AND t.message_id=m.id "
            "WHERE m.conv_id=? AND m.created_at>=? ORDER BY m.id",
            (
                attachment["id"],
                attachment["conv_id"],
                attachment["created_at"],
            ),
        ).fetchall()
    bodies: list[str] = []
    transcript_records: list[TranscriptDeliveryRecord] = []
    legacy: list[str] = []
    remaining = 0
    notice = re.compile(
        rf"^@?{re.escape(attachment['name'])}: relaying (\d+) message\(s\) that never "
    )
    resume_notice = f"@{attachment['name']} resumed with full context"
    for row in rows:
        if row["sender_type"] == "system":
            if row["body"].startswith(resume_notice):
                remaining = 0  # an interrupted flush cannot claim later speech
            elif match := notice.match(row["body"]):
                remaining = int(match.group(1))
            continue
        if row["sender_type"] != "agent" or row["sender"] != attachment["name"]:
            continue
        if remaining:
            remaining -= 1
            if row["fingerprint"] is None:
                legacy.append(row["body"])
            else:
                transcript_records.append(TranscriptDeliveryRecord(
                    bytes(row["fingerprint"]), row["body"]
                ))
        elif row["fingerprint"] is None:
            bodies.append(row["body"])
        else:
            transcript_records.append(TranscriptDeliveryRecord(
                bytes(row["fingerprint"]), row["body"]
            ))
    return DeliveryHistory(bodies, transcript_records, legacy)


def delivered_bodies(db, attachment: dict) -> list[str]:
    """Backward-compatible view of normally ordered agent speech."""
    return delivered_history(db, attachment).bodies


def mark_transcript_delivery(
    db, attachment: dict, runtime_owner: str, fingerprint: bytes, body: str
) -> bool:
    """Bind the latest owned chat post to the transcript record it relayed."""
    with db.lock:
        inserted = db.conn.execute(
            "INSERT OR IGNORE INTO transcript_delivery_records "
            "(attachment_id,message_id,fingerprint) "
            "SELECT ?,m.id,? FROM messages m JOIN attachments a ON a.id=? "
            "WHERE a.runtime_owner IS ? AND m.conv_id=a.conv_id "
            "AND m.sender=a.name AND m.sender_type='agent' AND m.body=? "
            "AND m.created_at>=a.created_at ORDER BY m.id DESC LIMIT 1",
            (
                attachment["id"], fingerprint, attachment["id"],
                runtime_owner, body,
            ),
        )
        db.conn.commit()
    return inserted.rowcount == 1


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
    history = delivered_history(runtime.db, att)
    att["delivered_bodies"] = history.bodies
    att["delivered_transcript_records"] = history.transcript_records
    att["legacy_relayed_bodies"] = history.legacy_relayed_bodies
    att["mark_transcript_delivery"] = lambda fingerprint, body: mark_transcript_delivery(
        runtime.db, att, runtime_owner, fingerprint, body
    )
    att["post_resume_record"] = presence.posting(
        conv["id"], att_id,
        runtime.post_callback(att_id, conv["id"], runtime_owner, route=False),
    )

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
    runtime.live[att_id] = presence.watch(
        adapter, att["conv_id"], att_id, adapter_completion(att["adapter"]),
        *runtime.held_wake_hooks(att["conv_id"], att_id, att["name"]),
    )

    await runtime.post_message(
        att["conv_id"],
        "system",
        "system",
        f"@{att['name']} resumed with full context · "
        f"session {att.get('cli_session') or att_id}",
    )
    return ResumedAttachment(adapter, startup_staged)
