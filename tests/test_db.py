import tempfile
import unittest

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
        self.assertEqual(replacement["attachment_ids"], ["new-1", "new-2"])
        self.assertEqual(replacement["debrief"], "second debrief")
        self.assertEqual(self.db.get_restart_plan(), replacement)

    def test_take_restart_plan_consumes_it_once(self):
        self.db.save_restart_plan("line", ["first", "second"], "continue from here")
        plan = self.db.get_restart_plan()

        self.assertIsNotNone(plan)
        self.assertEqual(self.db.take_restart_plan(), plan)
        self.assertIsNone(self.db.get_restart_plan())
        self.assertIsNone(self.db.take_restart_plan())

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
