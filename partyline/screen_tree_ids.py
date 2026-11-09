"""Short element ids that survive a new snapshot: a fingerprint of the element and where it sits."""
import base64
import hashlib

ID_CHARS = 6
MAX_CLAIMS = 100_000  # ids one window may be given before the numbering starts afresh
VOLATILE_NAME = {"Window", "Document"}  # a page title changes with the page; its contents are the same
VOLATILE_VALUE = {"Window", "Document", "Edit", "ComboBox", "Slider", "Spinner", "ProgressBar", "ScrollBar"}


def fingerprint(node):
    name = "" if node.type in VOLATILE_NAME else node.name
    value = "" if node.type in VOLATILE_VALUE else node.value
    return f"{node.type}\0{name}\0{value}\0{node.auto}"


def named(node):
    """Whether the element can be told apart by what it is called, not only where it sits."""
    return bool(node.name or node.auto) or node.type in VOLATILE_NAME


def identity(parent, node, ordinal):
    """What an element is: its anchor, type, name, value and place among identical siblings."""
    return hashlib.blake2b(f"{parent}\0{fingerprint(node)}\0{ordinal}".encode(), digest_size=16).digest()


class IdSpace:
    """The ids given for one window grant, however many snapshots it takes. `claims` maps every id given
    to the identity that holds it: a clash moves the newcomer on to its next candidate, and keeps doing so
    after the other element is gone, so an id never silently names a different element. A space that grows
    past MAX_CLAIMS starts a new epoch (every id changes, and carries the epoch as a suffix, so an id of
    an old epoch can never name an element of a new one) rather than forget a claim."""

    def __init__(self):
        self.claims, self.epoch = {}, 0

    def renew(self):
        if len(self.claims) > MAX_CLAIMS:
            self.claims, self.epoch = {}, self.epoch + 1

    def give(self, who):
        who += self.epoch.to_bytes(4, "big")
        salt = 0
        while True:
            digest = hashlib.blake2b(who + salt.to_bytes(4, "big"), digest_size=5).digest()
            ident = base64.b32encode(digest).decode().lower()[:ID_CHARS]
            if self.claims.get(ident, who) == who:
                self.claims[ident] = who
                return f"{ident}-{self.epoch}" if self.epoch else ident  # epochs never share an id
            salt += 1
