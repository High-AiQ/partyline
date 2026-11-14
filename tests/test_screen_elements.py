"""Window snapshot transport and local consent races."""
import asyncio
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
    async def test_capture_reads_every_part_and_answers_a_summary(self):
        socket = Socket()
        devices = {"d": {"id": "d", "conv_id": "line", "name": "PC", "socket": socket}}
        hub = ElementsHub(SimpleNamespace(devices=devices))
        principal = SimpleNamespace(kind="machine", attachment_id="a")
        grant = {"id": "g", "title": "Editor", "process": "app.exe"}
        from unittest.mock import patch
        with patch("partyline.screen_elements.resolve_window", return_value=(grant, devices["d"])), \
             patch("partyline.screen_elements.require_window"):
            task = asyncio.create_task(hub.read(principal))
            request = await socket.messages.get()
            self.assertNotIn("cursor", request)
            first = {"request_id": request["request_id"], "snapshot_id": "s", "truncated": True,
                     "next_cursor": "c1",
                     "elements": [{"id": "w", "control_type": "Window", "name": "Editor"}]}
            hub.receive({"id": "wrong"}, first)
            self.assertFalse(task.done())
            hub.receive({"id": "d"}, first)
            request = await socket.messages.get()
            self.assertEqual("c1", request["cursor"])
            hub.receive({"id": "d"}, {"request_id": request["request_id"], "elements": [
                {"id": "b", "parent": "w", "control_type": "Button", "name": "OK", "actions": ["invoke"]}]})
            result = await task
            self.assertEqual({}, hub.waiters)
            self.assertEqual("s", result["snapshot_id"])
            self.assertEqual(2, result["nodes"])
            self.assertEqual("Editor", result["window_title"])
            self.assertNotIn("partial", result)
            # Later questions use the stored tree: no message reaches the helper.
            found = await hub.read(principal, options={"query": "ok"})
            self.assertEqual(f'in: Window Editor\n{hub.snapshots["g"].by_helper["b"]} Button "OK" [invoke]',
                             found["lines"])
            self.assertTrue(socket.messages.empty())

    async def test_late_dropdown_update_is_read_and_action_uses_the_new_helper_id(self):
        from unittest.mock import AsyncMock, patch
        from partyline.screen_element_actions import ElementAction, element_action

        socket = Socket()
        device = {"id": "d", "socket": socket}
        devices = {"d": device}
        hub = ElementsHub(SimpleNamespace(devices=devices), clock=lambda: 10.0)
        principal = SimpleNamespace(kind="machine", attachment_id="a", name="agent")
        grant = {"id": "g", "title": "Editor", "process": "app.exe"}
        enabled = False

        async def read(enabled_state):
            task = asyncio.create_task(hub.read(principal, options={"query": "Continue"}))
            request = await socket.messages.get()
            elements = [{"id": "window", "control_type": "Window", "name": "Editor"},
                        {"id": "dropdown", "parent": "window", "control_type": "ComboBox",
                         "name": "Mode", "enabled": True},
                        {"id": "button-live" if enabled_state else "button-old", "parent": "window",
                         "control_type": "Button", "name": "Continue", "enabled": enabled_state,
                         "actions": ["invoke"]}]
            hub.receive(device, {"request_id": request["request_id"], "snapshot_id": "snap",
                                 "elements": elements})
            return await task

        with patch("partyline.screen_elements.resolve_window", return_value=(grant, device)), \
             patch("partyline.screen_elements.require_window"):
            stale = await read(enabled)
            self.assertIn("disabled", stale["lines"])
            old_id = next(key for key, node in hub.snapshots["g"].nodes.items()
                          if node.name == "Continue")
            dropdown_id = next(key for key, node in hub.snapshots["g"].nodes.items()
                               if node.name == "Mode")
            elements_hub = hub
            action_hub = SimpleNamespace(elements=elements_hub,
                                         window_grants=SimpleNamespace(spend=Mock()))
            exchange = elements_hub.exchange
            elements_hub.exchange = AsyncMock(return_value={"status": "completed"})
            with patch("partyline.screen_element_actions.request_principal", return_value=principal), \
                 patch("partyline.screen_element_actions.deny_unless"), \
                 patch("partyline.screen_element_actions.resolve_window", return_value=(grant, device)), \
                 patch("partyline.screen_elements.require_window"):
                selected = await element_action(SimpleNamespace(db=None), action_hub, "line",
                                                ElementAction(element_id=dropdown_id, action="select"), None)
            self.assertEqual("completed", selected["status"])
            self.assertEqual("dropdown", elements_hub.exchange.await_args.kwargs["element_id"])
            # The application handles the selection after the action; its event invalidates the stale read.
            enabled = True
            hub.changed("g")
            elements_hub.exchange = exchange
            fresh = await read(enabled)
            self.assertNotIn("disabled", fresh["lines"])
            self.assertEqual(0, fresh["snapshot_age_seconds"])
            new_id = next(key for key, node in hub.snapshots["g"].nodes.items()
                          if node.name == "Continue")
            self.assertEqual(old_id, new_id)

            elements_hub.exchange = AsyncMock(return_value={"status": "completed"})
            with patch("partyline.screen_element_actions.request_principal", return_value=principal), \
                 patch("partyline.screen_element_actions.deny_unless"), \
                 patch("partyline.screen_element_actions.resolve_window", return_value=(grant, device)), \
                 patch("partyline.screen_elements.require_window"):
                result = await element_action(SimpleNamespace(db=None), action_hub, "line",
                                              ElementAction(element_id=new_id, action="invoke"), None)
            self.assertEqual("completed", result["status"])
            self.assertEqual("button-live", elements_hub.exchange.await_args.kwargs["element_id"])
            self.assertIn("g", elements_hub.after_action)

    async def test_age_bound_refreshes_without_events_and_event_keeps_id_space(self):
        from unittest.mock import patch

        socket = Socket()
        device = {"id": "d", "socket": socket}
        principal = SimpleNamespace(kind="machine", attachment_id="a")
        grant = {"id": "g", "title": "Editor", "process": "app.exe"}
        clock = [1.0]
        hub = ElementsHub(SimpleNamespace(devices={"d": device}), clock=lambda: clock[0])

        async def capture(name):
            task = asyncio.create_task(hub.read(principal, options={"query": "OK"}))
            request = await socket.messages.get()
            hub.receive(device, {"request_id": request["request_id"], "snapshot_id": name,
                "elements": [{"id": "w", "control_type": "Window", "name": "Editor"},
                             {"id": name, "parent": "w", "control_type": "Button", "name": "OK",
                              "enabled": True, "actions": ["invoke"]}]})
            return await task

        with patch("partyline.screen_elements.resolve_window", return_value=(grant, device)), \
             patch("partyline.screen_elements.require_window"):
            first = await capture("first")
            ident = next(iter(hub.snapshots["g"].nodes))
            clock[0] += 3.1
            second = await capture("second")  # no event registration: bounded staleness is the fallback
            self.assertEqual(0, second["snapshot_age_seconds"])
            self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
            hub.changed("g")
            third = await capture("third")
            self.assertEqual(ident, next(iter(hub.snapshots["g"].nodes)))
            self.assertFalse(third["change_event_since_snapshot"])

    async def test_action_target_keeps_mapping_across_age_boundary(self):
        from partyline.screen_tree import Snapshot
        from partyline.screen_tree_ids import IdSpace

        times = iter((2.999, 3.001))
        space = IdSpace()
        tree = Snapshot("fresh", 0, space)
        tree.add([{"id": "window", "control_type": "Window", "name": "Editor"},
                  {"id": "helper-button", "parent": "window", "control_type": "Button",
                   "name": "Continue"}])
        tree.event_version = 0
        hub = ElementsHub(SimpleNamespace(devices={}), clock=lambda: next(times))
        hub.spaces["g"] = space
        hub.remember("g", tree)
        stable_id = next(key for key, node in tree.nodes.items() if node.name == "Continue")

        target, known = await hub.action_target(SimpleNamespace(), {"id": "g"}, stable_id)

        self.assertTrue(known)
        self.assertEqual("helper-button", target)

    async def test_more_continues_a_partial_capture_past_the_reuse_age(self):
        from unittest.mock import patch

        socket = Socket()
        device = {"id": "d", "socket": socket}
        principal = SimpleNamespace(kind="machine", attachment_id="a")
        grant = {"id": "g", "title": "Editor", "process": "app.exe"}
        clock = [0.0]
        hub = ElementsHub(SimpleNamespace(devices={"d": device}), clock=lambda: clock[0])
        with patch("partyline.screen_elements.resolve_window", return_value=(grant, device)), \
             patch("partyline.screen_elements.require_window"):
            task = asyncio.create_task(hub.read(principal))
            first = await socket.messages.get()
            clock[0] = 21  # finish the first part at the fake capture deadline
            hub.receive(device, {"request_id": first["request_id"], "snapshot_id": "same",
                                 "next_cursor": "cursor", "elements": [
                                     {"id": "w", "control_type": "Window", "name": "Editor"}]})
            partial = await task
            self.assertIn("partial", partial)
            clock[0] = 30
            task = asyncio.create_task(hub.read(principal, options={"more": True}))
            continuation = await socket.messages.get()
            self.assertEqual("cursor", continuation["cursor"])
            hub.receive(device, {"request_id": continuation["request_id"], "elements": []})
            final = await task
        self.assertEqual("same", final["snapshot_id"])
        self.assertEqual(0, final["snapshot_age_seconds"])

    async def test_plain_read_expires_an_old_partial_snapshot(self):
        from unittest.mock import patch

        socket = Socket()
        device = {"id": "d", "socket": socket}
        principal = SimpleNamespace(kind="machine", attachment_id="a")
        grant = {"id": "g", "title": "Editor", "process": "app.exe"}
        clock = [0.0]
        hub = ElementsHub(SimpleNamespace(devices={"d": device}), clock=lambda: clock[0])
        with patch("partyline.screen_elements.resolve_window", return_value=(grant, device)), \
             patch("partyline.screen_elements.require_window"):
            task = asyncio.create_task(hub.read(principal))
            first = await socket.messages.get()
            clock[0] = 21
            hub.receive(device, {"request_id": first["request_id"], "snapshot_id": "old",
                                 "next_cursor": "cursor", "elements": [
                                     {"id": "w", "control_type": "Window", "name": "Editor"}]})
            self.assertIn("partial", await task)
            clock[0] = 300
            task = asyncio.create_task(hub.read(principal, options={"query": "Editor"}))
            refresh = await socket.messages.get()
            self.assertNotIn("cursor", refresh)
            hub.receive(device, {"request_id": refresh["request_id"], "snapshot_id": "new",
                                 "elements": [{"id": "w", "control_type": "Window", "name": "Editor"}]})
            result = await task
        self.assertEqual("new", result["snapshot_id"])
        self.assertEqual(0, result["snapshot_age_seconds"])

    async def test_expired_stable_id_is_refreshed_before_real_helper_invoke(self):
        from unittest.mock import patch
        from partyline.screen_element_actions import ElementAction, element_action
        from partyline.screen_tree import Snapshot
        from partyline.screen_tree_ids import IdSpace
        from partyline_helper.uia_action_worker import run_action
        from partyline_helper.uia_gate import DispatchGate
        from partyline_helper.uia_identity import element_id

        class App:
            def __init__(self):
                self.invocations = 0

            def root(self):
                return 0

            def runtime_id(self, node):
                return [node]

            def same_window(self, node):
                return True

            def current(self):
                return True

            def children(self, node):
                return [1] if node == 0 else []

            def properties(self, node):
                return {"control_type": "Window", "name": "Editor", "enabled": True,
                        "patterns": []} if node == 0 else {
                            "control_type": "Button", "name": "Continue", "enabled": True,
                            "patterns": ["Invoke"]}

            def state(self, node, props):
                return None

            def password(self, node):
                return False

            def foreground(self):
                return 0

            def action_call(self, node, action, arg):
                def invoke():
                    self.invocations += 1
                return invoke

        now = [10.0]
        app = App()
        grant = {"id": "g", "hwnd": 42, "pid": 5, "title": "Editor", "process": "app.exe"}
        device = {"id": "d", "socket": Socket()}
        hub = ElementsHub(SimpleNamespace(devices={"d": device}), clock=lambda: now[0])
        space = IdSpace()
        old = Snapshot("old", 0, space)
        old.add([{"id": "old-window", "control_type": "Window", "name": "Editor"},
                 {"id": "old-button", "parent": "old-window", "control_type": "Button",
                  "name": "Continue", "enabled": True, "actions": ["invoke"]}])
        old.event_version = 0
        hub.spaces["g"] = space
        hub.remember("g", old)
        stable_id = next(key for key, node in old.nodes.items() if node.name == "Continue")
        live_helper_id = element_id(app, 1, [0])
        access = SimpleNamespace(paths={}, list_windows=lambda: [grant], gate=DispatchGate())
        generation = access.gate.grant()
        action_ids = []

        async def exchange(principal, current_grant, current_device, kind, **fields):
            if kind == "read_window_elements":
                now[0] += 4  # completion time, not capture start, defines the snapshot's age
                access.paths[live_helper_id] = [0]
                return {"snapshot_id": "fresh", "elements": [
                    {"id": "window-live", "control_type": "Window", "name": "Editor"},
                    {"id": live_helper_id, "parent": "window-live", "control_type": "Button",
                     "name": "Continue", "enabled": True, "actions": ["invoke"]}]}
            action_ids.append(fields["element_id"])
            return await asyncio.to_thread(run_action, access, grant, generation, fields,
                                           factory=lambda hwnd: app)

        hub.exchange = exchange
        principal = SimpleNamespace(name="agent", kind="machine", attachment_id="a")
        action_hub = SimpleNamespace(elements=hub, window_grants=SimpleNamespace(spend=Mock()))
        now[0] += 3.1
        with patch("partyline.screen_element_actions.request_principal", return_value=principal), \
             patch("partyline.screen_element_actions.deny_unless"), \
             patch("partyline.screen_element_actions.resolve_window", return_value=(grant, device)), \
             patch("partyline.screen_elements.resolve_window", return_value=(grant, device)), \
             patch("partyline.screen_elements.require_window"):
            result = await element_action(SimpleNamespace(db=None), action_hub, "line",
                                          ElementAction(element_id=stable_id, action="invoke"), None)
        self.assertEqual("completed", result["status"])
        self.assertEqual([live_helper_id], action_ids)
        self.assertEqual(1, app.invocations)

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

        async def snapshot(options=None):
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
        async def snapshot(options=None):
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
        from unittest.mock import AsyncMock, patch
        from fastapi import HTTPException
        from partyline.screen_element_actions import ElementAction, element_action
        socket = Socket()
        device = {"id": "pc", "socket": socket}
        elements = ElementsHub(SimpleNamespace(devices={}))
        hub = SimpleNamespace(elements=elements, window_grants=SimpleNamespace(spend=Mock()))
        grant = {"id": "g"}
        principal = SimpleNamespace(name="agent", kind="machine", attachment_id="a")
        body = ElementAction(element_id="target", action="toggle")
        with patch("partyline.screen_element_actions.request_principal", return_value=principal), \
             patch("partyline.screen_element_actions.deny_unless"), \
             patch("partyline.screen_element_actions.resolve_window", return_value=(grant, device)), \
             patch("partyline.screen_elements.require_window"), \
             patch.object(elements, "action_target", new=AsyncMock(return_value=("target", True))):
            task = asyncio.create_task(element_action(SimpleNamespace(db=None), hub, "line", body, None))
            request = await socket.messages.get()
            self.assertEqual("window_element_action", request["type"])
            elements.receive({"id": "other"}, {"request_id": request["request_id"]})
            self.assertFalse(task.done())
            elements.receive(device, {"request_id": request["request_id"], "status": "completed",
                                      "foreground_changed": True, "target_came_forward": True})
            result = await task
            self.assertIn("timing", result)
            self.assertEqual({"status": "completed", "foreground_changed": True,
                              "target_came_forward": True},
                             {k: v for k, v in result.items() if k != "timing"})
            self.assertFalse(elements.waiters)
            body.value = "foreign parameter"
            with self.assertRaises(HTTPException) as error:
                await element_action(SimpleNamespace(db=None), hub, "line", body, None)
            self.assertIn("does not take", error.exception.detail)


class WindowIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_registration_unavailable_uses_bounded_snapshot_fallback(self):
        from partyline.screen_elements import SNAPSHOT_TTL
        from partyline_helper.window_shares import WindowShares

        session = SimpleNamespace(status=SimpleNamespace(window_grants={}, window_title=None,
                                                           changed=Mock()))
        shares = WindowShares(session)
        entry = {"access": SimpleNamespace(), "worker": SimpleNamespace()}
        shares.grants["grant"] = entry
        await shares.start_events("grant", 42)
        self.assertFalse(entry["events_supported"])
        self.assertEqual(3, SNAPSHOT_TTL)
        await asyncio.to_thread(entry["events"].close)

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

    async def test_grant_end_unsubscribes_change_events(self):
        from unittest.mock import AsyncMock
        from partyline_helper.window_shares import WindowShares

        class Subscription:
            def __init__(self, hwnd, changed):
                self.changed = changed
                self.closed = False

            def start(self):
                return True

            def close(self):
                self.closed = True

        session = SimpleNamespace(status=SimpleNamespace(window_grants={}, window_title=None,
                                                           changed=Mock()), send=AsyncMock())
        shares = WindowShares(session, event_factory=Subscription)
        entry = {"access": SimpleNamespace(revoke=Mock()), "worker": SimpleNamespace(close=AsyncMock())}
        shares.grants["grant"] = entry
        await shares.start_events("grant", 42)
        subscription = entry["events"]
        self.assertTrue(entry["events_supported"])
        shares.revoke("grant", notify=False)
        await asyncio.gather(*shares.tasks)
        self.assertTrue(subscription.closed)
