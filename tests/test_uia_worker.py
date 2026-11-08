"""Dispatch and revocation races, using events and fake deadlines instead of sleeps."""
import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from partyline_helper.uia_action_worker import ActionWorker, run_action
from partyline_helper.uia_gate import DispatchGate
from partyline_helper.uia_identity import element_id
from tests.test_uia_action import ActionProvider


class Provider(ActionProvider):
    def __init__(self):
        super().__init__([{"rect": (0, 0, 10, 10), "children": [1]},
                          {"rect": (0, 0, 5, 5)}])
        self.calls = []
        self.foreground_hwnd = 99

    def foreground(self):
        return self.foreground_hwnd

    def action_call(self, node, action, value):
        return lambda: self.calls.append((node, action, value))


class GateTests(unittest.IsolatedAsyncioTestCase):
    async def test_revoke_before_dispatch_does_not_call(self):
        gate = DispatchGate()
        generation = gate.grant()
        gate.invalidate()
        call = Mock()
        with self.assertRaisesRegex(ValueError, "revoked"):
            gate.dispatch(generation, call)
        call.assert_not_called()

    async def test_revoke_after_dispatch_reports_it(self):
        gate = DispatchGate()
        generation = gate.grant()
        entered, finish = threading.Event(), threading.Event()
        def call():
            entered.set()
            finish.wait()
            return "ok"
        pending = asyncio.create_task(asyncio.to_thread(gate.dispatch, generation, call))
        await asyncio.to_thread(entered.wait)
        gate.invalidate()
        finish.set()
        self.assertEqual(("ok", True), await pending)

    async def test_queued_action_drops_after_revoke(self):
        gate = DispatchGate()
        generation = gate.grant()
        entered, finish = threading.Event(), threading.Event()
        def first():
            entered.set()
            finish.wait()
        pending = asyncio.create_task(asyncio.to_thread(gate.dispatch, generation, first))
        await asyncio.to_thread(entered.wait)
        called = Mock()
        queued = asyncio.create_task(asyncio.to_thread(gate.dispatch, generation, called))
        gate.invalidate()
        finish.set()
        await pending
        with self.assertRaisesRegex(ValueError, "revoked"):
            await queued
        called.assert_not_called()

    async def test_timeout_refuses_and_audits_length_only(self):
        gate = DispatchGate()
        gate.grant()
        entered, finish = threading.Event(), threading.Event()
        def runner(*args):
            entered.set()
            finish.wait()
            return {"status": "completed"}
        grant = {"hwnd": 1, "pid": 2, "process": "app"}
        access = SimpleNamespace(gate=gate, grant=grant, elements={"id": {"name": "field"}})
        audit = Mock()
        session = SimpleNamespace(window=access, accepted=True, share={"share_id": "s"},
                                  control=SimpleNamespace(granted=True),
                                  tools=SimpleNamespace(audit=audit))
        worker = ActionWorker(session, runner=runner)
        async def deadline(task, timeout):
            if asyncio.iscoroutine(task):
                return await task
            await asyncio.to_thread(entered.wait)
            raise TimeoutError
        message = {"element_id": "id", "action": "set_value", "value": "secret", "share_id": "s"}
        with patch("partyline_helper.uia_action_worker.asyncio.wait_for", deadline):
            result = await worker.perform(message)
        self.assertEqual("timeout", result["status"])
        self.assertTrue(gate.revoked.is_set())
        entry = str(audit.append.call_args)
        self.assertIn("value_length", entry)
        self.assertNotIn("secret", entry)
        finish.set()
        await worker.task

    async def test_validated_action_and_live_window_check(self):
        provider = Provider()
        gate = DispatchGate()
        generation = gate.grant()
        grant = {"hwnd": 1, "pid": 2}
        access = SimpleNamespace(gate=gate, list_windows=lambda: [grant])
        message = {"element_id": element_id(provider, 1, [0]), "action": "set_value", "value": "new"}
        result = run_action(access, grant, generation, message, factory=lambda _: provider)
        self.assertEqual("completed", result["status"])
        self.assertEqual([(1, "set_value", "new")], provider.calls)
        access.list_windows = lambda: None
        result = run_action(access, grant, generation, message, factory=lambda _: provider)
        self.assertEqual("secure desktop active", result["error"])
        self.assertEqual(1, len(provider.calls))

    async def test_revoke_during_audit_preflight_cannot_use_new_grant(self):
        gate = DispatchGate()
        gate.grant()
        entered, finish = threading.Event(), threading.Event()
        def probe():
            entered.set()
            finish.wait()
        calls = []
        def runner(access, grant, generation, message):
            try:
                access.gate.dispatch(generation, lambda: calls.append("dispatched"))
                return {"status": "completed"}
            except ValueError:
                return {"status": "failed", "error": "revoked"}
        access = SimpleNamespace(gate=gate, grant={"process": "app"}, elements={"id": {"name": "field"}})
        audit = SimpleNamespace(ensure_writable=probe, append=Mock())
        session = SimpleNamespace(window=access, accepted=True, share={"share_id": "s"},
                                  control=SimpleNamespace(granted=True), tools=SimpleNamespace(audit=audit))
        worker = ActionWorker(session, runner=runner)
        message = {"element_id": "id", "action": "toggle", "share_id": "s"}
        pending = asyncio.create_task(worker.perform(message))
        await asyncio.to_thread(entered.wait)
        gate.invalidate()
        gate.grant()
        finish.set()
        self.assertEqual("revoked", (await pending)["error"])
        self.assertEqual([], calls)
        audit.append.assert_called_once()

    async def test_revoke_while_final_window_check_is_pending(self):
        provider = Provider()
        gate = DispatchGate()
        generation = gate.grant()
        grant = {"hwnd": 1, "pid": 2}
        entered, finish = threading.Event(), threading.Event()
        checks = [0]
        def windows():
            checks[0] += 1
            if checks[0] == 3:
                entered.set()
                finish.wait()
            return [grant]
        access = SimpleNamespace(gate=gate, list_windows=windows)
        message = {"element_id": element_id(provider, 1, [0]), "action": "set_value", "value": "new"}
        pending = asyncio.create_task(asyncio.to_thread(run_action, access, grant, generation, message,
                                                         lambda _: provider))
        await asyncio.to_thread(entered.wait)
        gate.invalidate()
        finish.set()
        self.assertEqual("revoked", (await pending)["error"])
        self.assertEqual([], provider.calls)

    async def test_revoke_during_pattern_call_discards_reread(self):
        provider = Provider()
        entered, finish = threading.Event(), threading.Event()
        def action_call(*args):
            def call():
                entered.set()
                finish.wait()
            return call
        provider.action_call = action_call
        gate = DispatchGate()
        generation = gate.grant()
        grant = {"hwnd": 1, "pid": 2}
        access = SimpleNamespace(gate=gate, list_windows=lambda: [grant])
        message = {"element_id": element_id(provider, 1, [0]), "action": "set_value", "value": "x"}
        pending = asyncio.create_task(asyncio.to_thread(run_action, access, grant, generation, message,
                                                         lambda _: provider))
        await asyncio.to_thread(entered.wait)
        gate.invalidate()
        finish.set()
        result = await pending
        self.assertEqual("completed", result["status"])
        self.assertTrue(result["revoked_during"])
        self.assertNotIn("element", result)

    async def test_foreground_observations_and_audit(self):
        from partyline_helper.uia_action_worker import audit
        for before, after, expected_changed, expected_target in (
                (99, 99, False, False), (99, 1, True, True), (99, 7, True, False), (1, 1, False, False)):
            with self.subTest(before=before, after=after):
                provider = Provider()
                provider.foreground_hwnd = before
                def action_call(*_args, final=after, target=provider):
                    def call():
                        target.foreground_hwnd = final
                    return call
                provider.action_call = action_call
                gate = DispatchGate()
                generation = gate.grant()
                grant = {"hwnd": 1, "pid": 2, "process": "app"}
                access = SimpleNamespace(gate=gate, list_windows=lambda selected=grant: [selected])
                message = {"element_id": element_id(provider, 1, [0]), "action": "set_value",
                           "value": "secret"}
                result = run_action(access, grant, generation, message, factory=lambda _, p=provider: p)
                self.assertEqual("completed", result["status"])
                self.assertIs(result["foreground_changed"], expected_changed)
                self.assertIs(result["target_came_forward"], expected_target)
                sink = Mock()
                session = SimpleNamespace(tools=SimpleNamespace(audit=sink))
                audit(session, grant, message, {"name": "field"}, result)
                import json
                entry = json.loads(sink.append.call_args.args[4])
                self.assertIs(entry["foreground_changed"], expected_changed)
                self.assertIs(entry["target_came_forward"], expected_target)
                self.assertEqual(6, entry["value_length"])
                self.assertNotIn("secret", str(sink.append.call_args))

    async def test_foreground_is_recorded_when_pattern_raises(self):
        provider = Provider()
        def action_call(*_args):
            def call():
                provider.foreground_hwnd = 1
                raise RuntimeError("provider failed")
            return call
        provider.action_call = action_call
        gate = DispatchGate()
        generation = gate.grant()
        grant = {"hwnd": 1, "pid": 2}
        access = SimpleNamespace(gate=gate, list_windows=lambda: [grant])
        message = {"element_id": element_id(provider, 1, [0]), "action": "set_value", "value": "x"}
        result = run_action(access, grant, generation, message, factory=lambda _: provider)
        self.assertEqual("failed", result["status"])
        self.assertTrue(result["foreground_changed"])
        self.assertTrue(result["target_came_forward"])

    async def test_foreground_change_during_reread_is_reported(self):
        provider = Provider()
        properties = provider.properties
        reads = [0]
        def read(node):
            reads[0] += 1
            if reads[0] == 3:
                provider.foreground_hwnd = 1
            return properties(node)
        provider.properties = read
        gate = DispatchGate()
        generation = gate.grant()
        grant = {"hwnd": 1, "pid": 2}
        access = SimpleNamespace(gate=gate, list_windows=lambda: [grant])
        message = {"element_id": element_id(provider, 1, [0]), "action": "set_value", "value": "x"}
        result = run_action(access, grant, generation, message, factory=lambda _: provider)
        self.assertEqual("completed", result["status"])
        self.assertTrue(result["foreground_changed"])
        self.assertTrue(result["target_came_forward"])

    async def test_revocation_during_reread_keeps_only_immediate_observation(self):
        provider = Provider()
        gate = DispatchGate()
        generation = gate.grant()
        properties = provider.properties
        reads = [0]
        def read(node):
            reads[0] += 1
            if reads[0] == 3:
                provider.foreground_hwnd = 1
                gate.invalidate()
            return properties(node)
        provider.properties = read
        grant = {"hwnd": 1, "pid": 2}
        access = SimpleNamespace(gate=gate, list_windows=lambda: [grant])
        message = {"element_id": element_id(provider, 1, [0]), "action": "set_value", "value": "x"}
        result = run_action(access, grant, generation, message, factory=lambda _: provider)
        self.assertTrue(result["revoked_during"])
        self.assertFalse(result["foreground_changed"])
        self.assertFalse(result["target_came_forward"])
        self.assertNotIn("element", result)
