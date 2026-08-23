"""Parse process mentions from chat message text."""

import re
import unicodedata

MENTION_RE = re.compile(r"@([A-Za-z0-9][A-Za-z0-9_.-]*)")


def mentioned_names(body: str) -> set[str]:
    """Return handles, ignoring Unicode formatting between ``@`` and a name."""
    text: list[str] = []
    after_at = False
    for char in body:
        if after_at and unicodedata.category(char) == "Cf":
            continue
        text.append(char)
        after_at = char == "@"
    names: set[str] = set()
    for found in MENTION_RE.findall("".join(text)):
        names.add(found.lower())
        names.add(found.rstrip(".-_").lower())
    names.discard("")
    return names


def addresses(name: str, messages: list[dict]) -> bool:
    """Whether any message in the batch @mentions this handle or @all."""
    handle = name.lower()
    for message in messages:
        names = mentioned_names(str(message.get("body") or ""))
        if "all" in names or handle in names:
            return True
    return False
