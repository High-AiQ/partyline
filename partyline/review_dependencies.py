"""Provision locked JavaScript dependencies inside disposable review checkouts."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path

from .review_install_sandbox import (DependencyError, cache_location, install_argv, local_cache,
                                     run_installer)

LOCKS = {
    "uv.lock": ("uv", "sync", "--frozen", "--all-extras", "--all-groups"),
    "package-lock.json": ("npm", "ci", "--prefer-offline", "--ignore-scripts"),
    "npm-shrinkwrap.json": ("npm", "ci", "--prefer-offline", "--ignore-scripts"),
    "pnpm-lock.yaml": ("pnpm", "install", "--frozen-lockfile", "--prefer-offline",
                       "--package-import-method=copy", "--ignore-scripts"),
    "yarn.lock": ("yarn", "install", "--frozen-lockfile", "--prefer-offline", "--ignore-scripts"),
}


def _protected_install(modules: Path, root: str) -> bool:
    """Links must stay under the protected repository, away from writable review areas."""
    protected = Path(root).resolve()
    installed = modules.resolve()
    def safe(item: Path) -> bool:
        try:
            relative = item.resolve().relative_to(protected)
        except ValueError:
            return False
        return not relative.parts or relative.parts[0] not in (".review", ".scratch", ".git")

    pending, visited = [modules], set()
    while pending:
        directory = pending.pop()
        if not safe(directory):
            return False
        real = directory.resolve()
        if real in visited:
            continue
        visited.add(real)
        with os.scandir(real) as entries:
            for entry in entries:
                item = Path(entry.path)
                if entry.is_symlink():
                    if not safe(item) or not item.resolve().is_relative_to(installed):
                        return False  # workspace links must resolve against the reviewed tree
                if entry.is_dir(follow_symlinks=True):
                    pending.append(item)
    return True


def _incompatible_optional(data: dict) -> bool:
    """A missing optional package is explainable only by explicit platform restrictions."""
    if not data.get("optional"):
        return False
    system = {"Linux": "linux", "Darwin": "darwin", "Windows": "win32"}.get(platform.system())
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64",
            "i386": "ia32", "i686": "ia32", "armv7l": "arm"}.get(machine)
    for key, value in (("os", system), ("cpu", arch)):
        allowed = data.get(key, [])
        if not value or not isinstance(allowed, list):
            continue
        positives = [item for item in allowed if isinstance(item, str) and not item.startswith("!")]
        if f"!{value}" in allowed or (positives and value not in positives):
            return True
    return False


def _verified_install(candidate: Path, lock: str) -> bool:
    """Only npm's installed lock has a format we can verify; otherwise install locally."""
    if lock not in ("package-lock.json", "npm-shrinkwrap.json"):
        return False
    with (candidate / lock).open(encoding="utf-8") as file:
        expected = json.load(file)
    hidden = candidate / "node_modules" / ".package-lock.json"
    with hidden.open(encoding="utf-8") as file:
        installed = json.load(file)
    if expected.get("lockfileVersion") not in (2, 3) or installed.get("lockfileVersion") != 3:
        return False
    want, have = expected.get("packages"), installed.get("packages")
    if not isinstance(want, dict) or not isinstance(have, dict):
        return False
    if any(want.get(name) != data for name, data in have.items()):
        return False
    if any(name and name not in have and not _incompatible_optional(data)
           for name, data in want.items()):
        return False
    timestamp = hidden.stat().st_mtime_ns
    for name in have:
        item = candidate / name
        if not item.is_dir() or item.stat().st_mtime_ns > timestamp:
            return False
    return True


def _link_install(folder: str, path: str, sources: list[str], lock: str) -> bool:
    relative = os.path.relpath(folder, path)
    for source in sources:
        candidate = Path(source) / relative
        try:
            if any((candidate / name).read_bytes() != (Path(folder) / name).read_bytes()
                   for name in ("package.json", lock)):
                continue
            modules = candidate / "node_modules"
            if (not modules.is_dir() or not _verified_install(candidate, lock)
                    or not _protected_install(modules, sources[-1])):
                continue
            target = Path(folder) / "node_modules"
            target.mkdir()
            for item in modules.iterdir():
                if item.name.startswith(".") and item.name != ".bin":
                    continue  # caches belong in the review checkout
                (target / item.name).symlink_to(item.resolve(), target_is_directory=item.is_dir())
            return True
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return False


