"""Window snapshot transport and local consent races."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
        with patch("partyline.screen_elements.line_devices", return_value=[devices["d"]]) as visible:
            task = asyncio.create_task(hub.read("line"))
            request = await socket.messages.get()
            response = {"request_id": request["request_id"], "snapshot_id": "s", "window_title": "Editor",
                        "process_name": "app.exe", "elements": [{"id": 1, "name": "one\ntwo"}],
                        "truncated": True, "truncation": "time budget; page content not reached"}
            hub.receive({"id": "wrong"}, response)
            self.assertFalse(task.done())
            hub.receive({"id": "d"}, response)
            result = await task
            self.assertEqual("s", result["snapshot_id"])
            self.assertEqual("one\ntwo", json.loads(result["elements"])["name"])
            self.assertEqual(1, len(result["elements"].splitlines()))
            self.assertEqual("time budget; page content not reached", result["truncation"])
            self.assertEqual({}, hub.waiters)
            visible.return_value = []
            self.assertIn("elements_unavailable", await hub.read("elsewhere"))
            devices["other"] = {**devices["d"], "id": "other"}
            visible.return_value = list(devices.values())
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


class WindowTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_does_not_block_commands_and_rejects_overlap(self):
        from partyline_helper.uia_task import WindowTask
        entered, finish = asyncio.Event(), asyncio.Event()
        sent = []

        async def snapshot():
            entered.set()
            await finish.wait()
            return {"elements": []}

        async def send(kind, **fields):
            sent.append((kind, fields))

        worker = WindowTask(SimpleNamespace(window=SimpleNamespace(snapshot=snapshot), send=send))
        await worker.submit("first")
        await entered.wait()
        await worker.submit("second")
        self.assertEqual("window read already in progress", sent[0][1]["elements_unavailable"])
        finish.set()
        await worker.task
        self.assertEqual("first", sent[1][1]["request_id"])
        await worker.close()

    async def test_close_cancels_inflight_read(self):
        from partyline_helper.uia_task import WindowTask
        entered = asyncio.Event()
        async def snapshot():
            entered.set()
            await asyncio.Event().wait()
        send = unittest.mock.AsyncMock()
        worker = WindowTask(SimpleNamespace(window=SimpleNamespace(snapshot=snapshot), send=send))
        await worker.submit("first")
        await entered.wait()
        await worker.close()
        send.assert_not_awaited()


class ElementActionTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_control_consent_and_device_correlation(self):
        from unittest.mock import patch
        from fastapi import HTTPException
        from partyline.screen_element_actions import ElementAction, element_action
        socket = Socket()
        share = SimpleNamespace(share_id="share")
        device = {"id": "pc", "socket": socket}
        grant = SimpleNamespace(status="active", holder="agent")
        control = SimpleNamespace(target=lambda _: (share, device), grants={"share": grant}, _spend=Mock())
        elements = ElementsHub(SimpleNamespace(devices={}))
        hub = SimpleNamespace(control=control, elements=elements)
        principal = SimpleNamespace(name="agent")
        body = ElementAction(element_id="target", action="toggle")
        with patch("partyline.screen_element_actions.request_principal", return_value=principal), \
             patch("partyline.screen_element_actions.deny_unless"):
            task = asyncio.create_task(element_action(SimpleNamespace(db=None), hub, "line", body, None))
            request = await socket.messages.get()
            self.assertEqual("window_element_action", request["type"])
            elements.receive({"id": "other"}, {"request_id": request["request_id"]})
            self.assertFalse(task.done())
            elements.receive(device, {"request_id": request["request_id"], "status": "completed",
                                      "foreground_changed": True, "target_came_forward": True})
            self.assertEqual({"status": "completed", "foreground_changed": True,
                              "target_came_forward": True}, await task)
            self.assertFalse(elements.waiters)
            grant.status = "revoked"
            with self.assertRaises(HTTPException) as error:
                await element_action(SimpleNamespace(db=None), hub, "line", body, None)
            self.assertIn("not granted", error.exception.detail)


class WindowIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_recycled_handle_does_not_inherit_grant(self):
        from unittest.mock import patch
        grant = {"hwnd": 10, "pid": 42, "title": "Target", "process": "app", "marker": "unique"}
        session = SimpleNamespace(status=SimpleNamespace(window_title=None, changed=Mock()),
                                  tools=SimpleNamespace(audit=SimpleNamespace(append=Mock())),
                                  share=None, accepted=False, last_uia_frame=None)
        access = WindowAccess(session, picker=lambda: grant, list_windows=lambda: [grant], platform="win32")
        with patch("partyline_helper.uia_access.live", return_value=True), \
             patch("partyline_helper.uia_access.unmark") as unmark:
            await access.choose()
            self.assertIs(access.grant, grant)
            with patch("partyline_helper.uia_access.live", return_value=False):
                result = await access.snapshot()
            self.assertEqual("window closed", result["elements_unavailable"])
            self.assertIsNone(access.grant)
            unmark.assert_called_once_with(grant)
