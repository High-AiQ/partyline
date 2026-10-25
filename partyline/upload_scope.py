"""Upload-only access from a task worker to its root captain's line."""


UPLOAD_ONLY_CAPTION_REFUSAL = "upload-only access to this line cannot carry a caption"


def task_root_upload(db, principal, conv_id: str) -> bool:
    """The task's root_id grants uploads only, never general line writes."""
    if principal.kind != "machine" or not principal.conv_id:
        return False
    from .orchestrator_store import task

    row = task(db, principal.conv_id)
    return bool(row and conv_id == row["root_id"])
