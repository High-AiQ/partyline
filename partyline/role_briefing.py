"""Only managers receive hierarchy API instructions; permissions remain server-owned."""

from collections.abc import Collection


def role_instructions(actions: Collection[str], conv_id: str, parent_id: str | None) -> str:
    """Render knowledge for the capabilities actually granted on this line."""
    if "create_child" not in actions:
        return ""
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
    blocks.append(
        "Keep budget, acceptance, artifact ownership, and checkpoint responsibilities explicit. "
        "Do not start a paid wave or restart processes merely because an endpoint is available."
    )
    return "\n\n## Manager tools\n" + "\n\n".join(blocks)
