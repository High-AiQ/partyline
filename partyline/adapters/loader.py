"""Load adapter packages from the bundled directory or an imported checkout."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import logging
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from ..adapter_update import normalize_update_command
from .base import Adapter
from .registry import register_adapter, unregister_adapter

PACKAGE_ROOT = Path(__file__).parent
BUNDLED_ROOT = PACKAGE_ROOT / "bundled"
_LOADED_PATHS: dict[str, Path] = {}
_GENERATION = 0
logger = logging.getLogger(__name__)


def adapter_store() -> Path:
    """Directory holding repositories imported through the local API."""
    return Path(os.environ.get("PARTYLINE_ADAPTERS_DIR", "~/.partyline/adapters")).expanduser()


def _manifest(path: Path) -> dict:
    try:
        with (path / "adapter.toml").open("rb") as file:
            manifest = tomllib.load(file)["adapter"]
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"invalid adapter package: {path}") from exc
    required = {"name", "version", "description", "entrypoint", "command"}
    if missing := required - manifest.keys():
        raise ValueError(f"adapter manifest is missing: {', '.join(sorted(missing))}")
    manifest.setdefault("class", "PartylineAdapter")
    manifest.setdefault("requires", [])
    manifest.setdefault("capabilities", {})
    manifest.setdefault("env_unset", [])
    manifest.setdefault("compact_paste", None)
    command = manifest["command"]
    if not isinstance(command, list) or not all(isinstance(arg, str) for arg in command):
        raise ValueError("adapter command must be an argv array")
    if not isinstance(manifest["capabilities"], dict):
        raise ValueError("adapter capabilities must be a table, e.g. capabilities = { resume = true }")
    compact_paste = manifest["compact_paste"]
    if compact_paste is not None and (
        not isinstance(compact_paste, str) or not compact_paste.strip()
    ):
        raise ValueError("adapter compact_paste must be a non-empty paste string")
    manifest["update_command"] = normalize_update_command(manifest.get("update_command"))
    return manifest


def load_adapter(path: str | Path) -> str:
    """Load one adapter directory and return its registered ID."""
    directory = Path(path).resolve()
    manifest = _manifest(directory)
    adapter_id = str(manifest.get("id") or directory.name).strip().lower()
    entrypoint = directory / str(manifest["entrypoint"])
    if not entrypoint.is_file() or entrypoint.parent != directory:
        raise ValueError("adapter entrypoint must be a file in its package directory")
    # Every load gets a fresh module name rather than importlib.reload(), so a
    # reload re-executes the file instead of handing back a cached module. That
    # applies to bundled packages too: editing one and hitting reload should
    # take effect without restarting the server.
    global _GENERATION
    _GENERATION += 1
    fingerprint = hashlib.sha256(str(directory).encode()).hexdigest()[:12]
    module_name = f"partyline_adapter_{adapter_id}_{fingerprint}_{_GENERATION}"
    spec = importlib.util.spec_from_file_location(module_name, entrypoint)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load adapter entrypoint: {entrypoint}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    cls = getattr(module, str(manifest["class"]), None)
    if not isinstance(cls, type) or not issubclass(cls, Adapter):
        raise ValueError("adapter manifest class must inherit Adapter")
    # An imported package may share an id with a bundled one and take over. That
    # is intentional — it's how you override a shipped adapter — but it has to be
    # visible, so the listing always says where the loaded code came from.
    bundled_root = BUNDLED_ROOT.resolve()
    bundled = directory.parent == bundled_root
    overrides_bundled = not bundled and (bundled_root / adapter_id / "adapter.toml").is_file()
    manifest["source"] = "bundled" if bundled else str(directory)
    manifest["overrides_bundled"] = overrides_bundled
    if overrides_bundled:
        logger.warning("imported adapter %s overrides bundled adapter", adapter_id)
    register_adapter(adapter_id, cls, manifest)
    _LOADED_PATHS[adapter_id] = directory
    return adapter_id


def reload_adapter(adapter_id: str) -> str:
    """Replace a previously loaded adapter with the current package files."""
    path = _LOADED_PATHS.get(adapter_id)
    if path is None:
        raise ValueError(f"adapter is not loaded: {adapter_id}")
    replacement = _reload_path(adapter_id, path)
    if replacement is None:
        unregister_adapter(adapter_id)
        _LOADED_PATHS.pop(adapter_id, None)
        raise ValueError(f"adapter source is missing: {path}")
    return load_adapter(replacement)


def load_bundled_adapters():
    for manifest in sorted(BUNDLED_ROOT.glob("*/adapter.toml")):
        load_adapter(manifest.parent)


def load_installed_adapters() -> list[str]:
    """Re-register everything previously imported into the adapter store.

    Imports have to survive a restart: an attachment in the database names its
    adapter, so if a checkout were only registered at import time, every
    attachment using it would break the next time the server came up. A package
    that fails to load is skipped rather than taking the whole server down with
    it — one bad checkout should not make partyline unstartable.
    """
    loaded = []
    store = adapter_store()
    if not store.is_dir():
        return loaded
    for checkout in sorted(path for path in store.iterdir() if path.is_dir()):
        if checkout.name.startswith("."):
            logger.info("skipping hidden adapter checkout %s", checkout)
            continue
        for package in adapter_packages(checkout):
            try:
                loaded.append(load_adapter(package))
            except (ValueError, OSError, SyntaxError):
                continue
    return loaded


def adapter_packages(root: Path):
    """Yield package directories from a single package or a collection checkout."""
    if (root / "adapter.toml").is_file():
        yield root
    collection = root / "adapters"
    if collection.is_dir():
        yield from sorted(path.parent for path in collection.glob("*/adapter.toml"))


def _run_git(command: list[str]):
    subprocess.run(command, check=True, capture_output=True, text=True)


def _reload_path(adapter_id: str, path: Path) -> Path | None:
    if (path / "adapter.toml").is_file():
        return path
    bundled = BUNDLED_ROOT.resolve() / adapter_id
    return bundled if (bundled / "adapter.toml").is_file() else None


def import_repository(repository: str, ref: str | None = None) -> list[str]:
    """Clone or refresh a trusted repository and load all contained packages."""
    repository = repository.strip()
    if not repository:
        raise ValueError("repository is required")
    slug = repository.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", slug).strip(".-")
    if not slug:
        raise ValueError("repository must have a usable name")
    destination = adapter_store() / slug
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (destination / ".git").is_dir():
        git = ["git", "-C", str(destination)]
        _run_git(git + ["fetch", "--tags", "origin"])
        _run_git(git + ["checkout", "--force", ref or "origin/HEAD"])
    else:
        command = ["git", "clone", "--depth", "1"]
        if ref:
            command.extend(["--branch", ref])
        command.extend([repository, str(destination)])
        _run_git(command)
    loaded = [load_adapter(package) for package in adapter_packages(destination)]
    if not loaded:
        raise ValueError("repository contains no adapter.toml packages")
    return loaded


def reload_adapters() -> list[str]:
    """Reload known definitions; active attachments retain their loaded class."""
    loaded = []
    for adapter_id, path in list(_LOADED_PATHS.items()):
        replacement = _reload_path(adapter_id, path)
        if replacement is None:
            unregister_adapter(adapter_id)
            _LOADED_PATHS.pop(adapter_id, None)
            raise ValueError(f"adapter source is missing: {path}")
        loaded.append(load_adapter(replacement))
    return loaded
