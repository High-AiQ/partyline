"""Why a window grant is gone when its window closed, so a later read says so instead of "none is shared"."""

KEEP = 64


def closed_text(process=""):
    hint = " (Chrome may have restarted)" if str(process).lower() == "chrome.exe" else ""
    return f"the shared window closed{hint}; share the window again"


def is_closed(text):
    return isinstance(text, str) and text.startswith("the shared window closed")


def ended_answer(status, detail):
    """What an action in flight reports when its grant ended: outcome, retry advice, why a window closed."""
    note = ("The action was performed; the grant has since ended." if status == "completed" else
            "The grant has since ended; the action outcome is " + status + ". Do not retry automatically.")
    closed = detail if is_closed(detail) else None  # a closed window says so
    return {"status": status, "grant_ended": True, "note": f"{note} {closed}" if closed else note,
            **({"error": closed} if closed else {})}


class ClosedWindows:
    def __init__(self):
        self.items = {}  # grant id -> the line, owner, title and program of a window that closed

    def remember(self, grant_id, conv_id, owner_id, title, process):
        self.items[grant_id] = dict(conv_id=conv_id, owner_id=owner_id, title=title, process=process)
        while len(self.items) > KEEP:
            del self.items[next(iter(self.items))]

    def forget_line(self, conv_id):
        """Any other ending on a line settles what it last reported."""
        for ident in [k for k, v in self.items.items() if v["conv_id"] == conv_id]:
            del self.items[ident]

    def text(self, window=None, lines=(), owner_id=None):
        """The closed wording for the named window (or the latest) in the caller's lines or own windows."""
        found = [(ident, item) for ident, item in self.items.items()
                 if (item["conv_id"] in lines if owner_id is None else item["owner_id"] == owner_id)
                 and (window is None or window in (ident, item["title"]))]
        return closed_text(found[-1][1]["process"]) if found else None
