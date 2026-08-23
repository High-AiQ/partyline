import asyncio
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from partyline.db import Db
from partyline.media import MediaStore
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
        self.messages = [
            self.db.add_message("line", "greg", "human", f"message {number}")
            for number in range(1, 46)
        ]
        app = FastAPI()
        app.include_router(message_router(self.runtime, self.media))
        self.client = TestClient(app)

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
