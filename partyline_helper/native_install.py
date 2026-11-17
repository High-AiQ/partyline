"""Per-user native-host registration and installed unpacked extension assets."""
import json
import os
import re
import shutil
from pathlib import Path

from .chrome_identity import HOST, ORIGIN
from .config import config_path

REGISTRY_KEY = "Software\\Google\\Chrome\\NativeMessagingHosts\\" + HOST


def host_executable(launch, system):
    base = Path(launch[0]).parent
    names = ("PartylineChromeHost.exe", "partyline-chrome-host.exe") if system == "Windows" else (
        "partyline-chrome-host",)
    return next((base / name for name in names if (base / name).is_file()), None)


def paths(system, home):
    root = config_path().parent
    if system == "Darwin":
        manifest = home / "Library/Application Support/Google/Chrome/NativeMessagingHosts" / f"{HOST}.json"
    elif system == "Linux":
        manifest = home / ".config/google-chrome/NativeMessagingHosts" / f"{HOST}.json"
    else:
        manifest = root / "chrome-native-host.json"
    return root / "chrome-extension", manifest


def missing_worker_imports(source):
    """Return statically imported extension files that are absent from the source folder."""
    worker = source / "worker.js"
    if not worker.is_file():
        return [worker.name]
    pending, visited, missing = [worker], set(), []
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        for name in re.findall(r"\bimport\s+(?:[^;]*?\s+from\s+)?['\"]\./([^'\"]+\.js)['\"]",
                               path.read_text(encoding="utf-8")):
            imported = source / name
            if not imported.is_file():
                missing.append(name)
            elif imported not in visited:
                pending.append(imported)
    return sorted(set(missing))


def install(system, home, launch, registry=None):
    executable = host_executable(launch, system)
    if executable is None:
        return ["Chrome: native host launcher missing; reinstall the helper. "
                "Remote debugging remains available."]
    folder, manifest = paths(system, home)
    source = Path(__file__).with_name("chrome_extension")
    if not source.exists():
        source = Path(__file__).parent.parent / "partyline_chrome"
    missing = missing_worker_imports(source)
    if missing:
        return ["Chrome: extension worker imports missing file(s): " + ", ".join(missing)
                + "; reinstall the helper package."]
    folder.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.name == "manifest.json" or path.suffix == ".js" and not path.name.endswith(".test.js"):
            shutil.copyfile(path, folder / path.name)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"name": HOST, "description": "Partyline Chrome bridge",
                                  "path": str(executable.resolve()), "type": "stdio",
                                  "allowed_origins": [ORIGIN]}, indent=2))
    if system == "Windows":
        registry.set(REGISTRY_KEY, "", str(manifest.resolve()))
    elif os.name != "nt":
        manifest.chmod(0o600)
    return [f"Chrome native host: {manifest}", f"Load unpacked extension once: {folder}"]


def uninstall(system, home, registry=None):
    folder, manifest = paths(system, home)
    if system == "Windows":
        registry.delete_tree(REGISTRY_KEY)
    manifest_existed, folder_existed = manifest.exists(), folder.exists()
    manifest.unlink(missing_ok=True)
    folder.parent.joinpath("chrome-native.lock").unlink(missing_ok=True)  # the extension is no longer known
    if folder.exists():
        shutil.rmtree(folder)
    return [f"{'removed' if manifest_existed else 'not present'} Chrome native host: {manifest}",
            f"{'removed' if folder_existed else 'not present'} extension files: {folder}"]
