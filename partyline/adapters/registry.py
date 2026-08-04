"""Runtime registry for built-in and imported process adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import Adapter

ADAPTERS: dict[str, type[Adapter]] = {}
ADAPTER_METADATA: dict[str, dict[str, Any]] = {}


def register_adapter(adapter_id: str, cls: type[Adapter], metadata: Mapping[str, Any] | None = None):
    """Register an adapter class.

    Imported adapter packages call this function from their registration entry
    point.  IDs are stable, lowercase slugs used in the HTTP API and database.
    """
    adapter_id = adapter_id.strip().lower()
    if not adapter_id or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in adapter_id):
        raise ValueError("adapter id must be a lowercase slug")
    if not issubclass(cls, Adapter):
        raise TypeError("adapter class must inherit Adapter")
    ADAPTERS[adapter_id] = cls
    ADAPTER_METADATA[adapter_id] = {"id": adapter_id, **dict(metadata or {})}


def unregister_adapter(adapter_id: str):
    """Remove an adapter, used when an imported package is reloaded."""
    adapter_id = adapter_id.strip().lower()
    ADAPTERS.pop(adapter_id, None)
    ADAPTER_METADATA.pop(adapter_id, None)


def make_adapter(kind: str, att: dict, post, on_status, on_cli_session=None) -> Adapter:
    try:
        cls = ADAPTERS[kind]
    except KeyError as exc:
        raise ValueError(f"unknown adapter: {kind}") from exc
    attachment = dict(att)
    attachment["adapter_metadata"] = ADAPTER_METADATA[kind]
    return cls(attachment, post, on_status, on_cli_session)
