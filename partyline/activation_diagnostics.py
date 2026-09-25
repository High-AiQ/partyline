"""Safe, short diagnostics for a live attachment activation."""

from datetime import UTC, datetime
import hashlib


def activation_context(runtime, attachment: dict) -> str:
    adapter = runtime.live.get(attachment["id"])
    owner = attachment.get("runtime_owner") or getattr(adapter, "att", {}).get(
        "runtime_owner"
    )
    details = []
    if started_at := attachment.get("runtime_started_at"):
        started = datetime.fromtimestamp(started_at, UTC).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        details.append(f"started {started}")
    if owner:
        generation = hashlib.sha256(owner.encode()).hexdigest()[:8]
        details.append(f"generation {generation}")
    return f" ({', '.join(details)})" if details else ""


def line_name(db, conv_id: str) -> str:
    conversation = db.get_conversation(conv_id)
    return conversation["name"] if conversation is not None else conv_id
