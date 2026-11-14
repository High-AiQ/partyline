"""``bridge_send``: speak to the counterpart over this line's open bridge."""

from urllib.parse import quote

from .client import ApiError
from .validation import validate_arguments

NAME = "bridge_send"
DESCRIPTION = (
    "Send text to your counterpart over this line's open bridge. Only the ambassador of a line "
    "with an open bridge has it. It goes only to the peer (people read it in the bridge log, "
    "never in chat), so your normal final message stays free for your own line's people. "
    "Returns delivered, or queued when the peer is not attached. Text only, rate limited.")


def tool_list(state):
    if not state.get("bridge_open"):
        return []
    return [{"name": NAME, "description": DESCRIPTION, "inputSchema": {
        "type": "object", "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": 10000,
                     "description": "What to say to the peer; plain text."},
            "client_key": {"type": "string", "minLength": 1, "maxLength": 64,
                           "description": "Stable retry key, 1 to 64 characters."}},
        "required": ["text", "client_key"], "additionalProperties": False}}]


def call(client, name, args, state):
    available = {tool["name"]: tool for tool in tool_list(state)}
    if name not in available:
        raise ApiError("no open bridge: bridge_send is for the ambassador of a line with an open bridge")
    validate_arguments(available[name]["inputSchema"], args)
    return client.request("POST", f"/api/conversations/{quote(client.home, safe='')}/bridge-send",
                          {"text": args["text"], "client_key": args["client_key"]})
