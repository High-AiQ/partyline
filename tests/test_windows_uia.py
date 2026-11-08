"""Windows UIA integration: a background window remains readable without focusing it."""
import asyncio
import json
import queue
import subprocess
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock


@unittest.skipUnless(sys.platform == "win32", "Windows UI Automation requires Windows")
class WindowsUIATests(unittest.TestCase):
    def test_background_tk_window(self):  # pragma: no cover - Windows CI
        import ctypes
        process = subprocess.Popen([sys.executable, "-u", "-m", "tests.windows_uia_window"],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        try:
            try:
                ready = lines.get(timeout=20)
            except queue.Empty:
                self.fail("test window did not become ready")
            self.assertTrue(ready, "test window exited before reporting its controls")
            window = json.loads(ready)
            from partyline_helper.uia_access import WindowAccess
            grant = {"hwnd": window["hwnd"], "pid": window["pid"], "title": "Partyline UIA target",
                     "process": "python.exe"}
            session = SimpleNamespace(status=SimpleNamespace(window_title=None, changed=Mock()),
                                      tools=SimpleNamespace(audit=SimpleNamespace(append=Mock())),
                                      share=None, accepted=False, last_uia_frame=None)
            access = WindowAccess(session, picker=lambda: grant, list_windows=lambda: [grant],
                                  platform="win32")
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            foreground = user32.GetForegroundWindow()
            self.assertTrue(foreground)
            self.assertNotEqual(window["hwnd"], foreground)

            async def capture():
                await access.choose()
                return await access.snapshot()
            result = asyncio.run(capture())
            self.assertIn("elements", result, result)
            for expected in window["bounds"]:
                matches = (all(abs(a - b) <= 3 for a, b in zip(item["bounds"], expected, strict=True))
                           for item in result["elements"])
                self.assertTrue(any(matches), (expected, result))
            self.assertEqual(foreground, user32.GetForegroundWindow())
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            process.stdout.close()
