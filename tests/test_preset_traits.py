"""Append-only preset traits: migration, defaults, round trips, conservative matching."""

import tempfile
import unittest
from contextlib import closing

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline.db import Db
from partyline.preset_contracts import PresetIn
from partyline.preset_routes import presets_router
from partyline.preset_traits import match_preset
from partyline.runtime import ChatRuntime


class PresetTraitTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        app.include_router(presets_router(self.runtime, {"fake": object(), "raw": object()}))
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def test_migration_defaults_on_legacy_rows(self):
        names = {row[1] for row in self.db._exec("PRAGMA table_info(presets)").fetchall()}
        self.assertTrue({"reads_images", "can_manage", "implements", "emitter"} <= names)
        self.db._exec(
            "INSERT INTO presets(id,title,name,adapter,command,created_at)"
            " VALUES(?,?,?,?,?,?)",
            ("legacy", "Old", "old", "fake", "run", 1.0),
        )
        row = self.db.get_preset("legacy")
        self.assertEqual(row["reads_images"], 0)
        self.assertEqual(row["can_manage"], 0)
        self.assertEqual(row["implements"], 1)
        self.assertEqual(row["emitter"], 0)

    def test_omitted_writes_use_defaults_and_round_trip(self):
        created = self.client.post(
            "/api/presets",
            json={"title": "Worker", "name": "grok", "adapter": "fake", "command": "run"},
        ).json()
        self.assertFalse(created["reads_images"])
        self.assertFalse(created["can_manage"])
        self.assertTrue(created["implements"])
        listed = self.client.get("/api/presets").json()
        self.assertEqual(listed[0]["implements"], True)
        explicit = self.client.put(
            f"/api/presets/{created['id']}",
            json={
                "title": "Worker",
                "name": "grok",
                "adapter": "fake",
                "command": "run",
                "reads_images": True,
                "can_manage": True,
                "implements": False,
            },
        ).json()
        self.assertTrue(explicit["reads_images"])
        self.assertTrue(explicit["can_manage"])
        self.assertFalse(explicit["implements"])
        retained = self.client.put(
            f"/api/presets/{created['id']}",
            json={"title": "Worker", "name": "grok", "adapter": "fake", "command": "run"},
        ).json()
        self.assertTrue(retained["reads_images"])
        self.assertTrue(retained["can_manage"])
        self.assertFalse(retained["implements"])

    def test_pydantic_omitted_fields_are_defaults(self):
        body = PresetIn(title="t", name="n")
        self.assertFalse(body.reads_images)
        self.assertFalse(body.can_manage)
        self.assertTrue(body.implements)
        self.assertFalse(body.emitter)

    def test_raw_legacy_rows_migrate_and_raw_edits_normalize(self):
        self.db._exec(
            "INSERT INTO presets(id,title,name,adapter,command,created_at,reads_images,can_manage)"
            " VALUES('legacy','Old','old','raw','run',1,1,1)"
        )
        expected = {"reads_images": False, "can_manage": False, "implements": False, "emitter": True}
        self.assertEqual({key: self.client.get("/api/presets").json()[0][key] for key in expected}, expected)
        with closing(Db(self.db.path)) as migrated:
            self.assertEqual({key: migrated.get_preset("legacy")[key] for key in expected}, expected)
        edited = self.client.put("/api/presets/legacy", json={
            "title": "Renamed", "name": "old", "emitter": False, "implements": True,
        })
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["adapter"], "raw")
        self.assertEqual(edited.json()["command"], "run")
        self.assertEqual({key: edited.json()[key] for key in expected}, expected)
        changed = self.client.put("/api/presets/legacy", json={
            "title": "Switched", "name": "old", "adapter": "fake",
        }).json()
        self.assertFalse(changed["emitter"])
        self.assertTrue(changed["implements"])

    def test_optional_emitter_clears_inherited_traits_and_rejects_explicit_conflicts(self):
        payload = {"title": "Monitor", "name": "monitor", "adapter": "fake", "command": "run"}
        for flag in ("reads_images", "can_manage", "implements"):
            response = self.client.post("/api/presets", json={**payload, "emitter": True, flag: True})
            self.assertEqual(response.status_code, 422, response.text)
        created = self.client.post("/api/presets", json={
            **payload, "reads_images": True, "can_manage": True, "implements": True,
        }).json()
        path = f"/api/presets/{created['id']}"
        enabled = self.client.put(path, json={**payload, "emitter": True}).json()
        self.assertTrue(enabled["emitter"])
        for flag in ("reads_images", "can_manage", "implements"):
            self.assertFalse(enabled[flag])
            self.assertEqual(self.client.put(path, json={**payload, flag: True}).status_code, 422)
        self.assertTrue(self.client.put(path, json=payload).json()["emitter"])
        disabled = self.client.put(path, json={**payload, "emitter": False, "implements": True}).json()
        self.assertFalse(disabled["emitter"])
        self.assertTrue(disabled["implements"])

    def test_match_requires_unique_handle_adapter_and_command(self):
        presets = [
            {"id": "a", "name": "grok", "adapter": "fake", "command": "run", "title": "A"},
            {"id": "b", "name": "grok", "adapter": "fake", "command": "run", "title": "B"},
        ]
        att = {"name": "grok", "adapter": "fake", "command": ["run"]}
        self.assertIsNone(match_preset(att, presets))
        self.assertEqual(
            match_preset(att, presets[:1])["id"], "a",
        )
        # a numbered handle matches its base preset (5.3): the instances of a
        # preset are counted, not hidden. Two presets whose names both match
        # one handle stay ambiguous and match nothing.
        self.assertEqual(
            match_preset(
                {"name": "grok-2", "adapter": "fake", "command": ["run"]},
                presets[:1])["id"],
            "a",
        )
        self.assertIsNone(match_preset(
            {"name": "grok-2", "adapter": "fake", "command": ["run"]}, presets))
        self.assertIsNone(match_preset(
            {"name": "grok", "adapter": "fake", "command": ["other"]}, presets[:1]))
        self.assertIsNone(match_preset(
            {"name": "grok", "adapter": "other", "command": ["run"]}, presets[:1]))

    def test_malformed_preset_command_is_unmatched(self):
        presets = [
            {"id": "a", "name": "grok", "adapter": "fake", "command": '"', "title": "A"},
        ]
        self.assertIsNone(match_preset(
            {"name": "grok", "adapter": "fake", "command": ["run"]}, presets))
