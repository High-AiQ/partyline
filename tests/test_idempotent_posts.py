"""Finding 2.7: a retry and a terminal echo each land exactly one message."""

import json
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.agent_client import derived_client_key, with_client_key
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.idempotency_schema import MIGRATIONS as IDEMPOTENCY_MIGRATIONS
from partyline.media import MediaStore
from partyline.message_routes import message_router
from partyline.runtime import ChatRuntime


class IdempotentPostsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.db.create_conversation("line", "Line")
        self.runtime = ChatRuntime(self.db)
        self.db.add_attachment("worker", "line", "sol", "fake", ["fake"], "/tmp", "owner")
        self.db.set_attachment_status("worker", "running", "owner")
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(message_router(self.runtime, MediaStore(
            self.db, Path(self.directory.name) / "media")))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        user = auth_store.create_user(
            self.db, "greg@example.com", "greg", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.machine = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "worker")}

    def post(self, body, headers=None, key=None):
        payload = {"body": body}
        if key is not None:
            payload["client_key"] = key
        return self.client.post("/api/conversations/line/messages", json=payload,
                                headers=headers or self.human)

    def bodies(self):
        return [m["body"] for m in self.db.list_messages("line")]

    def backdate(self, body, seconds):
        self.db._exec("UPDATE messages SET created_at = created_at - ? WHERE body = ?",
                      (seconds, body))

    # -- client_key idempotency -------------------------------------------

    def test_the_same_client_key_posts_once_and_answers_with_the_same_id(self):
        first = self.post("deploy finished", key="retry-42")
        second = self.post("deploy finished", key="retry-42")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(self.bodies().count("deploy finished"), 1)

    def test_a_different_key_or_a_different_sender_posts_normally(self):
        first = self.post("deploy finished", key="retry-42")
        other_key = self.post("deploy finished", key="retry-43")
        other_sender = self.post("deploy finished", headers=self.machine, key="retry-42")

        self.assertNotEqual(other_key.json()["id"], first.json()["id"])
        self.assertNotEqual(other_sender.json()["id"], first.json()["id"])
        self.assertEqual(self.bodies().count("deploy finished"), 3)

    def test_a_stale_key_cannot_replay_an_old_message(self):
        first = self.post("deploy finished", key="retry-42")
        self.db._exec("UPDATE idempotent_posts SET created_at = created_at - 601")

        retry = self.post("deploy finished", key="retry-42")

        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertNotEqual(retry.json()["id"], first.json()["id"])
        self.assertEqual(self.bodies().count("deploy finished"), 2)

    def test_a_caller_key_still_replays_at_nine_minutes(self):
        first = self.post("deploy finished", key="retry-42")
        self.db._exec("UPDATE idempotent_posts SET created_at = created_at - 540")

        retry = self.post("deploy finished", key="retry-42")

        self.assertEqual(retry.json()["id"], first.json()["id"])
        self.assertEqual(self.bodies().count("deploy finished"), 1)

    def test_a_derived_key_replays_briefly_then_posts_fresh(self):
        derived = derived_client_key(
            "POST", "/api/conversations/line/messages", b'{"body": "wake up"}')
        self.assertTrue(derived.startswith("d:"))
        first = self.post("wake up", key=derived)

        self.db._exec("UPDATE idempotent_posts SET created_at = created_at - 30")
        soon = self.post("wake up", key=derived)
        self.assertEqual(soon.json()["id"], first.json()["id"])

        # Past the derived window a deliberate re-send must land, or a captain
        # re-waking an idle worker is silently swallowed.
        self.db._exec("UPDATE idempotent_posts SET created_at = created_at - 100")
        later = self.post("wake up", key=derived)
        self.assertNotEqual(later.json()["id"], first.json()["id"])
        self.assertEqual(self.bodies().count("wake up"), 2)

    def test_the_replayed_flag_marks_only_a_replay(self):
        fresh = self.post("deploy finished", key="retry-42")
        replay = self.post("deploy finished", key="retry-42")

        self.assertIs(fresh.json()["replayed"], False)
        self.assertIs(replay.json()["replayed"], True)

    def test_the_capture_echo_is_a_replay_too(self):
        captured = self.db.add_message("line", "sol", "agent", "mirrored update")

        echoed = self.post("mirrored update", headers=self.machine)

        self.assertIs(echoed.json()["replayed"], True)
        self.assertEqual(echoed.json()["id"], captured["id"])

    def test_the_machine_path_is_idempotent_too(self):
        first = self.post("suite green", headers=self.machine, key="m-1")
        second = self.post("suite green", headers=self.machine, key="m-1")

        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(self.bodies().count("suite green"), 1)

    # -- terminal-capture echo --------------------------------------------

    def test_a_machine_post_that_repeats_its_own_capture_stores_nothing(self):
        # The capture path stores the tail's twin unstamped, under the handle.
        captured = self.db.add_message("line", "sol", "agent", "mirrored update")

        echoed = self.post("mirrored update", headers=self.machine)

        self.assertEqual(echoed.status_code, 200, echoed.text)
        self.assertEqual(echoed.json()["id"], captured["id"])
        self.assertEqual(self.bodies().count("mirrored update"), 1)

    def test_the_same_text_after_the_window_or_from_another_process_posts(self):
        self.db.add_message("line", "sol", "agent", "mirrored update")
        self.backdate("mirrored update", 16)

        late = self.post("mirrored update", headers=self.machine)
        self.assertEqual(late.status_code, 200, late.text)
        self.assertEqual(self.bodies().count("mirrored update"), 2)

        self.db.add_message("line", "sol", "agent", "mirrored update")
        self.db.add_attachment("twin", "line", "gemini", "fake", ["fake"], "/tmp", "owner")
        twin = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "twin")}
        elsewhere = self.post("mirrored update", headers=twin)

        # capture + late post + second capture + the twin's own post
        self.assertEqual(elsewhere.status_code, 200, elsewhere.text)
        self.assertEqual(self.bodies().count("mirrored update"), 4)

    def test_whitespace_variants_are_the_same_words_to_the_echo_check(self):
        self.db.add_message("line", "sol", "agent", "mirrored   update")

        echoed = self.post("mirrored update", headers=self.machine)

        self.assertEqual(self.bodies().count("mirrored update"), 0)
        self.assertEqual(self.bodies().count("mirrored   update"), 1)
        self.assertEqual(echoed.json()["body"], "mirrored   update")

    # -- schema ------------------------------------------------------------

    def test_the_idempotency_migration_runs_twice(self):
        path = f"{self.directory.name}/partyline.db"
        for mig in IDEMPOTENCY_MIGRATIONS:
            self.db.conn.execute(mig)  # already applied at Db() open; must not raise
        self.db.conn.commit()

        reopened = Db(path)
        self.addCleanup(reopened.close)
        row = reopened._exec("SELECT COUNT(*) AS n FROM idempotent_posts").fetchone()
        self.assertEqual(row["n"], 0)


