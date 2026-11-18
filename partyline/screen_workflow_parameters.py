"""Bound the inputs to a workflow before the runner can dispatch any action."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Slug = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]
WorkflowName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,54}$")]
Text = Annotated[str, StringConstraints(max_length=500)]
Label = Annotated[str, StringConstraints(min_length=1, max_length=200)]
MediaID = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,128}$")]
MediaList = Annotated[list[MediaID], Field(min_length=1, max_length=10)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class TextParameter(Strict):
    type: Literal["text"]
    max_length: int = Field(default=500, ge=1, le=500)


class EnumParameter(Strict):
    type: Literal["enum"]
    choices: list[Text] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique(self):
        if len(self.choices) != len(set(self.choices)):
            raise ValueError("enum choices must be unique")
        return self


class MediaParameter(Strict):
    type: Literal["media_id"]


Scalar = Annotated[TextParameter | EnumParameter | MediaParameter, Field(discriminator="type")]


class RecordItem(Strict):
    type: Literal["record"]
    fields: dict[Slug, Scalar] = Field(min_length=1, max_length=16)


class ListParameter(Strict):
    type: Literal["list"]
    items: Annotated[Scalar | RecordItem, Field(discriminator="type")]
    min_items: int = Field(default=0, ge=0, le=32)
    max_items: int = Field(ge=1, le=32)

    @model_validator(mode="before")
    @classmethod
    def scalar_shorthand(cls, data):
        if isinstance(data, dict) and isinstance(data.get("items"), str):
            return {**data, "items": {"type": data["items"]}}
        return data

    @model_validator(mode="after")
    def ordered_bounds(self):
        if self.min_items > self.max_items:
            raise ValueError("inverted list bounds")
        return self


Parameter = Annotated[Scalar | ListParameter, Field(discriminator="type")]


def validate_input(spec, value):
    if isinstance(spec, ListParameter):
        if not isinstance(value, list) or not spec.min_items <= len(value) <= spec.max_items:
            raise ValueError("expected a list within its declared bounds")
        return [validate_input(spec.items, item) for item in value]
    if isinstance(spec, RecordItem):
        if not isinstance(value, dict) or value.keys() != spec.fields.keys():
            raise ValueError("expected exactly the declared record fields")
        return {field: validate_input(decl, value[field]) for field, decl in spec.fields.items()}
    if not isinstance(value, str):
        raise ValueError("expected text")
    if isinstance(spec, TextParameter) and len(value) > spec.max_length:
        raise ValueError("text exceeds its declared limit")
    if isinstance(spec, EnumParameter) and value not in spec.choices:
        raise ValueError("expected a declared choice")
    if isinstance(spec, MediaParameter):
        from pydantic import TypeAdapter

        TypeAdapter(MediaID).validate_python(value)
    return value
