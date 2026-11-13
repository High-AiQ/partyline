"""Retiring the legacy captain style preserves existing lines across restarts."""

import tempfile
import unittest
from pathlib import Path

from partyline.db import Db
from partyline.hierarchy import set_parent
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
