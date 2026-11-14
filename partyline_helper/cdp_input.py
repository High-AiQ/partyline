"""Trusted, consent-guarded CDP key input."""


async def key(page, key, code, modifiers=0):
    for kind in ("keyDown", "keyUp"):
        await page.call("Input.dispatchKeyEvent", {"type": kind, "key": key,
                        "windowsVirtualKeyCode": code, "modifiers": modifiers})
