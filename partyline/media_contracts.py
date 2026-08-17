"""Named contracts for images shared on a line.

These live apart from ``contracts.py`` on purpose: that file is within a
handful of lines of the 300-line production cap, and the image models would
have consumed nearly all of its remaining headroom. ``contracts.py`` imports
``ImageRef`` from here so the message contract stays in one place.
"""

from pydantic import BaseModel


class ImageThumb(BaseModel):
    """The derived, cheaper-to-read variant of an image."""

    mime: str
    width: int
    height: int


class ImageUrls(BaseModel):
    """Where the two variants are served from.

    Relative in broadcast events (the browser already knows its origin) and
    absolute in the upload response and the agent digest, where the reader is
    a process holding only an API base URL.
    """

    original: str
    thumb: str


class ImageRef(BaseModel):
    """One stored image, as it rides along with the message that posted it.

    ``thumb`` is ``None`` when the original was already small enough to serve
    directly; ``urls.thumb`` still resolves, so a reader never has to branch.
    """

    id: str
    title: str | None = None
    description: str | None = None
    mime: str
    width: int
    height: int
    bytes: int
    thumb: ImageThumb | None = None
    urls: ImageUrls
