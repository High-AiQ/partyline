"""Named contracts for images shared on a line.

These live apart from ``contracts.py`` on purpose: that file is within a
handful of lines of the 300-line production cap, and the image models would
have consumed nearly all of its remaining headroom. ``contracts.py`` imports
``ImageRef`` from here so the message contract stays in one place.
"""

from pydantic import BaseModel


class ImageVariant(BaseModel):
    """A derived rendering of an image: how big it is and what it costs.

    ``bytes`` is here so a process can decide what to fetch without fetching
    anything first — the whole point of the tiers.
    """

    mime: str
    width: int
    height: int
    bytes: int


class ImageUrls(BaseModel):
    """Where the three tiers are served from.

    Relative in broadcast events (the browser already knows its origin) and
    absolute in the upload response and the agent digest, where the reader is
    a process holding only an API base URL.
    """

    original: str
    thumb: str
    slim: str


class ImageRef(BaseModel):
    """One stored image, as it rides along with the message that posted it.

    Every upload derives both ``thumb`` (max edge 512) and ``slim`` (max edge
    1600). They are nullable only to describe rows written before those tiers
    existed; their URLs resolve either way, serving the original where no
    derivation was ever made.
    """

    id: str
    title: str | None = None
    description: str | None = None
    mime: str
    width: int
    height: int
    bytes: int
    thumb: ImageVariant | None = None
    slim: ImageVariant | None = None
    urls: ImageUrls
