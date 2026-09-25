"""The server-owned delivery history passed into resumable adapters."""

import tempfile
import unittest
import asyncio
from datetime import UTC, datetime
import hashlib
import os
from unittest.mock import patch

from fastapi import HTTPException

from partyline.attachment_resume import (
    TranscriptDeliveryRecord,
    delivered_bodies,
    delivered_history,
    mark_transcript_delivery,
)
from partyline.db import Db
from partyline.runtime import ChatRuntime
from partyline.attachment_resume import resume_adapter
from partyline.write_set_routes import add_write_grant
from tests.test_server import FakeAdapter

STARTED_AT = datetime(2026, 9, 25, 10, 14, 52, tzinfo=UTC).timestamp()


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


class AttachmentResumeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("one", "line", "luna", "fake", ["fake"], self.directory.name)
        self.db._exec("UPDATE attachments SET status='exited' WHERE id='one'")
        self.grant = os.path.join(self.directory.name, "granted")
        add_write_grant(self.db, "line", self.grant, "person")
        self.captured = {}

    async def asyncTearDown(self):
        self.db.close()
        self.directory.cleanup()

    def make_adapter(self, _adapter, att, *_args, **_kwargs):
        self.captured["write_grants"] = att.get("write_grants")
        return FakeAdapter(att=att)

    class _Presence:
        def watch(self, adapter, *_args):
            return adapter

        def posting(self, *_args):
            return lambda _body: None

        def statusing(self, *_args, **_kwargs):
            return lambda _status: None

    def resume_arguments(self, make_adapter=None):
        return dict(
            runtime=self.runtime,
            adapter_metadata={"fake": {"capabilities": {"resume": True}}},
            make_adapter=make_adapter or self.make_adapter,
            presence=self._Presence(),
            hook_url=lambda *_args: "hook",
        )

    @patch("partyline.attachment_resume.bind_role_delivery")
    @patch("partyline.attachment_resume.bind_connection_hint")
    @patch("partyline.attachment_resume.provision_connection")
    async def test_resume_adapter_loads_write_grants(self, *_mocks):
        await resume_adapter("one", None, **self.resume_arguments())
        self.assertEqual([row["path"] for row in self.captured["write_grants"]], [self.grant])

    @patch("partyline.attachment_resume.bind_role_delivery")
    @patch("partyline.attachment_resume.bind_connection_hint")
    @patch("partyline.attachment_resume.provision_connection")
    async def test_status_refusal_names_attachment_and_line(self, *_mocks):
        self.db.claim_attachment("one", "live-generation")
        self.db.set_attachment_status("one", "running", "live-generation")
        self.db._exec(
            "UPDATE attachments SET runtime_started_at=? WHERE id='one'", (STARTED_AT,)
        )
        self.runtime.live["one"] = FakeAdapter(att={"runtime_owner": "live-generation"})
        with self.assertRaises(HTTPException) as raised:
            await resume_adapter("one", None, **self.resume_arguments())

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail,
            "attachment 'one' (@luna) on line 'Line' is already live; "
            f"nothing to resume (started 2026-09-25 10:14:52 UTC, generation "
            f"{hashlib.sha256(b'live-generation').hexdigest()[:8]})",
        )

    @patch("partyline.attachment_resume.bind_role_delivery")
    @patch("partyline.attachment_resume.bind_connection_hint")
    @patch("partyline.attachment_resume.provision_connection")
    async def test_claim_refusal_refreshes_same_attachment_liveness(self, *_mocks):
        claim_attachment = self.db.claim_attachment_async

        async def competing_resume(att_id, runtime_owner):
            self.assertTrue(self.db.claim_attachment(att_id, "manual-generation"))
            self.assertTrue(
                self.db.set_attachment_status(att_id, "running", "manual-generation")
            )
            self.db._exec(
                "UPDATE attachments SET runtime_started_at=? WHERE id=?",
                (STARTED_AT, att_id),
            )
            self.runtime.live[att_id] = FakeAdapter(
                att={"runtime_owner": "manual-generation"}
            )
            return await claim_attachment(att_id, runtime_owner)

        self.db.claim_attachment_async = competing_resume
        with self.assertRaises(HTTPException) as raised:
            await resume_adapter("one", None, **self.resume_arguments())

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail,
            "attachment 'one' (@luna) on line 'Line' is already live; "
            f"nothing to resume (started 2026-09-25 10:14:52 UTC, generation "
            f"{hashlib.sha256(b'manual-generation').hexdigest()[:8]})",
        )

    @patch("partyline.attachment_resume.bind_role_delivery")
    @patch("partyline.attachment_resume.bind_connection_hint")
    @patch("partyline.attachment_resume.provision_connection")
    async def test_claim_refusal_identifies_a_different_live_attachment(self, *_mocks):
        claim_attachment = self.db.claim_attachment_async

        async def competing_handle(att_id, runtime_owner):
            self.db.add_attachment(
                "other", "line", "luna", "fake", ["fake"], self.directory.name
            )
            self.db.set_attachment_status("other", "exited", None)
            self.assertTrue(self.db.claim_attachment("other", "other-generation"))
            self.assertTrue(
                self.db.set_attachment_status("other", "running", "other-generation")
            )
            self.db._exec(
                "UPDATE attachments SET runtime_started_at=? WHERE id='other'",
                (STARTED_AT,),
            )
            self.runtime.live["other"] = FakeAdapter(
                att={"runtime_owner": "other-generation"}
            )
            return await claim_attachment(att_id, runtime_owner)

        self.db.claim_attachment_async = competing_handle
        with self.assertRaises(HTTPException) as raised:
            await resume_adapter("one", None, **self.resume_arguments())

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail,
            "cannot resume attachment 'one' (@luna) on line 'Line': handle is already "
            "live as attachment 'other' (@luna) on line 'Line' "
            f"(started 2026-09-25 10:14:52 UTC, generation "
            f"{hashlib.sha256(b'other-generation').hexdigest()[:8]})",
        )

    @patch("partyline.attachment_resume.bind_role_delivery")
    @patch("partyline.attachment_resume.bind_connection_hint")
    @patch("partyline.attachment_resume.provision_connection")
    async def test_concurrent_resumes_only_start_one_attachment(self, *_mocks):
        started = asyncio.Event()
        release = asyncio.Event()
        made = []

        class BlockingAdapter(FakeAdapter):
            async def start(self):
                started.set()
                await release.wait()

        def make_adapter(_adapter, att, *_args, **_kwargs):
            adapter = BlockingAdapter(att=att)
            made.append(adapter)
            return adapter

        arguments = self.resume_arguments(make_adapter)
        first = asyncio.create_task(resume_adapter("one", None, **arguments))
        await started.wait()
        second = asyncio.create_task(resume_adapter("one", None, **arguments))
        await asyncio.sleep(0)
        self.assertEqual(len(made), 1)
        release.set()
        resumed = await first
        with self.assertRaises(HTTPException) as raised:
            await second

        self.assertEqual(len(made), 1)
        self.assertEqual(resumed.adapter, made[0])
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("already live", raised.exception.detail)
        self.assertIn("one", raised.exception.detail)
