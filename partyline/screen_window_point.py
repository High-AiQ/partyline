"""Scroll, drag, type and key on a window granted to a line: what each takes, in the click's own pipeline.

`screen_window_click.point_operation` does the rest, so each one has the click's geometry, routing, consent,
deadline and floor rules: scroll and drag name pixels of a snapshot; type and key name none, need an earlier
click in the grant, and are refused into a password field. The combos that lock, log out or end the session,
read or write the clipboard or close the window are refused here and again by the helper.
"""
from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from partyline_helper.point_keys import clean_text, combo, inserts_text, refusal

from .screen_window_click import PointInput

SNAPSHOT = Field(min_length=1, max_length=64)
STEPS = Annotated[int, Field(ge=-50, le=50)]
SPOT = Annotated[int, Field(ge=0, le=100_000)]


class Spot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: SPOT
    y: SPOT


class WindowScroll(PointInput):
    operation: ClassVar[str] = "scroll"
    snapshot: str = SNAPSHOT
    x: SPOT
    y: SPOT
    dx: STEPS = 0
    dy: STEPS = 0

    @field_validator("dy")
    @classmethod
    def moves(cls, value, info):
        if not value and not info.data.get("dx"):
            raise ValueError("scroll needs a nonzero dx or dy")
        return value

    def pixels(self):
        return [(self.x, self.y)]

    def wire(self, points):
        return {"snapshot": self.snapshot, "x": self.x, "y": self.y, "screen": list(points[0]),
                "dx": self.dx, "dy": self.dy}

    def detail(self):
        return {"snapshot": self.snapshot, "point": [self.x, self.y], "dx": self.dx, "dy": self.dy}


class WindowDrag(PointInput):
    operation: ClassVar[str] = "drag"
    snapshot: str = SNAPSHOT
    start: Spot = Field(alias="from")
    end: Spot = Field(alias="to")

    def pixels(self):
        return [(self.start.x, self.start.y), (self.end.x, self.end.y)]

    def wire(self, points):
        return {"snapshot": self.snapshot, "x": self.start.x, "y": self.start.y, "screen": list(points[0]),
                "x2": self.end.x, "y2": self.end.y, "screen2": list(points[1])}

    def detail(self):
        return {"snapshot": self.snapshot, "point": [self.start.x, self.start.y],
                "to": [self.end.x, self.end.y]}


class WindowType(PointInput):
    operation: ClassVar[str] = "type"
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def printable(cls, value):
        return clean_text(value)

    def wire(self, points):
        return {"text": self.text}

    def detail(self):
        return {"characters": len(self.text)}  # what is typed is never logged


class WindowKey(PointInput):
    operation: ClassVar[str] = "key"
    keys: str = Field(min_length=1, max_length=64)

    @field_validator("keys")
    @classmethod
    def allowed(cls, value):
        names = combo(value)
        if reason := refusal(names):
            raise ValueError(reason)
        return value

    def wire(self, points):
        return {"keys": self.keys}

    def detail(self):
        names = combo(self.keys)  # a key that types is logged as a count, like text
        return {"characters": 1} if inserts_text(names) else {"keys": self.keys}


POINT_MODELS = {"scroll": WindowScroll, "drag": WindowDrag, "type": WindowType, "key": WindowKey}
