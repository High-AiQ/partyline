"""Fixed MCP schemas for authorized captain operations."""

def obj(properties=None, required=()):
    return {"type": "object", "properties": properties or {},
            "required": list(required), "additionalProperties": False}


def text(description, maximum=2000, minimum=0):
    return {"type": "string", "description": description, "maxLength": maximum,
            "minLength": minimum}


def schema(name):
    """A short, operation-specific argument schema; no route/method fields exist."""
    line = {"conv_id": text("Authorized target line id.", 80)}
    specs = {
        "staffing": obj(line, ["conv_id"]),
        "write_set_requests": obj(line, ["conv_id"]),
        "list_presets": obj(),
        "attach_worker": obj({**line, "name": text("Exact worker handle.", 32, 1),
            "adapter": text("Exact adapter id.", 80, 1), "command": text("Optional command.", 2000),
            "preset_name": text("Optional exact preset name; read-only match.", 32),
            "allow_shared_branch": {"type": "boolean"}}, ["conv_id", "name", "adapter"]),
        "detach_worker": obj({**line, "attachment_id": text("Attachment id.", 80)},
                              ["conv_id", "attachment_id"]),
        "create_child": obj({**line, "name": text("Child line name.", 120),
            "goal": text("Child goal.", 3000), "topic": text("Child context.", 20000),
            "base": {"type": "string", "enum": ["checkout", "upstream"]},
            "repository": text("Optional repository path.", 4096)}, ["conv_id", "name"]),
        "appoint_lead": obj({**line, "attachment_id": text("Lead attachment id; empty clears lead.", 80)},
                              ["conv_id", "attachment_id"]),
        "retire_child": obj({"conv_id": text("Direct child line id.", 80),
            "stop_processes": {"type": "boolean"}}, ["conv_id"]),
        "accept": obj({**line, "sha": text("Commit SHA.", 64, 4),
            "allow_descendant": {"type": "boolean"}, "findings": {"type": "array",
                "items": text("Review finding.", 300), "maxItems": 20},
            "run_gates": {"type": "boolean"}}, ["conv_id", "sha"]),
        "review_worktree": obj({**line, "sha": text("Commit SHA.", 64, 4),
            "repository": text("Optional subtree repository.", 4096)}, ["conv_id", "sha"]),
        "request_write_set": obj({**line, "path": text("Requested writable path.", 4096)},
                                  ["conv_id", "path"]),
        "decide_write_set": obj({**line, "request_id": text("Pending request id.", 80),
            "decision": {"type": "string", "enum": ["approve", "deny", "withdraw"]},
            "reason": text("Required for deny.", 500)}, ["conv_id", "request_id", "decision"]),
        "request_restart": obj({**line, "reason": text("Reason for a person to review.", 2000, 1),
            "confirm_no_deploy": {"type": "boolean"}}, ["conv_id", "reason"]),
        "process_overview": obj({**line}, ["conv_id"]),
        "ack_report": obj({**line, "report_id": {"type": "integer", "minimum": 1},
            "revision": {"type": "integer", "minimum": 1}}, ["conv_id", "report_id", "revision"]),
        "reports": obj({"operation": {"type": "string", "enum": ["list", "post"]},
            "body": text("Report body for post; at most 2000 characters.", 2000, 1),
            "notify": {"type": "boolean"}}, ["operation"]),
        "set_goal": obj({**line, "goal": text("Goal text; empty clears it.", 3000)},
                        ["conv_id", "goal"]),
        "set_gates": obj({**line, "commands": {"type": "array", "items": text("Gate command.", 2000),
            "maxItems": 20}, "timeout_s": {"type": "integer", "minimum": 1, "maximum": 14400}},
                         ["conv_id", "commands"]),
        "docs_read": obj({"category": text("Guide category.", 100), "topic": text("Guide topic.", 100)}),
    }
    return specs[name]


OPERATIONS = tuple(schema_name for schema_name in (
    "staffing", "write_set_requests", "list_presets", "attach_worker", "detach_worker", "create_child",
    "appoint_lead", "retire_child", "accept", "review_worktree", "request_write_set",
    "decide_write_set", "request_restart", "process_overview", "ack_report", "set_goal",
    "set_gates", "docs_read", "reports"))


def validate(name, args):
    spec = schema(name)
    props = spec["properties"]
    unknown = set(args) - set(props)
    missing = set(spec["required"]) - set(args)
    if unknown or missing:
        raise ValueError("invalid arguments for captain operation")
    for key, value in args.items():
        rule = props[key]
        kind = rule["type"]
        valid = (isinstance(value, str) if kind == "string" else
                 isinstance(value, bool) if kind == "boolean" else
                 isinstance(value, int) and not isinstance(value, bool) if kind == "integer" else
                 isinstance(value, list) if kind == "array" else False)
        if not valid:
            raise ValueError(f"{key} has the wrong type")
        if kind == "string" and (len(value) > rule.get("maxLength", 100000)
                                  or len(value) < rule.get("minLength", 0)):
            raise ValueError(f"{key} exceeds its allowed length")
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError(f"{key} has an unsupported value")
        if kind == "integer" and (value < rule.get("minimum", value)
                                   or value > rule.get("maximum", value)):
            raise ValueError(f"{key} is outside its allowed range")
        if kind == "array":
            item_rule = rule.get("items", {})
            if (len(value) > rule.get("maxItems", 100000)
                    or any(not isinstance(item, str)
                           or len(item) > item_rule.get("maxLength", 100000)
                           for item in value)):
                raise ValueError(f"{key} has invalid items")
    return args
