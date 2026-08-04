"""Built-in process adapters and the public adapter registration API."""

from .base import Adapter
from .bundled.raw.adapter import RawAdapter
from .registry import ADAPTER_METADATA, ADAPTERS, make_adapter, register_adapter, unregister_adapter
from .loader import (import_repository, load_adapter, load_bundled_adapters,
                     load_installed_adapters, reload_adapter, reload_adapters)

load_bundled_adapters()
# Previously imported checkouts load after the bundled ones, so an import that
# shares an id with a shipped adapter keeps overriding it across restarts.
load_installed_adapters()

__all__ = [
    "Adapter", "RawAdapter", "ADAPTERS", "ADAPTER_METADATA", "make_adapter", "register_adapter",
    "unregister_adapter", "load_adapter", "load_installed_adapters", "reload_adapter",
    "reload_adapters", "import_repository",
]
