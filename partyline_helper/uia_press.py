"""Narrow window-message commits. Queueing a key is never evidence that an app used it."""
import ctypes
import json
from ctypes import wintypes

from .uia_patterns import check_argument

PRESS_VERSION = 1
KEYS = {"enter": (13, 0x1C), "tab": (9, 0x0F), "escape": (27, 0x01)}
RENDERER = "Chrome_RenderWidgetHostHWND"
NO_EFFECT = "No key effect observed; re-read with then or screen_elements, or invoke a submit button."


def preview(value):
    """Bound observation strings by rendered JSON bytes, including escaped control characters."""
    if not isinstance(value, str):
        return value
    shown, used = [], 0
    for char in value:
        cost = len(json.dumps(char, ensure_ascii=False).encode("utf-8")) - 2
        if used + cost > 200:
            break
        shown.append(char)
        used += cost
    return "".join(shown)


class WindowMessages:
    """The only input API used here is PostMessageW, always to a validated nonzero HWND."""

    def __init__(self, user32):
        self.api = user32
        self.callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        signatures = {
            "PostMessageW": ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
            "GetClassNameW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetAncestor": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            "GetWindowRect": ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            "IsWindow": ([wintypes.HWND], wintypes.BOOL),
            "EnumChildWindows": ([wintypes.HWND, self.callback, wintypes.LPARAM], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(user32, name)
            function.argtypes, function.restype = args, result

    def belongs(self, hwnd, top):
        return bool(hwnd and hwnd != 0xFFFF and self.api.IsWindow(hwnd)
                    and self.api.GetAncestor(hwnd, 2) == top)

    def class_name(self, hwnd):
        buffer = ctypes.create_unicode_buffer(256)
        self.api.GetClassNameW(hwnd, buffer, len(buffer))
        return buffer.value

    def renderers(self, top, bounds):
        x, y = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
        found = []

        def visit(hwnd, _):
            if self.belongs(hwnd, top) and self.class_name(hwnd) == RENDERER:
                rect = wintypes.RECT()
                if (self.api.GetWindowRect(hwnd, ctypes.byref(rect))
                        and rect.left <= x < rect.right and rect.top <= y < rect.bottom):
                    found.append(hwnd)
            return True

        self.api.EnumChildWindows(top, self.callback(visit), 0)
        return found

    def post(self, hwnd, message, key, flags):
        return bool(self.api.PostMessageW(hwnd, message, key, flags))


def ancestry(provider, node):
    """Require the control-view parent chain to reach this grant, even for windowless nodes."""
    chain = []
    for _ in range(40):
        if not node or not provider.same_window(node):
            break
        chain.append(node)
        handle = provider.prop(node, "NativeWindowHandle")
        if handle == provider.hwnd or (handle and provider.scope.accepts(handle) and
                                       provider.user32.GetAncestor(handle, 2) == handle):
            return chain
        node = provider.walker.GetParentElement(node)
    return []


def target_hwnd(provider, node, messages):
    chain = ancestry(provider, node)
    if not chain:
        return None
    root = provider.prop(chain[-1], "NativeWindowHandle")
    if root != provider.hwnd:
        return next((handle for handle in (provider.prop(item, "NativeWindowHandle") for item in chain)
                     if messages.belongs(handle, root) and provider.scope.accepts(handle)), None)
    chrome = messages.class_name(provider.hwnd).startswith("Chrome_WidgetWin")
    page = any(provider.properties(item).get("control_type") == "Document" for item in chain)
    handles = [provider.prop(item, "NativeWindowHandle") for item in chain]
    if chrome and page:
        candidates = [handle for handle in handles if handle and messages.belongs(handle, provider.hwnd)
                      and messages.class_name(handle) == RENDERER]
        if not candidates:
            candidates = messages.renderers(provider.hwnd, provider.bounds(node))
        return candidates[0] if len(set(candidates)) == 1 else None
    # Chrome browser chrome (including its windowless omnibox) uses the top-level HWND.
    return provider.hwnd if chrome else next((handle for handle in handles
                                              if messages.belongs(handle, provider.hwnd)), None)


def submit_hint(provider, node):
    """Offer nearby explicit submit controls, without guessing which button to invoke."""
    chain = ancestry(provider, node)
    if not chain:
        return None
    scope = chain[1] if len(chain) > 1 else chain[0]
    for child in provider.children(scope)[:80]:
        props = provider.properties(child)
        name = str(props.get("name", ""))[:100]
        if (provider.same_window(child) and props.get("enabled") and "Invoke" in props.get("patterns", [])
                and props.get("control_type") == "Button" and name.casefold() in ("submit", "search", "go")):
            return {"query": name, "control_type": "Button"}
    return None


def observe(provider, node):
    try:
        state = provider.properties(node)
    except Exception:  # navigation may have removed the field; title/address can still be read
        state = {}
    result = {key: state[key] for key in ("focused", "value") if key in state}
    if state and provider.password(node):
        result.pop("value", None)
    result["window_title"] = provider.properties(provider.root()).get("name", "")
    # Browser chrome only: never inspect page fields to infer a URL.
    stack = [provider.root()]
    for _ in range(256):
        if not stack:
            break
        item = stack.pop()
        try:
            props = provider.properties(item)
        except Exception:  # stale children must not hide a fresh window title
            continue
        if not provider.same_window(item) or props.get("control_type") == "Document":
            continue
        if (props.get("control_type") == "Edit" and not provider.password(item)
                and (props.get("automation_id") in ("omnibox", "addressEditBox")
                     or str(props.get("name", "")).casefold() in
                     ("address and search bar", "search or enter web address"))):
            if "value" in props:
                result["url"] = props["value"]
            break
        stack.extend(reversed(provider.children(item)))
    return result


def press(provider, node, key, messages=None, active=lambda: True):
    check_argument("press", {"key": key})
    result = {"status": "no_effect", "hint": NO_EFFECT, "posted": 0}
    try:
        if not active():
            return result
        if key == "enter" and (candidate := submit_hint(provider, node)):
            return {**result, "native_submit": candidate,
                    "hint": "UIA submit candidate found; find it with screen_elements and invoke its id."}
        messages = messages or WindowMessages(provider.user32)
        hwnd = target_hwnd(provider, node, messages)
        top = provider.user32.GetAncestor(hwnd, 2) if hwnd else None
        def belongs():
            return bool(top and messages.belongs(hwnd, top) and
                        (top == provider.hwnd or provider.scope.accepts(hwnd)))
        if not belongs():
            return {**result, "hint": "No unambiguous HWND in this grant; invoke a UIA control instead."}
        foreground = provider.foreground()
        if not active():
            return result
        node.SetFocus()  # UIA focus only; no activation API or thread-input attachment
        if provider.foreground() != foreground:
            return {**result, "hint": "The app changed foreground during UIA focus; no key was posted."}
        before = observe(provider, node)  # focus preparation is not a key effect
        if not before.get("focused"):
            return {**result, "hint": "UIA did not confirm target focus; no key was posted."}
        if not belongs() or target_hwnd(provider, node, messages) != hwnd:
            return {**result, "hint": "The target HWND changed; read the window again."}
        code, scan = KEYS[key]
        flags = 1 | (scan << 16)
        # No TranslateMessage dependency: explicitly post the character as well as down/up.
        for message, bits in ((0x100, flags), (0x102, flags), (0x101, flags | (3 << 30))):
            if (not active() or not belongs()
                    or not messages.post(hwnd, message, code, bits)):
                result["hint"] = "Window message delivery failed; re-read before deciding what to do next."
                break
            result["posted"] += 1
        result["delivery"] = "window_messages"
        after = observe(provider, node)
        changed = [field for field in before.keys() & after.keys() if before[field] != after[field]]
        shown = [{field: preview(value) for field, value in state.items()}
                 for state in (before, after)]
        result["observation"] = {"before": shown[0], "after": shown[1], "changed": sorted(changed)}
        if shown != [before, after]:
            result["observation"]["truncated"] = True
        if changed:
            result.update(status="completed")
            result.pop("hint", None)
        return result
    except Exception:
        return {**result, "hint": "Could not confirm a key effect; re-read or invoke a UIA submit control."}
