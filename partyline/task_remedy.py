"""The exact way to reach a task's worker from outside its line."""

from .orchestrator_store import attachment_task


def task_role(db, attachment_id: str):
    """``(task row, role)`` of the task this process staffs, or None."""
    row = attachment_task(db, attachment_id)
    if row is None:
        return None
    return row, "reviewer" if row["reviewer_id"] == attachment_id else "implementer"


def message_task_call(row: dict, role: str) -> str:
    return f"message_task(conv_id={row['conv_id']}, text, to='{role}')"


def task_remedy(db, target: dict) -> str:
    """A sentence tail naming the call that reaches ``target``, when it is a task worker."""
    found = task_role(db, target["id"])
    return f"; {message_task_call(*found)} reaches it" if found else ""
