"""Lead-scoped staffing over a subtree, with conservative preset matching."""

import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.hierarchy_routes import hierarchy_router
from partyline.runtime import ChatRuntime
from partyline.staffing_routes import staffing_router


class StaffingApiTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))
        app.include_router(staffing_router(self.runtime))
        self.client = TestClient(app)
        self.db.create_conversation("parent", "Parent")
        self.db.add_attachment("lead-att", "parent", "astra", "fake", ["run"], "/tmp")
        self.db.add_attachment("impl-att", "parent", "grok", "fake", ["run"], "/tmp")
        # Not live: a line carrying a live worker is assigned, not split.
        self.db.set_attachment_status("impl-att", "detached", None)
        user = auth_store.create_user(
            self.db, "greg@example.com", "greg",
            auth_tokens.hash_password("hunter2222"),
        )
        self.human = {
            "Authorization": "Bearer "
            + auth_tokens.create_access_token(
                auth_tokens.signing_secret(self.db), user["id"]
            )
        }
        self.lead = {
            "Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "lead-att")
        }
        self.impl = {
            "Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "impl-att")
        }
        self._original_runtime = server.runtime
        server.runtime = self.runtime
        self.client.post(
            "/api/conversations/parent/lead",
            json={"attachment_id": "lead-att"},
            headers=self.human,
        )

    def tearDown(self):
        server.runtime = self._original_runtime
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def test_implementer_is_forbidden_and_lead_sees_subtree(self):
        self.assertEqual(
            self.client.get("/api/conversations/parent/staffing", headers=self.impl).status_code,
            401,
        )
        child = self.client.post(
            "/api/conversations/parent/children",
            json={"name": "Slice"},
            headers=self.lead,
        ).json()["conversation"]
        self.db.add_attachment(
            "child-att", child["id"], "worker", "fake", ["build"], "/tmp")
        self.db.save_preset(
            "p1", "Astra", "astra", "fake", "run", can_manage=True, implements=False)
        self.db.save_preset("p2", "Worker", "worker", "fake", "build", implements=True)
        self.db.set_attachment_status("impl-att", "exited", None)
        body = self.client.get(
            "/api/conversations/parent/staffing", headers=self.lead).json()
        self.assertTrue(body["presets_in_use"])
        titles = {p["title"]: p for p in body["presets"]}
        self.assertTrue(titles["Astra"]["can_manage"])
        self.assertFalse(titles["Astra"]["implements"])
        handles = {p["handle"]: p for p in body["processes"]}
        self.assertNotIn("grok", handles)
        self.assertTrue(handles["astra"]["captain"])
        self.assertEqual(handles["astra"]["matched_preset"]["name"], "astra")
        self.assertTrue(handles["astra"]["traits"]["can_manage"])
        self.assertEqual(handles["worker"]["line"], "Slice")
        self.assertEqual(handles["worker"]["matched_preset"]["id"], "p2")
        self.assertIsNone(handles.get("mystery"))

    def test_uncertain_matches_stay_unmatched(self):
        self.db.save_preset("a", "One", "astra", "fake", "run")
        self.db.save_preset("b", "Two", "astra", "fake", "run")
        self.db.add_attachment("odd", "parent", "astra-2", "fake", ["run"], "/tmp")
        body = self.client.get(
            "/api/conversations/parent/staffing", headers=self.human).json()
        by_handle = {p["handle"]: p for p in body["processes"]}
        self.assertIsNone(by_handle["astra"]["matched_preset"])
        self.assertIsNone(by_handle["astra"]["traits"])
        self.assertIsNone(by_handle["astra-2"]["matched_preset"])
        self.assertFalse(body["presets_in_use"])

    def test_malformed_preset_command_does_not_break_staffing(self):
        self.db.save_preset("bad", "Broken", "astra", "fake", '"')
        response = self.client.get(
            "/api/conversations/parent/staffing", headers=self.lead)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        astra = next(p for p in body["processes"] if p["handle"] == "astra")
        self.assertIsNone(astra["matched_preset"])
        self.assertIsNone(astra["traits"])
        self.assertEqual(len(body["presets"]), 1)
        self.assertFalse(body["presets_in_use"])


class StaffingLineTest(unittest.TestCase):
    def test_the_wake_line_names_who_is_busy_and_which_presets_are_free(self):
        from partyline.db import Db
        from partyline.staffing import staffing_line
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        db = Db(f"{directory.name}/partyline.db")
        self.addCleanup(db.close)
        self.assertEqual(staffing_line(db, "root"), "")  # no presets: nothing to say
        db.create_conversation("root", "Root")
        db.create_conversation("kid", "Kid")
        db.create_conversation("other", "Other")
        db._exec("UPDATE conversations SET parent_id=? WHERE id=?", ("root", "kid"))
        for name, adapter, traits in (
            ("opus", "claude", {"can_manage": True, "implements": False}),
            ("astra", "codex", {"can_manage": True, "implements": False}),
            ("luna", "codex", {"can_manage": False, "implements": True}),
            ("glm-flash", "opencode", {"can_manage": False, "implements": True}),
        ):
            db.save_preset(name, name, name, adapter, f"{adapter} --x", reads_images=False, **traits)
        db.add_attachment("a1", "kid", "opus", "claude", ["claude", "--x"], "/tmp")
        db._exec("UPDATE attachments SET status='running', is_lead=1 WHERE id='a1'")
        db.add_attachment("a2", "kid", "luna", "codex", ["codex", "--x"], "/tmp")
        db._exec("UPDATE attachments SET status='running' WHERE id='a2'")
        db.add_attachment("a3", "other", "glm-flash", "opencode", ["opencode", "--x"], "/tmp")
        db._exec("UPDATE attachments SET status='running' WHERE id='a3'")
        line = staffing_line(db, "root")
        self.assertNotIn("glm-flash «Other»", line)
        self.assertNotIn("free workers: glm-flash", line)
        # a can_manage preset with a live instance stays listed: captains run
        # one instance per line, and the seat count says when they run out
        self.assertEqual(
            line,
            "(staffing — in use: opus «Kid» captain; luna «Kid». "
            "free captains: astra, opus. free workers: none)",
        )


