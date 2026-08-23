"""The server-owned delivery history passed into resumable adapters."""

import tempfile
import unittest

from partyline.attachment_resume import (
    TranscriptDeliveryRecord,
    delivered_bodies,
    delivered_history,
    mark_transcript_delivery,
)
from partyline.db import Db


class DeliveredBodiesTest(unittest.TestCase):
    def test_history_belongs_to_one_attachment_lifetime_and_line(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Db(f"{directory}/partyline.db")
            db.create_conversation("line-a", "A")
            db.create_conversation("line-b", "B")
            db.add_message("line-a", "grok", "agent", "from an older attachment")
            attachment = db.add_attachment(
                "att", "line-a", "grok", "grok", ["grok"], directory
            )
            db.add_message("line-a", "grok", "agent", "first")
            db.add_message("line-a", "other", "agent", "not this attachment")
            db.add_message("line-a", "grok", "system", "not agent speech")
            db.add_message("line-b", "grok", "agent", "wrong line")
            db.add_message("line-a", "grok", "agent", "second")

            self.assertEqual(delivered_bodies(db, attachment), ["first", "second"])
            db.close()

    def test_resume_relay_is_recorded_outside_normal_speech_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/partyline.db"
            db = Db(path)
            db.create_conversation("line", "Line")
            attachment = db.add_attachment(
                "att", "line", "grok", "grok", ["grok"], directory, "owner"
            )
            db.add_message("line", "grok", "agent", "normal before")
            db.add_message(
                "line", "system", "system",
                "@grok: relaying 1 message(s) that never reached this line before now "
                "— they may answer an older state of it",
            )
            db.add_message("line", "grok", "agent", "late transcript record")

            self.assertTrue(mark_transcript_delivery(
                db, attachment, "owner", b"record fingerprint", "late transcript record"
            ))
            history = delivered_history(db, attachment)

            self.assertEqual(history.bodies, ["normal before"])
            self.assertEqual(history.transcript_records, [
                TranscriptDeliveryRecord(b"record fingerprint", "late transcript record")
            ])
            self.assertEqual(history.legacy_relayed_bodies, [])
            db.close()

            reopened = Db(path)
            self.addCleanup(reopened.close)
            persisted = delivered_history(reopened, reopened.get_attachment("att"))
            self.assertEqual(persisted.transcript_records, [
                TranscriptDeliveryRecord(b"record fingerprint", "late transcript record")
            ])
            reopened.delete_conversation("line")
            count = reopened.conn.execute(
                "SELECT COUNT(*) FROM transcript_delivery_records"
            ).fetchone()[0]
            self.assertEqual(count, 0)

    def test_old_resume_notices_recover_the_marker_after_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Db(f"{directory}/partyline.db")
            self.addCleanup(db.close)
            db.create_conversation("line", "Line")
            attachment = db.add_attachment(
                "att", "line", "grok", "grok", ["grok"], directory
            )
            db.add_message("line", "grok", "agent", "normal before")
            for _ in range(3):
                db.add_message(
                    "line", "system", "system",
                    "@grok: relaying 1 message(s) that never reached this line before now "
                    "— they may answer an older state of it",
                )
                db.add_message("line", "grok", "agent", "same stale record")
            db.add_message("line", "grok", "agent", "normal after")

            history = delivered_history(db, attachment)

            self.assertEqual(history.bodies, ["normal before", "normal after"])
            self.assertEqual(history.legacy_relayed_bodies, ["same stale record"] * 3)

    def test_stale_owner_cannot_mark_a_transcript_record(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Db(f"{directory}/partyline.db")
            self.addCleanup(db.close)
            db.create_conversation("line", "Line")
            attachment = db.add_attachment(
                "att", "line", "grok", "grok", ["grok"], directory, "current"
            )
            db.add_message("line", "grok", "agent", "speech")

            self.assertFalse(mark_transcript_delivery(
                db, attachment, "stale", b"fingerprint", "speech"
            ))
            self.assertEqual(delivered_history(db, attachment).transcript_records, [])
