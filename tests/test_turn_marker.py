"""A process cut off mid-turn is told to continue when it is resumed."""

import tempfile
import unittest
from pathlib import Path

from partyline import server
from partyline.db import Db
from partyline.presence import Presence
from partyline.runtime import ChatRuntime
from partyline.turn_marker import was_interrupted


class TurnMarkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_presence_writes_the_open_turn_to_the_row(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Db(f"{directory}/partyline.db")
            runtime = ChatRuntime(db)
            presence = Presence(runtime)
            saved = (server.runtime, server.presence, server.media)
            server.runtime, server.presence = runtime, presence
            server.media = server.MediaStore(db, Path(directory) / "media")
            try:
                db.create_conversation("line", "Line")
                db.add_attachment("busy", "line", "luna", "fake", ["fake"], directory)
                self.assertFalse(was_interrupted(db, "busy"))
                await presence.started("line", "busy")
                self.assertTrue(was_interrupted(db, "busy"))
                await presence.spoke("line", "busy")
                self.assertTrue(was_interrupted(db, "busy"))
                await presence.finished("line", "busy")
                self.assertFalse(was_interrupted(db, "busy"))
            finally:
                server.runtime, server.presence, server.media = saved
                db.close()
