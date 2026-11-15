"""The CDP route of scroll, drag, type and key: the page's own input; no cursor, no window comes forward.

Every function takes the `guard` of `point_cdp.click` (deadline, revocation) and calls it before each input.
A drag is plain mouse events, so it moves sliders, selections and canvases but does not start HTML5
drag-and-drop in every page.
"""
from .cdp_transport import CDPError
from .point_cdp import release, to_page
from .point_keys import cdp_event, cdp_modifiers, inserts_text

WHEEL_STEP = 100  # CSS pixels the page scrolls per wheel step
PASSWORD = ("the focused field is a password field; Partyline never types into one. Ask the person to "
            "enter it themselves")
SHIFTED = ("shift with a digit or punctuation key types a different character on each layout; "
           "use screen_window_type")
UNKNOWN = ("the focused field cannot be inspected (a cross-origin frame or no field), so nothing was typed; "
           "click the field first, or use screen_element_action set_value")
FOCUS = """(() => {
 let a = document.activeElement;
 for (let i = 0; a && i < 20; i++) {
  if (a.shadowRoot && a.shadowRoot.activeElement) { a = a.shadowRoot.activeElement; continue; }
  if (a.tagName === 'IFRAME' || a.tagName === 'FRAME') {
   let d = null; try { d = a.contentDocument; } catch (e) { d = null; }
   if (!d) return 'unknown';
   a = d.activeElement; continue;
  }
  break;
 }
 if (!a || a === document.body || a === document.documentElement) return 'none';
 const style = getComputedStyle(a);
 if ((a.tagName === 'INPUT' && String(a.type).toLowerCase() === 'password')
     || (style.webkitTextSecurity && style.webkitTextSecurity !== 'none')) return 'password';
 return 'ok';
})()"""


async def password_check(page, typing=True):
    """Typing is refused (CDPError) unless the focused field can be seen and is not a password field.
    Keys that only move or edit (tab, arrows, backspace) are not typing."""
    result = await page.call("Runtime.evaluate", {"expression": FOCUS, "returnByValue": True})
    state = result.get("result", {}).get("value") if isinstance(result, dict) else None
    if typing and state == "password":
        raise CDPError(PASSWORD)
    if typing and state != "ok":
        raise CDPError(UNKNOWN)


async def wheel(page, frame, point, dx, dy, guard):
    """Wheel steps at a screen point; `dy` > 0 scrolls up and `dx` > 0 right, as the pixel-control scroll."""
    x, y = to_page(frame, *point)
    guard()
    await page.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "button": "none",
                                                 "deltaX": dx * WHEEL_STEP, "deltaY": -dy * WHEEL_STEP})
    return {"page_point": [round(x, 1), round(y, 1)]}


async def drag(page, frame, points, guard):
    """Press at the first screen point, move through the rest, release at the last."""
    path = [to_page(frame, *point) for point in points]
    base = {"button": "left"}

    def at(spot, **extra):
        return {**base, "x": spot[0], "y": spot[1], **extra}
    guard()
    await page.call("Input.dispatchMouseEvent", at(path[0], type="mouseMoved", button="none", buttons=0))
    guard()
    try:
        await page.call("Input.dispatchMouseEvent", at(path[0], type="mousePressed", clickCount=1, buttons=1))
    except CDPError as exc:  # the press may have been delivered although its answer failed
        raise CDPError(f"{exc}; {await release(page, at(path[0], buttons=0), 1)}") from exc
    try:
        for spot in path[1:]:
            guard()
            await page.call("Input.dispatchMouseEvent", at(spot, type="mouseMoved", buttons=1))
        await page.call("Input.dispatchMouseEvent",
                        at(path[-1], type="mouseReleased", clickCount=1, buttons=0))
    except CDPError as exc:  # never leave the button down
        raise CDPError(f"{exc}; {await release(page, at(path[-1], buttons=0), 1)}") from exc
    return {"page_points": [[round(x, 1), round(y, 1)] for x, y in (path[0], path[-1])]}


async def insert(page, text, guard):
    guard()
    await page.call("Input.insertText", {"text": text})
    return {"characters": len(text)}


async def press(page, names, guard):
    key, code, vk = cdp_event(names[-1])
    modifiers = cdp_modifiers(names)
    if "shift" in names[:-1] and inserts_text(names) and names[-1] != "space":
        if not (len(key) == 1 and key.isalpha()):  # what Shift+1 or Shift+/ types depends on the layout
            raise CDPError(SHIFTED)
        key = key.upper()
    text = ("\r" if names[-1] == "enter" else key) if inserts_text(names) or names[-1] == "enter" else None
    guard()
    down = {"type": "keyDown" if text else "rawKeyDown", "key": key, "code": code,
            "windowsVirtualKeyCode": vk, "modifiers": modifiers, **({"text": text} if text else {})}
    await page.call("Input.dispatchKeyEvent", down)
    await page.call("Input.dispatchKeyEvent", {**down, "type": "keyUp", "text": ""})
    return {"keys": "+".join(names)}
