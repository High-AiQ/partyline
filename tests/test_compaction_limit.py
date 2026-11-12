"""The compaction-limit setting, its per-preset override and the briefings it adds."""

import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import compaction_limit
from partyline.adapters.briefing import fresh_checkpoint_briefing
from partyline.auth_guard import install_auth_guard
from partyline.auth_store import create_user, ensure_api_token
from partyline.auth_tokens import create_access_token, hash_password, signing_secret
from partyline.db import Db
from partyline.line_notes import NUDGE, write_notes
from partyline.preset_routes import presets_router
from partyline.rebrief import render_rebrief
from partyline.runtime import ChatRuntime
from partyline.settings_routes import settings_router


class LimitSettingTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(settings_router(self.runtime))
        app.include_router(presets_router(self.runtime, {"fake": object()}))
        self.client = TestClient(app)
        user = create_user(self.db, "test@example.com", "tester", hash_password("hunter2222"))
        self.headers = {"Authorization": "Bearer "
                        + create_access_token(signing_secret(self.db), user["id"])}
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("machine", "line", "worker", "fake", ["run"], "/tmp")
        self.machine = {"Authorization": "Bearer " + ensure_api_token(self.db, "machine")}

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def test_the_default_is_two_and_people_can_change_it(self):
        path = "/api/settings/max_compactions"
        self.assertEqual(401, self.client.get(path).status_code)
        self.assertEqual(403, self.client.get(path, headers=self.machine).status_code)
        self.assertEqual(403, self.client.put(path, json={"value": 1}, headers=self.machine).status_code)
        self.assertEqual({"value": 2}, self.client.get(path, headers=self.headers).json())
        self.assertEqual({"value": 3}, self.client.put(path, json={"value": 3}, headers=self.headers).json())
        self.assertEqual(3, compaction_limit.global_limit(self.db))
        self.assertEqual({"value": 0}, self.client.put(path, json={"value": 0}, headers=self.headers).json())
        self.assertEqual(0, compaction_limit.global_limit(self.db))  # 0 is a value, not 'unset'
        for bad in (-1, 21, "x", None):
            rejected = self.client.put(path, json={"value": bad}, headers=self.headers)
            self.assertEqual(422, rejected.status_code)

    def test_a_garbled_stored_value_falls_back_to_the_default(self):
        self.db.set_setting(compaction_limit.SETTING, "many")
        self.assertEqual(compaction_limit.DEFAULT_LIMIT, compaction_limit.global_limit(self.db))
        self.db.set_setting(compaction_limit.SETTING, "999")
        self.assertEqual(compaction_limit.LIMIT_CEILING, compaction_limit.global_limit(self.db))
        self.assertEqual(0, compaction_limit.global_limit(object()))  # a minimal fake db

    def preset(self, **extra):
        body = {"title": "Worker", "name": "grok", "adapter": "fake", "command": "run", **extra}
        return body

    def test_a_preset_override_round_trips_and_is_kept_when_omitted(self):
        created = self.client.post("/api/presets", json=self.preset(), headers=self.headers).json()
        self.assertIsNone(created["max_compactions"])
        saved = self.client.put(f"/api/presets/{created['id']}",
                                json=self.preset(max_compactions=0, max_instances=3,
                                                 auto_compact_tokens=500000),
                                headers=self.headers).json()
        self.assertEqual((saved["max_compactions"], saved["max_instances"]), (0, 3))
        # an edit that never mentions the knobs (the Settings form) must not reset them
        edited = self.client.put(f"/api/presets/{created['id']}",
                                 json=self.preset(title="Renamed", can_manage=True),
                                 headers=self.headers).json()
        self.assertEqual((edited["max_compactions"], edited["max_instances"],
                          edited["auto_compact_tokens"]), (0, 3, 500000))
        cleared = self.client.put(f"/api/presets/{created['id']}",
                                  json=self.preset(max_compactions=None), headers=self.headers).json()
        self.assertIsNone(cleared["max_compactions"])
        self.assertEqual(self.client.put(f"/api/presets/{created['id']}",
                                         json=self.preset(max_compactions=99),
                                         headers=self.headers).status_code, 422)

    def test_limit_for_resolves_the_recorded_preset_then_the_instance_setting(self):
        self.db.save_preset("p1", "Builder", "builder", "fake", "run", max_compactions=5)
        self.db.save_preset("p2", "Other", "other", "fake", "run")
        att = self.db.get_attachment("machine")
        self.assertEqual(compaction_limit.limit_for(self.db, att), 2)  # command is ambiguous
        self.db._exec("UPDATE attachments SET preset='builder' WHERE id='machine'")
        att = self.db.get_attachment("machine")
        self.assertEqual(compaction_limit.limit_for(self.db, att), 5)
        self.db._exec("UPDATE presets SET max_compactions=0 WHERE name='builder'")
        self.assertEqual(compaction_limit.limit_for(self.db, att), 0)  # explicit 0 is respected
        self.db._exec("UPDATE presets SET max_compactions=NULL WHERE name='builder'")
        self.db.set_setting(compaction_limit.SETTING, "7")
        self.assertEqual(compaction_limit.limit_for(self.db, att), 7)
        self.assertEqual(compaction_limit.limit_for(object(), att), 0)

    def test_the_migration_runs_twice(self):
        from partyline.auto_compact_schema import MIGRATIONS

        import sqlite3

        for statement in MIGRATIONS:
            with self.assertRaises(sqlite3.OperationalError):  # already applied at open
                self.db._exec(statement)
        self.assertEqual(self.db.get_attachment("machine")["session_pin"], None)

    def test_every_rebrief_asks_for_the_note_with_its_contents(self):
        att = self.db.get_attachment("machine")
        text = render_rebrief(self.db, att)
        self.assertIn("Update your attachment notes now", text)
        for word in ("state", "decisions made", "next step", "SHAs", "4000", "notes tool"):
            self.assertIn(word, NUDGE)
        self.assertTrue(text.endswith("notes?scope=attachment"))

    def test_a_handoff_rebrief_leads_with_the_predecessors_note(self):
        write_notes(self.db, "line", "attachment", "MY HANDOFF", "machine")
        write_notes(self.db, "line", "line", "LINE CHARGE", "")
        att = self.db.get_attachment("machine")
        text = render_rebrief(self.db, att, reason="rotated after 3 compactions", handoff=True)
        self.assertIn("replacing the previous @worker: rotated after 3 compactions", text)
        self.assertIn("continue from its next step", text)
        self.assertLess(text.index("MY HANDOFF"), text.index("LINE CHARGE"))
        plain = render_rebrief(self.db, att, reason="because")
        self.assertLess(plain.index("LINE CHARGE"), plain.index("MY HANDOFF"))

    def test_a_rotated_instance_continues_instead_of_waiting_for_a_mention(self):
        waiting = fresh_checkpoint_briefing("intro", {"fresh_checkpoint": "state"})
        self.assertIn("wait for the first @mention", waiting)
        going = fresh_checkpoint_briefing(
            "intro", {"fresh_checkpoint": "state", "fresh_resume_now": True})
        self.assertIn("continue the work now", going)
        self.assertNotIn("wait for the first @mention", going)
        self.assertIn("state", going)
