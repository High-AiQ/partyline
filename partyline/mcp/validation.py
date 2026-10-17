"""Small JSON-schema checks for MCP core tool inputs."""


def validate_arguments(schema: dict, args: dict) -> None:
    """Reject arguments outside the bounds advertised in a tool schema."""
    def invalid(message: str) -> None:
        raise ValueError(f"invalid tool arguments: {message}")

    if not isinstance(args, dict):
        invalid("expected object")
    if schema.get("additionalProperties") is False:
        if set(args) - set(schema.get("properties", {})):
            invalid("unexpected field")
    if any(key not in args for key in schema.get("required", [])):
        invalid("missing required field")
    for key, value in args.items():
        rule = schema.get("properties", {}).get(key)
        if rule is None:
            continue
        kind = rule.get("type")
        valid_type = {
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "array": lambda item: isinstance(item, list),
            "object": lambda item: isinstance(item, dict),
        }.get(kind, lambda _item: True)
        if not valid_type(value):
            invalid("field has wrong type")
        if "enum" in rule and value not in rule["enum"]:
            invalid("field has unsupported value")
        if isinstance(value, str):
            if len(value) < rule.get("minLength", 0):
                invalid("field is too short")
            if len(value) > rule.get("maxLength", float("inf")):
                invalid("field is too long")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value < rule.get("minimum", float("-inf")):
                invalid("field is below minimum")
            if value > rule.get("maximum", float("inf")):
                invalid("field is above maximum")
        if isinstance(value, list):
            if len(value) < rule.get("minItems", 0):
                invalid("array is too short")
            if len(value) > rule.get("maxItems", float("inf")):
                invalid("array is too long")
            if "items" in rule:
                for item in value:
                    validate_arguments({"properties": {"item": rule["items"]}}, {"item": item})
        if isinstance(value, dict) and "properties" in rule:
            validate_arguments(rule, value)
