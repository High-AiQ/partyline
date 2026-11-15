"""Canonical task modes, accepting the retired light spelling on input."""

from typing import Annotated, Literal

from pydantic import BeforeValidator


def normalize_mode(value):
    return 'full' if value == 'light' else value


TaskMode = Annotated[Literal['full', 'express', 'suite'], BeforeValidator(normalize_mode)]
