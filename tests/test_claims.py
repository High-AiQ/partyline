"""Path-glob claims: overlap is refused, expiry is lazy, same owner refreshes."""

import os
import tempfile
import time
import unittest
os.environ.setdefault("PARTYLINE_DB", "/tmp/partyline-test-claims.db")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline.claims import (
    ClaimTaken,
    clean_paths,
    conflict_for,
    create_claim,
    expire,
    list_claims,
    overlaps,
    purge_claims,
)
from partyline.claim_routes import claims_router
from partyline.db import Db
from partyline.runtime import ChatRuntime


class OverlapTest(unittest.TestCase):
    def test_a_file_matches_its_glob(self):
        self.assertTrue(overlaps(["partyline/claims.py"], ["partyline/*.py"]))
        self.assertTrue(overlaps(["partyline/*.py"], ["partyline/server.py"]))
        self.assertFalse(overlaps(["partyline/claims.py"], ["frontend/**"]))

    def test_dotdot_and_absolute_paths_are_refused(self):
        with self.assertRaises(ValueError):
            clean_paths(["../secrets"])
        with self.assertRaises(ValueError):
            clean_paths(["/etc/passwd"])


class ClaimStoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.db.create_conversation("line", "Line")

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def test_a_second_owner_is_refused_with_the_holder(self):
        """The failing control for today's two-writer collision."""
        first = create_claim(self.db, "line", "opus", ["partyline/media.py"])
        with self.assertRaises(ClaimTaken) as raised:
            create_claim(self.db, "line", "grok", ["partyline/*.py"])
        self.assertEqual(raised.exception.conflict.id, first.id)
        self.assertEqual(raised.exception.conflict.owner, "opus")

    def test_the_same_owner_refreshes_instead_of_conflicting(self):
        first = create_claim(self.db, "line", "grok", ["partyline/claims.py"])
        again = create_claim(self.db, "line", "grok", ["scripts/claim.py"])
        self.assertEqual(again.id, first.id)
        self.assertEqual(set(again.paths), {"partyline/claims.py", "scripts/claim.py"})

    def test_expired_claims_do_not_block(self):
        create_claim(self.db, "line", "opus", ["partyline/claims.py"])
        expire(self.db, now=time.time() + 5 * 3600)
        self.assertIsNone(conflict_for(self.db, "line", "grok", ["partyline/claims.py"]))
        create_claim(self.db, "line", "grok", ["partyline/claims.py"])

    def test_purge_drops_the_line(self):
        create_claim(self.db, "line", "grok", ["a.py"])
        purge_claims(self.db, "line")
        self.assertEqual(conflict_for(self.db, "line", "opus", ["a.py"]), None)

    def test_a_claim_on_another_line_does_not_block_here(self):
        """A one-line fixture cannot see a missing conv_id filter."""
        self.db.create_conversation("elsewhere", "Elsewhere")
        create_claim(self.db, "elsewhere", "opus", ["partyline/*.py"])
        here = create_claim(self.db, "line", "grok", ["partyline/server.py"])
        self.assertEqual(here.owner, "grok")
        self.assertEqual([c.owner for c in list_claims(self.db, "line")], ["grok"])
        self.assertEqual([c.owner for c in list_claims(self.db, "elsewhere")], ["opus"])


class ClaimApiTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = ChatRuntime(Db(f"{self.directory.name}/t.db"))
        self.runtime.db.create_conversation("line", "Line")
        app = FastAPI()
        app.include_router(claims_router(self.runtime))
        self.client = TestClient(app)

    def tearDown(self):
        self.runtime.db.close()
        self.directory.cleanup()

    def test_post_get_and_delete(self):
        created = self.client.post(
            "/api/conversations/line/claims",
            json={"owner": "grok", "paths": ["partyline/claims.py"]},
        )
        self.assertEqual(created.status_code, 200)
        ident = created.json()["id"]
        listed = self.client.get("/api/conversations/line/claims")
        self.assertEqual([row["id"] for row in listed.json()], [ident])
        gone = self.client.delete(f"/api/claims/{ident}?owner=grok")
        self.assertEqual(gone.json(), {"ok": True})

    def test_overlap_is_http_409_with_the_holder(self):
        self.client.post(
            "/api/conversations/line/claims",
            json={"owner": "opus", "paths": ["partyline/*.py"]},
        )
        clash = self.client.post(
            "/api/conversations/line/claims",
            json={"owner": "grok", "paths": ["partyline/server.py"]},
        )
        self.assertEqual(clash.status_code, 409)
        self.assertEqual(clash.json()["detail"]["conflict"]["owner"], "opus")

    def test_another_line_does_not_see_this_claim(self):
        self.runtime.db.create_conversation("elsewhere", "Elsewhere")
        self.client.post(
            "/api/conversations/line/claims",
            json={"owner": "opus", "paths": ["partyline/*.py"]},
        )
        listed = self.client.get("/api/conversations/elsewhere/claims")
        self.assertEqual(listed.json(), [])
        taken = self.client.post(
            "/api/conversations/elsewhere/claims",
            json={"owner": "grok", "paths": ["partyline/server.py"]},
        )
        self.assertEqual(taken.status_code, 200)

    def test_an_unknown_line_is_404(self):
        missing = self.client.get("/api/conversations/nope/claims")
        self.assertEqual(missing.status_code, 404)

    def test_an_unsafe_path_is_400(self):
        bad = self.client.post(
            "/api/conversations/line/claims",
            json={"owner": "grok", "paths": ["../secrets"]},
        )
        self.assertEqual(bad.status_code, 400)

    def test_the_wrong_owner_cannot_release(self):
        created = self.client.post(
            "/api/conversations/line/claims",
            json={"owner": "opus", "paths": ["partyline/claims.py"]},
        )
        ident = created.json()["id"]
        refused = self.client.delete(f"/api/claims/{ident}?owner=grok")
        self.assertEqual(refused.status_code, 403)
        missing = self.client.delete("/api/claims/does-not-exist?owner=grok")
        self.assertEqual(missing.status_code, 404)
