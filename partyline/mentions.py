"""Parse process mentions from chat message text.

``@name`` is an ordinary mention. ``@!name`` is the same mention carrying a
request to interrupt whatever that process is doing first — a deliberate
"stop and read this", never the routine path. Both forms name the same
handle, so a message is delivered either way; the bang only adds the
interrupt, and only when a human wrote it.
"""

import re
import unicodedata

MENTION_RE = re.compile(r"@(!?)([A-Za-z0-9][A-Za-z0-9_.-]*)")


def _normalized(body: str) -> str:
    """Body with Unicode formatting characters after ``@`` removed.

    Copied mentions can carry a zero-width joiner between the sigil and the
    name; a reader sees ``@name`` and the router must too. The bang is part
    of the sigil, so the same skip has to survive it.
    """
    text: list[str] = []
    after_sigil = False
    for char in body:
        if after_sigil and unicodedata.category(char) == "Cf":
            continue
        text.append(char)
        after_sigil = char in "@!" if (after_sigil or char == "@") else False
    return "".join(text)


def _found(body: str) -> list[tuple[str, str]]:
    return MENTION_RE.findall(_normalized(body))


def _handles(name: str) -> set[str]:
    # Trailing punctuation belongs to the sentence, not the handle: "@sol."
    # names sol. Both spellings are offered so either can match.
    return {name.lower(), name.rstrip(".-_").lower()} - {""}


def mentioned_names(body: str) -> set[str]:
    """Every handle this message addresses, with or without the bang."""
    names: set[str] = set()
    for _, name in _found(body):
        names |= _handles(name)
    return names


def interrupt_names(body: str) -> set[str]:
    """Handles addressed as ``@!name`` — an explicit interrupt-and-send.

    ``@all`` is deliberately not interruptible in this form: ``@!all`` names
    the reserved handle like any other and rings the room, but stopping every
    process at once is a blast radius nobody asked for, so the bang is
    dropped there rather than multiplied.
    """
    names: set[str] = set()
    for bang, name in _found(body):
        if bang:
            names |= _handles(name)
    names.discard("all")
    return names


def addresses(name: str, messages: list[dict]) -> bool:
    """Whether any message in the batch @mentions this handle or @all."""
    handle = name.lower()
    for message in messages:
        names = mentioned_names(str(message.get("body") or ""))
        if "all" in names or handle in names:
            return True
    return False
