"""Only managers receive hierarchy API instructions; permissions remain server-owned."""

from collections.abc import Collection


def _line_people_url(conv_id: str) -> str:
    return f"GET /api/conversations/{conv_id} lists every process on the line by name and ID."


def role_instructions(actions: Collection[str], conv_id: str, parent_id: str | None) -> str:
    """Render knowledge for the capabilities actually granted on this line."""
    if "create_child" not in actions:
        if "appoint_lead" not in actions:
            return ""
        # A line with no live manager: any process on it may hand the role to a
        # named replacement, which is how a person's "B takes the lead" works.
        return (
            "\n\n## Manager handoff\n"
            "This line has no live manager. If the person asks you to appoint one, "
            f"{_line_people_url(conv_id)} and then POST "
            f'/api/conversations/{conv_id}/lead with JSON {{"attachment_id":"<the process ID>"}}.'
        )
    root = f"/api/conversations/{conv_id}"
    blocks = [
        "You manage this line and its delegated child projects. Use the authenticated API helper "
        "from your briefing; `request GET /api/capabilities` shows your current permissions.",
        f'Create a child with POST {root}/children and JSON {{"name":"project name"}}. '
        "The returned conversation ID is the explicit destination for later actions.",
    ]
    if "attach" in actions:
        blocks.append(
            "On an authorized descendant, POST /api/conversations/<child-id>/attachments with "
            "the chosen preset's name, adapter, command, and cwd. Preserve the user's presets."
        )
    if "appoint_lead" in actions:
        blocks.append(
            'Designate a child manager with POST /api/conversations/<child-id>/lead and '
            'JSON {"attachment_id":"the attached process ID"}.'
        )
    if "assign" in actions:
        blocks.append(
            'Send a named assignment with POST /api/conversations/<child-id>/messages and '
            'JSON {"body":"@handle the concrete assignment"}. Mentions reach only that destination line.'
        )
    if "read_reports" in actions:
        blocks.append(
            f"Pull child reports with GET {root}/reports. Inspect the latest report before "
            f'acknowledging it with POST {root}/reports/<report-id>/ack and JSON {{"revision":N}}, '
            "where N is the revision you read. A 409 means read the update before retrying. "
            "Receipt is not acceptance of the child's work."
        )
    if parent_id and "report" in actions:
        blocks.append(
            f'You are also a child manager. POST {root}/reports with JSON {{"body":"status"}} '
            "deposits a routine report without waking your parent. For a completed result, question, "
            'or blocker needing attention, explicitly set "notify":true. Updates coalesce while '
            "attention is pending. Check notified_at: null means notification has not completed; "
            "retry when the parent manager is available. "
            "Do not notify for acknowledgments or routine chatter."
        )
    if parent_id is None:
        blocks.append(
            "You are the root manager, so you may run a heartbeat on yourself: a timer that "
            "reminds you to work your inbox while a goal is in progress. Enable it with "
            'POST /api/heartbeat and JSON {"interval_seconds":900,"goal":"what you are seeing '
            'through"} — the interval is 60-3600 seconds. GET /api/heartbeat shows whether it '
            "is on, the interval, when the next reminder is due, and whether one is still "
            "undelivered. Only one reminder is ever outstanding, and it is delivered like any "
            "other message. It needs no reply when nothing is waiting, and it authorizes no "
            "spending, rendering, or deployment. Turn it off with DELETE /api/heartbeat once "
            "the goal is met — it will not decide that for you, and an idle room is not "
            "evidence the work is done."
        )
    blocks.append(
        "Keep budget, acceptance, artifact ownership, and checkpoint responsibilities explicit. "
        "Do not start a paid wave or restart processes merely because an endpoint is available."
    )
    return "\n\n## Manager tools\n" + "\n\n".join(blocks)
