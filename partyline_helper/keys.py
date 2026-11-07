"""Key-combo parsing and the agent blocklist, shared by the server and the helper.

Pure Python: the server imports this module, so it must not import pynput.
"""

MODIFIERS = ("ctrl", "alt", "shift", "meta")
ALIASES = {
    "control": "ctrl", "ctl": "ctrl", "option": "alt", "opt": "alt", "altgr": "alt",
    "win": "meta", "windows": "meta", "super": "meta", "cmd": "meta", "command": "meta",
    "return": "enter", "escape": "esc", "del": "delete", "bksp": "backspace",
    "pgup": "page_up", "pageup": "page_up", "pgdn": "page_down", "pagedown": "page_down",
    "ins": "insert", "spacebar": "space", "arrowup": "up", "arrowdown": "down",
    "arrowleft": "left", "arrowright": "right",
}
NAMED = {"enter", "esc", "tab", "backspace", "delete", "space", "home", "end", "page_up",
         "page_down", "up", "down", "left", "right", "insert", *(f"f{n}" for n in range(1, 13))}
# Each rule blocks its key with these modifiers or any superset of them.
ALWAYS = [("ctrl", "alt", "delete"), ("ctrl", "alt", "backspace"),
          ("ctrl", "alt", "esc"),  # reserved: the person's kill-switch hotkey
          *(("ctrl", "alt", f"f{n}") for n in range(1, 13))]
BY_OS = {
    "windows": [("meta", "l")],
    "linux": [("meta", "l"), ("ctrl", "alt", "l")],
    "darwin": [("ctrl", "meta", "q"), ("alt", "meta", "esc"), ("shift", "meta", "q")],
}


def parse(combo):
    """Return the canonical combo: modifiers in fixed order, then at most one key."""
    if not isinstance(combo, str) or not 0 < len(combo) <= 64:
        raise ValueError("keys must be a combo such as ctrl+s, enter or alt+tab")
    names = [ALIASES.get(part.strip().lower(), part.strip().lower()) for part in combo.split("+")]
    mods = [name for name in names if name in MODIFIERS]
    keys = [name for name in names if name not in MODIFIERS]
    if not all(names) or len(set(mods)) != len(mods) or len(keys) > 1 or not names:
        raise ValueError(f"invalid key combo {combo!r}: use modifiers plus one key, e.g. ctrl+s")
    if keys and keys[0] not in NAMED and not (len(keys[0]) == 1 and keys[0].isprintable()):
        raise ValueError(f"unknown key {keys[0]!r}")
    return tuple(mod for mod in MODIFIERS if mod in mods) + tuple(keys)


def blocked(names, os_name):
    """True when the combo can lock, log out, kill or escape the session."""
    system = str(os_name or "").lower()
    rules = ALWAYS + (BY_OS.get(system) or [rule for group in BY_OS.values() for rule in group])
    mods, key = set(names[:-1]), names[-1]
    return any(rule[-1] == key and set(rule[:-1]) <= mods for rule in rules)


def label(names):
    return "+".join(names)
