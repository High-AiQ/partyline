"""The words for a share that ended because its window closed, never the bare "consent revoked".

The internal reason stays "window closed" (the server's revoke message and every `check` use it); only the
text a person or process reads is translated, at the point a reply is built."""

CLOSED = "window closed"
BARE = ("consent revoked", "window read failed", "not consented")
KEEP = 64  # ended grants remembered, so a late request still learns why


def closed_text(process=""):
    hint = " (Chrome may have restarted)" if str(process).lower() == "chrome.exe" else ""
    return f"the shared window closed{hint}; share the window again"


def explain(access, text):
    """`text` as the reply should say it: a closed window's own wording, anything else unchanged."""
    if text == CLOSED and access is not None:
        grant = getattr(access, "grant", None) or {}
        process = grant.get("process") or (getattr(access, "ended", None) or ("", ""))[1]
        return closed_text(process)
    ended = getattr(access, "ended", None)
    if text in BARE and ended and ended[0] == CLOSED and not getattr(access, "grant", None):
        return closed_text(ended[1])
    return text


def remember(ended, ident, process):
    """Record an ended grant in the bounded `ended` dict."""
    ended[ident] = closed_text(process)
    while len(ended) > KEEP:
        del ended[next(iter(ended))]
