import asyncio
from contextlib import contextmanager
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from partyline.db import Db


class DbTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = f"{self.directory.name}/partyline.db"
        self.db = Db(self.db_path)

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def test_conversation_lifecycle_and_message_ordering(self):
        self.db.create_conversation("first", "First")
        self.db.create_conversation("second", "Second")
        self.assertEqual([c["id"] for c in self.db.list_conversations()], ["second", "first"])

        one = self.db.add_message("first", "a", "human", "one")
        two = self.db.add_message("first", "b", "agent", "two")
        self.assertEqual(self.db.messages_after("first", one["id"]), [two])
        self.assertEqual(self.db.messages_after("first", 0, exclude_sender="a"), [two])

        self.db.archive_conversation("first")
        self.assertEqual([c["id"] for c in self.db.list_conversations()], ["second"])
        self.assertEqual([c["id"] for c in self.db.list_conversations(archived=True)], ["first"])
        self.db.restore_conversation("first")
        self.assertIsNone(self.db.get_conversation("first")["archived_at"])

    def test_attachments_sessions_and_stale_marking(self):
        self.db.create_conversation("line", "Line")
        attachment = self.db.add_attachment("att", "line", "terra", "fake", ["fake"], "/tmp")
        self.assertEqual(attachment["command"], ["fake"])
        self.db.set_attachment_status("att", "running", None)
        self.assertTrue(self.db.set_last_seen("att", 9, None))
        self.assertTrue(self.db.set_last_seen("att", 3, None))
        self.db.set_cli_session("att", "session", None)
        self.db.mark_stale_attachments()
        attachment = self.db.get_attachment("att")
        self.assertEqual(attachment["status"], "exited")
        self.assertEqual(attachment["last_seen"], 9)
        self.assertEqual(attachment["cli_session"], "session")

    def test_command_changes_only_while_the_attachment_is_inactive(self):
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("att", "line", "terra", "fake", ["old"], "/tmp")
        self.db.set_attachment_status("att", "exited", None)

        changed = asyncio.run(
            self.db.update_inactive_attachment_command("att", ["new", "two words"])
        )
        self.assertEqual(changed["command"], ["new", "two words"])

        self.assertTrue(self.db.claim_attachment("att", "new-generation"))
        refused = asyncio.run(
            self.db.update_inactive_attachment_command("att", ["must-not-land"])
        )
        self.assertIsNone(refused)
        self.assertEqual(self.db.get_attachment("att")["command"], ["new", "two words"])

    def test_new_activation_rejects_an_old_server_shutdown_write(self):
        self.db.create_conversation("line", "Line")
        self.db.add_attachment(
            "att", "line", "opus", "fake", ["fake"], "/tmp", "old-generation"
        )
        self.assertTrue(
            self.db.set_attachment_status("att", "running", "old-generation")
        )

        replacement = Db(self.db_path)
        try:
            replacement.mark_stale_attachments()
            self.assertTrue(replacement.claim_attachment("att", "new-generation"))
            self.assertTrue(
                replacement.set_attachment_status("att", "running", "new-generation")
            )

            # The old lifespan releases its port before adapter shutdown is
            # complete. Its late stop callback must not detach the new process.
            self.assertFalse(
                self.db.set_attachment_status("att", "detached", "old-generation")
            )
            self.assertFalse(
                self.db.set_cli_session("att", "stale-session", "old-generation")
            )
            self.assertFalse(self.db.set_last_seen("att", 11, "old-generation"))
            self.assertIsNone(
                self.db.add_owned_message(
                    "att",
                    "old-generation",
                    "line",
                    "opus",
                    "agent",
                    "stale output",
                )
            )
            self.assertIsNone(
                self.db.detach_attachment_with_message(
                    "att", "old-generation", "@opus detached"
                )
            )
            attachment = replacement.get_attachment("att")
            self.assertEqual(attachment["status"], "running")
            self.assertEqual(attachment["runtime_owner"], "new-generation")
            self.assertIsNone(attachment["cli_session"])
            self.assertEqual(attachment["last_seen"], 0)
            self.assertEqual(replacement.list_messages("line"), [])

            owned_message = replacement.add_owned_message(
                "att",
                "new-generation",
                "line",
                "opus",
                "agent",
                "current output",
            )
            self.assertIsNotNone(owned_message)

            self.assertTrue(
                replacement.set_attachment_status("att", "exited", "new-generation")
            )
            message = replacement.detach_attachment_with_message(
                "att", "new-generation", "@opus detached"
            )
            self.assertIsNotNone(message)
            self.assertEqual(replacement.get_attachment("att")["status"], "detached")
            self.assertEqual(
                replacement.list_messages("line"), [owned_message, message]
            )
        finally:
            replacement.close()

    def test_delivery_reservation_releases_after_an_exception(self):
        self.db.create_conversation("line", "Line")
        self.db.add_attachment(
            "att", "line", "opus", "fake", ["fake"], "/tmp", "old-generation"
        )

        async def fail_during_delivery():
            async with self.db.reserve_attachment_delivery(
                "att", "old-generation"
            ) as reserved:
                self.assertTrue(reserved)
                raise RuntimeError("delivery failed")

        with self.assertRaisesRegex(RuntimeError, "delivery failed"):
            asyncio.run(fail_during_delivery())

        replacement = Db(self.db_path)
        try:
            replacement.mark_stale_attachments()
            self.assertTrue(replacement.claim_attachment("att", "new-generation"))
        finally:
            replacement.close()

    def test_cancelled_delivery_wait_does_not_leak_the_runtime_lock(self):
        self.db.create_conversation("line", "Line")
        self.db.add_attachment(
            "att", "line", "opus", "fake", ["fake"], "/tmp", "old-generation"
        )
        contender = Db(self.db_path)

        async def contend_then_cancel():
            async with self.db.reserve_attachment_delivery(
                "att", "old-generation"
            ) as reserved:
                self.assertTrue(reserved)

                async def wait_for_same_lock():
                    async with contender.reserve_attachment_delivery(
                        "att", "old-generation"
                    ):
                        self.fail("a second reservation crossed the held lock")

                waiting = asyncio.create_task(wait_for_same_lock())
                await asyncio.sleep(0.02)
                waiting.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await waiting

        try:
            asyncio.run(contend_then_cancel())
            contender.mark_stale_attachments()
            self.assertTrue(contender.claim_attachment("att", "new-generation"))
        finally:
            contender.close()

    def test_atomic_detach_cannot_cross_an_active_delivery_reservation(self):
        self.db.create_conversation("line", "Line")
        self.db.add_attachment(
            "att", "line", "opus", "fake", ["fake"], "/tmp", "old-generation"
        )
        self.assertTrue(
            self.db.set_attachment_status("att", "exited", "old-generation")
        )
        contender = Db(self.db_path)
        lock_attempted = threading.Event()
        transition_finished = threading.Event()
        original_guard = contender._runtime_serialized

        @contextmanager
        def signalled_guard():
            lock_attempted.set()
            with original_guard():
                yield

        contender._runtime_serialized = signalled_guard

        def detach_then_claim():
            message = contender.detach_attachment_with_message(
                "att", "old-generation", "@opus detached"
            )
            self.assertIsNotNone(message)
            self.assertTrue(contender.claim_attachment("att", "new-generation"))
            transition_finished.set()

        async def reserve_while_detach_starts():
            async with self.db.reserve_attachment_delivery(
                "att", "old-generation"
            ) as reserved:
                self.assertTrue(reserved)
                transition = asyncio.create_task(asyncio.to_thread(detach_then_claim))
                await asyncio.to_thread(lock_attempted.wait)
                await asyncio.sleep(0.02)
                self.assertFalse(transition_finished.is_set())
            await transition

        try:
            asyncio.run(reserve_while_detach_starts())
            current = contender.get_attachment("att")
            self.assertEqual(current["runtime_owner"], "new-generation")
            self.assertEqual(current["status"], "starting")
        finally:
            contender.close()

    def test_detach_rolls_back_when_its_notice_cannot_be_persisted(self):
        self.db.create_conversation("line", "Line")
        self.db.add_attachment(
            "att", "line", "opus", "fake", ["fake"], "/tmp", "generation"
        )
        self.assertTrue(self.db.set_attachment_status("att", "exited", "generation"))
        self.db._exec(
            "CREATE TRIGGER reject_detach_notice BEFORE INSERT ON messages "
            "BEGIN SELECT RAISE(ABORT, 'notice rejected'); END"
        )

        with self.assertRaisesRegex(sqlite3.IntegrityError, "notice rejected"):
            self.db.detach_attachment_with_message(
                "att", "generation", "@opus detached"
            )

        self.assertEqual(self.db.get_attachment("att")["status"], "exited")
        self.assertEqual(self.db.list_messages("line"), [])

    def test_presets_upsert_and_delete(self):
        self.db.save_preset("one", "Zebra", "z", "fake", "run")
        self.db.save_preset("two", "Alpha", "a", "fake", "")
        self.db.save_preset("one", "Beta", "b", "fake", "new")
        self.assertEqual([p["title"] for p in self.db.list_presets()], ["Alpha", "Beta"])
        self.assertEqual(self.db.get_preset("one")["command"], "new")
        self.db.delete_preset("one")
        self.assertIsNone(self.db.get_preset("one"))

    def test_delete_conversation_removes_related_rows(self):
        self.db.create_conversation("line", "Line")
        self.db.add_message("line", "a", "human", "hello")
        self.db.add_attachment("att", "line", "terra", "fake", [], "/tmp")
        self.db.delete_conversation("line")
        self.assertIsNone(self.db.get_conversation("line"))
        self.assertEqual(self.db.list_messages("line"), [])
        self.assertEqual(self.db.list_attachments("line"), [])

    def test_restart_plan_replaces_the_single_pending_plan_and_preserves_order(self):
        first = self.db.save_restart_plan("one", ["old-2", "old-1"], "first debrief")
        replacement = self.db.save_restart_plan("two", ["new-1", "new-2"], "second debrief")

        self.assertEqual(first["attachment_ids"], ["old-2", "old-1"])
        self.assertEqual(replacement["conversation_id"], "two")
        self.assertNotEqual(first["token"], replacement["token"])
        self.assertEqual(replacement["mode"], "offer")
        self.assertEqual(replacement["attachment_ids"], ["new-1", "new-2"])
        self.assertEqual(replacement["debrief"], "second debrief")
        self.assertEqual(self.db.get_restart_plan(), replacement)

    def test_take_restart_plan_consumes_it_once(self):
        self.db.save_restart_plan("line", ["first", "second"], "continue from here")
        plan = self.db.get_restart_plan()

        self.assertIsNotNone(plan)
        self.assertIsNone(self.db.take_restart_plan("other-line", plan["token"], "offer"))
        self.assertIsNone(self.db.take_restart_plan("line", "stale-token", "offer"))
        self.assertIsNone(self.db.take_restart_plan("line", plan["token"], "automatic"))
        self.assertEqual(self.db.take_restart_plan("line", plan["token"], "offer"), plan)
        self.assertIsNone(self.db.get_restart_plan())
        self.assertIsNone(self.db.take_restart_plan("line", plan["token"], "offer"))

    def test_automatic_restart_plan_requires_automatic_take(self):
        plan = self.db.save_restart_plan("line", ["agent"], "continue", mode="automatic")

        self.assertEqual(plan["mode"], "automatic")
        self.assertIsNone(self.db.take_restart_plan("line", plan["token"], "offer"))
        self.assertEqual(self.db.take_restart_plan("line", plan["token"], "automatic"), plan)

    def test_restart_plan_claim_excludes_a_second_owner_until_expiry(self):
        plan = self.db.save_restart_plan("line", ["agent"], "continue", mode="automatic")
        self.assertEqual(plan["attempt_count"], 0)
        second_lifespan = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(second_lifespan.close)
        with patch("partyline.db.time.time", return_value=10.0):
            claimed = self.db.claim_restart_plan("automatic", "server-one", 5)
            blocked = second_lifespan.claim_restart_plan("automatic", "server-two", 5)
        with patch("partyline.db.time.time", return_value=15.0):
            reclaimed = second_lifespan.claim_restart_plan("automatic", "server-two", 5)

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["claim_owner"], "server-one")
        self.assertEqual(claimed["claim_until"], 15.0)
        self.assertEqual(claimed["attempt_count"], 1)
        self.assertIsNone(blocked)
        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed["claim_owner"], "server-two")
        self.assertEqual(reclaimed["attempt_count"], 2)

    def test_manual_claim_does_not_count_as_an_automatic_recovery_attempt(self):
        self.db.save_restart_plan("line", ["agent"], "continue", mode="offer")

        claimed = self.db.claim_restart_plan("offer", "server-one", 5)

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["attempt_count"], 0)

    def test_restart_plan_claim_requires_the_exact_owner_to_renew_or_release(self):
        self.db.save_restart_plan("line", ["agent"], "continue", mode="automatic")
        with patch("partyline.db.time.time", return_value=10.0):
            claimed = self.db.claim_restart_plan("automatic", "server-one", 5)
        self.assertIsNotNone(claimed)

        with patch("partyline.db.time.time", return_value=11.0):
            self.assertFalse(self.db.renew_restart_plan_claim(claimed["token"], "server-two", 10))
            self.assertFalse(self.db.release_restart_plan_claim(claimed["token"], "server-two"))
            self.assertTrue(self.db.renew_restart_plan_claim(claimed["token"], "server-one", 10))
        with patch("partyline.db.time.time", return_value=21.0):
            self.assertFalse(self.db.renew_restart_plan_claim(claimed["token"], "server-one", 10))

        plan = self.db.get_restart_plan()
        self.assertIsNotNone(plan)
        self.assertEqual(plan["claim_until"], 21.0)
        self.assertTrue(self.db.release_restart_plan_claim(claimed["token"], "server-one"))
        self.assertIsNone(self.db.get_restart_plan()["claim_owner"])
        self.assertIsNotNone(self.db.claim_restart_plan("automatic", "server-two", 5))

    def test_replacing_a_plan_clears_its_lease(self):
        original = self.db.save_restart_plan("line", ["agent"], "continue", mode="automatic")
        with patch("partyline.db.time.time", return_value=10.0):
            self.assertIsNotNone(self.db.claim_restart_plan("automatic", "server-one", 5))

        replacement = self.db.save_restart_plan("line", ["replacement"], "new debrief", mode="automatic")

        self.assertIsNone(replacement["claim_owner"])
        self.assertIsNone(replacement["claim_until"])
        self.assertEqual(replacement["attempt_count"], 0)
        self.assertFalse(self.db.renew_restart_plan_claim(original["token"], "server-one", 5))
        self.assertFalse(self.db.release_restart_plan_claim(original["token"], "server-one"))
        self.assertFalse(self.db.complete_restart_plan(original["token"], "server-one"))

    def test_restart_plan_completion_requires_an_automatic_plan_held_by_its_owner(self):
        automatic = self.db.save_restart_plan("line", ["agent"], "continue", mode="automatic")
        with patch("partyline.db.time.time", return_value=10.0):
            self.assertIsNotNone(self.db.claim_restart_plan("automatic", "server-one", 5))
            self.assertFalse(self.db.complete_restart_plan(automatic["token"], "server-two"))
            self.assertTrue(self.db.complete_restart_plan(automatic["token"], "server-one"))
        self.assertIsNone(self.db.get_restart_plan())

        manual = self.db.save_restart_plan("line", ["agent"], "continue", mode="offer")
        with patch("partyline.db.time.time", return_value=20.0):
            self.assertIsNotNone(self.db.claim_restart_plan("offer", "server-one", 5))
            self.assertFalse(self.db.complete_restart_plan(manual["token"], "server-one"))

    def test_restart_plan_survives_a_database_reopen(self):
        self.db.save_restart_plan("line", ["agent"], "continue")
        self.db.close()
        self.db = Db(f"{self.directory.name}/partyline.db")

        plan = self.db.get_restart_plan()

        self.assertIsNotNone(plan)
        self.assertEqual(plan["conversation_id"], "line")
        self.assertEqual(plan["attachment_ids"], ["agent"])
        self.assertEqual(plan["debrief"], "continue")

    def test_deleting_planned_conversation_clears_restart_plan(self):
        self.db.create_conversation("line", "Line")
        self.db.save_restart_plan("line", ["agent"], "continue")

        self.db.delete_conversation("line")

        self.assertIsNone(self.db.get_restart_plan())

    def test_existing_restart_plan_migrates_to_manual_offer(self):
        legacy_path = f"{self.directory.name}/legacy.db"
        legacy = sqlite3.connect(legacy_path)
        legacy.execute(
            "CREATE TABLE restart_plan("
            "singleton INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL, token TEXT NOT NULL,"
            "attachment_ids TEXT NOT NULL, debrief TEXT NOT NULL, created_at REAL NOT NULL)"
        )
        legacy.execute(
            "INSERT INTO restart_plan VALUES(1, 'line', 'token', '[\"agent\"]', 'continue', 1.0)"
        )
        legacy.commit()
        legacy.close()
        migrated = Db(legacy_path)
        self.addCleanup(migrated.close)

        plan = migrated.get_restart_plan()

        self.assertIsNotNone(plan)
        self.assertEqual(plan["mode"], "offer")
