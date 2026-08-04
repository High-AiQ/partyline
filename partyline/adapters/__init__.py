"""Built-in process adapters and the public adapter registration API."""

from .base import Adapter
from .bundled.raw.adapter import RawAdapter
from .registry import ADAPTER_METADATA, ADAPTERS, make_adapter, register_adapter, unregister_adapter
from .loader import import_repository, load_adapter, load_bundled_adapters, reload_adapter, reload_adapters

load_bundled_adapters()

__all__ = [
    "Adapter", "RawAdapter", "ADAPTERS", "ADAPTER_METADATA", "make_adapter", "register_adapter",
    "unregister_adapter", "load_adapter", "reload_adapter", "reload_adapters", "import_repository",
]
