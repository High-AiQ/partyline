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
        "resources": obj({**line, "operation": {"type": "string",
            "enum": ["list", "declare", "remove"]}, "name": text("Resource name.", 64, 1)},
            ["conv_id", "operation"]),
        "staffing": obj(line, ["conv_id"]),
        "write_set_requests": obj(line, ["conv_id"]),
        "list_presets": obj(),
        "kernel_log": obj({"boot": {"type": "string", "enum": ["previous", "current"]},
                           "lines": {"type": "integer", "minimum": 1, "maximum": 300}}),
        "attach_worker": obj({**line, "name": text("Exact worker handle.", 32, 1),
            "adapter": text("Exact adapter id.", 80, 1), "command": text("Optional command.", 2000),
            "preset_name": text("Optional exact preset name; read-only match.", 32),
            "counts_toward_total": {"type": "boolean"},
            "allow_shared_branch": {"type": "boolean"}}, ["conv_id", "name", "adapter"]),
        "detach_worker": obj({**line, "attachment_id": text(
            "Attachment id, or a process handle on that line such as impl-48da9d.", 80)},
            ["conv_id", "attachment_id"]),
        "create_child": obj({**line, "name": text("Child line name.", 120),
            "goal": text("Child goal.", 3000), "topic": text("Child context.", 20000),
            "base": {"type": "string", "enum": ["checkout", "upstream"]},
            "repository": text("Optional repository path.", 4096)}, ["conv_id", "name"]),
        "appoint_lead": obj({**line, "attachment_id": text(
            "Lead attachment id or handle on that line; empty clears lead.", 80)},
            ["conv_id", "attachment_id"]),
        "retirement_preview": obj({**line, "include_children": {"type": "boolean"}}, ["conv_id"]),
        "retire_child": obj({"conv_id": text("Child id; root captains may target any strict descendant.", 80),
            **{key: {"type": "boolean"} for key in
               ("stop_processes", "clear_goal", "include_children", "discard", "force_discard")},
            "preview_token": text("Echo retirement_preview token for force_discard.", 64)}, ["conv_id"]),
        "accept": obj({**line, "sha": text("Commit SHA.", 64, 4),
            "allow_descendant": {"type": "boolean"}, "findings": {"type": "array",
                "items": text("Review finding.", 300), "maxItems": 20},
            "run_gates": {"type": "boolean"}}, ["conv_id", "sha"]),
        "review_worktree": obj({**line, "sha": text("Commit SHA.", 64, 4),
            "repository": text("Optional subtree repository.", 4096)}, ["conv_id", "sha"]),
        "share_ref": obj({**line,
            "ref_or_sha": text("Commit or branch to share with a running task.", 2000),
            "name": text("Shared ref name: letters, digits, dot, underscore or dash.", 64, 1),
            "repository": text("Optional task workspace repository.", 4096),
            "replace": {"type": "boolean"}}, ["conv_id", "ref_or_sha", "name"]),
        "request_write_set": obj({**line, "path": text("Requested writable path.", 4096)},
                                  ["conv_id", "path"]),
        "decide_write_set": obj({**line, "request_id": text("Pending request id.", 80),
            "decision": {"type": "string", "enum": ["approve", "deny", "withdraw"]},
            "reason": text("Required for deny.", 500)}, ["conv_id", "request_id", "decision"]),
        "request_restart": obj({**line, "reason": text("Reason for a person to review.", 2000, 1),
            "confirm_no_deploy": {"type": "boolean"}}, ["conv_id", "reason"]),
        "process_overview": obj({**line}, ["conv_id"]),
        "ack_report": obj({**line, "conv_id": text(
                "Your line, or a child line you captain; its reports ack on yours.", 80),
            "report_id": {"type": "integer", "minimum": 1},
            "revision": {"type": "integer", "minimum": 1}}, ["conv_id", "report_id", "revision"]),
        "reports": obj({"operation": {"type": "string", "enum": ["list", "get", "post"]},
            "report_id": {"type": "integer", "minimum": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            "before_id": {"type": "integer", "minimum": 1},
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
    "resources", "staffing", "write_set_requests", "list_presets", "attach_worker", "detach_worker",
    "create_child", "appoint_lead", "retire_child", "retirement_preview", "accept", "review_worktree",
    "share_ref", "request_write_set",
    "decide_write_set", "request_restart", "process_overview", "ack_report", "set_goal",
    "set_gates", "docs_read", "reports", "kernel_log"))


ACK_HINT = "acknowledging a report is the captain op ack_report(conv_id, report_id, revision)"


def validate(name, args):
    spec = schema(name)
    props = spec["properties"]
    unknown = set(args) - set(props)
    missing = set(spec["required"]) - set(args)
    if unknown or missing:
        parts = []
        if unknown:
            parts.append("unknown field(s) " + ", ".join(sorted(unknown)))
        if missing:
            parts.append("missing required field(s) " + ", ".join(sorted(missing)))
        parts.append("accepted fields: " + ", ".join(props))
        raise ValueError(f"captain op '{name}': " + "; ".join(parts))
    for key, value in args.items():
        rule = props[key]
        kind = rule["type"]
        valid = (isinstance(value, str) if kind == "string" else
                 isinstance(value, bool) if kind == "boolean" else
                 isinstance(value, int) and not isinstance(value, bool) if kind == "integer" else
                 isinstance(value, list) if kind == "array" else False)
        if not valid:
            raise ValueError(f"captain op '{name}': {key} has the wrong type")
        if kind == "string" and (len(value) > rule.get("maxLength", 100000)
                                  or len(value) < rule.get("minLength", 0)):
            raise ValueError(f"captain op '{name}': {key} exceeds its allowed length")
        if "enum" in rule and value not in rule["enum"]:
            allowed = ", ".join(rule["enum"])
            hint = (f"; {ACK_HINT}" if name == "reports" and key == "operation" else "")
            raise ValueError(f"captain op '{name}': {key} must be one of {allowed}{hint}")
        if kind == "integer" and (value < rule.get("minimum", value)
                                   or value > rule.get("maximum", value)):
            raise ValueError(f"captain op '{name}': {key} is outside its allowed range")
        if kind == "array":
            item_rule = rule.get("items", {})
            if (len(value) > rule.get("maxItems", 100000)
                    or any(not isinstance(item, str)
                           or len(item) > item_rule.get("maxLength", 100000)
                           for item in value)):
                raise ValueError(f"captain op '{name}': {key} has invalid items")
    return args
