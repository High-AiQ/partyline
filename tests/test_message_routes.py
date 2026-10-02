import asyncio
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.media import MediaStore
from partyline.media_routes import media_router
from partyline.message_routes import conversation_detail_response, message_router
from partyline.runtime import ChatRuntime


class Presence:
    def working_ids(self, _conv_id):
        return []

    def snapshot(self, _conv_id):
        return []


class MessageRoutesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.db.create_conversation("line", "Line")
        self.runtime = ChatRuntime(self.db)
        self.media = MediaStore(self.db, Path(self.directory.name) / "media")
        self.db.add_attachment("worker", "line", "sol", "fake", ["fake"], "/tmp", "owner")
        self.db.set_attachment_status("worker", "running", "owner")
        self.messages = [
            self.db.add_message("line", "greg", "human", f"message {number}")
            for number in range(1, 46)
        ]
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(message_router(self.runtime, self.media))
        app.include_router(media_router(self.runtime, self.media))
        self.client = TestClient(app)
        user = auth_store.create_user(
            self.db, "greg@example.com", "greg", auth_tokens.hash_password("hunter2222"))
        self.human_token = auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])
        self.client.headers["Authorization"] = f"Bearer {self.human_token}"

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def ids(self, response):
        return [message["id"] for message in response.json()["messages"]]

    def test_detail_is_bounded_to_the_newest_twenty_messages(self):
        detail = asyncio.run(
            conversation_detail_response(self.runtime, Presence(), self.media, "line")
        )

        self.assertEqual([message["id"] for message in detail["messages"]], [
            message["id"] for message in self.messages[-20:]
        ])
        self.assertTrue(detail["has_more_messages"])
        with self.assertRaises(HTTPException):
            asyncio.run(
                conversation_detail_response(self.runtime, Presence(), self.media, "missing")
            )

    def test_before_pages_are_oldest_to_newest_without_overlap(self):
        latest = self.client.get("/api/conversations/line/messages")
        older = self.client.get(
            "/api/conversations/line/messages",
            params={"before_id": self.messages[-20]["id"]},
        )
        oldest = self.client.get(
            "/api/conversations/line/messages",
            params={"before_id": self.messages[5]["id"]},
        )

        self.assertEqual(self.ids(latest), [message["id"] for message in self.messages[-20:]])
        self.assertTrue(latest.json()["has_more"])
        self.assertEqual(self.ids(older), [message["id"] for message in self.messages[5:25]])
        self.assertTrue(older.json()["has_more"])
        self.assertEqual(self.ids(oldest), [message["id"] for message in self.messages[:5]])
        self.assertFalse(oldest.json()["has_more"])

    def test_after_pages_catch_up_without_redownloading_history(self):
        first = self.client.get(
            "/api/conversations/line/messages",
            params={"after_id": self.messages[9]["id"], "limit": 20},
        )
        second = self.client.get(
            "/api/conversations/line/messages",
            params={"after_id": self.messages[29]["id"], "limit": 20},
        )

        self.assertEqual(self.ids(first), [message["id"] for message in self.messages[10:30]])
        self.assertTrue(first.json()["has_more"])
        self.assertEqual(self.ids(second), [message["id"] for message in self.messages[30:]])
        self.assertFalse(second.json()["has_more"])

    def test_human_post_matches_socket_routing(self):
        posted = self.client.post(
            "/api/conversations/line/messages",
            json={"body": "hello from REST"},
        )
        self.assertEqual(posted.status_code, 200)
        body = posted.json()
        self.assertEqual(body["sender"], "greg")
        self.assertEqual(body["sender_type"], "human")
        self.assertEqual(body["body"], "hello from REST")

    def test_human_post_is_blocked_when_only_stopped_or_exited_processes_remain(self):
        self.db.set_attachment_status("worker", "exited", "owner")
        self.db.add_attachment("old-worker", "line", "terra", "fake", ["fake"], "/tmp")
        self.db.set_attachment_status("old-worker", "detached", None)

        response = self.client.post(
            "/api/conversations/line/messages", json={"body": "please help"}
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "attach a process to this line before sending")

    def test_a_starting_process_allows_a_human_message(self):
        self.db.set_attachment_status("worker", "starting", "owner")
        response = self.client.post(
            "/api/conversations/line/messages", json={"body": "@sol get ready"}
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_child_process_does_not_make_parent_line_live(self):
        self.db.create_conversation("child", "Child")
        self.db._exec("UPDATE conversations SET parent_id='line' WHERE id='child'")
        self.db.set_attachment_status("worker", "exited", "owner")
        self.db.add_attachment("child-worker", "child", "terra", "fake", ["fake"], "/tmp")
        self.db.set_attachment_status("child-worker", "running", None)

        response = self.client.post(
            "/api/conversations/line/messages", json={"body": "hello parent"}
        )

        self.assertEqual(response.status_code, 409)

    def test_all_and_multiple_processes_are_allowed(self):
        self.db.add_attachment("worker-2", "line", "terra", "fake", ["fake"], "/tmp")
        self.db.set_attachment_status("worker-2", "running", None)

        response = self.client.post(
            "/api/conversations/line/messages", json={"body": "@all please read"}
        )

        self.assertEqual(response.status_code, 200, response.text)

    def test_agent_posts_and_system_notices_do_not_require_a_live_attachment(self):
        self.db.set_attachment_status("worker", "exited", "owner")
        self.client.headers["Authorization"] = "Bearer " + auth_store.ensure_api_token(
            self.db, "worker"
        )
        agent = self.client.post(
            "/api/conversations/line/messages", json={"body": "agent update"}
        )
        self.assertEqual(agent.status_code, 200, agent.text)
        system = asyncio.run(self.runtime.post_message("line", "system", "system", "notice"))
        self.assertEqual(system["sender_type"], "system")

    def test_file_upload_is_not_blocked_when_no_process_is_live(self):
        self.db.set_attachment_status("worker", "exited", "owner")
        self.client.headers["Authorization"] = f"Bearer {self.human_token}"

        response = self.client.post(
            "/api/conversations/line/files",
            files={"file": ("note.txt", b"shared note", "text/plain")},
        )

        self.assertEqual(response.status_code, 200, response.text)

    def test_file_upload_with_human_text_is_blocked_when_no_process_is_live(self):
        self.db.set_attachment_status("worker", "exited", "owner")

        response = self.client.post(
            "/api/conversations/line/files",
            data={"body": "please review this"},
            files={"file": ("note.txt", b"shared note", "text/plain")},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "attach a process to this line before sending")

    def test_invalid_page_shapes_are_rejected(self):
        both = self.client.get(
            "/api/conversations/line/messages",
            params={"before_id": 3, "after_id": 1},
        )
        self.assertEqual(both.status_code, 400)
        self.assertEqual(
            self.client.get("/api/conversations/missing/messages").status_code, 404
        )
        self.assertEqual(
            self.client.get(
                "/api/conversations/line/messages", params={"limit": 101}
            ).status_code,
            422,
        )

    def test_around_window_includes_target_and_reports_first_and_last_edges(self):
        first = self.messages[0]["id"]
        last = self.messages[-1]["id"]
        at_first = self.client.get(
            "/api/conversations/line/messages/around", params={"message_id": first}
        )
        at_last = self.client.get(
            "/api/conversations/line/messages/around", params={"message_id": last}
        )
        self.assertEqual(at_first.status_code, 200)
        self.assertEqual(self.ids(at_first)[:2], [first, self.messages[1]["id"]])
        self.assertFalse(at_first.json()["has_more_before"])
        self.assertTrue(at_first.json()["has_more_after"])
        self.assertEqual(self.ids(at_last)[-2:], [self.messages[-2]["id"], last])
        self.assertTrue(at_last.json()["has_more_before"])
        self.assertFalse(at_last.json()["has_more_after"])

    def test_around_window_missing_id_and_size_clamps(self):
        missing = self.client.get(
            "/api/conversations/line/messages/around", params={"message_id": 999999}
        )
        self.assertEqual(missing.status_code, 404)
        capped = self.client.get(
            "/api/conversations/line/messages/around",
            params={"message_id": self.messages[22]["id"], "limit": 500},
        )
        self.assertEqual(len(capped.json()["messages"]), 45)
        narrow = self.client.get(
            "/api/conversations/line/messages/around",
            params={"message_id": self.messages[22]["id"], "limit": 0},
        )
        self.assertEqual(len(narrow.json()["messages"]), 3)
