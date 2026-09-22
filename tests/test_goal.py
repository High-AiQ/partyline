"""The goal: recorded once, carried on every wake of the line's manager only."""

import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.goal import goal_rider, register_goal_route
from partyline.hierarchy import set_lead
from partyline.role_delivery import bind_role_delivery
from partyline.runtime import ChatRuntime


class GoalRouteTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        register_goal_route(app, self.runtime)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("lead", "line", "lead", "fake", ["fake"], "/tmp", "own")
        self.db.add_attachment("worker", "line", "worker", "fake", ["fake"], "/tmp", "own")
        for att in ("lead", "worker"):
            self.db.set_attachment_status(att, "running", "own")
        set_lead(self.db, "line", "lead")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.lead = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "lead")}
        self.worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "worker")}

    def put(self, goal, headers):
        return self.client.put("/api/conversations/line/goal", json={"goal": goal}, headers=headers)

    def test_a_person_records_the_goal_and_the_line_hears_it(self):
        response = self.put("ship the helper with tests", self.human)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["goal"], "ship the helper with tests")
        self.assertEqual(self.db.get_conversation("line")["goal"], "ship the helper with tests")
        [notice] = self.db.list_messages("line")
        self.assertEqual(notice["body"], "☏ goal set by @person: ship the helper with tests")

    def test_the_manager_may_record_it_and_an_implementer_may_not(self):
        self.assertEqual(self.put("by the lead", self.lead).status_code, 200)
        [notice] = self.db.list_messages("line")
        self.assertEqual(notice["source_attachment_id"], "lead")
        self.assertEqual(self.put("by the worker", self.worker).status_code, 403)
        self.assertEqual(self.db.get_conversation("line")["goal"], "by the lead")

    def test_clearing_is_announced_and_resaving_is_silent(self):
        self.put("first", self.human)
        self.put("first", self.human)
        self.put("", self.human)

        bodies = [m["body"] for m in self.db.list_messages("line")]
        self.assertEqual(bodies, ["☏ goal set by @person: first", "☏ goal cleared by @person"])

    def test_the_goal_is_capped(self):
        self.assertEqual(self.put("x" * 3001, self.human).status_code, 400)

    def test_an_unknown_line_is_404(self):
        response = self.client.put(
            "/api/conversations/nope/goal", json={"goal": "x"}, headers=self.human)
        self.assertEqual(response.status_code, 404)


class GoalRiderTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("lead", "line", "lead", "fake", ["fake"], "/tmp", "own")
        self.db.add_attachment("worker", "line", "worker", "fake", ["fake"], "/tmp", "own")
        for att in ("lead", "worker"):
            self.db.set_attachment_status(att, "running", "own")
        set_lead(self.db, "line", "lead")

    def test_the_rider_is_empty_without_a_goal_and_carries_the_rule_with_one(self):
        self.assertEqual(goal_rider(self.db, "line"), "")
        self.db.set_attachment_status("worker", "exited", "own")
        self.db._exec("UPDATE conversations SET goal=? WHERE id=?", ("finish  the\nbook", "line"))
        self.assertEqual(
            goal_rider(self.db, "line"),
            "(goal you are seeing through: finish the book; you are the captain — delegate to a "
            "sub-captain, review, decide; you do not implement)",
        )

    def test_the_manager_carries_the_goal_and_the_implementer_does_not(self):
        self.db._exec("UPDATE conversations SET goal=? WHERE id=?", ("finish the book", "line"))
        lead = {"id": "lead", "digest_rider": lambda: "tasks"}
        worker = {"id": "worker", "digest_rider": lambda: "tasks"}
        bind_role_delivery(self.db, lead)
        bind_role_delivery(self.db, worker)
        first = lead["digest_rider"]()  # the first wake carries the current goal
        self.assertIn("(goal you are seeing through: finish the book;", first)
        self.assertIn("captain pack: GET /api/conversations/line/briefing", lead["digest_rider"]())
        self.assertNotIn("you do not implement", worker["digest_rider"]())
