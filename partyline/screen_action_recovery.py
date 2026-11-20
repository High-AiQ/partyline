"""A requested compact read also answers stale element-action failures."""


def needed(result):
    """Whether fresh IDs can explain a refusal; uncertain actions are never repeated."""
    error = result.get("error", "")
    return result.get("reason") == "target_changed" or isinstance(error, str) and error.startswith(
        ("unknown element id:", "could not refresh the window;"))


async def attach(hub, principal, grant, then, result):
    """Attach the same bounded `then` answer used after success to a stale-target refusal."""
    if not needed(result):
        return result
    from .screen_element_actions import after, diffed

    result["after"] = await after(hub, principal, grant, then, result)
    if not then.explicit():
        result["after"] = diffed(result["after"])
    return result
