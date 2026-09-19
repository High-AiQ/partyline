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
    """Where the tiers are served from.

    Relative in broadcast events (the browser already knows its origin) and
    absolute in the upload response and the agent digest, where the reader is
    a process holding only an API base URL. ``readable`` always resolves: for
    an upload with no transcoded tier it serves the original bytes.
    """

    original: str
    thumb: str
    slim: str
    readable: str


class FileRef(BaseModel):
    """One stored file, as it rides along with the message that posted it.

    Images derive ``thumb``, ``slim``, and — when the original is in an
    encoding agents cannot decode — a full-size PNG ``readable`` tier.
    ``format`` is the encoding the magic bytes named, not what the uploader
    declared. Other kinds have only an original, but every URL still resolves
    so readers see one shape.
    """

    id: str
    kind: FileKind
    filename: str | None = None
    title: str | None = None
    description: str | None = None
    mime: str
    bytes: int
    format: str | None = None
    width: int | None = None
    height: int | None = None
    thumb: ImageVariant | None = None
    slim: ImageVariant | None = None
    readable: ImageVariant | None = None
    urls: ImageUrls