class CaptainInstancesTest(unittest.TestCase):
    """Numbered captain instances (finding 5.3): a can_manage preset holds one
    live instance per line, the staffing line counts seats, and worker
    presets keep their old hide-when-used behaviour."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(os.path.join(self.directory.name, "partyline.db"))
        self.addCleanup(self.db.close)
        self.db.create_conversation("root", "Root")
        self.db.create_conversation("a", "Alpha")
        self.db.create_conversation("b", "Beta")
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id IN ('a','b')")
        self.db.save_preset("astra", "Astra", "astra", "raw", "raw --x",
                            can_manage=True, implements=False, max_instances=3)
        self.db.save_preset("luna", "Luna", "luna", "raw", "raw --x",
                            can_manage=False, implements=True)

    def seat(self, conv_id, att_id, handle):
        self.db.add_attachment(att_id, conv_id, handle, "raw", ["raw", "--x"], "/tmp")
        self.db._exec("UPDATE attachments SET status='running' WHERE id=?", (att_id,))

    def staffing(self):
        from partyline.staffing import staffing_line

        return staffing_line(self.db, "root", runtime=None)

    def captains(self, line):
        return line.split("free captains: ", 1)[1].split(".")[0]

    def test_two_lines_appoint_instances_of_the_same_captain_preset(self):
        from partyline.hierarchy import set_lead

        self.seat("a", "cap-a1", "astra")
        self.seat("b", "cap-b1", "astra-2")
        set_lead(self.db, "a", "cap-a1")
        set_lead(self.db, "b", "cap-b1")
        self.assertTrue(self.db.get_attachment("cap-a1")["is_lead"])
        self.assertTrue(self.db.get_attachment("cap-b1")["is_lead"])
        line = self.staffing()
        # one seat left: shown plain — the "(N more)" count only appears when
        # more than one instance is still available
        self.assertEqual(self.captains(line), "astra")
        self.db.save_preset("astra", "Astra", "astra", "raw", "raw --x",
                            can_manage=True, implements=False, max_instances=4)
        self.assertEqual(self.captains(self.staffing()), "astra (2 more)")
        self.assertNotIn("free captains: none", line)

    def test_the_preset_hides_only_when_max_instances_is_reached(self):
        self.seat("a", "cap-a1", "astra")
        self.seat("a", "cap-a2", "astra-2")
        self.seat("b", "cap-b1", "astra-3")
        line = self.staffing()
        self.assertNotIn("(1 more)", line)  # one seat left: shown plain
        self.assertIn("free captains: none", line)  # 3 of 3 seats live

    def test_worker_presets_keep_their_old_behaviour(self):
        self.seat("a", "w1", "luna")
        line = self.staffing()
        self.assertNotIn("luna", self.captains(line))
        self.assertIn("free workers: none", line)  # in use: hidden, as before
        self.assertIn("in use: luna «Alpha»", line)

    def test_max_instances_round_trips_through_the_api(self):
        from partyline.preset_routes import presets_router

        runtime = ChatRuntime(self.db)
        app = FastAPI()
        app.include_router(presets_router(runtime, {"raw"}))
        client = TestClient(app)
        made = client.post("/api/presets", json={
            "title": "Astra", "name": "astra", "adapter": "raw", "command": "raw --x",
            "can_manage": True, "implements": False, "max_instances": 3})
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(made.json()["max_instances"], 3)
        row = self.db._exec(
            "SELECT max_instances FROM presets WHERE id=?", ("astra",)).fetchone()
        self.assertEqual(row["max_instances"], 3)

    def test_auto_compact_tokens_round_trips_and_resolves_at_spawn(self):
        from partyline.preset_routes import presets_router
        from partyline.preset_traits import auto_compact_tokens_for

        runtime = ChatRuntime(self.db)
        app = FastAPI()
        app.include_router(presets_router(runtime, {"claude"}))
        client = TestClient(app)
        made = client.post("/api/presets", json={
            "title": "Haiku", "name": "haiku", "adapter": "claude",
            "command": "claude", "auto_compact_tokens": 80000})
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(made.json()["auto_compact_tokens"], 80000)

        # The spawn seam resolves it from the matched preset; a preset the
        # attachment does not match leaves the CLI default in place.
        att = {"name": "haiku", "adapter": "claude", "command": ["claude"]}
        self.assertEqual(auto_compact_tokens_for(self.db, att), 80000)
        other = {"name": "dig", "adapter": "claude", "command": ["claude"]}
        self.assertEqual(auto_compact_tokens_for(self.db, other), 0)

        # Unset means unset: a fresh preset without the field stays 0.
        made = client.post("/api/presets", json={
            "title": "Opus", "name": "opus", "adapter": "claude", "command": "claude"})
        self.assertEqual(made.json()["auto_compact_tokens"], 0)
        att = {"name": "opus", "adapter": "claude", "command": ["claude"]}
        self.assertEqual(auto_compact_tokens_for(self.db, att), 0)

        # Over-limit values are refused at the contract, like max_instances.
        refused = client.post("/api/presets", json={
            "title": "Bad", "name": "bad", "adapter": "claude", "command": "claude",
            "auto_compact_tokens": -1})
        self.assertEqual(refused.status_code, 422)
