"""A line's declared gates, run fenced at the SHA (finding 5.6)."""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.goal import register_goal_route
from partyline.accept_sha import register_accept_route
from partyline.hierarchy_routes import hierarchy_router
from partyline.line_gates import register_gates_routes
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _identity(*args, cwd):
    return _git("-c", "user.email=t@example.com", "-c", "user.name=t", *args, cwd=cwd)


class LineGatesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = os.path.join(self.directory.name, "repo")
        os.makedirs(self.repo)
        _git("init", "-q", "-b", "main", cwd=self.repo)
        _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=self.repo)
        self.db = Db(os.path.join(self.directory.name, "partyline.db"))
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))
        register_goal_route(app, self.runtime)
        register_accept_route(app, self.runtime)
        register_gates_routes(app, self.runtime)
        async def fake_start(att, **kwargs):
            return att
        register_conversation_routes(
            app, self.runtime, MediaStore(self.db, self.directory.name + "/media"),
            None, {}, {}, fake_start,
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("root", "Root")
        self.db.add_attachment("root-lead", "root", "terra", "fake", ["fake"], self.repo)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='root-lead'")
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "root-lead")}
        self.client.headers.update(self.captain)
        made = self.client.post("/api/conversations/root/children", json={"name": "kid"})
        self.assertEqual(made.status_code, 201, made.text)
        self.kid = made.json()["conversation"]
        self.worktree = self.kid["cwd"]

    def commit(self, message, filename="code.txt"):
        with open(os.path.join(self.worktree, filename), "a") as fh:
            fh.write(message + "\n")
        _git("add", "-A", cwd=self.worktree)
        _identity("commit", "-q", "-m", message, cwd=self.worktree)
        return _git("rev-parse", "HEAD", cwd=self.worktree).stdout.strip()

    def test_gates_are_stored_and_read(self):
        made = self.client.put("/api/conversations/root/gates", json={
            "commands": ["uv run --locked ruff check .", "./scripts/capped-test"],
            "timeout_s": 1800})
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(made.json(), {"commands": [
            "uv run --locked ruff check .", "./scripts/capped-test"], "timeout_s": 1800})
        seen = self.client.get("/api/conversations/root/gates")
        self.assertEqual(seen.json(), made.json())

    def test_gates_validation_and_permissions(self):
        self.assertEqual(self.client.put(
            "/api/conversations/root/gates",
            json={"commands": []}).status_code, 422)
        self.assertEqual(self.client.put(
            "/api/conversations/root/gates",
            json={"commands": ["x" * 501]}).status_code, 422)
        self.assertEqual(self.client.put(
            "/api/conversations/root/gates",
            json={"commands": ["x"], "timeout_s": 0}).status_code, 422)
        # a worker may not set the line's gates
        self.db.add_attachment("kid-worker", self.kid["id"], "dig", "raw", ["raw"], "/tmp")
        self.db._exec(
            "UPDATE attachments SET status='running' WHERE id='kid-worker'")
        worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "kid-worker")}
        refused = self.client.put("/api/conversations/root/gates",
                                  json={"commands": ["x"]}, headers=worker)
        self.assertEqual(refused.status_code, 403, refused.text)

    def test_the_schema_migration_runs_twice(self):
        import sqlite3

        from partyline.gates_schema import MIGRATIONS as GATES_MIGRATIONS

        for _ in range(2):
            for migration in GATES_MIGRATIONS:
                try:
                    self.db._exec(migration)
                except sqlite3.OperationalError:
                    pass  # already applied, exactly as db.py tolerates it
        self.assertEqual(self.client.put(
            "/api/conversations/root/gates",
            json={"commands": ["x"], "timeout_s": 600}).status_code, 200)

    def test_a_failing_gate_returns_409_with_the_tail(self):
        sha = self.commit("the candidate")
        with patch("partyline.line_gates.get_gates",
                   return_value={"commands": [
                       "echo gated-run", "echo boom >&2; exit 7"], "timeout_s": 600}), \
             patch("partyline.line_gates.fence.command_argv",
                   side_effect=lambda att, command: command), \
             patch("partyline.line_gates.scope_argv", side_effect=lambda argv, limit: argv), \
             patch("partyline.fence.features.enabled", return_value=True), \
             patch("partyline.fence.backend_available", return_value=(True, "")):
            made = self.client.post(
                f"/api/conversations/{self.kid['id']}/accept",
                json={"sha": sha, "run_gates": True}, headers=self.captain)
        self.assertEqual(made.status_code, 409, made.text)
        gates = made.json()["detail"]["gates"]
        self.assertEqual([g["command"] for g in gates],
                         ["echo gated-run", "echo boom >&2; exit 7"])
        self.assertEqual([g["exit"] for g in gates], [0, 7])
        self.assertIn("boom", gates[1]["tail"])
        self.assertIsNone(self.db.get_conversation(self.kid["id"])["accepted_sha"])

    def test_a_passing_gate_accepts_and_reports(self):
        sha = self.commit("the candidate")
        with patch("partyline.line_gates.get_gates",
                   return_value={"commands": ["true"], "timeout_s": 600}), \
             patch("partyline.line_gates.fence.command_argv",
                   side_effect=lambda att, command: command), \
             patch("partyline.fence.command_argv",
                   side_effect=lambda att, command: command), \
             patch("partyline.line_gates.scope_argv", side_effect=lambda argv, limit: argv), \
             patch("partyline.fence.features.enabled", return_value=True), \
             patch("partyline.fence.backend_available", return_value=(True, "")):
            made = self.client.post(
                f"/api/conversations/{self.kid['id']}/accept",
                json={"sha": sha, "run_gates": True}, headers=self.captain)
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(made.json()["gates"][0]["exit"], 0)
        self.assertEqual(made.json()["gates"][0]["command"], "true")
        self.assertIn("(gates passed)", " ".join(
            m["body"] for m in self.db.list_messages(self.kid["id"])))

    def test_run_gates_without_declared_gates_is_refused(self):
        sha = self.commit("the candidate")
        made = self.client.post(
            f"/api/conversations/{self.kid['id']}/accept",
            json={"sha": sha, "run_gates": True}, headers=self.captain)
        self.assertEqual(made.status_code, 409, made.text)
        self.assertIn("no gates are declared", made.json()["detail"])


if __name__ == "__main__":
    unittest.main()
