"""Lifecycle coverage for lines that have been archived."""

import asyncio
import os
import tempfile
import unittest

os.environ.setdefault("PARTYLINE_DB", "/tmp/partyline-test-import.db")

from fastapi import WebSocketDisconnect

from partyline import auth_store, auth_tokens, server
from partyline.db import Db
from partyline.runtime import ChatRuntime


class FakeWebSocket:
    def __init__(self, payload, token=""):
        self.payload = payload
        self.sent = []
        self.headers = {}
        self.query_params = {"token": token} if token else {}

    async def accept(self):
        pass

    async def close(self, code, reason=""):
        self.closed = (code, reason)

    async def receive_json(self):
        if self.payload is None:
            raise WebSocketDisconnect()
        payload, self.payload = self.payload, None
        return payload

    async def send_json(self, event):
        self.sent.append(event)


class ArchivedLineLifecycleTest(unittest.TestCase):
    def test_websocket_message_to_archived_line_is_rejected_and_not_saved(self):
        with tempfile.NamedTemporaryFile(suffix=".db") as database:
            original_runtime = server.runtime
            try:
                server.runtime = ChatRuntime(Db(database.name))
                conversation = server.runtime.db.create_conversation("archived", "Old line")
                server.runtime.db.archive_conversation(conversation["id"])
                user = auth_store.create_user(
                    server.runtime.db, "terra@example.com", "terra",
                    auth_tokens.hash_password("hunter2222"))
                token = auth_tokens.create_access_token(
                    auth_tokens.signing_secret(server.runtime.db), user["id"])
                socket = FakeWebSocket({"body": "should not persist"}, token=token)

                asyncio.run(server.ws_endpoint(socket, conversation["id"]))

                self.assertEqual(socket.sent, [{
                    "type": "error",
                    "conversation_id": conversation["id"],
                    "message": "this line is archived — restore it to talk here",
                }])
                self.assertEqual(server.runtime.db.list_messages(conversation["id"]), [])
            finally:
                server.runtime.db.close()
                server.runtime = original_runtime
