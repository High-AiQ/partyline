"""Line bridges: a person-opened channel between ambassadors of two different trees."""

import asyncio
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens
from partyline.auth_guard import install_auth_guard
from partyline.bridge_store import WINDOW_LIMIT, attachment_ref, open_bridge_for_line
from partyline.db import Db
from partyline.bridge_routes import bridge_router
from partyline.media import MediaStore
from partyline.message_routes import message_router
from partyline.rebrief import render_rebrief
from partyline.reattach_liveness import mark_unlive_exited
from partyline.role_delivery import announce_restored, bind_role_delivery
from partyline.runtime import ChatRuntime


class Adapter:
    def __init__(self, att):
        self.att = att
        self.delivered = []

    async def deliver(self, messages):
        self.delivered.extend(messages)
        return True


class Socket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class LineBridgeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = f"{self.directory.name}/partyline.db"
        self.db = Db(self.path)
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(message_router(self.runtime, MediaStore(
            self.db, f"{self.directory.name}/media")))
        app.include_router(bridge_router(self.runtime))
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        for conv, name in (("x", "3d game"), ("y", "tool"), ("kid", "kid of x")):
            self.db.create_conversation(conv, name)
        self.db._exec("UPDATE conversations SET parent_id='x' WHERE id='kid'")
        self.adapters = {}
        for att_id, name, conv in (("x-amb", "sonnet", "x"), ("x-other", "gem", "x"),
                                   ("y-amb", "fable", "y"), ("y-other", "luna", "y"),
                                   ("kid-amb", "dig", "kid")):
            self.db.add_attachment(att_id, conv, name, "fake", ["fake"], "/tmp", att_id)
            self.db._exec("UPDATE attachments SET status='running' WHERE id=?", (att_id,))
            self.adapters[att_id] = Adapter(self.db.get_attachment(att_id))
            self.runtime.live[att_id] = self.adapters[att_id]
        user = auth_store.create_user(
            self.db, "greg@example.com", "greg", auth_tokens.hash_password("hunter2222"))
        self.person = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}

    def machine(self, att_id):
        return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, att_id)}

    def open(self, a=("x", "x-amb"), b=("y", "y-amb"), headers=None):
        body = {"a": {"conv_id": a[0], "attachment_id": a[1]},
                "b": {"conv_id": b[0], "attachment_id": b[1]}}
        return self.client.post("/api/bridges", json=body, headers=headers or self.person)

    def say(self, conv, att_id, body):
        return self.client.post(f"/api/conversations/{conv}/messages", json={"body": body},
                                headers=self.machine(att_id))

    def rows(self, conv):
        return self.db._exec("SELECT * FROM messages WHERE conv_id=? ORDER BY id",
                             (conv,)).fetchall()

    def opened(self):
        made = self.open()
        self.assertEqual(made.status_code, 200, made.text)
        self.adapters["x-amb"].delivered.clear()
        self.adapters["y-amb"].delivered.clear()
        return made.json()

    def test_a_person_opens_and_both_ambassadors_get_the_pack(self):
        bridge = self.opened()
        self.assertEqual([s["name"] for s in bridge["sides"]], ["sonnet", "fable"])
        self.assertEqual(bridge["opened_by"], "greg")
        packs = [r["body"] for r in self.rows("x") if r["audience_attachment_id"] == "x-amb"]
        self.assertIn("ambassador to @fable on «tool»", packs[0])
        self.assertIn("@[bridge]fable", packs[0])
        notices = [r["body"] for r in self.rows("y") if r["sender_type"] == "system"
                   and not r["audience_attachment_id"]]
        self.assertTrue(any("bridge opened by greg" in n for n in notices))
        got = self.client.get("/api/bridges?conv_id=x", headers=self.machine("x-other"))
        self.assertEqual(got.json()["id"], bridge["id"])
        self.assertIsNone(self.client.get("/api/bridges?conv_id=kid", headers=self.person).json())

    def test_a_process_may_not_open_close_or_read_the_log(self):
        self.assertEqual(self.open(headers=self.machine("x-amb")).status_code, 403)
        bridge = self.opened()
        denied = self.client.delete(f"/api/bridges/{bridge['id']}", headers=self.machine("x-amb"))
        self.assertEqual(denied.status_code, 403)
        log = self.client.get(f"/api/bridges/{bridge['id']}/messages",
                              headers=self.machine("y-amb"))
        self.assertEqual(log.status_code, 403)
        self.assertIsNotNone(open_bridge_for_line(self.db, "x"))

    def test_refusals_are_409_with_the_reason(self):
        same_tree = self.open(a=("x", "x-amb"), b=("kid", "kid-amb"))
        self.assertEqual(same_tree.status_code, 409)
        self.assertIn("one tree", same_tree.json()["detail"])
        self.db._exec("UPDATE attachments SET status='detached' WHERE id='y-amb'")
        self.assertIn("not live", self.open().json()["detail"])
        self.db._exec("UPDATE attachments SET status='running' WHERE id='y-amb'")
        self.db._exec("UPDATE conversations SET archived_at=1 WHERE id='y'")
        self.assertIn("archived", self.open().json()["detail"])

    def test_a_line_has_at_most_one_bridge(self):
        self.opened()
        again = self.open(a=("x", "x-other"), b=("y", "y-other"))
        self.assertEqual(again.status_code, 409)
        self.assertIn("already has an open bridge", again.json()["detail"])

    def test_delivery_wakes_the_counterpart_and_stamps_both_copies(self):
        bridge = self.opened()
        sent = self.say("x", "x-amb", "@[bridge]fable the schema changed; please re-pull")
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json()["bridge_id"], bridge["id"])
        woken = self.adapters["y-amb"].delivered
        self.assertEqual(len(woken), 1)
        self.assertEqual(woken[0]["bridge_id"], bridge["id"])
        self.assertEqual(woken[0]["audience_attachment_id"], "y-amb")
        self.assertEqual(woken[0]["source_conv_id"], "x")
        self.assertIn("schema changed", woken[0]["body"])
        self.assertEqual(self.adapters["x-other"].delivered, [])
        self.assertEqual(self.adapters["y-other"].delivered, [])
        stored = [r for r in self.rows("x") if r["sender"] == "sonnet"][-1]
        self.assertEqual(stored["bridge_id"], bridge["id"])

    def test_handle_matching_is_case_insensitive(self):
        self.opened()
        self.say("x", "x-amb", "@[bridge]Fable. hello")
        self.assertEqual(len(self.adapters["y-amb"].delivered), 1)

    def test_an_adapter_spoken_message_is_stamped_and_hidden_too(self):
        bridge = self.opened()
        socket = Socket()
        self.runtime.sockets["x"] = {socket}
        att = self.db.get_attachment("x-amb")
        post = self.runtime.post_callback("x-amb", "x", att["runtime_owner"])
        asyncio.run(post("sonnet", "agent", "@[bridge]fable via the pty"))
        self.assertEqual(len(self.adapters["y-amb"].delivered), 1)
        self.assertEqual(socket.sent, [])
        self.assertEqual(self.rows("x")[-1]["bridge_id"], bridge["id"])

    def test_people_never_see_bridge_rows_in_reads_or_fanout(self):
        bridge = self.opened()
        sockets = {"x": Socket(), "y": Socket()}
        self.runtime.sockets["x"], self.runtime.sockets["y"] = {sockets["x"]}, {sockets["y"]}
        self.say("x", "x-amb", "@[bridge]fable secret plan")
        self.say("y", "y-amb", "@[bridge]sonnet reply")
        for conv in ("x", "y"):
            page = self.client.get(f"/api/conversations/{conv}/messages", headers=self.person)
            self.assertNotIn("bridge", " ".join(m["body"] for m in page.json()["messages"]
                                                 if m["sender_type"] == "agent"))
            self.assertFalse(any(m.get("bridge_id") for m in page.json()["messages"]))
            self.assertFalse(any("bridge" in str(p).lower() and "secret" in str(p)
                                 for p in sockets[conv].sent))
            self.assertEqual([p for p in sockets[conv].sent if p.get("type") == "message"
                              and p["message"].get("bridge_id")], [])
        log = self.client.get(f"/api/bridges/{bridge['id']}/messages", headers=self.person)
        self.assertEqual(len(log.json()), 4)  # two originals, two copies

    def test_other_processes_digests_exclude_bridge_rows(self):
        self.opened()
        self.say("x", "x-amb", "@[bridge]fable for your eyes")
        for conv, att in (("x", "x-other"), ("y", "y-other")):
            name = self.db.get_attachment(att)["name"]
            seen = self.db.messages_after(conv, 0, name, att)
            self.assertFalse([m for m in seen if "for your eyes" in m["body"]])
        peer = self.db.messages_after("y", 0, "fable", "y-amb")
        self.assertTrue([m for m in peer if "for your eyes" in m["body"]])

    def test_the_wrong_handle_and_no_bridge_get_private_notices(self):
        self.opened()
        self.say("x", "x-amb", "@[bridge]luna wrong person")
        notice = [r for r in self.rows("x") if r["audience_attachment_id"] == "x-amb"][-1]
        self.assertIn("your counterpart is @fable", notice["body"])
        self.assertEqual(self.adapters["y-other"].delivered, [])
        self.say("x", "x-other", "@[bridge]fable let me in")
        notice = [r for r in self.rows("x") if r["audience_attachment_id"] == "x-other"][-1]
        self.assertIn("no open bridge", notice["body"])
        self.assertEqual(self.adapters["y-amb"].delivered, [])

    def test_a_persons_bridge_mention_is_ignored(self):
        self.opened()
        self.say("x", "x-amb", "hello")
        self.client.post("/api/conversations/x/messages", json={"body": "@[bridge]fable hi"},
                         headers=self.person)
        self.assertEqual(self.adapters["y-amb"].delivered, [])
        self.assertFalse([r for r in self.rows("y") if r["bridge_id"]])

    def test_a_copy_is_never_relayed_onward(self):
        bridge = self.opened()
        self.say("x", "x-amb", "@[bridge]fable and also @luna and @gem")
        self.assertEqual(len(self.adapters["y-amb"].delivered), 1)
        self.assertEqual(self.adapters["y-other"].delivered, [])
        self.assertEqual(self.adapters["x-other"].delivered, [])
        copies = [r for r in self.rows("y") if r["bridge_id"] == bridge["id"]]
        self.assertEqual(len(copies), 1)
        self.assertEqual(len([r for r in self.rows("x") if r["bridge_id"]]), 1)

    def test_the_rate_limit_stops_delivery_and_posts_one_notice(self):
        self.opened()
        for n in range(WINDOW_LIMIT):
            self.say("x", "x-amb", f"@[bridge]fable message {n}")
        self.assertEqual(len(self.adapters["y-amb"].delivered), WINDOW_LIMIT)
        self.say("x", "x-amb", "@[bridge]fable one too many")
        self.say("x", "x-amb", "@[bridge]fable and another")
        self.assertEqual(len(self.adapters["y-amb"].delivered), WINDOW_LIMIT)
        private = [r for r in self.rows("x") if r["audience_attachment_id"] == "x-amb"
                   and "rate limit" in r["body"]]
        self.assertEqual(len(private), 2)
        for conv in ("x", "y"):
            paused = [r for r in self.rows(conv) if r["body"] == "⇄ bridge paused: rate limit"]
            self.assertEqual(len(paused), 1)

    def test_a_detached_ambassador_closes_the_bridge_and_both_sides_hear(self):
        bridge = self.opened()
        att = self.db.get_attachment("x-amb")
        on_status = self.runtime.status_callback("x-amb", "x", att["runtime_owner"])
        asyncio.run(on_status("detached"))
        closed = self.client.get("/api/bridges?conv_id=y", headers=self.person).json()
        self.assertIsNone(closed)
        row = self.db._exec("SELECT * FROM line_bridges WHERE id=?", (bridge["id"],)).fetchone()
        self.assertEqual(row["close_reason"], "ambassador detached")
        self.assertEqual(row["closed_by"], "system")
        for conv in ("x", "y"):
            self.assertTrue([r for r in self.rows(conv) if "bridge closed by" in r["body"]
                             and not r["audience_attachment_id"]])
        private = [r for r in self.rows("y") if r["audience_attachment_id"] == "y-amb"][-1]
        self.assertIn("@[bridge] no longer delivers", private["body"])
        self.say("y", "y-amb", "@[bridge]sonnet anyone?")
        self.assertIn("no open bridge",
                      [r for r in self.rows("y") if r["audience_attachment_id"] == "y-amb"][-1]["body"])

    def test_archiving_a_line_closes_its_bridge(self):
        from partyline.line_subtree import archive_line

        self.opened()
        asyncio.run(archive_line(self.runtime, "y"))
        self.assertIsNone(open_bridge_for_line(self.db, "x"))

    def test_a_person_closes_idempotently(self):
        bridge = self.opened()
        first = self.client.delete(f"/api/bridges/{bridge['id']}", headers=self.person)
        again = self.client.delete(f"/api/bridges/{bridge['id']}", headers=self.person)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(again.json()["closed_by"], "greg")
        self.assertEqual(self.client.delete("/api/bridges/nope", headers=self.person).status_code, 404)

    def test_the_pack_follows_the_bridge(self):
        att = self.db.get_attachment("x-amb")
        att["digest_rider"] = lambda: ""
        bind_role_delivery(self.db, att, self.runtime)
        self.assertNotIn("Bridge open", att["role_briefing"])
        self.assertNotIn("Bridge open", render_rebrief(self.db, att))
        bridge = self.opened()
        fresh = self.db.get_attachment("x-amb")
        fresh["digest_rider"] = lambda: ""
        bind_role_delivery(self.db, fresh, self.runtime)
        self.assertIn("Bridge open", fresh["role_briefing"])
        self.assertIn("Bridge open", render_rebrief(self.db, fresh))
        self.assertEqual(attachment_ref(self.db, "x-amb")["peer_name"], "fable")
        self.assertIsNone(attachment_ref(self.db, "x-other"))
        self.client.delete(f"/api/bridges/{bridge['id']}", headers=self.person)
        self.assertNotIn("Bridge open", render_rebrief(self.db, fresh))
        later = self.db.get_attachment("x-amb")
        later["digest_rider"] = lambda: ""
        bind_role_delivery(self.db, later, self.runtime)
        self.assertNotIn("Bridge open", later["role_briefing"])

    def test_a_restart_does_not_close_and_the_resumed_ambassador_is_restored(self):
        bridge = self.opened()
        att = self.db.get_attachment("x-amb")
        on_status = self.runtime.status_callback("x-amb", "x", att["runtime_owner"])
        self.runtime.stopping = True  # the service is coming down
        asyncio.run(on_status("detached"))
        self.runtime.stopping = False
        self.runtime.reattaching.add("x-amb")  # sequential reattachment in progress
        asyncio.run(self.runtime.status_callback("x-amb", "x", att["runtime_owner"])("exited"))
        self.runtime.reattaching.discard("x-amb")
        self.assertEqual(open_bridge_for_line(self.db, "x")["id"], bridge["id"])
        # A bridge message arrives while the ambassador is down: it waits.
        self.runtime.live.pop("x-amb", None)
        self.say("y", "y-amb", "@[bridge]sonnet are you back?")
        self.assertEqual(self.adapters["x-amb"].delivered, [])
        # It resumes: pack in the briefing, a restored notice, the backlog from its cursor.
        self.db._exec("UPDATE attachments SET status='running' WHERE id='x-amb'")
        resumed = self.db.get_attachment("x-amb")
        resumed["digest_rider"] = lambda: ""
        bind_role_delivery(self.db, resumed, self.runtime)
        self.assertIn("Bridge open", resumed["role_briefing"])
        revived = Adapter(resumed)
        self.runtime.live["x-amb"] = revived
        asyncio.run(announce_restored(self.runtime, resumed))
        self.assertTrue(asyncio.run(
            self.runtime.deliver_pending("x", self.db.get_attachment("x-amb"), revived)))
        bodies = [m["body"] for m in revived.delivered]
        self.assertTrue(any("bridge restored after the restart" in b and "@fable" in b
                            for b in bodies), bodies)
        self.assertTrue(any("are you back?" in b for b in bodies), bodies)

    def test_an_ambassador_that_does_not_come_back_closes_the_bridge_after_reattachment(self):
        bridge = self.opened()
        self.db._exec("UPDATE attachments SET status='exited' WHERE id='x-amb'")
        self.runtime.live.pop("x-amb", None)
        self.assertIsNotNone(open_bridge_for_line(self.db, "y"))  # not closed by the exit itself
        asyncio.run(mark_unlive_exited(self.runtime, ["x-amb"], {}))
        row = self.db._exec("SELECT * FROM line_bridges WHERE id=?", (bridge["id"],)).fetchone()
        self.assertIn("@sonnet did not come back after the restart", row["close_reason"])
        told = [r["body"] for r in self.rows("y") if r["audience_attachment_id"] == "y-amb"][-1]
        self.assertIn("closed by ambassador @sonnet did not come back", told)

    def test_reconciliation_leaves_a_bridge_whose_ambassadors_are_back(self):
        self.opened()
        asyncio.run(mark_unlive_exited(self.runtime, ["x-amb", "y-amb"], {}))
        self.assertIsNotNone(open_bridge_for_line(self.db, "x"))

    def test_opening_broadcasts_the_bridge_badge_to_both_lines(self):
        sockets = {"x": Socket(), "y": Socket()}
        self.runtime.sockets["x"], self.runtime.sockets["y"] = {sockets["x"]}, {sockets["y"]}
        self.opened()
        refs = [p["attachment"]["bridge"] for p in sockets["x"].sent
                if p.get("type") == "attachment" and p["attachment"]["id"] == "x-amb"]
        self.assertEqual(refs[-1]["peer_name"], "fable")
        self.assertEqual(refs[-1]["peer_conv_name"], "tool")
        from partyline.message_routes import _attachment_response

        ambassador = asyncio.run(_attachment_response(self.runtime, self.db.get_attachment("y-amb")))
        other = asyncio.run(_attachment_response(self.runtime, self.db.get_attachment("y-other")))
        self.assertEqual(ambassador["bridge"]["peer_name"], "sonnet")
        self.assertIsNone(other["bridge"])

    def test_the_migration_runs_twice(self):
        self.db.close()
        second = Db(self.path)
        self.addCleanup(second.close)
        third = Db(self.path)
        self.addCleanup(third.close)
        columns = [r["name"] for r in third._exec("PRAGMA table_info(messages)").fetchall()]
        self.assertEqual(columns.count("bridge_id"), 1)
        self.assertEqual(third._exec("SELECT COUNT(*) AS n FROM line_bridges").fetchone()["n"], 0)


if __name__ == "__main__":
    unittest.main()
