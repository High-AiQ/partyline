"""Local re-validation of agent actions: the helper never trusts the server's checks alone."""
from .keys import blocked, label, parse

MAX_TEXT = 500
MAX_SCROLL = 50
BUTTONS = ("left", "right", "middle")


def point(action, kx, ky, region):
    x, y = action.get(kx), action.get(ky)
    if type(x) is not int or type(y) is not int:
        raise ValueError("coordinates must be integer desktop pixels")
    if not (region["x"] <= x < region["x"] + region["width"]
            and region["y"] <= y < region["y"] + region["height"]):
        raise ValueError(f"({x}, {y}) is outside the shared region")
    return x, y


def validate(action, region, os_name):
    """Return the checked action with desktop-pixel points; ValueError explains a refusal."""
    if not isinstance(action, dict):
        raise ValueError("action must be an object")
    kind = action.get("kind")
    checked = {"kind": kind}
    if kind in ("move", "click", "scroll"):
        checked["at"] = point(action, "x", "y", region)
    if kind == "drag":
        checked["start"] = point(action, "x1", "y1", region)
        checked["end"] = point(action, "x2", "y2", region)
    elif kind == "click":
        checked["button"] = action.get("button", "left")
        checked["count"] = 2 if action.get("double") is True else 1
        if checked["button"] not in BUTTONS:
            raise ValueError("button must be left, right or middle")
    elif kind == "scroll":
        dx, dy = action.get("dx", 0), action.get("dy", 0)
        if type(dx) is not int or type(dy) is not int or max(abs(dx), abs(dy)) > MAX_SCROLL or not (dx or dy):
            raise ValueError(f"scroll dx/dy must be integers within ±{MAX_SCROLL}, not both 0")
        checked["delta"] = (dx, dy)
    elif kind == "type":
        text = action.get("text")
        if not isinstance(text, str) or not 0 < len(text) <= MAX_TEXT or any(
                not char.isprintable() and char not in "\n\t" for char in text):
            raise ValueError(f"text must be 1-{MAX_TEXT} printable characters")
        checked["text"] = text
    elif kind == "key":
        names = parse(action.get("keys"))
        if blocked(names, os_name):
            raise ValueError(f"{label(names)} is blocked for agents")
        checked["keys"] = names
    elif kind != "move":
        raise ValueError("unknown action")
    return checked
