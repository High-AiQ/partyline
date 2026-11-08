"""Window snapshot transport and local consent races."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from partyline.screen_elements import ElementsHub
from partyline_helper.uia_access import WindowAccess


class Socket:
    def __init__(self):
        self.messages = asyncio.Queue()

    async def send_json(self, message):
        self.messages.put_nowait(message)


class ElementsTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_correlates_device_and_formats_one_line_per_element(self):
        socket = Socket()
        devices = {"d": {"id": "d", "conv_id": "line", "name": "PC", "socket": socket}}
        hub = ElementsHub(SimpleNamespace(devices=devices))
        task = asyncio.create_task(hub.read("line"))
        request = await socket.messages.get()
        response = {"request_id": request["request_id"], "snapshot_id": "s", "window_title": "Editor",
                    "process_name": "app.exe", "elements": [{"id": 1, "name": "one\ntwo"}],
                    "truncated": False}
        hub.receive({"id": "wrong"}, response)
        self.assertFalse(task.done())
        hub.receive({"id": "d"}, response)
        result = await task
        self.assertEqual("s", result["snapshot_id"])
        self.assertEqual("one\ntwo", json.loads(result["elements"])["name"])
        self.assertEqual(1, len(result["elements"].splitlines()))
        self.assertEqual({}, hub.waiters)
        self.assertIn("elements_unavailable", await hub.read("elsewhere"))
        devices["other"] = {**devices["d"], "id": "other"}
        self.assertIn("multiple", (await hub.read("line"))["elements_unavailable"])

    async def test_revocation_during_read_discards_result(self):
        import threading
        entered, resume = threading.Event(), threading.Event()
        grant = {"hwnd": 10, "pid": 42, "title": "Target", "process": "app.exe"}
        session = SimpleNamespace(status=SimpleNamespace(window_title=None, changed=Mock()),
                                  tools=SimpleNamespace(audit=SimpleNamespace(append=Mock())),
                                  share=None, accepted=False, last_uia_frame=None)
        def reader(*args):
            entered.set()
            resume.wait()
            return {"elements": [{"name": "private"}], "snapshot_id": "id"}
        access = WindowAccess(session, picker=lambda: grant, list_windows=lambda: [grant], reader=reader,
                              platform="win32")
        await access.choose()
        task = asyncio.create_task(access.snapshot())
        await asyncio.to_thread(entered.wait)
        access.revoke()
        resume.set()
        self.assertEqual("consent revoked", (await task)["elements_unavailable"])
