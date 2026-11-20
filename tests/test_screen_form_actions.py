"""Compact form groups reuse checked actions, bounded reads and fresh recovery IDs."""
import asyncio
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from partyline.screen_element_actions import ElementAction, Then, element_action
from partyline.screen_element_routes import elements_router
from partyline.screen_elements import ElementsHub
from partyline.screen_form_actions import act as form_action
from tests.cdp_fakes import Fixture
from tests.test_cdp_settle import Clock

GRANT = {"id": "g", "conv_id": "line", "process": "chrome.exe", "title": "Form"}
FIELDS = (("First name", "given"), ("Last name", "family"), ("City", "city"))


def encoded(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


class FormFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture()
        self.addAsyncCleanup(self.f.close)
        self.clock = Clock()
        self.elements = ElementsHub(SimpleNamespace(), clock=self.clock)
        self.runtime = SimpleNamespace(db=None)
        self.outer = SimpleNamespace(elements=self.elements, runtime=self.runtime,
                                     window_grants=SimpleNamespace(spend=Mock()))
        self.principal = SimpleNamespace(name="agent", conv_id="line")
        self.device = {"id": "device"}
        self.reads = self.actions = self.probes = 0
        self.inserts = []
        self.on_insert = None
        self.elements.exchange = self.exchange
        self.f.socket.nodes = [
            dict(nodeId="1", backendDOMNodeId=1, role={"value": "RootWebArea"}, name={"value": "Form"}),
            dict(nodeId="2", parentId="1", backendDOMNodeId=2, role={"value": "group"},
                 name={"value": "Details"}),
            *[dict(nodeId=str(index + 3), parentId="2", backendDOMNodeId=index + 3,
                   role={"value": "textbox"}, name={"value": name})
              for index, (name, _) in enumerate(FIELDS)],
        ]
        self.f.socket.states = {1: {}, 2: {}, **{index + 3: dict(tag="INPUT", value="", hit=True)
                                                 for index in range(len(FIELDS))}}
        self.f.socket.hook = self.edited
        self.audit = Mock()
        self.standing = AsyncMock()
        patches = [
            patch("partyline.screen_form_actions.audit_call", self.audit),
            patch("partyline.screen_form_conditions.audit_call", self.audit),
            patch("partyline.screen_form_conditions.deny_unless"),
            patch("partyline.screen_form_actions.record_standing_window_access", self.standing),
            patch("partyline.screen_workflow_learning.record_call"),
            patch("partyline.screen_element_actions.deny_unless"),
            patch("partyline.screen_element_actions.request_principal", return_value=self.principal),
            patch("partyline.screen_element_actions.resolve_window", return_value=(GRANT, self.device)),
            patch("partyline.screen_elements.resolve_window", return_value=(GRANT, self.device)),
            patch("partyline.screen_elements.require_window"),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def edited(self, message):
        if message["method"] != "Input.insertText":
            return
        backend = self.f.socket.focused
        self.f.socket.states[backend]["value"] = message["params"]["text"]
        self.inserts.append((backend, message["params"]["text"]))
        if self.on_insert:
            self.on_insert(backend, message["params"]["text"])

    async def exchange(self, principal, grant, device, kind, **fields):
        if kind == "window_element_condition":
            self.probes += 1
            return await self.f.chrome.action(self.f.access, {**fields, "type": kind})
        if kind == "window_element_action":
            self.actions += 1
            request = {"request_id": "request"} if fields.get("workflow_source") else {}
            return await self.f.chrome.action(self.f.access, {**fields, **request})
        if fields.get("event_status"):
            return self.f.chrome.status(self.f.access)
        self.reads += 1
        result = await self.f.read(**fields)
        page = self.f.chrome.pages[self.f.access]["a"]
        page.quiet.wait = AsyncMock(return_value="quiet")
        return result

    async def initial(self):
        result = await self.elements.read(self.principal, window="g", options={"refresh": True})
        tree = self.elements.snapshots["g"]
        ids = {node.name: node.id for node in tree.nodes.values()}
        return result, ids

    def body(self, ids, values):
        return ElementAction(action="set_values", window="g", assignments=[
            {"element_id": ids[name], "value": value} for (name, _), value in zip(FIELDS, values, strict=True)
        ], then={"root": ids["Details"], "depth": 1})

    def combo(self, disabled=False):
        self.f.socket.nodes[4]["role"]["value"] = "combobox"
        self.f.socket.states[5] = dict(tag="SELECT", value="old", selected_index=0, selected_count=1,
                                       hit=True, aria_disabled=disabled)

    def dependent_body(self, ids, timeout_ms=2000):
        return ElementAction(action="set_values", window="g", assignments=[
            {"element_id": ids["First name"], "value": "Ada"},
            {"element_id": ids["City"], "value": "New", "action": "select",
             "when": {"root": ids["Details"], "name": "City", "control_type": "ComboBox",
                      "timeout_ms": timeout_ms}},
            {"element_id": ids["Last name"], "value": "Lovelace"},
        ], then={"root": ids["Details"], "depth": 1})

    async def test_equivalent_worked_form_measures_reads_bytes_and_round_trips(self):
        before_values = ("Ada", "Lovelace", "London")
        after_values = ("Grace", "Hopper", "New York")
        started = time.perf_counter()
        initial, ids = await self.initial()
        responses = [initial]
        for (name, _), value in zip(FIELDS, before_values, strict=True):
            responses.append(await element_action(self.runtime, self.outer, "line", ElementAction(
                element_id=ids[name], action="set_value", value=value, window="g",
                then=Then(root=ids["Details"], depth=1)), None))
        before = {"tool_calls_measured": 1 + len(FIELDS), "helper_reads_measured": self.reads,
                  "helper_actions_measured": self.actions, "model_decisions_inferred": len(FIELDS),
                  "response_bytes_measured": sum(map(encoded, responses)),
                  "elapsed_ms_measured": round((time.perf_counter() - started) * 1000, 3)}
        self.assertEqual(before_values, tuple(self.f.socket.states[index + 3]["value"]
                                              for index in range(len(FIELDS))))

        for index in range(len(FIELDS)):
            self.f.socket.states[index + 3]["value"] = ""
        started = time.perf_counter()
        initial, ids = await self.initial()
        page = self.f.chrome.pages[self.f.access]["a"]
        with patch.object(page.cue, "target", wraps=page.cue.target) as cue:
            grouped = await form_action(self.runtime, self.outer, "line", self.body(ids, after_values),
                                        self.principal, GRANT)
        self.assertEqual(3, cue.call_count)  # the existing visible target cue runs for every assignment
        measured_reads = self.reads - before["helper_reads_measured"]
        after = {"tool_calls_measured": 2, "helper_reads_measured": measured_reads,
                 "helper_actions_measured": self.actions - before["helper_actions_measured"],
                 "model_decisions_inferred": 1,
                 "response_bytes_measured": encoded(initial) + encoded(grouped),
                 "elapsed_ms_measured": round((time.perf_counter() - started) * 1000, 3)}
        print("FORM_ACTION_METRICS " + json.dumps({"before": before, "after": after}, sort_keys=True))
        self.assertEqual("completed", grouped["status"])
        self.assertIn("g", self.elements.after_action)
        self.assertEqual(after_values, tuple(self.f.socket.states[index + 3]["value"]
                                             for index in range(len(FIELDS))))
        self.assertTrue(all(value in grouped["after"]["lines"] for value in after_values))
        self.assertEqual((4, 3), (before["helper_reads_measured"], before["helper_actions_measured"]))
        self.assertEqual((2, 3), (after["helper_reads_measured"], after["helper_actions_measured"]))
        self.assertLess(after["response_bytes_measured"], before["response_bytes_measured"])
        self.assertEqual(3, self.audit.call_count)  # every grouped assignment is independently audited
        self.assertEqual(6, self.standing.await_count)  # start + outcome for each grouped assignment

    async def test_immediate_dependency_is_probed_without_waiting_or_extra_model_handback(self):
        self.combo()
        _, ids = await self.initial()
        with patch.object(self.elements, "wait_changed", new=AsyncMock()) as waiting:
            result = await form_action(self.runtime, self.outer, "line", self.dependent_body(ids),
                                       self.principal, GRANT, self.device)
        self.assertEqual("completed", result["status"])
        self.assertEqual(1, self.probes)
        waiting.assert_not_awaited()
        self.assertEqual("New", self.f.socket.states[5]["value"])

    async def test_zero_timeout_still_performs_one_immediate_ready_check_without_event_wait(self):
        self.combo()
        _, ids = await self.initial()
        body = self.dependent_body(ids, timeout_ms=0)
        with patch.object(self.elements, "wait_changed", new=AsyncMock()) as waiting:
            result = await form_action(self.runtime, self.outer, "line", body,
                                       self.principal, GRANT, self.device)
        self.assertEqual("completed", result["status"])
        self.assertEqual(1, self.probes)
        waiting.assert_not_awaited()

    async def test_delayed_replacement_resolves_from_event_and_completes_inside_one_executor_call(self):
        self.combo(disabled=True)
        _, ids = await self.initial()
        waiting = self.elements.wait_changed
        full_before = sum(call["method"] == "Accessibility.getFullAXTree" for call in self.f.socket.calls)
        partial_before = sum(call["method"] == "Accessibility.getPartialAXTree"
                             for call in self.f.socket.calls)

        async def update(grant_id, version, delay):
            def arrive():
                self.f.socket.nodes[4] = dict(nodeId="6", parentId="2", backendDOMNodeId=6,
                                              role={"value": "combobox"}, name={"value": "City"})
                self.f.socket.states.pop(5)
                self.f.socket.states[6] = dict(tag="SELECT", value="old", selected_index=0,
                                               selected_count=1, hit=True)
                self.elements.changed("g")
            asyncio.get_running_loop().call_soon(arrive)
            return await waiting(grant_id, version, delay)

        with patch.object(self.elements, "wait_changed", side_effect=update) as changed:
            result = await form_action(self.runtime, self.outer, "line", self.dependent_body(ids),
                                       self.principal, GRANT, self.device)
        self.assertEqual("completed", result["status"])
        self.assertEqual(1, changed.call_count)
        self.assertEqual(1, self.probes)
        self.assertEqual("New", self.f.socket.states[6]["value"])
        self.assertEqual(3, self.actions)  # two edits and one select, with no model-mediated handback
        full = sum(call["method"] == "Accessibility.getFullAXTree"
                   for call in self.f.socket.calls) - full_before
        partial = sum(call["method"] == "Accessibility.getPartialAXTree"
                      for call in self.f.socket.calls) - partial_before
        # Only the final ordinary then read; neither dependency recheck used a full tree.
        self.assertEqual(1, full)
        self.assertGreaterEqual(partial, 2)
        print("DEPENDENCY_READ_METRICS " + json.dumps({
            "dependency_full_tree_reads_measured": full - 1,
            "dependency_partial_ax_calls_measured": partial,
            "model_handbacks_measured": 0}))

    async def test_scope_change_after_probe_is_refused_by_action_dispatch_evidence(self):
        self.combo()
        _, ids = await self.initial()
        from partyline.screen_form_conditions import probe as checking

        async def change_after_probe(*args):
            observed = await checking(*args)
            self.f.socket.nodes.append(dict(nodeId="6", parentId="2", backendDOMNodeId=6,
                                            role={"value": "combobox"}, name={"value": "City"}))
            self.f.socket.states[6] = dict(tag="SELECT", value="old", selected_index=0,
                                           selected_count=1, hit=True)
            self.f.state.changed()
            self.elements.changed("g")
            return observed

        with patch("partyline.screen_form_conditions.probe", side_effect=change_after_probe):
            result = await form_action(self.runtime, self.outer, "line", self.dependent_body(ids),
                                       self.principal, GRANT, self.device)
        self.assertEqual(("partial", 1, 1), (result["status"], result["completed"], result["remaining"]))
        self.assertEqual("workflow_evidence", result["results"][1]["reason"])
        self.assertEqual([(3, "Ada")], self.inserts)
        self.assertEqual("old", self.f.socket.states[5]["value"])

    async def test_scope_change_on_focus_is_refused_at_first_input(self):
        self.combo()
        _, ids = await self.initial()

        def duplicate_on_focus(message):
            self.edited(message)
            if message["method"] != "DOM.focus" or message["params"]["backendNodeId"] != 5:
                return
            self.f.socket.nodes.append(dict(nodeId="6", parentId="2", backendDOMNodeId=6,
                                            role={"value": "combobox"}, name={"value": "City"}))
            self.f.socket.states[6] = dict(tag="SELECT", value="old", selected_index=0,
                                           selected_count=1, hit=True)
            self.f.state.changed()
            self.elements.changed("g")

        self.f.socket.hook = duplicate_on_focus
        result = await form_action(self.runtime, self.outer, "line", self.dependent_body(ids),
                                   self.principal, GRANT, self.device)
        self.assertEqual(("partial", 1, 1), (result["status"], result["completed"], result["remaining"]))
        self.assertEqual("workflow_evidence", result["results"][1]["reason"])
        self.assertEqual([(3, "Ada")], self.inserts)
        self.assertEqual("old", self.f.socket.states[5]["value"])
        self.assertEqual([], self.f.socket.native_select.committed_values)

    async def test_legacy_workflow_scroll_event_keeps_its_existing_dispatch_contract(self):
        _, ids = await self.initial()
        tree = self.elements.snapshots["g"]
        node = tree.nodes[ids["First name"]]

        def observed_scroll(message):
            self.edited(message)
            if message["method"] == "DOM.scrollIntoViewIfNeeded":
                self.f.state.changed()

        self.f.socket.hook = observed_scroll
        result = await self.f.chrome.action(self.f.access, {
            "action": "set_value", "element_id": node.helper, "value": "Ada", "request_id": "legacy",
            "action_token": node.cached["action_token"], "workflow_source": "cdp",
            "workflow_document": tree.document, "workflow_counter": tree.event_counter,
        })
        self.assertEqual("completed", result["status"])
        self.assertEqual("Ada", self.f.socket.states[3]["value"])

    async def test_partial_dependency_capture_cannot_establish_uniqueness_or_dispatch(self):
        self.combo()
        _, ids = await self.initial()
        reading = self.elements.read

        async def partial(*args, **kwargs):
            reply = await reading(*args, **kwargs)
            self.elements.snapshots["g"].cursor = "unread"
            return reply

        with patch.object(self.elements, "read", side_effect=partial):
            result = await form_action(self.runtime, self.outer, "line", self.dependent_body(ids),
                                       self.principal, GRANT, self.device)
        self.assertEqual(("partial", 1, 1), (result["status"], result["completed"], result["remaining"]))
        self.assertEqual("condition_unavailable", result["results"][1]["reason"])
        self.assertEqual((1, 0), (self.actions, self.probes))

    async def test_raced_dependency_capture_cannot_establish_uniqueness_or_dispatch(self):
        self.combo()
        _, ids = await self.initial()
        reading = self.elements.read

        async def raced(*args, **kwargs):
            reply = await reading(*args, **kwargs)
            self.elements.snapshots["g"].moved = True
            return reply

        with patch.object(self.elements, "read", side_effect=raced):
            result = await form_action(self.runtime, self.outer, "line", self.dependent_body(ids),
                                       self.principal, GRANT, self.device)
        self.assertEqual(("partial", 1, 1), (result["status"], result["completed"], result["remaining"]))
        self.assertEqual("condition_unavailable", result["results"][1]["reason"])
        self.assertEqual((1, 0), (self.actions, self.probes))

    async def test_dependency_deadline_bounds_the_read_and_prevents_late_dispatch(self):
        self.combo()
        _, ids = await self.initial()
        reading = self.elements.read

        async def slow(*args, **kwargs):
            await asyncio.sleep(0.02)
            return await reading(*args, **kwargs)

        body = self.dependent_body(ids, timeout_ms=1)
        with patch.object(self.elements, "read", side_effect=slow):
            result = await form_action(self.runtime, self.outer, "line", body,
                                       self.principal, GRANT, self.device)
        self.assertEqual(("partial", 1, 1), (result["status"], result["completed"], result["remaining"]))
        self.assertEqual("condition_timeout", result["results"][1]["reason"])
        self.assertEqual((1, 0), (self.actions, self.probes))
        self.assertEqual("old", self.f.socket.states[5]["value"])

    async def test_missing_condition_times_out_with_partial_progress_and_never_dispatches_select(self):
        self.combo(disabled=True)
        _, ids = await self.initial()
        with patch.object(self.elements, "wait_changed", new=AsyncMock(return_value=False)) as waiting:
            result = await form_action(self.runtime, self.outer, "line", self.dependent_body(ids),
                                       self.principal, GRANT, self.device)
        self.assertEqual(("partial", 1, 1), (result["status"], result["completed"], result["remaining"]))
        self.assertEqual("condition_timeout", result["results"][1]["reason"])
        self.assertEqual("control is disabled", result["results"][1]["condition"]["error"])
        waiting.assert_awaited_once()
        self.assertEqual(0, self.probes)
        self.assertEqual(1, self.actions)
        self.assertEqual("old", self.f.socket.states[5]["value"])
        self.assertIn("disabled", result["after"]["lines"])

    async def test_dependent_rerender_stops_and_returns_current_controls_without_repeating_input(self):
        _, ids = await self.initial()

        def replace(backend, text):
            if backend != 3:
                return
            replacement = dict(nodeId="6", parentId="2", backendDOMNodeId=6,
                               role={"value": "textbox"}, name={"value": "Last name updated"})
            self.f.socket.nodes[2] = replacement
            self.f.socket.states.pop(4)
            self.f.socket.states[6] = dict(tag="INPUT", value="", hit=True)

        self.on_insert = replace
        result = await form_action(self.runtime, self.outer, "line",
                                   self.body(ids, ("Ada", "Lovelace", "London")), self.principal, GRANT)
        self.assertEqual(("partial", 1, 1), (result["status"], result["completed"], result["remaining"]))
        self.assertEqual(["completed", "failed"], [row["status"] for row in result["results"]])
        self.assertEqual("target_changed", result["results"][1]["reason"])
        self.assertIn("lines", result["after"], result)
        lines = result["after"]["lines"].splitlines()
        line = next((line for line in lines if "Last name updated" in line), None)
        self.assertIsNotNone(line, result)
        self.assertIn("set_value", line)
        self.assertNotIn("disabled", line)
        self.assertEqual([(3, "Ada")], self.inserts)
        current = line.split()[0]
        recovered = await element_action(self.runtime, self.outer, "line", ElementAction(
            element_id=current, action="set_value", value="Lovelace", window="g"), None)
        self.assertEqual("completed", recovered["status"])
        self.assertEqual([(3, "Ada"), (6, "Lovelace")], self.inserts)  # only the refused field was reissued

    async def test_group_can_use_the_existing_select_action(self):
        self.f.socket.nodes[4]["role"]["value"] = "combobox"
        self.f.socket.states[5] = dict(tag="SELECT", value="old", selected_index=0,
                                       selected_count=1, hit=True)
        _, ids = await self.initial()
        body = ElementAction(action="set_values", window="g", assignments=[
            {"element_id": ids["First name"], "value": "Ada"},
            {"element_id": ids["City"], "value": "New", "action": "select"},
        ], then={"root": ids["Details"]})
        result = await form_action(self.runtime, self.outer, "line", body, self.principal, GRANT)
        self.assertEqual("completed", result["status"])
        self.assertEqual(("Ada", "New"), (self.f.socket.states[3]["value"],
                                         self.f.socket.states[5]["value"]))

    async def test_grouped_select_cannot_click_a_non_native_button(self):
        self.combo()
        self.f.socket.states[5]["tag"] = "BUTTON"
        _, ids = await self.initial()
        body = ElementAction(action="set_values", window="g", assignments=[
            {"element_id": ids["City"], "value": "New", "action": "select"},
            {"element_id": ids["First name"], "value": "Ada"},
        ], then={"root": ids["Details"]})
        result = await form_action(self.runtime, self.outer, "line", body, self.principal, GRANT)
        self.assertEqual(("failed", 0, 1), (result["status"], result["completed"], result["remaining"]))
        self.assertIn("native SELECT", result["results"][0]["error"])
        self.assertFalse(any(call["method"].startswith("Input.") or call["method"] == "DOM.focus"
                             for call in self.f.socket.calls))

    async def test_settled_select_readback_rejects_a_selection_reverted_during_settle(self):
        self.combo()
        _, ids = await self.initial()
        page = self.f.chrome.pages[self.f.access]["a"]

        async def revert():
            self.f.socket.states[5].update(value="old", selected_index=0, selected_count=1)
            return "quiet"

        page.quiet.wait = revert
        body = ElementAction(action="set_values", window="g", assignments=[
            {"element_id": ids["City"], "value": "New", "action": "select"},
            {"element_id": ids["First name"], "value": "Ada"},
        ], then={"root": ids["Details"]})
        result = await form_action(self.runtime, self.outer, "line", body, self.principal, GRANT)
        self.assertEqual(("unconfirmed", 0, 1),
                         (result["status"], result["completed"], result["remaining"]))
        self.assertEqual(1, self.actions)
        self.assertEqual("old", self.f.socket.states[5]["value"])
        self.assertIn("settled", result["results"][0]["state_unavailable"])

    async def test_single_stale_action_also_carries_the_requested_scoped_read(self):
        _, ids = await self.initial()
        self.f.socket.nodes[2] = dict(nodeId="6", parentId="2", backendDOMNodeId=6,
                                      role={"value": "textbox"}, name={"value": "Last name updated"})
        self.f.socket.states.pop(4)
        self.f.socket.states[6] = dict(tag="INPUT", value="", hit=True)
        result = await element_action(self.runtime, self.outer, "line", ElementAction(
            element_id=ids["Last name"], action="set_value", value="Lovelace", window="g",
            then=Then(root=ids["Details"])), None)
        self.assertEqual("failed", result["status"])
        self.assertIn("after", result)
        self.assertIn("Last name updated", result["after"]["lines"])

    async def test_disconnected_settled_readback_is_unverified_and_stops_later_input(self):
        _, ids = await self.initial()

        def detach(backend, text):
            self.f.socket.states[backend]["connected"] = False

        self.on_insert = detach
        result = await form_action(self.runtime, self.outer, "line",
                                   self.body(ids, ("A", "B", "C")), self.principal, GRANT)
        self.assertEqual(("unconfirmed", 0, 2),
                         (result["status"], result["completed"], result["remaining"]))
        self.assertEqual(1, self.actions)
        self.assertEqual([(3, "A")], self.inserts)
        self.assertEqual("unconfirmed", result["results"][0]["status"])
        self.assertIn("connected", result["results"][0]["state_unavailable"])

    async def test_mismatched_readback_is_unverified_and_stops_before_later_input(self):
        _, ids = await self.initial()
        outcomes = [{"status": "completed", "source": "cdp",
                     "element": {"connected": True, "value": "different"}}]
        with patch("partyline.screen_form_actions.perform_element_action",
                   new=AsyncMock(side_effect=outcomes)) as perform:
            result = await form_action(self.runtime, self.outer, "line", self.body(ids, ("A", "B", "C")),
                                       self.principal, GRANT)
        self.assertEqual(1, perform.await_count)
        self.assertEqual(("unconfirmed", 0, 2), (result["status"], result["completed"], result["remaining"]))
        self.assertEqual("unconfirmed", result["results"][0]["status"])
        self.assertIn("did not confirm", result["results"][0]["state_unavailable"])

    async def test_unconfirmed_assignment_is_not_retried_and_later_fields_are_not_attempted(self):
        _, ids = await self.initial()
        outcomes = [{"status": "completed"}, {"status": "unconfirmed", "note": "may have run"}]
        with patch("partyline.screen_form_actions.perform_element_action",
                   new=AsyncMock(side_effect=outcomes)) as perform:
            result = await form_action(self.runtime, self.outer, "line", self.body(ids, ("A", "B", "C")),
                                       self.principal, GRANT)
        self.assertEqual(2, perform.await_count)
        self.assertEqual(("unconfirmed", 1, 1), (result["status"], result["completed"], result["remaining"]))
        self.assertTrue(result["partial"])
        self.assertIn("after", result)
        self.assertIn("g", self.elements.after_action)


class ContractTests(unittest.IsolatedAsyncioTestCase):
    def test_group_validation_and_legacy_single_action_contract(self):
        with self.assertRaises(ValidationError):
            ElementAction(action="set_values", assignments=[{"element_id": "a", "value": "1"},
                                                           {"element_id": "a", "value": "2"}])
        with self.assertRaises(ValidationError):
            ElementAction(action="set_values", element_id="a",
                          assignments=[{"element_id": "a", "value": "1"}])
        with self.assertRaises(ValidationError):
            ElementAction(action="set_value", element_id="a", value="1",
                          assignments=[{"element_id": "b", "value": "2"}])
        self.assertEqual({"element_id": "a", "action": "set_value", "value": "1"},
                         ElementAction(element_id="a", action="set_value", value="1").parameters())

    def test_route_delegates_only_the_group_action(self):
        runtime, hub = SimpleNamespace(db=None), SimpleNamespace()
        principal = SimpleNamespace(name="agent", conv_id="line")
        app = FastAPI()
        app.include_router(elements_router(runtime, hub))
        client = TestClient(app)
        grouped = AsyncMock(return_value={"status": "completed", "results": []})
        with patch("partyline.screen_element_routes.core.request_principal", return_value=principal), \
             patch("partyline.screen_element_routes.core.deny_unless"), \
             patch("partyline.screen_element_routes.core.resolve_window", return_value=(GRANT, {})), \
             patch("partyline.screen_form_actions.act", grouped):
            response = client.post("/api/conversations/line/screen-control/element-action", json={
                "action": "set_values", "assignments": [{"element_id": "a", "value": "1"}],
                "then": {"root": "section"}})
            self.assertEqual(200, response.status_code)
            grouped.assert_awaited_once()
            dependent = client.post("/api/conversations/line/screen-control/element-action", json={
                "action": "set_values", "assignments": [{"element_id": "a", "value": "1",
                    "when": {"root": "section", "name": "Field"}}], "then": {"root": "section"}})
            self.assertEqual(409, dependent.status_code)  # older helpers cannot probe conditions
            selected = client.post("/api/conversations/line/screen-control/element-action", json={
                "action": "set_values", "assignments": [{"element_id": "a", "value": "1",
                    "action": "select"}], "then": {"root": "section"}})
            self.assertEqual(409, selected.status_code)  # older helpers ignore the fill-only click guard
            grouped.assert_awaited_once()

    async def test_http_refusal_becomes_a_bounded_partial_result(self):
        principal = SimpleNamespace(name="agent", conv_id="line")
        elements = SimpleNamespace(snapshots={}, fresh=Mock(return_value=None))
        hub = SimpleNamespace(elements=elements)
        body = ElementAction(action="set_values", assignments=[{"element_id": "a", "value": "1"}])
        with patch("partyline.screen_form_actions.audit_call"), \
             patch("partyline.screen_form_actions.record_standing_window_access", new=AsyncMock()), \
             patch("partyline.screen_workflow_learning.record_call"), \
             patch("partyline.screen_form_actions.perform_element_action",
                   new=AsyncMock(side_effect=HTTPException(409, "changing"))):
            result = await form_action(SimpleNamespace(db=None), hub, "line", body, principal, GRANT)
        self.assertEqual(("failed", 0, 0), (result["status"], result["completed"], result["remaining"]))


if __name__ == "__main__":
    unittest.main()
