"""Which keys and text a point `key` or `type` may send, and how each route spells them.

Pure and shared by both routes. `parse` and `blocked` are the pixel-control rules (lock, log-out and session
combos); on top of them no route sends a clipboard combo or one that closes the window, and the real-keyboard
route also refuses everything that leaves the granted window (the Windows key, window switchers).
"""
from .keys import blocked, label, parse

MAX_TEXT = 500
CLIPBOARD = "that combo reads or writes the person's clipboard, which stays guarded"
CLOSES = "that combo closes the window; use screen_element_action window_close"
LEAVES = "that combo leaves the granted window (shell or window switcher), so it is never sent"
BAD_TEXT = "text may hold printable characters, new lines and tabs only"
TEXT_KEYS = {"space"}
NAMED = {"enter": (13, "Enter", "Enter"), "tab": (9, "Tab", "Tab"), "esc": (27, "Escape", "Escape"),
         "backspace": (8, "Backspace", "Backspace"), "delete": (46, "Delete", "Delete"),
         "space": (32, "Space", " "), "home": (36, "Home", "Home"), "end": (35, "End", "End"),
         "page_up": (33, "PageUp", "PageUp"), "page_down": (34, "PageDown", "PageDown"),
         "up": (38, "ArrowUp", "ArrowUp"), "down": (40, "ArrowDown", "ArrowDown"),
         "left": (37, "ArrowLeft", "ArrowLeft"), "right": (39, "ArrowRight", "ArrowRight"),
         "insert": (45, "Insert", "Insert"), **{f"f{n}": (111 + n, f"F{n}", f"F{n}") for n in range(1, 13)}}
MODIFIER_VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "meta": 0x5B}
CDP_BITS = {"alt": 1, "ctrl": 2, "meta": 4, "shift": 8}
EXIT_COMBOS = [("alt", "tab"), ("alt", "esc"), ("ctrl", "esc"), ("ctrl", "shift", "esc")]


def combo(text):
    """The canonical names of `text`, or ValueError with a message for the agent."""
    names = parse(text)
    if not names or names[-1] in ("ctrl", "alt", "shift", "meta"):
        raise ValueError("a combo needs one key besides its modifiers, such as ctrl+s or enter")
    return names


def refusal(names, cursor=False):
    """Why this combo is never sent, or None."""
    if blocked(names, "windows"):
        return f"{label(names)} can lock, log out or end the session, so it is never sent"
    mods, key = set(names[:-1]), names[-1]
    if (key in ("c", "x", "v", "insert") and "ctrl" in mods) or (
            key in ("insert", "delete") and "shift" in mods and not mods - {"shift"}):
        return CLIPBOARD
    if key == "f4" and "alt" in mods:
        return CLOSES
    if cursor and ("meta" in mods or key == "meta" or any(
            key == rule[-1] and set(rule[:-1]) <= mods for rule in EXIT_COMBOS)):
        return LEAVES
    return None


def inserts_text(names):
    """True when the combo puts characters into a field, so a password field refuses it."""
    mods, key = set(names[:-1]), names[-1]
    return not mods & {"ctrl", "alt", "meta"} and (key in TEXT_KEYS or (len(key) == 1 and key.isprintable()))


def clean_text(text):
    if not isinstance(text, str) or not 0 < len(text) <= MAX_TEXT:
        raise ValueError(f"text must be 1 to {MAX_TEXT} characters")
    if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in text):
        raise ValueError(BAD_TEXT)
    return text


def cdp_event(name):
    """`(key, code, virtual key code)` of one key name for Input.dispatchKeyEvent."""
    if name in NAMED:
        vk, code, key = NAMED[name]
        return key, code, vk
    upper = name.upper()
    if name.isalpha():
        return name, f"Key{upper}", ord(upper)
    if name.isdigit():
        return name, f"Digit{name}", ord(name)
    return name, "", 0


def cdp_modifiers(names):
    return sum(CDP_BITS[name] for name in names[:-1])


def virtual_keys(names):
    """Windows virtual-key codes: modifiers first, then the key; None for a character the pointer resolves."""
    mods = [MODIFIER_VK[name] for name in names[:-1]]
    key = names[-1]
    if key in NAMED:
        return mods, NAMED[key][0]
    if len(key) == 1 and key.isalnum():
        return mods, ord(key.upper())
    return mods, None
