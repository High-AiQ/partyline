"""Validate agent actions and map frame pixels to OS desktop pixels."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt

from partyline_helper.keys import blocked, label, parse

MAX_SCROLL = 50


class ControlAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["click", "move", "drag", "scroll", "type", "key"]
    x: StrictInt | None = None
    y: StrictInt | None = None
    x1: StrictInt | None = None
    y1: StrictInt | None = None
    x2: StrictInt | None = None
    y2: StrictInt | None = None
    dx: StrictInt = 0
    dy: StrictInt = 0
    button: Literal["left", "right", "middle"] = "left"
    double: StrictBool = False
    text: str | None = None
    keys: str | None = None


def _axis(f: int, origin: int, span: int, out: int) -> int:
    # Desktop pixels [f*span/out, (f+1)*span/out) all show as frame pixel f (out <= span).
    # Take the one nearest its centre that still lies in that range; integer maths only.
    first = -((-f * span) // out)
    return origin + max(first, ((2 * f + 1) * span) // (2 * out))


def to_os(fx, fy, frame) -> tuple[int, int]:
    """Invert pointer_coordinates: frame pixel (fx, fy) as a desktop pixel inside the region."""
    if type(fx) is not int or type(fy) is not int:
        raise ValueError("x and y are required integer frame pixels")
    if not (0 <= fx < frame.out_width and 0 <= fy < frame.out_height):
        raise ValueError(f"({fx}, {fy}) is outside the shared region: the frame is "
                         f"{frame.out_width}x{frame.out_height} pixels, (0, 0) at its top left")
    region = frame.region
    return (_axis(fx, region["x"], region["width"], frame.out_width),
            _axis(fy, region["y"], region["height"], frame.out_height))


def command(action: ControlAction, frame, max_text: int, os_name: str) -> dict:
    """The helper's action payload in OS desktop pixels; ValueError explains a refusal."""
    kind = action.kind
    if kind in ("click", "move", "scroll"):
        x, y = to_os(action.x, action.y, frame)
    if kind == "move":
        return {"kind": kind, "x": x, "y": y}
    if kind == "click":
        return {"kind": kind, "x": x, "y": y, "button": action.button, "double": action.double}
    if kind == "drag":
        x1, y1 = to_os(action.x1, action.y1, frame)
        x2, y2 = to_os(action.x2, action.y2, frame)
        return {"kind": kind, "x1": x1, "y1": y1, "x2": x2, "y2": y2}
    if kind == "scroll":
        if max(abs(action.dx), abs(action.dy)) > MAX_SCROLL or not (action.dx or action.dy):
            raise ValueError(f"dx and dy are scroll steps within ±{MAX_SCROLL}, not both 0")
        return {"kind": kind, "x": x, "y": y, "dx": action.dx, "dy": action.dy}
    if kind == "type":
        text = action.text
        if not isinstance(text, str) or not text:
            raise ValueError("text is required")
        if len(text) > max_text:
            raise ValueError(f"text is limited to {max_text} characters per action")
        if any(not char.isprintable() and char not in "\n\t" for char in text):
            raise ValueError("text may contain printable characters, newlines and tabs only")
        return {"kind": kind, "text": text}
    names = parse(action.keys)
    if blocked(names, os_name):
        raise ValueError(f"{label(names)} is blocked for agents (lock, log-out, kill or session keys)")
    return {"kind": kind, "keys": label(names)}


def describe(cmd: dict) -> str:
    """A compact audit entry; typed text is bounded and cannot break out of its code span."""
    kind = cmd["kind"]
    if kind == "move":
        return f"move ({cmd['x']},{cmd['y']})"
    if kind == "click":
        return f"{'double-' if cmd['double'] else ''}click {cmd['button']} ({cmd['x']},{cmd['y']})"
    if kind == "drag":
        return f"drag ({cmd['x1']},{cmd['y1']})→({cmd['x2']},{cmd['y2']})"
    if kind == "scroll":
        return f"scroll {cmd['dx']},{cmd['dy']} at ({cmd['x']},{cmd['y']})"
    if kind == "type":
        text = cmd["text"]
        preview = text[:40].replace("`", "'").replace("\n", "⏎").replace("\t", "⇥")
        return f"type `{preview}{'…' if len(text) > 40 else ''}` ({len(text)} chars)"
    return f"key {cmd['keys']}"
