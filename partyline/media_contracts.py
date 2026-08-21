"""Named contracts for uploaded files shared on a line.

These live apart from ``contracts.py`` on purpose: that file is within a
handful of lines of the 300-line production cap, and the image models would
have consumed nearly all of its remaining headroom. ``contracts.py`` imports
``FileRef`` from here so the message contract stays in one place.
"""

from typing import Literal

from pydantic import BaseModel

FileKind = Literal["image", "audio", "video", "file"]


class ImageVariant(BaseModel):
    """A derived rendering of an image: how big it is and what it costs.

    ``bytes`` is here so a process can decide what to fetch without fetching
    anything first — the whole point of the tiers. It is ``None`` only for a
    variant derived before the size was recorded: reporting ``0`` there would
    read as "free", which is a false price rather than a missing one.
    """

    mime: str
    width: int
    height: int
    bytes: int | None = None


class ImageUrls(BaseModel):
    """Where the three tiers are served from.

    Relative in broadcast events (the browser already knows its origin) and
    absolute in the upload response and the agent digest, where the reader is
    a process holding only an API base URL.
    """

    original: str
    thumb: str
    slim: str


class FileRef(BaseModel):
    """One stored file, as it rides along with the message that posted it.

    Images derive ``thumb`` and ``slim`` tiers. Other kinds have only an
    original, but all three URLs still resolve so readers see one shape.
    """

    id: str
    kind: FileKind
    filename: str | None = None
    title: str | None = None
    description: str | None = None
    mime: str
    bytes: int
    width: int | None = None
    height: int | None = None
    thumb: ImageVariant | None = None
    slim: ImageVariant | None = None
    urls: ImageUrls
