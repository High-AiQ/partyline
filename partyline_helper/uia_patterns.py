"""UIA action catalogue: pattern requirements, argument validation and per-element refusals."""
import math

PATTERN = {"invoke": "Invoke", "toggle": "Toggle", "set_value": "Value",
           "select": "SelectionItem", "add_to_selection": "SelectionItem",
           "remove_from_selection": "SelectionItem", "expand": "ExpandCollapse",
           "collapse": "ExpandCollapse", "scroll": "Scroll", "set_scroll_percent": "Scroll",
           "scroll_into_view": "ScrollItem", "set_range_value": "RangeValue",
           "window_close": "Window", "window_minimize": "Window", "window_maximize": "Window",
           "window_restore": "Window", "window_move": "Transform", "window_resize": "Transform"}
WINDOW_ACTIONS = tuple(name for name in PATTERN if name.startswith("window_"))
PARAMS = {"scroll": ("direction", "amount"), "set_scroll_percent": ("horizontal_percent", "vertical_percent"),
          "set_range_value": ("number",), "window_move": ("x", "y"), "window_resize": ("width", "height")}
FIELDS = tuple(name for names in PARAMS.values() for name in names)
DIRECTIONS = ("up", "down", "left", "right")
AMOUNTS = ("small", "large")
MAX_COORD, MAX_SIZE = 32767, 16384


class ActionRefused(ValueError):
    """A refusal whose text is built only from fixed strings and the caller's own numbers."""


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def integer(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def argument(message):
    """The raw action argument: set_value text, or the dict of parameters other actions take."""
    if message.get("action") == "set_value":
        return message.get("value")
    return {key: message[key] for key in FIELDS if message.get(key) is not None}


def check_argument(action, arg):
    if action not in PATTERN:
        raise ActionRefused("unsupported action")
    if action == "set_value":
        if not isinstance(arg, str):
            raise ActionRefused("set_value requires a text value")
        return
    arg = arg or {}
    allowed = PARAMS.get(action, ())
    if extra := sorted(set(arg) - set(allowed)):
        raise ActionRefused(f"{action} does not take {', '.join(extra)}")
    if action == "scroll":
        if arg.get("direction") not in DIRECTIONS or arg.get("amount") not in AMOUNTS:
            raise ActionRefused("scroll requires direction up, down, left or right and amount small or large")
    elif action == "set_scroll_percent":
        if not arg or not all(number(v) and 0 <= v <= 100 for v in arg.values()):
            raise ActionRefused("set_scroll_percent requires horizontal_percent and/or "
                                "vertical_percent, 0 to 100")
    elif action == "set_range_value":
        if not number(arg.get("number")):
            raise ActionRefused("set_range_value requires a finite number")
    elif action == "window_move":
        if not all(integer(arg.get(key), -MAX_COORD - 1, MAX_COORD) for key in ("x", "y")):
            raise ActionRefused("window_move requires integer x and y screen coordinates")
    elif action == "window_resize":
        if not all(integer(arg.get(key), 1, MAX_SIZE) for key in ("width", "height")):
            raise ActionRefused(f"window_resize requires integer width and height, 1 to {MAX_SIZE}")


def supported(props, is_window):
    """Actions the element's patterns allow; window actions apply only to the shared window."""
    patterns = props.get("patterns", [])
    return [name for name, pattern in PATTERN.items()
            if pattern in patterns and (is_window or name not in WINDOW_ACTIONS)]


def refuse_unsupported(action, props, is_window):
    if action in WINDOW_ACTIONS and not is_window and PATTERN[action] in props.get("patterns", []):
        raise ActionRefused("window actions apply only to the shared window itself")
    names = supported(props, is_window)
    raise ActionRefused(f"element does not support this action ({action}); it supports: "
                        + (", ".join(names) if names else "no actions"))


def refuse_state(action, props, arg):
    """Refusals that depend on the element's live state or the argument's range."""
    if action == "set_range_value":
        low, high = props.get("range_min"), props.get("range_max")
        if props.get("range_read_only"):
            raise ActionRefused("element is read-only")
        if not number(low) or not number(high):
            raise ActionRefused("element range is unavailable")
        if not low <= arg["number"] <= high:
            raise ActionRefused(f"value must be between {low:g} and {high:g}")
    elif action == "scroll":
        key = "v_scrollable" if arg["direction"] in ("up", "down") else "h_scrollable"
        if not props.get(key):
            raise ActionRefused("element cannot scroll in that direction")
    elif action == "set_scroll_percent":
        for field, key in (("horizontal_percent", "h_scrollable"), ("vertical_percent", "v_scrollable")):
            if field in arg and not props.get(key):
                raise ActionRefused(f"element cannot scroll for {field}")
    elif action in ("expand", "collapse") and props.get("expand_state") == "leaf":
        raise ActionRefused("element has nothing to expand or collapse")
    elif action == "window_minimize" and not props.get("can_minimize"):
        raise ActionRefused("window cannot be minimized")
    elif action == "window_maximize" and not props.get("can_maximize"):
        raise ActionRefused("window cannot be maximized")
    elif action == "window_move" and not props.get("can_move"):
        raise ActionRefused("window cannot be moved")
    elif action == "window_resize" and not props.get("can_resize"):
        raise ActionRefused("window cannot be resized")
