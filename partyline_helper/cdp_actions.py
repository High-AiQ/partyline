"""Page input dispatched through a consent-guarded CDP session."""
import json

from .cdp_recipes import HIT, STATE
from .cdp_input import key
from .cdp_select import select_option
from .cdp_transport import CDPError, DocumentChanged

KEYS = {"enter": ("Enter", 13), "tab": ("Tab", 9), "escape": ("Escape", 27)}


async def act(page, message):
    node = page.nodes.get(message.get("element_id"))
    if not node or not node.get("backendDOMNodeId"):
        raise CDPError("stale or virtual CDP element; read it again")
    backend = node["backendDOMNodeId"]
    state = await page.function(backend, STATE)
    action = message["action"]
    if not message.get("force") and any(state.get(k) for k in ("native_disabled", "aria_disabled", "inert")):
        raise CDPError("element reports disabled (DOM/ARIA/inert)")
    if action == "set_value" and (state.get("readonly") or state.get("password")):
        raise CDPError("element is read-only or a password field")
    if action not in ("invoke", "toggle", "select", "set_value", "set_files", "press", "scroll_into_view"):
        raise CDPError("action unavailable for CDP page element")
    if action != "set_files":
        await page.call("DOM.scrollIntoViewIfNeeded", {"backendNodeId": backend})
        await page.call("DOM.focus", {"backendNodeId": backend})
    navigation, released = page.navigations, False
    try:
        extra = {}
        if action == "set_files":
            from .cdp_files import set_files
            extra = await set_files(page, message, backend)
        elif action == "select" and state.get("tag") == "SELECT":
            if not isinstance(message.get("value"), str):
                raise CDPError("select requires an option name or value")
            extra = await select_option(page, backend, message["value"])
        elif action in ("invoke", "toggle", "select"):
            hit = await page.function(backend, HIT)
            if not hit.get("hit"):
                raise CDPError(hit.get("reason") or hit.get("hit_reason")
                               or "element is covered or outside the viewport")
            box = await page.call("DOM.getBoxModel", {"backendNodeId": backend})
            quad = box["model"]["content"]
            point = {"x": sum(quad[::2]) / 4, "y": sum(quad[1::2]) / 4, "button": "left", "clickCount": 1}
            for kind in ("mousePressed", "mouseReleased"):
                page.guard()
                released = kind == "mouseReleased"
                await page.call("Input.dispatchMouseEvent", {"type": kind, **point})
        elif action == "set_value":
            await key(page, "a", 65, 2)  # select existing text using real keyboard input
            await page.call("Input.insertText", {"text": message.get("value", "")})
        elif action == "scroll_into_view":
            extra = {"hit": await page.function(backend, HIT)}
        elif action == "press":
            if message.get("key") not in KEYS:
                raise CDPError("press requires enter, tab or escape")
            await key(page, *KEYS[message["key"]])
        settle = await page.quiet.wait()
        counter = page.access.event_status()["event_counter"]
        observed = await page.function(backend, STATE)
        if action == "set_files":
            if not isinstance(observed.get("files"), list) or not isinstance(observed.get("file_count"), int):
                raise CDPError("file input read-back unavailable")
            extra = {"files": observed.pop("files"), "count": observed["file_count"]}
        if page.access.event_status()["event_counter"] != counter and settle == "quiet":
            settle = "changing"
        return {"status": "completed", "source": "cdp", "settle": settle,
                "settled_event_counter": counter, "element": observed, **extra}
    except DocumentChanged:
        if action != "invoke" or state.get("tag") != "A" or not released or page.navigations == navigation:
            raise
        page.guard(document=False)  # navigation success never overrides revocation
        return {"status": "completed", "source": "cdp", "navigated": True, "settle": "changing",
                "settled_event_counter": page.access.event_status()["event_counter"]}


async def evaluate(page, expression, budget=3000):
    result = await page.call("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                "awaitPromise": True, "timeout": 5000})
    if result.get("exceptionDetails"):
        return {"status": "failed", "source": "cdp", "error": "JavaScript raised an exception"}
    remote = result.get("result", {})
    value = remote.get("value", remote.get("unserializableValue"))
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode()) > budget:
        preview = encoded.encode()[:budget].decode("utf-8", errors="ignore")
        while len(json.dumps(preview, ensure_ascii=False).encode()) > budget:
            preview = preview[:len(preview) * 3 // 4]
        return {"status": "completed", "source": "cdp", "truncated": True, "result_preview": preview}
    return {"status": "completed", "source": "cdp", "result": value}
