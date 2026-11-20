"""Build captain attach requests from the tool's fixed set of choices."""

from ..preset_traits import is_emitter


def attach_request(client, args):
    body = {key: args[key] for key in ("name", "adapter")}
    body["command"] = args.get("command", "")
    body.update({key: args[key] for key in ("counts_toward_total", "allow_shared_branch",
                "successor", "staffing_role", "model", "effort") if key in args})
    preset_name = args.get("preset_name")
    emitter = body["adapter"] == "raw"
    if preset_name:
        body["preset_name"] = preset_name
        presets = client.request("GET", "/api/presets")
        matches = [item for item in presets if item.get("name") == preset_name]
        if len(matches) != 1 or matches[0].get("adapter") != body["adapter"]:
            raise ValueError("preset_name must exactly match one preset with this adapter")
        emitter = is_emitter(matches[0])
        if not body["command"]:
            body["command"] = matches[0].get("command", "")
    role = body.get("staffing_role", "emitter" if emitter else "implementer")
    capability = "attach_emitter" if role == "emitter" and not body.get("successor") else "attach"
    return body, capability
