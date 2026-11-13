"""Retiring the legacy captain style preserves existing lines across restarts."""

import tempfile
import unittest
from pathlib import Path

from partyline.db import Db
from partyline.conversation_contracts import ConversationResponse
from partyline.hierarchy import create_child_conversation, set_parent
from partyline.role_delivery import _instructions, current_role


class RetireManagerModeTest(unittest.TestCase):
    def test_migration_is_idempotent_and_existing_captains_get_the_orchestrator_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db.sqlite'
            db = Db(path)
            db.create_conversation('root', 'Root', captain_mode='manager_tree')
            db.create_conversation('child', 'Child', captain_mode='manager_tree')
            set_parent(db, 'child', 'root')
            db.add_attachment('captain', 'root', 'captain', 'fake', ['fake'], directory, 'owner')
            db._exec("UPDATE attachments SET is_lead=1,status='running' WHERE id='captain'")
            # Reproduce the legacy column default as well as its data.
            db.conn.execute('PRAGMA writable_schema=ON')
            db.conn.execute("UPDATE sqlite_schema SET sql=replace(sql, \"DEFAULT 'orchestrator'\", "
                            "\"DEFAULT 'manager_tree'\") WHERE name='conversations' AND type='table'")
            db.conn.execute('PRAGMA writable_schema=RESET')
            db.conn.commit()
            db.close()
            for _ in range(2):
                db = Db(path)
                self.assertEqual(db.get_conversation('root')['captain_mode'], 'orchestrator')
                self.assertEqual(db.get_conversation('child')['captain_mode'], 'orchestrator')
                self.assertEqual(db.get_conversation('child')['parent_id'], 'root')
                self.assertIn('Orchestrator captain pack', _instructions(current_role(db, 'captain'), db))
                db.conn.execute("INSERT OR IGNORE INTO conversations(id,name,created_at) "
                                "VALUES('new','New',0)")
                self.assertEqual(db.get_conversation('new')['captain_mode'], 'orchestrator')
                db.close()

    def test_child_creation_does_not_depend_on_the_column_default(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Db(Path(directory) / 'db.sqlite')
            self.addCleanup(db.close)
            db.create_conversation('root', 'Root')
            # Simulate a SQLite build that declined the writable_schema rewrite.
            db.conn.execute('PRAGMA writable_schema=ON')
            db.conn.execute("UPDATE sqlite_schema SET sql=replace(sql, \"DEFAULT 'orchestrator'\", "
                            "\"DEFAULT 'manager_tree'\") WHERE name='conversations' AND type='table'")
            db.conn.execute('PRAGMA writable_schema=RESET')
            db.conn.execute("INSERT INTO conversations(id,name,created_at) VALUES('probe','Probe',0)")
            self.assertEqual(db.get_conversation('probe')['captain_mode'], 'manager_tree')
            self.assertEqual(db.create_conversation('new-root', 'New root')['captain_mode'], 'orchestrator')
            child = create_child_conversation(db, 'root', 'child', 'Child')
            self.assertEqual(child['captain_mode'], 'orchestrator')
            self.assertEqual(ConversationResponse.model_validate(child).captain_mode, 'orchestrator')
