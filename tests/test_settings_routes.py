"""Round trips and empty-value behavior for instance settings."""

import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline.auth_guard import install_auth_guard
from partyline.auth_store import create_user, ensure_api_token
from partyline.auth_tokens import create_access_token, hash_password, signing_secret
from partyline.db import Db
from partyline.runtime import ChatRuntime
from partyline.settings_routes import settings_router


class SettingsRoutesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(settings_router(self.runtime))
        self.client = TestClient(app)
        user = create_user(self.db, "test@example.com", "tester", hash_password("hunter2222"))
        self.headers = {
            "Authorization": "Bearer "
            + create_access_token(signing_secret(self.db), user["id"])
        }
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("machine", "line", "worker", "fake", ["run"], "/tmp")
        self.machine_headers = {
            "Authorization": "Bearer " + ensure_api_token(self.db, "machine")
        }

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def test_get_put_and_whitespace_reset(self):
        path = "/api/settings/global_prose"
        self.assertEqual(401, self.client.get(path).status_code)
        self.assertEqual(403, self.client.get(path, headers=self.machine_headers).status_code)
        self.assertEqual(
            403,
            self.client.put(path, json={"value": "no"}, headers=self.machine_headers).status_code,
        )
        self.assertEqual({"value": None}, self.client.get(path, headers=self.headers).json())
        prose = "Keep {id}, {{braces}}, and %s intact."
        saved = self.client.put(path, json={"value": prose}, headers=self.headers)
        self.assertEqual({"value": prose}, saved.json())
        self.assertEqual(prose, self.client.get(path, headers=self.headers).json()["value"])
        for value in ("", "  \n \t", None):
            cleared = self.client.put(path, json={"value": value}, headers=self.headers)
            self.assertEqual({"value": None}, cleared.json())
            self.assertIsNone(self.db.get_setting("global_prose"))

    def test_value_length_is_bounded(self):
        response = self.client.put(
            "/api/settings/global_prose", json={"value": "x" * 10001}, headers=self.headers,
        )
        self.assertEqual(422, response.status_code)
