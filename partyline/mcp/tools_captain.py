"""Captain-tier registry extension point, populated by implementation slice 2."""


def tool_list(_state: dict) -> list[dict]:
    """Return no captain tools until the fixed-operation registry is installed."""
    return []


def call(_client, _name: str, _args: dict, _state: dict):
    raise ValueError("unknown captain MCP tool")
