"""Resolve attachments another resume path brought back first."""

from .activation_diagnostics import activation_context, line_name


def is_live(runtime, attachment_id: str) -> bool:
    attachment = runtime.db.get_attachment(attachment_id)
    adapter = runtime.live.get(attachment_id)
    if (
        attachment is None
        or adapter is None
        or attachment["status"] not in ("starting", "running")
    ):
        return False
    matches = getattr(runtime, "activation_matches", None)
    return matches(adapter, attachment) if matches is not None else True


async def report_live(runtime, attachment_id: str, line: str, name: str) -> bool:
    if not is_live(runtime, attachment_id):
        return False
    attachment = runtime.db.get_attachment(attachment_id)
    runtime.reattaching.discard(attachment_id)
    await runtime.post_message(
        line,
        "system",
        "system",
        f"☏ @{name} is already live on line '{line_name(runtime.db, line)}'; "
        f"treating it as ready and skipping resume{activation_context(runtime, attachment)}",
    )
    return True


async def report_live_refusal(runtime, exc, attachment_id: str, line: str, name: str) -> bool:
    if (
        getattr(exc, "status_code", None) != 409
        or "is already live" not in str(getattr(exc, "detail", ""))
    ):
        return False
    return await report_live(runtime, attachment_id, line, name)


async def abandon(runtime, attachment_id: str) -> None:
    adapter = runtime.live.pop(attachment_id, None)
    if adapter is None:
        return
    try:
        await adapter.stop()
    except Exception:
        await runtime.db.set_attachment_status_async(
            attachment_id, "exited", adapter.att.get("runtime_owner")
        )


async def mark_unlive_exited(
    runtime, attachment_ids: list[str], expected_owners: dict[str, str | None]
) -> None:
    """Free planned handles whose current-generation adapter did not survive."""
    for attachment_id in attachment_ids:
        attachment = runtime.db.get_attachment(attachment_id)
        adapter = runtime.live.get(attachment_id)
        if attachment is None or is_live(runtime, attachment_id):
            continue
        if attachment["runtime_owner"] != expected_owners.get(attachment_id):
            continue
        if adapter is not None and adapter.att.get("runtime_owner") == attachment["runtime_owner"]:
            continue
        if attachment["status"] in ("starting", "running"):
            await runtime.db.set_attachment_status_async(
                attachment_id, "exited", attachment["runtime_owner"]
            )
        runtime.reattaching.discard(attachment_id)
