"""Explicit local operator adoption is read-only by default and atomic when applied."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.line_management import LineAssignment, Setup, apply, preview


class LineManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "instance.db"
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("CREATE TABLE conversations(id TEXT PRIMARY KEY,name TEXT,"
                         "created_at REAL,archived_at REAL)")
            conn.execute("CREATE TABLE attachments(id TEXT PRIMARY KEY,conv_id TEXT,name TEXT)")
            conn.executemany("INSERT INTO conversations VALUES(?,?,1,NULL)",
                             [("root", "Project"), ("child", "Child"), ("other", "Other")])
            conn.executemany("INSERT INTO attachments VALUES(?,?,?)",
                             [("lead", "root", "manager"), ("child-lead", "child", "manager")])
        self.setup = Setup(lines=[
            LineAssignment(conversation_id="root", parent_id=None, manager_attachment_id="lead"),
            LineAssignment(conversation_id="child", parent_id="root", manager_attachment_id="child-lead"),
        ])

    def test_preview_on_old_schema_does_not_migrate_or_read_credentials(self):
        before = self.path.read_bytes()
        result = preview(self.path, self.setup)
        self.assertEqual(self.path.read_bytes(), before)
        root = next(row for row in result["changes"] if row["conversation_id"] == "root")
        self.assertEqual([row["id"] for row in root["managed_lines"]], ["child", "root"])
        self.assertEqual(root["manager_attachment_id"], "lead")
        self.assertNotIn("token", str(result))

    def test_wrong_line_manager_or_cycle_refuses_before_any_write(self):
        before = self.path.read_bytes()
        bad_manager = Setup(lines=[LineAssignment(conversation_id="root", parent_id=None,
                                                  manager_attachment_id="child-lead")])
        with self.assertRaises(ValueError):
            apply(self.path, bad_manager, "irrelevant")
        cyclic = self.setup.model_copy(deep=True)
        cyclic.lines[0].parent_id = "child"
        with self.assertRaises(ValueError):
            preview(self.path, cyclic)
        self.assertEqual(self.path.read_bytes(), before)

    def test_a_stale_review_refuses_without_migrating(self):
        digest = preview(self.path, self.setup)["sha256"]
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE conversations SET name='Changed identity' WHERE id='root'")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "changed since review"):
            apply(self.path, self.setup, digest)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_database_is_not_created(self):
        missing = self.path.with_name("missing.db")
        with self.assertRaises(sqlite3.Error):
            preview(missing, self.setup)
        self.assertFalse(missing.exists())

    def test_duplicate_lines_and_missing_parents_are_rejected(self):
        duplicate = Setup(lines=[self.setup.lines[0], self.setup.lines[0]])
        with self.assertRaises(ValueError):
            preview(self.path, duplicate)
        missing = self.setup.model_copy(deep=True)
        missing.lines[1].parent_id = "absent"
        with self.assertRaises(ValueError):
            preview(self.path, missing)


class CurrentSchemaAdoptionTests(unittest.TestCase):
    def test_apply_changes_only_explicit_roles_and_parents(self):
        from partyline.db import Db
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instance.db"
            db = Db(path)
            for ident in ("root", "child", "other"):
                db.create_conversation(ident, ident)
                db.add_attachment(ident + "-lead", ident, "manager", "codex", ["codex"], directory)
            db.close()
            setup = Setup(lines=[
                LineAssignment(conversation_id="root", parent_id=None, manager_attachment_id="root-lead"),
                LineAssignment(conversation_id="child", parent_id="root", manager_attachment_id="child-lead"),
            ])
            digest = preview(path, setup)["sha256"]
            apply(path, setup, digest)
            db = Db(path)
            try:
                self.assertEqual(db.get_conversation("child")["parent_id"], "root")
                self.assertTrue(db.get_attachment("root-lead")["is_lead"])
                self.assertTrue(db.get_attachment("child-lead")["is_lead"])
                self.assertFalse(db.get_attachment("other-lead")["is_lead"])
                self.assertIsNone(db.get_conversation("other")["parent_id"])
            finally:
                db.close()
