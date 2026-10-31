"""The worker guide: live non-captain tools and the route to curated docs."""

from . import tools_handover, tools_resources, tools_tasks


def guide(state: dict) -> dict:
    """Return every non-captain tool available to this attachment right now."""
    from . import tools_core

    return {
        "title": "Partyline worker guide",
        "description": "Live permission-filtered tools for implementers, reviewers, and participants.",
        "tools": (tools_core.tool_list(state) + tools_tasks.tool_list(state)
                  + tools_resources.tool_list(state) + tools_handover.tool_list(state)),
        "docs": {
            "index": "GET /api/docs",
            "topic": 'guide(category="<category>", topic="<topic>")',
        },
    }
