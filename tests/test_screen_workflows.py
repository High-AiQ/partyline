"""Exercise the HTTP runner through real grant and element services with a fake helper."""

import asyncio
import json
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from partyline.media_files import prepared_file
from tests.test_return_path import Recorder
from tests.window_grant_fixtures import WindowGrantFixture

BASE = "/api/conversations/alpha/screen-workflows"
LAB = Path(__file__).parent / "fixtures" / "screen-workflows" / "edit-record.yaml"
PORTABLE = """
version: 1
name: portable
description: Edit fields in a native editor.
use_when: The native editor is open.
parameters:
  text: {type: text}
steps:
  - id: open
    target: {role: button, name: Edit record}
    action: invoke
    confirm: false
    postcondition: {check: present, target: {role: dialog, name: Record editor}, timeout_ms: 1000}
  - id: select
    target: {role: combobox, name: Record type}
    action: select
    inputs: {value: image}
    confirm: false
    postcondition: {check: value_equals, expected: image, timeout_ms: 1000}
  - id: fill
    target: {role: textbox, name: Title}
    action: set_value
    inputs: {value: {param: text}}
    confirm: false
    postcondition: {check: value_equals, expected: {param: text}, timeout_ms: 1000}
  - id: close
    target: {role: button, name: Close editor}
    action: invoke
    confirm: false
    postcondition: {check: absent, target: {role: dialog, name: Record editor}, timeout_ms: 1000}
"""


class Clock:
    def __init__(self):
        self.now = 0
        self.deadlines = {}

    @asynccontextmanager
    async def deadline(self, at):
        task = asyncio.current_task()
        self.deadlines[task] = at
        try:
            yield
        except asyncio.CancelledError:
            if self.now >= at:
                raise TimeoutError from None
            raise
        finally:
            self.deadlines.pop(task, None)

    def advance(self, seconds):
        self.now += seconds
        for task, deadline in self.deadlines.items():
            if deadline <= self.now:
                task.cancel()


class WorkflowTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.service = self.hub.workflows
        self.clock = Clock()
        self.service.clock = self.hub.control.clock = lambda: self.clock.now
        self.service.timeout_at = self.clock.deadline
        self.device.update(workflow_actions=True, chrome_dom=0)
        self.root = Path(self.tmp.name) / "project"
        self.workflow_dir = self.root / ".partyline" / "workflows"
        self.workflow_dir.mkdir(parents=True)
        self.db._exec("UPDATE conversations SET cwd=? WHERE id='alpha'", (str(self.root),))
        self.machine_headers = self.machine("a")
        self.human_headers = self.human(self.owner)
        self.source = "uia"
        self.live = True
        self.event_counter = 0
        self.editor = False
        self.ambiguous = False
        self.pending_save = False
        self.notice = ""
        self.values = {"kind": "text"}
        self.actions = []
        self.save_checked = asyncio.Event()
        self.sent_input = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.hold = False
        self.confirmation_ready = asyncio.Event()
        original_broadcast = self.runtime.broadcast

        async def broadcast(line, event):
            if "waiting for human confirmation" in getattr(getattr(event, "message", None), "body", ""):
                self.confirmation_ready.set()
            await original_broadcast(line, event)

        self.runtime.broadcast = broadcast
        await self.grant("a")
        self.device["socket"].send_json = self.helper
        self.starter = Recorder("activation-a")
        self.peer = Recorder("activation-peer")
        for ident, adapter in (("a", self.starter), ("peer", self.peer)):
            self.db.set_attachment_status(ident, "running", adapter.att["runtime_owner"])
            self.runtime.live[ident] = adapter

    async def asyncTearDown(self):
        await self.service.close()
        await super().asyncTearDown()

    def tree(self):
        yield {"id": "root", "control_type": "Window", "name": "Record window"}
        yield self.element("open", "root", "Button", "Edit record", "invoke")
        yield {
            "id": "notice",
            "parent": "root",
            "control_type": "Text",
            "name": "Save status",
            "semantic_role": "status",
        }
        if self.notice:
            yield {"id": "notice-text", "parent": "notice", "control_type": "Text", "name": self.notice}
        if not self.editor:
            return
        yield {"id": "dialog", "parent": "root", "control_type": "Window", "name": "Record editor"}
        for ident, role, name, action in (
            ("kind", "ComboBox", "Record type", "select"),
            ("image", "FileInput", "Record image", "set_files"),
            ("alt", "Edit", "Alternative text", "set_value"),
            ("title", "Edit", "Title", "set_value"),
            ("notes", "Edit", "Notes", "set_value"),
            ("save", "Button", "Save record", "invoke"),
            ("close", "Button", "Close editor", "invoke"),
        ):
            yield self.element(ident, "dialog", role, name, action)
        if self.ambiguous:
            yield self.element("save-2", "dialog", "Button", "Save record", "invoke")
        for ident, name in (("first", "First row"), ("second", "Second row")):
            yield self.element(ident, "dialog", "Row", name, None)
            yield self.element(ident + "-label", ident, "Edit", "Label", "set_value")
            yield self.element(ident + "-value", ident, "Edit", "Value", "set_value")

    def element(self, ident, parent, role, name, action):
        return {
            "id": ident,
            "parent": parent,
            "control_type": role,
            "name": name,
            "actions": [action] if action else [],
            "value": self.values.get(ident, ""),
            **({"file_count": self.values.get(ident, 0)} if ident == "image" else {}),
            **({"action_token": "token-" + ident} if self.source == "cdp" else {}),
        }

    async def helper(self, message):
        self.sent.append(message)
        kind = message["type"]
        ident = message.get("request_id")
        if kind == "read_window_elements":
            response = {
                "request_id": ident,
                "source": self.source,
                "event_counter": self.event_counter,
                "events_supported": self.live,
                "subscription_live": self.live,
            }
            if not message.get("event_status"):
                response.update(
                    snapshot_id=f"snapshot-{ident}",
                    elements=list(self.tree()),
                    captured_event_counter=self.event_counter,
                    workflow_document="page:0" if self.source == "cdp" else "1",
                    action_identity_supported=self.source == "cdp",
                )
            elif self.pending_save:
                self.save_checked.set()
            self.hub.elements.receive(self.device, response)
        elif kind == "window_element_action":
            await self.apply_action(message)
        elif kind == "cancel_workflow_action":
            self.cancelled.set()

    async def apply_action(self, message):
        target, action = message["element_id"], message["action"]
        self.assertEqual(message["workflow_source"], self.source)
        if self.source == "cdp":
            self.assertEqual(message["action_token"], "token-" + target)
        self.actions.append((target, action))
        self.clock.advance(0.125)
        self.sent_input.set()
        if self.hold:
            return
        if target == "open":
            self.editor = True
        if target == "close":
            self.editor = False
        if target == "save":
            self.pending_save = True
        if action in ("set_value", "select"):
            self.values[target] = message["value"]
        if action == "set_files":
            self.assertTrue(self.hub.file_tickets[message["file_ticket"]])
            self.assertNotIn("path", message["files"][0])
            self.values[target] = len(message["files"])
        await self.push_change()
        self.hub.elements.receive(
            self.device, {"request_id": message["request_id"], "status": "completed", "source": self.source}
        )

    async def push_change(self):
        self.event_counter += 1
        await self.hub.window_grants.from_helper(self.device, {"type": "window_changed", "grant_id": "g1"})

    async def approve_definition(self, name="portable"):
        shown = await self.client.get(f"{BASE}/definitions/{name}/review", headers=self.human_headers)
        approved = await self.client.put(
            f"{BASE}/definitions/{name}/approval",
            headers=self.human_headers,
            json={"revision": shown.json()["revision"]},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        return shown.json()["revision"]

    async def start(self, workflow="portable", parameters=None, key="client-key", headers=None):
        response = await self.client.post(
            f"{BASE}/runs",
            headers=headers or self.machine_headers,
            json={
                "workflow": workflow,
                "window": "g1",
                "client_key": key,
                "parameters": ({"text": "private text"} if parameters is None else parameters),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        run_id = response.json()["run_id"]
        return run_id, self.service.runs.get(run_id)

    async def get_status(self, run_id, headers=None):
        response = await self.client.get(f"{BASE}/runs/{run_id}", headers=headers or self.machine_headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def prepare_lab(self, source="cdp"):
        self.source = source
        self.device["chrome_dom"] = 5 if source == "cdp" else 0
        (self.workflow_dir / LAB.name).write_bytes(LAB.read_bytes())
        await self.approve_definition("edit-record")
        msg = self.db.add_message("alpha", "owner", "human", "fixture media")
        file = prepared_file((b"fixture image", "sensitive-name.txt", "text/plain"))
        ident = self.store.store("alpha", msg["id"], [file], None, None)[0].id
        inputs = {
            "kind": "image",
            "images": [ident],
            "alt_text": "sensitive alt text",
            "title": "sensitive title",
            "notes": "sensitive notes",
            "rows": [
                {"row": "First row", "label": "first-label", "value": "first-value"},
                {"row": "Second row", "label": "second-label", "value": "second-value"},
            ],
        }
        run_id, run = await self.start("edit-record", inputs)
        return run_id, run, inputs

    async def reached(self, run, event):
        self.assertIsNotNone(run)
        reached = asyncio.create_task(event.wait())
        try:
            await asyncio.wait((run.task, reached), return_when=asyncio.FIRST_COMPLETED)
            if not event.is_set():
                self.fail(f"workflow stopped early: {await self.get_status(run.id)}")
        finally:
            reached.cancel()

    async def confirm_save(self, run_id, run):
        await self.reached(run, self.confirmation_ready)
        status = await self.get_status(run_id, self.human_headers)
        token = status["confirmation"]["token"]
        path = f"{BASE}/runs/{run_id}/confirmation"
        self.assertNotIn("confirmation", await self.get_status(run_id))
        denied = await self.client.post(
            path, headers=self.machine_headers, json={"token": token, "allow": True}
        )
        self.assertEqual(denied.status_code, 403)
        accepted = await self.client.post(
            path, headers=self.human_headers, json={"token": token, "allow": True}
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        repeated = await self.client.post(
            path, headers=self.human_headers, json={"token": token, "allow": True}
        )
        self.assertEqual(repeated.status_code, 409)

    async def test_lab_page_is_available_without_a_grant(self):
        page = await self.client.get("/lab/window-bench/workflow.html")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Record editor", page.text)

    async def test_non_cdp_portable_route_and_idempotent_start(self):
        (self.workflow_dir / "portable.yaml").write_text(PORTABLE)
        await self.approve_definition()
        run_id, run = await self.start()
        if run:
            await run.task
        self.assertEqual((await self.get_status(run_id))["verified_steps"], 4)
        repeated, _ = await self.start()
        self.assertEqual(repeated, run_id)
        self.assertEqual(
            self.actions,
            [("open", "invoke"), ("kind", "select"), ("title", "set_value"), ("close", "invoke")],
        )
        captures = [
            message
            for message in self.sent
            if message["type"] == "read_window_elements" and not message.get("event_status")
        ]
        self.assertEqual(len(captures), 5)  # initial view plus one check per action
        self.assertEqual(self.values["title"], "private text")
        self.assertEqual((await self.get_status(run_id))["state"], "completed")
        self.assertEqual(len(self.starter.delivered), 1)
        final = self.starter.bodies()[-1]
        self.assertTrue(final.startswith("@a Screen workflow portable"))
        self.assertIn(run_id, final)
        self.assertIn("all steps verified", final)
        self.assertEqual(self.peer.delivered, [])

    async def test_human_started_run_broadcasts_without_waking_attachments(self):
        (self.workflow_dir / "portable.yaml").write_text(PORTABLE)
        await self.approve_definition()
        with patch.object(self.runtime, "route_mentions", wraps=self.runtime.route_mentions) as route:
            run_id, run = await self.start(headers=self.human_headers)
            if run:
                await run.task
        route.assert_not_awaited()
        self.assertEqual((await self.get_status(run_id, self.human_headers))["state"], "completed")
        final = self.db.messages_after("alpha", 0)[-1]["body"]
        self.assertTrue(final.startswith("Screen workflow portable"))
        self.assertIn("all steps verified", final)
        self.assertEqual(self.starter.delivered, [])
        self.assertEqual(self.peer.delivered, [])

    async def test_point_handoff_wakes_only_the_starter_without_sending_input(self):
        (self.workflow_dir / "portable.yaml").write_text(
            PORTABLE.replace("name: Edit record", "name: Missing control").replace(
                "action: invoke", "action: invoke\n    allow_point: true", 1
            )
        )
        await self.approve_definition()
        run_id, run = await self.start()
        if run:
            await run.task
        self.assertEqual((await self.get_status(run_id))["state"], "paused")
        self.assertEqual(len(self.starter.delivered), 1)
        self.assertIn("point input requires the person", self.starter.bodies()[-1])
        self.assertEqual(self.peer.delivered, [])
        self.assertEqual(self.actions, [])

    async def test_cdp_lab_confirms_and_verifies_delayed_notice_without_audit_content(self):
        run_id, run, parameters = await self.prepare_lab()
        await self.confirm_save(run_id, run)
        await self.reached(run, self.save_checked)
        self.assertEqual((await self.get_status(run_id))["verified_steps"], 10)
        self.assertEqual(self.values["second-value"], "second-value")
        self.notice, self.editor, self.pending_save = "Record saved", False, False
        await self.push_change()
        await run.task
        self.assertEqual((await self.get_status(run_id))["state"], "completed")
        self.assertEqual(len(self.starter.delivered), 2)  # confirmation and outcome
        addressed = [body for body in self.starter.bodies() if body.startswith("@a Screen workflow")]
        confirmation, final = addressed
        self.assertIn("waiting for human confirmation", confirmation)
        self.assertIn(f"GET `{BASE}/runs/{run_id}`", confirmation)
        self.assertIn(f"POST the decision to `{BASE}/runs/{run_id}/confirmation`", confirmation)
        self.assertIn("all steps verified", final)
        self.assertEqual(self.peer.delivered, [])
        report = await self.client.get(f"{BASE}/runs/{run_id}/audit", headers=self.human_headers)
        self.assertEqual(report.status_code, 200)
        self.assertEqual([event["event"] for event in report.json()["events"]].count("verified"), 11)
        for forbidden in ("sensitive", "first-value", "second-label", parameters["images"][0]):
            self.assertNotIn(forbidden, json.dumps(report.json()))
        screen = self.db._exec("SELECT entry FROM screen_control_audit").fetchall()
        self.assertNotIn(parameters["images"][0], str([row["entry"] for row in screen]))

    async def test_cdp_lab_ambiguous_save_never_dispatches(self):
        self.ambiguous = True
        run_id, run, _ = await self.prepare_lab()
        if run:
            await run.task
        result = await self.get_status(run_id)
        self.assertIn("ambiguous", result["outcome"])
        self.assertEqual(result["current_step"], "save-record")
        self.assertNotIn(("save", "invoke"), self.actions)

    async def test_cdp_lab_timeout_is_one_shot(self):
        run_id, run, _ = await self.prepare_lab()
        await self.confirm_save(run_id, run)
        await self.reached(run, self.save_checked)
        self.clock.advance(5)
        await run.task
        self.assertIn("deadline elapsed", (await self.get_status(run_id))["outcome"])
        self.assertEqual(self.actions.count(("save", "invoke")), 1)

    async def test_grant_revocation_cancels_in_flight_request(self):
        (self.workflow_dir / "portable.yaml").write_text(PORTABLE)
        await self.approve_definition()
        self.hold = True
        run_id, run = await self.start()
        await self.reached(run, self.sent_input)
        await self.hub.window_grants.revoke("g1")
        await run.task
        self.assertTrue(self.cancelled.is_set())
        result = await self.get_status(run_id)
        self.assertEqual(result["state"], "stopped")
        self.assertIn("uncertain", result["outcome"])
        self.assertEqual(self.actions, [("open", "invoke")])
        workflow_notices = [body for body in self.starter.bodies() if body.startswith("@a Screen workflow")]
        self.assertEqual(len(workflow_notices), 1)
        self.assertIn("window grant ended", workflow_notices[0])

    async def test_interrupt_ends_wait_before_additional_input(self):
        run_id, run, _ = await self.prepare_lab()
        await self.confirm_save(run_id, run)
        await self.reached(run, self.save_checked)
        self.service.interrupt("a")
        await run.task
        self.assertIn("attachment interrupted", (await self.get_status(run_id))["outcome"])
        self.assertEqual(len(self.actions), 11)

    async def test_capability_refusal_names_step_and_observed_source_before_input(self):
        run_id, run, _ = await self.prepare_lab("uia")
        if run:
            await run.task
        result = await self.get_status(run_id)
        self.assertIn("attach-image requires cdp.set_files, observed source uia", result["outcome"])
        self.assertEqual(self.actions, [])

    async def test_losing_starting_attachment_stops_grant_wait(self):
        (self.workflow_dir / "portable.yaml").write_text(PORTABLE)
        await self.approve_definition()
        self.hold = True
        run_id, run = await self.start()
        await self.reached(run, self.sent_input)
        self.db.set_attachment_status("a", "exited", "activation-a")
        await run.task
        self.assertTrue(self.cancelled.is_set())
        self.assertIn("attachment ended", (await self.get_status(run_id, self.human_headers))["outcome"])
        self.assertEqual(self.starter.delivered, [])
        self.assertEqual(self.peer.delivered, [])

    async def test_review_and_approval_human_only_and_edit_invalidates(self):
        path = self.workflow_dir / "portable.yaml"
        path.write_text(PORTABLE)
        revision = await self.approve_definition()
        api = f"{BASE}/definitions/portable"
        self.assertEqual(
            (await self.client.get(api + "/review", headers=self.machine_headers)).status_code, 403
        )
        for headers, expected in ((self.machine_headers, 403), (self.human_headers, 409)):
            path.write_text(PORTABLE + "\n# edit")
            response = await self.client.put(api + "/approval", headers=headers, json={"revision": revision})
            self.assertEqual(response.status_code, expected)
        shown = await self.client.get(api, headers=self.machine_headers)
        self.assertFalse(shown.json()["approved"])
        self.assertNotEqual(shown.json()["revision"], revision)
        attempted = await self.client.post(
            f"{BASE}/runs",
            headers=self.machine_headers,
            json={
                "workflow": "portable",
                "window": "g1",
                "client_key": "edited",
                "parameters": {"text": "private"},
            },
        )
        self.assertEqual(attempted.status_code, 403)
