"""Lifecycle coverage for lines that have been archived."""

import asyncio
import os
import tempfile
import unittest

os.environ.setdefault("PARTYLINE_DB", "/tmp/partyline-test-import.db")

from fastapi import WebSocketDisconnect

from partyline import server
from partyline.db import Db


class FakeWebSocket:
    def __init__(self, payload):
        self.payload = payload
        self.sent = []

    async def accept(self):
        pass

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
            original_db = server.db
            original_sockets = server.sockets
            try:
                server.db = Db(database.name)
                server.sockets = {}
                conversation = server.db.create_conversation("archived", "Old line")
                server.db.archive_conversation(conversation["id"])
                socket = FakeWebSocket({"sender": "terra", "body": "should not persist"})

                asyncio.run(server.ws_endpoint(socket, conversation["id"]))

                self.assertEqual(socket.sent, [{
                    "type": "error",
                    "conversation_id": conversation["id"],
                    "message": "this line is archived — restore it to talk here",
                }])
                self.assertEqual(server.db.list_messages(conversation["id"]), [])
            finally:
                server.db.close()
                server.db = original_db
                server.sockets = original_sockets

