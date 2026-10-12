import os
import tempfile
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from partyline import auth_store, auth_tokens, docker_relay
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.docker_relay_routes import register_docker_relay_routes


class DockerRelayStatusTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for patcher in (
                patch.object(docker_relay, "RELAY_ROOT", os.path.join(self.tmp.name, "d")),
                patch.dict(os.environ, {"DOCKER_HOST": f"unix://{self.tmp.name}/none.sock"})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.db = Db(f"{self.tmp.name}/p.db")
        self.addCleanup(self.db.close)
        for line in ("a", "b"):
            self.db.create_conversation(line, line)
            self.db.add_attachment(f"{line}-cap", line, f"{line}cap", "fake", ["f"], self.tmp.name)
            self.db._exec("UPDATE attachments SET is_lead=1 WHERE id=?", (f"{line}-cap",))
            self.db.add_attachment(f"{line}-w", line, f"{line}w", "fake", ["f"], self.tmp.name)
        user = auth_store.create_user(
            self.db, "p@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.person = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}

        def token(att):
            return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, att)}

        self.captain, self.worker = token("a-cap"), token("a-w")
        app = FastAPI()
        install_auth_guard(app, self.db)
        register_docker_relay_routes(app)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        self.addAsyncCleanup(self.client.aclose)
        for line in ("a", "b"):
            docker_relay.start(line)
            self.addAsyncCleanup(docker_relay.stop, line)

    async def test_a_person_sees_every_relay_and_a_captain_only_its_own(self):
        everyone = (await self.client.get("/api/docker-relay", headers=self.person)).json()
        self.assertEqual([row["conv_id"] for row in everyone], ["a", "b"])
        row = everyone[0]
        self.assertEqual(row["socket"], docker_relay.relay_socket("a"))
        self.assertTrue(row["listening"])
        self.assertEqual(row["connections"], 0)
        self.assertIn("cannot connect", row["probe"])
        own = (await self.client.get("/api/docker-relay", headers=self.captain)).json()
        self.assertEqual([row["conv_id"] for row in own], ["a"])

    async def test_a_worker_is_refused(self):
        refused = await self.client.get("/api/docker-relay", headers=self.worker)
        self.assertEqual(refused.status_code, 403)
