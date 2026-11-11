"""Run UIA in a child: initialization has its own deadline; a hung walk is killed."""
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from .uia_snapshot import BUDGET

KILL_SLACK = 4  # a part may overrun its budget by one slow call before the kill; see uia_task.READ_TIMEOUT
START_LIMIT = 25


def command(payload):
    if getattr(sys, "frozen", False):
        return [sys.executable, "uia-snapshot", payload]
    return [sys.executable, "-m", "partyline_helper.uia_process", payload]


def read(hwnd, frame=None, state=None, deep=True, popen=subprocess.Popen, platform=sys.platform,
         ready_wait=None):
    if platform != "win32":
        return {"elements_unavailable": "Windows UI Automation is not available on this platform"}
    with tempfile.TemporaryDirectory(prefix="partyline-uia-") as directory:
        path, ready = Path(directory) / "snapshot.json", Path(directory) / "ready"
        saved = Path(directory) / "state.json"  # the frontier can be far longer than a command line
        if state:
            saved.write_text(json.dumps(state), encoding="utf-8")
        payload = json.dumps([hwnd, frame, str(path), str(ready), str(saved) if state else None, deep])
        process = None
        try:
            process = popen(command(payload), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=0x08000000)
            ready_event = threading.Event()
            announcement = []

            def initialized():
                try:
                    announcement.append(process.stdout.readline())
                except OSError:
                    pass  # A failed child closes its pipe; readiness remains unproved.
                finally:
                    ready_event.set()

            threading.Thread(target=initialized, name='uia-ready', daemon=True).start()
            wait_ready = ready_wait or ready_event.wait
            # Windows text-mode stdout writes CRLF, so compare the stripped line.
            if not wait_ready(START_LIMIT) or [line.strip() for line in announcement] != [b"READY"]:
                process.kill()
                process.wait()
                return {"elements_unavailable": "timeout", "truncated": True}
            try:
                process.wait(timeout=BUDGET + KILL_SLACK)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                return {"elements_unavailable": "timeout", "truncated": True}
            if process.returncode:
                return {"elements_unavailable": "Windows UI Automation failed"}
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, subprocess.SubprocessError):
            return {"elements_unavailable": "Windows UI Automation failed"}
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            if process is not None and getattr(process, 'stdout', None) is not None:
                process.stdout.close()


def initialize():  # pragma: no cover - native Windows UIA type library
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient
    return UIAutomationClient


def main(request=None):  # pragma: no cover - isolated Windows child process
    from .uia_snapshot import snapshot
    from .uia_windows import WindowsProvider
    hwnd, frame, path, ready, saved, deep = json.loads(request or sys.argv[1])
    provider = WindowsProvider(hwnd, cached=True, deep=deep and not saved)
    provider.root()  # the whole-tree prefetch runs under the start limit, not the walk's budget
    print("READY", flush=True)
    state = json.loads(Path(saved).read_text(encoding="utf-8")) if saved else None
    result = snapshot(provider, frame, state=state)
    Path(path).write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
