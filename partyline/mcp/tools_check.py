"""Render checks: ask a hosted decision model which renders need a closer look (needs consent)."""

from urllib.parse import quote

from .client import ApiError
from .validation import validate_arguments

NOTE = (" Only renders produced by a render call in your current local tools session can be checked, and "
        "only if the person allowed render checks for it (ask with checker=true). The images are sent to "
        "OpenAI.")
DESCRIPTION = (
    "Find which renders need a closer look before you fetch any of them. Give the file ids of renders and "
    "questions written as PROBLEM STATEMENTS in plain words, so that yes means something is wrong (for "
    "example \"The lamp visibly intersects the table.\" or \"Part of the sofa is cut off by the frame "
    "edge.\"). Each render is checked against every question; the reply gives a verdict per render: pass "
    "(confidently fine, you may skip it), flag, uncertain or unchecked (look at these with get_media; "
    "unchecked means the check could not run, so nothing is known). The model is told to answer 'not sure' "
    "when the image does not settle a question. `compare` picks the best of 2-6 variants (A, B, ... in the "
    "order given) or abstains. `evidence` (JSON, 16 KB) is any scene facts you measured, such as the "
    "geometry report from the scene tool's project_to_camera; a `reference` render the result should match "
    "may be added. A budget limits checks per session." + NOTE)
ID = {"type": "string", "minLength": 1, "maxLength": 80}


def tool_list(state):
    if "write" not in set(state.get("actions", [])):
        return []
    properties = {
        "media": {"type": "array", "minItems": 1, "maxItems": 12, "items": ID,
                  "description": "File ids returned by your render calls."},
        "questions": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 500},
                      "description": "Problem statements; yes means a problem."},
        "compare": {"type": "string", "maxLength": 500,
                    "description": "A question that picks one of 2-6 media, e.g. which matches the brief."},
        "reference": {**ID, "description": "File id of a render the result should match."},
        "evidence": {"type": "object", "description": "Scene facts as JSON, at most 16 KB."}}
    return [{"name": "render_check", "description": DESCRIPTION, "inputSchema": {
        "type": "object", "properties": properties, "required": ["media"], "additionalProperties": False}}]


def call(client, name, args, state):
    available = {tool["name"]: tool for tool in tool_list(state)}
    if name not in available:
        raise ApiError("render checks need write access to your line")
    validate_arguments(available[name]["inputSchema"], args)
    base = f"/api/conversations/{quote(client.home, safe='')}/local-tools"
    return client.request("POST", base + "/render-check", args, timeout=180)