class AgentClientKeyTest(unittest.TestCase):
    def test_a_message_post_is_stamped_and_the_key_is_deterministic(self):
        body = b'{"body": "hello"}'
        stamped = with_client_key("POST", "/api/conversations/line/messages", body)

        self.assertEqual(json.loads(stamped)["body"], "hello")
        key = json.loads(stamped)["client_key"]
        self.assertLessEqual(len(key), 64)
        self.assertEqual(key, derived_client_key("POST", "/api/conversations/line/messages", body))
        self.assertEqual(stamped, with_client_key(
            "POST", "/api/conversations/line/messages", body))  # a re-run reuses it

    def test_only_an_unstamped_messages_post_is_touched(self):
        body = b'{"body": "hello"}'
        self.assertIsNone(with_client_key("GET", "/api/conversations/line/messages", None))
        self.assertEqual(with_client_key("GET", "/api/conversations/line/messages", body), body)
        self.assertEqual(with_client_key("POST", "/api/conversations/line/files", body), body)
        stamped = b'{"body": "hello", "client_key": "chosen"}'
        self.assertEqual(with_client_key("POST", "/api/conversations/line/messages", stamped),
                         stamped)

    def test_a_replay_is_announced_on_stderr(self):
        import contextlib
        import io
        from unittest.mock import patch

        from partyline.agent_client import main

        replayed = json.dumps({"id": 7, "replayed": True}).encode()
        fresh = json.dumps({"id": 8, "replayed": False}).encode()
        error, out = io.StringIO(), io.StringIO()
        stdin = io.StringIO('{"body": "wake"}')
        with patch("partyline.agent_client.api_request", return_value=replayed), \
                patch("sys.stdin", stdin), \
                patch("partyline.agent_client.load_connection", return_value={
                    "api": "http://x", "token": "t", "conversation_id": "c",
                    "attachment_id": "a", "handle": "h"}):
            with contextlib.redirect_stderr(error), contextlib.redirect_stdout(out):
                code = main(["--connection", "ignored", "request", "POST",
                             "/api/conversations/line/messages", "--json-file", "-"])
        self.assertEqual(code, 0)
        self.assertIn("replayed original message 7", error.getvalue())
        self.assertIn("add a distinct client_key", error.getvalue())

        error, out = io.StringIO(), io.StringIO()
        stdin = io.StringIO('{"body": "wake"}')
        with patch("partyline.agent_client.api_request", return_value=fresh), \
                patch("sys.stdin", stdin), \
                patch("partyline.agent_client.load_connection", return_value={
                    "api": "http://x", "token": "t", "conversation_id": "c",
                    "attachment_id": "a", "handle": "h"}):
            with contextlib.redirect_stderr(error), contextlib.redirect_stdout(out):
                main(["--connection", "ignored", "request", "POST",
                      "/api/conversations/line/messages", "--json-file", "-"])
        self.assertEqual(error.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
