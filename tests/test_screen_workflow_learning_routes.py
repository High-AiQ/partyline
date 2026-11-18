"""Visibility, preview dispatch boundaries and draft approval integration tests."""

import json
import shutil
import time
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from partyline.mcp.telemetry import record as telemetry_record
from partyline.tool_telemetry import store as store_telemetry
from partyline.tool_telemetry_contracts import ToolCall

from tests.window_grant_fixtures import WindowGrantFixture
from partyline.screen_tree import Snapshot
from partyline.screen_tree_ids import IdSpace

PREFIX = "/api/conversations/alpha/screen-workflows"
WORKFLOW = """version: 1
name: preview-only
description: Check a visible control.
use_when: A generic editor is open.
steps:
  - id: save
    target: {role: button, name: Save}
    action: invoke
    confirm: false
    postcondition: {check: present, target: step_target, timeout_ms: 1000}
"""


class LearningRouteTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.service = self.hub.workflows
        self.root = Path(self.tmp.name) / "project"
        self.folder = self.root / ".partyline/workflows"
        self.folder.mkdir(parents=True)
        self.db._exec("UPDATE conversations SET cwd=? WHERE id='alpha'", (str(self.root),))
        await self.grant("a", grant_id="g1")
        self.device["socket"].send_json = self.receive

    async def asyncTearDown(self):
        await self.service.close()
        await super().asyncTearDown()

    async def demo(self):
        response = await self.client.post(PREFIX + "/demonstrations", json={"window": "g1"},
                                          headers=self.human(self.owner))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    async def test_demo_reads_require_recorded_grant_visibility(self):
        demo_id = await self.demo()
        visible = await self.client.get(PREFIX + f"/demonstrations/{demo_id}",
                                        headers=self.machine("a"))
        hidden = await self.client.get(PREFIX + f"/demonstrations/{demo_id}",
                                       headers=self.human(self.other_user))
        other_line_process = await self.client.get(PREFIX + f"/demonstrations/{demo_id}",
                                                   headers=self.machine("b"))
        self.assertEqual(visible.status_code, 200)
        self.assertEqual(hidden.status_code, 404)
        self.assertNotEqual(other_line_process.status_code, 200)
        self.hub.devices.clear()
        after_grant_closed = await self.client.get(PREFIX + f"/demonstrations/{demo_id}",
                                                   headers=self.human(self.owner))
        self.assertEqual(after_grant_closed.status_code, 200)
        owner_listing = await self.client.get(PREFIX + "/learning", headers=self.human(self.owner))
        self.assertEqual([item["id"] for item in owner_listing.json()["demonstrations"]], [demo_id])
        listing = await self.client.get(PREFIX + "/learning", headers=self.human(self.other_user))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["demonstrations"], [])

    async def test_preview_reads_without_input_or_replacing_live_element_ids(self):
        (self.folder / "preview-only.yaml").write_text(WORKFLOW)
        revision = await self.service.revision("alpha", "preview-only")
        demo_id = await self.demo()
        await self.client.post(PREFIX + f"/demonstrations/{demo_id}/stop",
                               headers=self.human(self.owner))
        self.db._exec(
            "INSERT INTO screen_workflow_drafts(id,conv_id,demonstration_id,name,path,revision,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            ("draft-1", "alpha", demo_id, "preview-only", ".partyline/workflows/preview-only.yaml",
             revision.digest, time.time()),
        )
        prior = len(self.sent)
        old_snapshot, old_space = Snapshot("prior", 0, IdSpace()), IdSpace()
        self.hub.elements.snapshots["g1"] = old_snapshot
        self.hub.elements.spaces["g1"] = old_space
        response = await self.client.post(PREFIX + "/preview",
                                          json={"draft_id": "draft-1", "window": "g1", "parameters": {}},
                                          headers=self.machine("a"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["steps"][0]["state"], "missing")
        self.assertTrue(response.json()["read_only"])
        audits = [json.loads(row["entry"]) for row in self.db._exec(
            "SELECT entry FROM screen_control_audit ORDER BY id").fetchall()]
        self.assertTrue(any(item["operation"] == "screen_workflow_read" for item in audits))
        self.assertTrue(all(message["type"] == "read_window_elements" for message in self.sent[prior:]))
        self.assertIs(self.hub.elements.snapshots["g1"], old_snapshot)
        self.assertIs(self.hub.elements.spaces["g1"], old_space)

    async def test_draft_bundle_is_not_runnable_without_person_approval(self):
        shutil.rmtree(self.folder)
        shutil.copytree(Path(__file__).parent / "fixtures/screen-workflows/publish-document", self.folder)
        demo_id = await self.demo()
        await self.client.post(PREFIX + f"/demonstrations/{demo_id}/stop",
                               headers=self.human(self.owner))
        saved = await self.client.post(PREFIX + "/drafts",
                                       json={"demonstration_id": demo_id, "workflow": "publish-document"},
                                       headers=self.machine("a"))
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertFalse(saved.json()["approved"])
        hidden_preview = await self.client.post(
            PREFIX + "/preview",
            json={"draft_id": saved.json()["id"], "window": "g1", "parameters": {}},
            headers=self.human(self.other_user),
        )
        self.assertEqual(hidden_preview.status_code, 404)
        started = await self.client.post(PREFIX + "/runs", json={"workflow": "publish-document",
                                      "window": "g1", "parameters": {}, "client_key": "draft-run"},
                                         headers=self.machine("a"))
        self.assertEqual(started.status_code, 403)
        self.assertIn("person must approve", started.text)
        approval = await self.client.put(
            PREFIX + "/definitions/publish-document/approval",
            json={"revision": saved.json()["revision"]},
            headers=self.human(self.owner),
        )
        self.assertEqual(approval.status_code, 200, approval.text)
        learning = await self.client.get(PREFIX + "/learning", headers=self.human(self.owner))
        draft_view = next(item for item in learning.json()["drafts"] if item["id"] == saved.json()["id"])
        self.assertTrue(draft_view["approved"])

    async def test_history_interval_preserves_missing_arguments_as_unresolved(self):
        start = time.time() - 5
        end = time.time() + 5
        metrics = {"tool": "screen_window_look", "sub_op": "", "outcome": "unknown",
                   "media_source": "screen"}
        self.db._exec("INSERT INTO tool_calls(conv_id,attachment_id,adapter,timestamp,metrics) "
                      "VALUES(?,?,?,?,?)", ("alpha", "a", "fixture", time.time(), json.dumps(metrics)))
        metric = telemetry_record(
            "screen_element_action", {"action": "invoke"}, "completed",
            {"status": "completed"}, False, time.perf_counter(),
        )
        store_telemetry(self.db, self.db.get_attachment("a"), [ToolCall.model_validate(metric)])
        other_metric = telemetry_record(
            "screen_window_snapshot", {}, "completed", {"status": "completed"},
            False, time.perf_counter(),
        )
        store_telemetry(self.db, self.db.get_attachment("a"), [ToolCall.model_validate(other_metric)])
        spoken_at = time.time()
        self.db._exec("INSERT INTO messages(conv_id,sender,sender_type,body,created_at) VALUES(?,?,?,?,?)",
                      ("alpha", "owner", "human",
                       'Walkthrough · 0:04 · 0 frames\n[0:02] "I save the module."', spoken_at))
        at = time.time()
        evidence = [
            {"at": at - 1, "completed_at": at, "operation": "screen_element_action",
             "arguments": {"action": "invoke"}, "window": "Editor",
             "outcome": "completed", "observation": {"targets": [{"role": "button",
                                                                        "name": "Save",
                                                                        "scope": "Editor"}]}},
            {"at": at - 1, "completed_at": at, "operation": "screen_window_snapshot",
             "arguments": {"window": "another"}, "window": "another",
             "outcome": "unknown", "observation": None},
        ]
        with patch("partyline.screen_workflow_transcripts.read_attachment_calls", return_value=evidence):
            result = await self.client.post(PREFIX + "/demonstrations/from-history",
                                            json={"window": "g1", "start": start, "end": end},
                                            headers=self.machine("a"))
        self.assertEqual(result.status_code, 200, result.text)
        calls = result.json()["calls"]
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]["arguments"], None)
        self.assertIn("unknown", calls[0]["unresolved"])
        self.assertIn("attributed", calls[0]["unresolved"])
        self.assertEqual(calls[1]["operation"], "screen_element_action")
        self.assertEqual(calls[1]["arguments"]["action"], "invoke")
        self.assertEqual(calls[1]["observation"]["targets"][0]["name"], "Save")
        self.assertEqual(calls[1]["outcome"], "completed")
        self.assertNotIn("unresolved", calls[1])
        self.assertEqual(calls[2]["operation"], "screen_window_snapshot")
        self.assertIsNone(calls[2]["arguments"])
        self.assertIsNone(calls[2]["observation"])
        self.assertIn("unknown", calls[2]["unresolved"])
        self.assertIn("attributed", calls[2]["unresolved"])
        self.assertEqual(result.json()["narration"][0]["at"], spoken_at - 2)

    async def test_history_pairs_repeated_operations_in_order_only_when_counts_match(self):
        from partyline.screen_workflow_learning import history_evidence

        start = time.time() - 2
        end = time.time() + 2
        timestamps = [time.time(), time.time() + 0.2]

        def insert_rows(values):
            self.db._exec("DELETE FROM tool_calls WHERE conv_id=?", ("alpha",))
            for timestamp in values:
                metrics = {"tool": "screen_element_action", "sub_op": "invoke",
                           "outcome": "ok", "media_source": "screen"}
                self.db._exec(
                    "INSERT INTO tool_calls(conv_id,attachment_id,adapter,timestamp,metrics) "
                    "VALUES(?,?,?,?,?)",
                    ("alpha", "a", "claude", timestamp,
                     json.dumps(metrics)),
                )

        native = [
            {"at": timestamps[0] - 0.2, "completed_at": timestamps[0],
             "operation": "screen_element_action", "arguments": {"action": "invoke", "value": "first"},
             "window": "g1", "outcome": "completed", "observation": {"targets": [
                 {"role": "button", "name": "First"}]}},
            {"at": timestamps[1] - 0.2, "completed_at": timestamps[1],
             "operation": "screen_element_action", "arguments": {"action": "invoke", "value": "second"},
             "window": "Editor", "outcome": "completed", "observation": {"targets": [
                 {"role": "button", "name": "Second"}]}},
        ]
        insert_rows(timestamps)
        with patch("partyline.screen_workflow_transcripts.read_attachment_calls", return_value=native):
            calls, _ = history_evidence(self.db, "alpha", start, end, "g1", "Editor")
        self.assertEqual([call["arguments"]["value"] for call in calls], ["first", "second"])
        self.assertTrue(all("unresolved" not in call for call in calls))

        insert_rows(timestamps)
        with patch("partyline.screen_workflow_transcripts.read_attachment_calls",
                   return_value=native[:1]):
            calls, _ = history_evidence(self.db, "alpha", start, end, "g1", "Editor")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call["arguments"] is None and "unresolved" in call for call in calls))

    async def test_preview_reports_missing_multiple_and_ambiguous_scopes_separately(self):
        from partyline.screen_workflow_format import Check, Target
        from partyline.screen_workflow_preview import inspect_plan, precondition_report, target_report

        tree = Snapshot("snapshot", 0, IdSpace())
        tree.add([{"id": "root", "control_type": "Window", "name": "Editor"},
                  {"id": "one", "control_type": "Button", "name": "Save", "parent": "root"},
                  {"id": "two", "control_type": "Button", "name": "Save", "parent": "root"},
                  {"id": "add-row", "control_type": "Button", "name": "Add row", "parent": "root"},
                  {"id": "scope-one", "control_type": "Window", "name": "Dialog"},
                  {"id": "scope-two", "control_type": "Window", "name": "Dialog"}])
        multiple = target_report(tree, Target(role="button", name="Save"))
        ambiguous = target_report(tree, Target(role="button", name="Save",
                                                within={"role": "dialog", "name": "Dialog"}))
        missing = target_report(tree, Target(role="textbox", name="Absent"))
        ordinal = target_report(tree, Target(role="button", name="Save", within={
            "role": "window", "name": "Editor",
        }, ordinal=1, match_count=2))
        self.assertEqual((multiple["state"], multiple["match_count"], multiple["multiply_matched"],
                          multiple["ambiguous"]), ("multiply_matched", 2, True, False))
        self.assertEqual((ambiguous["state"], ambiguous["match_count"], ambiguous["ambiguous"],
                          ambiguous["multiply_matched"]), ("ambiguous", 2, True, False))
        self.assertEqual((missing["state"], missing["match_count"]), ("missing", 0))
        self.assertEqual((ordinal["state"], ordinal["match_count"], ordinal["multiply_matched"],
                          ordinal["ambiguous"]), ("resolved", 2, True, False))
        self.assertEqual(target_report(tree, None)["state"], "not_required")

        absent_target = Target(role="row", name="Optional row")
        step_target = Target(role="button", name="Add row")
        absent_check = Check(check="absent", target=absent_target)
        step = SimpleNamespace(target=step_target, preconditions=[absent_check])
        satisfied = inspect_plan(tree, [("add-row", step)])[0]
        self.assertEqual((satisfied["state"], satisfied["preconditions"][0]["state"],
                          satisfied["preconditions"][0]["verdict"]),
                         ("resolved", "resolved", True))

        tree.add([{"id": "optional-row", "control_type": "Row", "name": "Optional row"}])
        violated = inspect_plan(tree, [("add-row", step)])[0]
        self.assertEqual((violated["state"], violated["preconditions"][0]["state"],
                          violated["preconditions"][0]["verdict"]),
                         ("resolved", "resolved", False))

        missing_action_target = Target(role="button", name="Missing action")
        own_target_absent = SimpleNamespace(target=missing_action_target,
                                            preconditions=[Check(check="absent")])
        missing_step = inspect_plan(tree, [("missing-action", own_target_absent)])[0]
        self.assertEqual((missing_step["state"], missing_step["preconditions"][0]["verdict"]),
                         ("missing", True))

        missing_value_target = Target(role="textbox", name="Missing value")
        value_checks = (
            Check(check="value_equals", target=missing_value_target, expected="expected"),
            Check(check="notice_text", target=missing_value_target, expected="expected"),
            Check(check="file_count_equals", target=missing_value_target, expected=1,
                  requires=["cdp.set_files"]),
        )
        for check in value_checks:
            with self.subTest(check=check.check):
                report = precondition_report(tree, check, step_target)
                self.assertEqual((report["state"], report["verdict"]), ("missing", None))
        missing_present = precondition_report(
            tree, Check(check="present", target=missing_value_target), step_target,
        )
        self.assertEqual((missing_present["state"], missing_present["verdict"]), ("resolved", False))
        self.assertEqual(target_report(Snapshot("empty", 0, IdSpace()), absent_target)["state"], "missing")


if __name__ == "__main__":
    unittest.main()
