"""The closed, credential-derived structured review-observation API."""

import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.db import Db
from partyline.review_observation_routes import review_observation_router
from partyline.runtime import ChatRuntime


class ReviewObservationRoutesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.db.create_conversation("line", "Line")
        self.db.create_conversation("other", "Other")
        self.message = self.db.add_message("line", "agent", "agent", "review this")
        self.other_message = self.db.add_message("other", "agent", "agent", "other")
        self.greg = self._user("greg@example.com", "greg")
        self.ada = self._user("ada@example.com", "ada")
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(review_observation_router(self.runtime))
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def _user(self, email, handle):
        user = auth_store.create_user(
            self.db, email, handle, auth_tokens.hash_password("hunter2222")
        )
        token = auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"]
        )
        return user, {"Authorization": f"Bearer {token}"}

    def _post(self, headers, *, decision="approve", message=None):
        return self.client.post(
            "/api/conversations/line/review-decisions",
            headers=headers,
            json={
                "presentation_message_id": message or self.message["id"],
                "decision": decision,
            },
        )

    def _get(self, headers, *, conversation="line", message=None):
        return self.client.get(
            f"/api/conversations/{conversation}/review-observations",
            headers=headers,
            params={"presentation_message_id": str(message or self.message["id"])},
        )

    def test_post_then_get_has_exact_closed_wire_shape(self):
        response = self._post(self.greg[1])
        self.assertEqual(201, response.status_code)
        row = response.json()
        self.assertEqual(set(row), {
            "conversation_id", "presentation_message_id", "evidence_kind",
            "evidence_ref", "sender_id", "decision", "observed_at",
        })
        self.assertEqual("line", row["conversation_id"])
        self.assertEqual(str(self.message["id"]), row["presentation_message_id"])
        self.assertEqual("decision", row["evidence_kind"])
        self.assertTrue(row["evidence_ref"].startswith("decision:"))
        self.assertEqual(f"partyline-user-{self.greg[0]['id']}", row["sender_id"])
        self.assertEqual("approve", row["decision"])
        self.assertTrue(row["observed_at"].endswith("Z"))
        self.assertEqual({"observations": [row]}, self._get(self.greg[1]).json())

    def test_empty_binding_is_200_and_unknown_binding_is_404(self):
        self.assertEqual({"observations": []}, self._get(self.greg[1]).json())
        self.assertEqual(404, self._get(self.greg[1], conversation="missing").status_code)
        self.assertEqual(
            404, self._get(self.greg[1], message=self.other_message["id"]).status_code
        )

    def test_decision_is_credential_derived_immutable_and_unique_per_human(self):
        first = self._post(self.greg[1]).json()
        self.assertEqual(409, self._post(self.greg[1], decision="reject").status_code)
        second = self._post(self.ada[1], decision="reject")
        self.assertEqual(201, second.status_code)
        rows = self._get(self.greg[1]).json()["observations"]
        self.assertEqual([first, second.json()], rows)

    def test_machine_cannot_write_but_can_read_and_archiving_preserves_decision(self):
        self._post(self.greg[1])
        self.db.add_attachment("machine", "line", "agent", "raw", ["sh"], "/tmp")
        machine = auth_store.ensure_api_token(self.db, "machine")
        headers = {"Authorization": f"Bearer {machine}"}
        self.assertEqual(403, self._post(headers).status_code)
        self.assertEqual(200, self._get(headers).status_code)
        self.db.archive_conversation("line")
        self.assertEqual(409, self._post(self.greg[1]).status_code)
        self.assertEqual(200, self._get(headers).status_code)

    def test_purge_destroys_review_decisions_with_the_line(self):
        self._post(self.greg[1])
        self.db.delete_conversation("line")
        with self.db.lock:
            count = self.db.conn.execute("SELECT count(*) FROM review_decisions").fetchone()[0]
        self.assertEqual(0, count)

    def test_missing_or_invalid_credentials_and_bodies_fail_closed(self):
        self.assertEqual(401, self._get({}).status_code)
        self.assertEqual(401, self._post({}).status_code)
        invalid = self.client.post(
            "/api/conversations/line/review-decisions",
            headers=self.greg[1],
            json={"presentation_message_id": self.message["id"], "decision": "maybe"},
        )
        self.assertEqual(422, invalid.status_code)
        string_id = self.client.post(
            "/api/conversations/line/review-decisions",
            headers=self.greg[1],
            json={"presentation_message_id": str(self.message["id"]), "decision": "approve"},
        )
        self.assertEqual(422, string_id.status_code)
        extra = self.client.post(
            "/api/conversations/line/review-decisions",
            headers=self.greg[1],
            json={
                "presentation_message_id": self.message["id"],
                "decision": "approve",
                "sender_id": "partyline-user-other",
            },
        )
        self.assertEqual(422, extra.status_code)
