"""/api/version names the served checkout; a no-change restart cannot masquerade as a deploy."""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, deployment, server
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.restart_requests import register_restart_request_routes
from partyline.runtime import ChatRuntime


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _identity(*args, cwd):
    return _git("-c", "user.email=t@example.com", "-c", "user.name=t", *args, cwd=cwd)


class DeploymentModuleTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.checkout = os.path.join(self.directory.name, "checkout")
        os.makedirs(self.checkout)
        _git("init", "-q", "-b", "main", cwd=self.checkout)
        _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=self.checkout)
        self.plain = os.path.join(self.directory.name, "plain")
        os.makedirs(self.plain)

    def test_head_and_path_resolve_inside_a_repository(self):
        self.assertEqual(deployment.checkout_path(self.checkout), self.checkout)
        self.assertEqual(deployment.git_head(self.checkout),
                         _git("rev-parse", "HEAD", cwd=self.checkout).stdout.strip())

    def test_a_directory_outside_git_resolves_to_none(self):
        self.assertIsNone(deployment.checkout_path(self.plain))
        self.assertIsNone(deployment.git_head(self.plain))

    def test_startup_facts_are_captured_at_import(self):
        self.assertTrue(deployment.startup_path() is None
                        or os.path.isdir(deployment.startup_path()))
        head = deployment.startup_head()
        self.assertTrue(head is None or len(head) == 40)


class RestartDeploymentGuardTest(unittest.TestCase):
    """The deployment checkout's HEAD moved since startup, or a restart deploys nothing."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.checkout = os.path.join(self.directory.name, "deployment")
        os.makedirs(self.checkout)
        _git("init", "-q", "-b", "main", cwd=self.checkout)
        _identity("commit", "-q", "--allow-empty", "-m", "deployed", cwd=self.checkout)
        self.head = _git("rev-parse", "HEAD", cwd=self.checkout).stdout.strip()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        register_restart_request_routes(
            app, self.runtime, {"fake": {"capabilities": {"resume": True}}}, lambda: None)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("cap", "line", "astra", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='cap'")
        auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "cap")}
        self.enterContext(patch.object(deployment, "_STARTUP_PATH", self.checkout))
        self.enterContext(patch.object(deployment, "_STARTUP_HEAD", self.head))

    def file(self, **fields):
        body = {"reason": "deploy the reviewed change", **fields}
        return self.client.post("/api/conversations/line/restart-request",
                                json=body, headers=self.captain)

    def test_an_unmoved_checkout_is_refused_as_nothing_to_deploy(self):
        made = self.file()
        self.assertEqual(made.status_code, 409, made.text)
        self.assertIn("nothing to deploy", made.json()["detail"])
        self.assertIn("merge and pull first", made.json()["detail"])
        pending = self.client.get("/api/restart-request", headers=self.captain).json()
        self.assertIsNone(pending["request"])

    def test_confirm_no_deploy_files_with_a_loud_warning_the_person_sees(self):
        made = self.file(confirm_no_deploy=True)
        self.assertEqual(made.status_code, 200, made.text)
        self.assertIn("⚠ confirmed no code to deploy", made.json()["reason"])
        pending = self.client.get("/api/restart-request", headers=self.captain).json()["request"]
        self.assertIn("⚠ confirmed no code to deploy", pending["reason"])
        self.assertIn("deploy the reviewed change", pending["reason"])

    def test_a_moved_checkout_files_normally(self):
        with open(os.path.join(self.checkout, "new.txt"), "w") as fh:
            fh.write("the pulled work\n")
        _git("add", "-A", cwd=self.checkout)
        _identity("commit", "-q", "-m", "pulled work", cwd=self.checkout)
        made = self.file()
        self.assertEqual(made.status_code, 200, made.text)
        self.assertNotIn("nothing to deploy", made.json()["reason"])

    def test_an_unknown_checkout_never_blocks_the_request(self):
        self.enterContext(patch.object(deployment, "_STARTUP_PATH", None))
        self.enterContext(patch.object(deployment, "_STARTUP_HEAD", None))
        made = self.file()
        self.assertEqual(made.status_code, 200, made.text)
        self.assertNotIn("nothing to deploy", made.json()["reason"])


class VersionCheckoutTest(unittest.TestCase):
    def test_the_version_names_the_served_checkout_and_head(self):
        with patch.object(deployment, "_STARTUP_PATH", "/some/deployment"), \
                patch.object(deployment, "_STARTUP_HEAD", "b" * 40):
            client = TestClient(server.app)
            payload = client.get("/api/version").json()
        self.assertEqual(payload["checkout_path"], "/some/deployment")
        self.assertEqual(payload["git_head"], "b" * 40)


if __name__ == "__main__":
    unittest.main()