def provision(path: str, sources: list[str] | None = None,
              changed: list[str] | None = None, overrides=None) -> None:
    """Link protected matching installs or install each locked package locally."""
    try:
        selected = None
        custom = {}
        if changed is not None:
            selected = set()
            overrides = overrides or []
            for entry in overrides:
                folder = os.path.join(path, entry.subpath)
                if not Path(folder).resolve().is_relative_to(Path(path).resolve()):
                    raise ValueError(f"environment subpath escapes review checkout: {entry.subpath}")
                if entry.setup_command:
                    custom[folder] = entry.setup_command
            for name in changed:
                parts = Path(name).parts
                matches = [e for e in overrides
                           if parts[:len(Path(e.subpath).parts)] == Path(e.subpath).parts]
                entry = max(matches, key=lambda e: len(Path(e.subpath).parts)) if matches else None
                if entry and entry.setup_command:
                    continue
                folder = Path(path, name).parent
                while folder.is_relative_to(path):
                    if any((folder / lock).is_file() for lock in LOCKS):
                        selected.add(str(folder))
                        break
                    if folder == Path(path):
                        break
                    folder = folder.parent
            for folder, command in custom.items():
                tmp = local_cache(path, "tmp")
                env = dict(os.environ, TMPDIR=tmp, TMP=tmp, TEMP=tmp)
                result = run_installer(install_argv(path, ("/bin/sh", "-c", command), os.path.dirname(tmp)),
                                       cwd=folder, timeout=300, env=env)
                if result.returncode:
                    detail = (result.stderr or result.stdout).strip()[-1000:]
                    raise ValueError(f"setup in {folder} failed: {detail}")
        for folder, dirs, files in os.walk(path, followlinks=False):
            dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", ".venv")
                       and not os.path.islink(os.path.join(folder, d))]
            if selected is not None and folder not in selected:
                continue
            locks = [name for name in LOCKS if name in files]
            if not locks:
                continue
            if "npm-shrinkwrap.json" in locks and "package-lock.json" in locks:
                locks.remove("package-lock.json")  # npm gives shrinkwrap precedence
            js_locks = [name for name in locks if name in (
                "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock")]
            if len(js_locks) > 1:
                raise ValueError(f"multiple lockfiles in {folder} for JavaScript")
            for lock_name in locks:
                _install_lock(path, folder, lock_name, sources or [])
    except subprocess.TimeoutExpired as exc:
        raise DependencyError("installer timed out after 300 seconds") from exc
    except (OSError, ValueError) as exc:
        raise DependencyError(str(exc)) from exc


def _install_lock(path: str, folder: str, lock_name: str, sources: list[str]) -> None:
    if (lock_name in ("package-lock.json", "npm-shrinkwrap.json")
            and _link_install(folder, path, sources or [], lock_name)):
        return
    command = LOCKS[lock_name]
    if lock_name == "yarn.lock":
        with open(os.path.join(folder, "yarn.lock"), encoding="utf-8") as lock:
            if "__metadata:" in lock.read():
                command = ("yarn", "install", "--immutable")
    env = dict(os.environ, YARN_ENABLE_SCRIPTS="0")
    tmp = local_cache(path, "tmp")
    env.update(TMPDIR=tmp, TMP=tmp, TEMP=tmp)
    if lock_name == "uv.lock":
        env["UV_CACHE_DIR"] = cache_location(path, "uv", ".cache/uv")
        env["UV_LINK_MODE"] = "copy"
        env["UV_PROJECT_ENVIRONMENT"] = os.path.join(folder, ".venv")
        if not Path(env["UV_PROJECT_ENVIRONMENT"]).resolve().is_relative_to(Path(path).resolve()):
            raise ValueError("dependency directory escapes review checkout")
    elif lock_name in ("package-lock.json", "npm-shrinkwrap.json"):
        env["npm_config_cache"] = cache_location(path, "npm", ".npm")
    elif lock_name == "pnpm-lock.yaml":
        store = cache_location(path, "pnpm", ".local/share/pnpm/store")
        command = (*command, "--store-dir", store)
    elif lock_name == "yarn.lock":
        cache = ".yarn/berry/cache" if "--immutable" in command else ".cache/yarn"
        env["YARN_CACHE_FOLDER"] = cache_location(path, "yarn", cache)
    result = run_installer(install_argv(path, command, os.path.dirname(tmp)),
                           cwd=folder, timeout=300, env=env)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-1000:]
        raise ValueError(f"{lock_name} install in {folder} failed: {detail}")
    if lock_name == "uv.lock":
        venv = os.path.join(folder, ".venv")
        if not os.path.realpath(venv).startswith(os.path.realpath(path) + os.sep):
            raise ValueError(f"dependency directory escapes review checkout: {venv}")
        return
    if lock_name not in ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock"):
        return
    modules = os.path.join(folder, "node_modules")
    if not os.path.isdir(modules):
        os.makedirs(modules)
    for base, subdirs, names in os.walk(modules, followlinks=False):
        for name in subdirs + names:
            item = os.path.join(base, name)
            if os.path.islink(item) and os.path.commonpath(
                    (os.path.realpath(path), os.path.realpath(item))) != os.path.realpath(path):
                raise ValueError(f"dependency symlink escapes review checkout: {item}")
    if os.path.commonpath((os.path.realpath(path), os.path.realpath(modules))) != \
            os.path.realpath(path):
        raise ValueError(f"dependency directory escapes review checkout: {modules}")


def sources_for(db, conv_id: str, root: str) -> list[str]:
    """Prefer this task's checkout, then the repository's host checkout."""
    from .line_worktree import line_cwd, repo_and_worktree, _git
    from .task_workspaces import workspaces

    sources = [item["path"] for item in workspaces(db, conv_id)
               if os.path.realpath(item["repository"]) == os.path.realpath(root)]
    cwd = line_cwd(db, conv_id)
    if cwd and os.path.realpath(repo_and_worktree(cwd)[0] or "") == os.path.realpath(root):
        result = _git("rev-parse", "--show-toplevel", cwd=cwd)
        if result.returncode == 0:
            sources.append(result.stdout.strip())
    return list(dict.fromkeys([*sources, root]))
