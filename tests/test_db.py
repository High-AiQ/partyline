import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from partyline.db import Db


class DbTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")

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
        self.db.set_attachment_status("att", "running")
        self.db.set_last_seen("att", 9)
        self.db.set_last_seen("att", 3)
        self.db.set_cli_session("att", "session")
        self.db.mark_stale_attachments()
        attachment = self.db.get_attachment("att")
        self.assertEqual(attachment["status"], "exited")
        self.assertEqual(attachment["last_seen"], 9)
        self.assertEqual(attachment["cli_session"], "session")

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
        self.db.save_restart_plan("line", ["agent"], "continue", mode="automatic")
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
        self.assertIsNone(blocked)
        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed["claim_owner"], "server-two")

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
