"""A separate helper process waits on OS events and retains the previous version for rollback."""
import ctypes as C
import json
import os
import subprocess
import uuid

from partyline.process_events import wait_pid
from .config import config_path, save_config
from .launch import current_launch
from .update_installer import Installer
from . import update_timing as budget
from . import update_cleanup as cleanup


class Completion:
    def __init__(self, name, kernel=None):
        self.kernel = kernel or C.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateEventW.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_wchar_p]
        self.kernel.CreateEventW.restype = C.c_void_p
        self.kernel.OpenEventW.argtypes = [C.c_uint32, C.c_int, C.c_wchar_p]
        self.kernel.OpenEventW.restype = C.c_void_p
        self.kernel.WaitForSingleObject.argtypes = [C.c_void_p, C.c_uint32]
        self.kernel.WaitForSingleObject.restype = C.c_uint32
        self.kernel.SetEvent.argtypes = [C.c_void_p]
        self.kernel.CloseHandle.argtypes = [C.c_void_p]
        self.handle = self.kernel.CreateEventW(None, True, False, name)
        if not self.handle:
            raise OSError("Cannot create update completion event")

    def wait(self, seconds):
        return self.kernel.WaitForSingleObject(self.handle, int(seconds * 1000)) == 0

    def close(self):
        self.kernel.CloseHandle(self.handle)


def signal(name, kernel=None):
    event = Completion(name, kernel)
    try:
        if not event.kernel.SetEvent(event.handle):
            raise OSError("Cannot signal update completion")
    finally:
        event.close()


def launch(installer, version, popen=subprocess.Popen, command=None, readiness=Completion, name=None):
    root = config_path().parent / "updates"
    root.mkdir(parents=True, exist_ok=True)
    name = name or "Local\\PartylineHelperUpdate-" + uuid.uuid4().hex
    command = command or current_launch()
    plan = root / "install-plan.json"
    save_config({"installer": str(installer), "previous": command, "pid": os.getpid(),
                 "event": name, "version": version}, plan)
    # Versioned installer folders keep this supervisor and the old native host's files intact.
    ready = readiness(name + "-ready")
    try:
        child = popen([*command, "update-install", str(plan)], creationflags=0x08000000,
                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, close_fds=True)
        if not ready.wait(budget.READY):
            child.terminate()
            raise OSError("Update supervisor did not become ready")
    finally:
        ready.close()
    return name


def run(plan, execute=subprocess.run, wait=wait_pid, completion=Completion,
        installation=Installer, ready=signal):
    data = json.loads(plan.read_text(encoding="utf-8"))
    event = installer = None
    try:
        event = completion(data["event"])
        ready(data["event"] + "-ready")
        if not wait(data["pid"], timeout=budget.PARENT_STOP):
            raise RuntimeError("Previous helper did not stop")
        installer = installation(data["installer"])
        if installer.wait(timeout=budget.INSTALL) or not event.wait(budget.RECONNECT):
            raise RuntimeError("Installer failed or updated helper did not reconnect")
        cleanup.versions(data["previous"], data["version"])
        return True
    except (OSError, RuntimeError, subprocess.SubprocessError):
        if installer:
            installer.abort()
        # The new helper may be alive but unable to connect. Stop by its protected instance PID.
        execute([*data["previous"], "stop"], timeout=budget.ROLLBACK_STOP, check=True)
        save_config({"version": data["version"], "failed": True}, plan.parent / "result.json")
        try:
            execute([*data["previous"], "install"], timeout=budget.ROLLBACK_INSTALL, check=True)
        except (OSError, subprocess.SubprocessError):
            pass  # A registration/shortcut repair failure must still restart the previous working helper.
        execute([*data["previous"], "start"], timeout=budget.ROLLBACK_START, check=True)
        return False
    finally:
        if installer:
            installer.close()
        if event:
            event.close()
        cleanup.installer(data["installer"])


def result():
    path = config_path().parent / "updates" / "result.json"
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
