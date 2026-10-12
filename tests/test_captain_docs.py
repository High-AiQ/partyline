"""Curated captain docs: shelves over the repository's own docs, captains only."""

import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.captain_docs import (
    CATEGORIES,
    TOPICS,
    _doc_text,
    register_docs_route,
    slice_section,
)
from partyline.db import Db
from partyline.runtime import ChatRuntime


class CaptainDocsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        register_docs_route(app, self.runtime)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.db.create_conversation("root", "Root")
        self.db.add_attachment("root-lead", "root", "terra", "fake", ["fake"], "/tmp")
        self.db.add_attachment("root-worker", "root", "dig", "fake", ["fake"], "/tmp")
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='root-lead'")
        self.db._exec("UPDATE attachments SET status='running' WHERE id='root-worker'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "root-lead")}
        self.worker = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "root-worker")}

    def test_the_index_lists_every_category_with_topics(self):
        seen = self.client.get("/api/docs", headers=self.human)
        self.assertEqual(seen.status_code, 200, seen.text)
        self.assertEqual([entry["slug"] for entry in seen.json()],
                         [slug for slug, _title, _summary in CATEGORIES])
        for entry in seen.json():
            self.assertTrue(entry["title"])
            self.assertTrue(entry["summary"])
            self.assertTrue(entry["topics"], entry)

    def test_a_category_lists_its_topics_and_unknown_is_404(self):
        seen = self.client.get("/api/docs/captaining", headers=self.human)
        self.assertEqual(seen.status_code, 200, seen.text)
        topics = seen.json()
        self.assertTrue(topics)
        self.assertIn("hand-off", [topic["slug"] for topic in topics])
        for topic in topics:
            self.assertTrue(topic["title"] and topic["summary"])
        self.assertEqual(
            self.client.get("/api/docs/nope", headers=self.human).status_code, 404)

    def test_a_topic_returns_body_sliced_from_the_real_doc(self):
        seen = self.client.get(
            "/api/docs/review-and-accept/prereview-and-tree-sync", headers=self.captain)
        self.assertEqual(seen.status_code, 200, seen.text)
        body = seen.json()
        self.assertEqual(body["title"], "Pre-review checks and the tree sync")
        self.assertEqual(body["source"], "docs/hierarchy.md#Pre-review checks and the tree sync")
        self.assertIn("prereview", body["body"])
        self.assertIn("res_roots", body["body"])
        self.assertEqual(
            self.client.get("/api/docs/captaining/nope",
                            headers=self.captain).status_code, 404)

    def test_people_and_captains_read_workers_are_refused(self):
        self.assertEqual(self.client.get("/api/docs", headers=self.worker).status_code, 403)
        self.assertEqual(
            self.client.get("/api/docs/captaining", headers=self.worker).status_code, 403)
        self.assertEqual(self.client.get("/api/docs", headers=self.captain).status_code, 200)
        self.assertEqual(self.client.get("/api/docs", headers=self.human).status_code, 200)

    def test_every_mapped_section_exists_in_the_real_docs(self):
        for topic in TOPICS:
            body = slice_section(_doc_text(topic["doc"]), topic["heading"], topic["doc"])
            self.assertTrue(
                body, f"{topic['doc']}#{topic['heading']} is gone — the map drifted")

    def test_a_missing_doc_file_answers_410_not_500(self):
        # an install without docs/ must not turn the request into a 500
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        with patch("partyline.captain_docs.DOCS_ROOT", Path(empty.name)):
            seen = self.client.get(
                "/api/docs/captaining/hand-off", headers=self.captain)
        self.assertEqual(seen.status_code, 410, seen.text)
        self.assertIn("docs moved", seen.json()["detail"])

    def test_long_sections_are_capped_with_a_pointer_to_the_doc(self):
        text = "## Head\n" + ("word " * 4000)
        body = slice_section(text, "Head", "docs/example.md", limit=100)
        self.assertIsNotNone(body)
        self.assertLess(len(body), 300)
        self.assertIn("truncated", body)
        self.assertIn("docs/example.md", body)

    def test_no_duplicate_topic_slugs(self):
        from partyline.docs_catalog import TOPICS

        seen = set()
        for topic in TOPICS:
            key = (topic["category"], topic["slug"])
            self.assertNotIn(key, seen, f"duplicate catalogue topic {key}")
            seen.add(key)


if __name__ == "__main__":
    unittest.main()
