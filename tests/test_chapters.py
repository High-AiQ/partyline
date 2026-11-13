"""New chapter: a line continues in a fresh line that carries its standing state forward."""

import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.features import overridden
from partyline.hierarchy_routes import hierarchy_router
from partyline.line_notes import notes_router, read_notes, write_notes
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime


def setUpModule():
    global _fence
    _fence = overridden(write_fence=False)
    _fence.__enter__()


def tearDownModule():
    _fence.__exit__(None, None, None)


class ChapterApiTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        self.media = MediaStore(self.db, self.directory.name + "/media")
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))
        app.include_router(notes_router(self.runtime))

        async def fake_start(att, **kwargs):
            return {"id": att["id"], "name": att["name"], "status": att["status"]}

        register_conversation_routes(app, self.runtime, self.media, None, {}, {}, fake_start)
        self.client = TestClient(app)
        user = auth_store.create_user(self.db, "greg@example.com", "greg",
                                      auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.db.create_conversation("root", "Root", captain_mode="orchestrator")
        self.db.save_preset("fixture-manager", "Fixture", "fixture", "fake", "fake", can_manage=True)
        self.db.add_attachment("lead-att", "root", "fixture", "fake", ["fake"], "/tmp")
        self.db.add_attachment("other-att", "root", "grok", "fake", ["fake"], "/tmp")
        self.lead = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "lead-att")}
        self.other = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "other-att")}
        self.db._exec("UPDATE attachments SET is_lead=1 WHERE id='lead-att'")
        self._runtime = server.runtime
        server.runtime = self.runtime

    def tearDown(self):
        server.runtime = self._runtime
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def chapter(self, conv="root", headers=None, **body):
        return self.client.post(f"/api/conversations/{conv}/chapter", json=body,
                                headers=headers or self.human)

    def test_copies_standing_state_and_links_both_ways(self):
        self.db.set_topic("root", "the topic")
        self.db._exec("UPDATE conversations SET goal='the goal',cwd='/work/here',"
                      "default_review_policy='none' WHERE id='root'")
        write_notes(self.db, "root", "line", "line notes")
        write_notes(self.db, "root", "attachment", "private", attachment_id="lead-att")
        response = self.chapter()
        self.assertEqual(response.status_code, 200, response.text)
        new = response.json()["conversation"]
        self.assertEqual(new["name"], "Root · ch 2")
        self.assertEqual((new["topic"], new["goal"], new["cwd"]), ("the topic", "the goal", "/work/here"))
        self.assertEqual((new["captain_mode"], new["default_review_policy"]), ("orchestrator", "none"))
        self.assertEqual((new["chapter_of"], new["chapter"], new["parent_id"]), ("root", 2, None))
        self.assertEqual(read_notes(self.db, new["id"], "line")["notes"], "line notes")
        self.assertEqual(read_notes(self.db, new["id"], "attachment", "lead-att")["notes"], "")
        self.assertEqual(self.db.list_attachments(new["id"]), [])  # nothing moved
        self.assertEqual(len(self.db.list_attachments("root")), 2)
        old = [m["body"] for m in self.db.list_messages("root")]
        fresh = [m["body"] for m in self.db.list_messages(new["id"])]
        self.assertTrue(any(f"continued in [Root · ch 2](#/c/{new['id']})" in b for b in old), old)
        self.assertTrue(any("continues from [Root](#/c/root)" in b for b in fresh), fresh)
        self.assertIsNone(self.db.get_conversation("root")["archived_at"])

    def test_stored_link_survives_a_round_trip_and_lists(self):
        new = self.chapter(name="Second act").json()["conversation"]
        row = self.db.get_conversation(new["id"])
        self.assertEqual((row["chapter_of"], row["chapter"], row["name"]), ("root", 2, "Second act"))
        listed = {c["id"]: c for c in self.client.get("/api/conversations", headers=self.human).json()}
        self.assertEqual(listed[new["id"]]["chapter_of"], "root")
        self.assertEqual(listed["root"]["chapter"], 1)

    def test_chapter_number_increments_across_a_chain(self):
        first = self.chapter().json()["conversation"]
        second = self.chapter(first["id"]).json()["conversation"]
        third = self.chapter(second["id"]).json()["conversation"]
        self.assertEqual([c["chapter"] for c in (first, second, third)], [2, 3, 4])
        self.assertEqual(third["name"], "Root · ch 4")  # the suffix is replaced, not stacked
        self.assertEqual(third["chapter_of"], second["id"])

    def test_a_line_continues_once(self):
        self.assertEqual(self.chapter().status_code, 200)
        again = self.chapter()
        self.assertEqual(again.status_code, 409)
        self.assertIn("already continues in", again.json()["detail"])
        self.assertEqual(self.client.get("/api/conversations/root/chapter",
                                         headers=self.human).json()["continued_in"] is not None, True)

    def test_refuses_task_archived_and_unknown_lines(self):
        self.db._exec("INSERT INTO conversations(id,name,created_at,parent_id) VALUES('kid','Kid',1,'root')")
        self.db._exec("INSERT INTO task_reviews(conv_id,root_id,implementer_id,implementer_preset,policy,"
                      "created_at) VALUES('kid','root','kid-worker','fake','captain',0)")
        self.assertEqual(self.chapter("kid").status_code, 409)
        self.db._exec("UPDATE conversations SET archived_at=1 WHERE id='root'")
        self.assertEqual(self.chapter().status_code, 409)
        self.assertEqual(self.chapter("nope").status_code, 404)

    def test_child_line_keeps_parent_and_tree_notes_stay_on_the_tree_root(self):
        write_notes(self.db, "root", "tree", "tree notes")
        self.db._exec("INSERT INTO conversations(id,name,created_at,parent_id,cwd) "
                      "VALUES('kid','Kid',1,'root','/kid/dir')")
        write_notes(self.db, "kid", "line", "kid line notes")
        new = self.chapter("kid").json()["conversation"]
        self.assertEqual((new["parent_id"], new["cwd"], new["name"]), ("root", "/kid/dir", "Kid · ch 2"))
        self.assertEqual(read_notes(self.db, new["id"], "line")["notes"], "kid line notes")
        self.assertEqual(read_notes(self.db, new["id"], "tree")["notes"], "tree notes")  # still the root's
        trees = self.db._exec("SELECT COUNT(*) n FROM line_notes WHERE scope='tree'").fetchone()
        self.assertEqual(trees["n"], 1)

    def test_a_root_chapter_starts_its_own_tree_with_the_tree_notes(self):
        write_notes(self.db, "root", "tree", "tree notes")
        new = self.chapter().json()["conversation"]
        self.assertEqual(read_notes(self.db, new["id"], "tree")["notes"], "tree notes")

    def test_permissions(self):
        self.db.create_conversation("elsewhere", "Elsewhere")
        self.assertEqual(self.chapter(headers={"Authorization": "Bearer nope"}).status_code, 401)
        self.assertEqual(self.chapter(headers=self.other).status_code, 403)  # not the captain
        self.assertEqual(self.chapter("elsewhere", headers=self.lead).status_code, 403)  # another line
        self.assertEqual(self.client.get("/api/conversations/elsewhere/chapter",
                                         headers=self.lead).status_code, 403)
        allowed = self.chapter(headers=self.lead)
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertTrue(any("by @fixture" in m["body"] for m in self.db.list_messages("root")))

    def test_preview_and_captain_preset(self):
        shown = self.client.get("/api/conversations/root/chapter", headers=self.human).json()
        self.assertEqual((shown["chapter"], shown["name"], shown["continued_in"]), (2, "Root · ch 2", None))
        self.assertEqual(shown["captain_preset"]["name"], "fixture")
        self.assertEqual(shown["live_processes"], 2)
        done = self.chapter().json()
        self.assertEqual(done["captain_preset"]["adapter"], "fake")
        bare = self.db.create_conversation("bare", "Bare")
        self.assertIsNone(self.client.get(f"/api/conversations/{bare['id']}/chapter",
                                          headers=self.human).json()["captain_preset"])

    def test_long_and_suffixed_names(self):
        from partyline.chapters import next_name
        self.assertEqual(next_name({"name": "A · ch 7", "chapter": 7}), "A · ch 8")
        long = next_name({"name": "x" * 120, "chapter": 1})
        self.assertEqual((len(long), long.endswith(" · ch 2")), (120, True))
        self.assertEqual(next_name({"name": " · ch 2", "chapter": 2}), "untitled · ch 3")
