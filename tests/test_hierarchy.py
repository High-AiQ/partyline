"""Line hierarchy, scoped machine tokens, reports, and revocation."""

import asyncio
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from partyline import auth_store, reports, auth_tokens, server
from partyline.auth_guard import install_auth_guard, resolve_principal
from partyline.db import Db
from partyline.hierarchy import create_child_conversation, stamp_source, would_cycle
from partyline.reports import wake_message
from partyline.machine_scope import deny_unless_attachment
from partyline.hierarchy_routes import hierarchy_router
from partyline.media import MediaStore
from partyline.message_routes import message_router
from partyline.media_routes import media_router
from partyline.runtime import ChatRuntime
from partyline.conversation_routes import register_conversation_routes
from partyline.features import overridden


def setUpModule():
    global _write_fence_off
    _write_fence_off = overridden(write_fence=False)
    _write_fence_off.__enter__()


def tearDownModule():
    _write_fence_off.__exit__(None, None, None)


def png():
    from io import BytesIO
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


class HierarchyApiTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.runtime = ChatRuntime(self.db)
        self.media = MediaStore(self.db, self.directory.name + "/media")
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))
        app.include_router(message_router(self.runtime, self.media))
        app.include_router(media_router(self.runtime, self.media))

        async def fake_start(att, **kwargs):
            return {"id": att["id"], "name": att["name"], "status": att["status"]}

        register_conversation_routes(
            app, self.runtime, self.media, None, {}, {}, fake_start
        )
        self.client = TestClient(app)
        self.parent = self.db.create_conversation("parent", "Parent")
        self.db.add_attachment("lead-att", "parent", "astra", "fake", ["fake"], "/tmp")
        self.db.add_attachment("impl-att", "parent", "grok", "fake", ["fake"], "/tmp")
        # Not live: a captain whose line carries a live worker assigns it rather
        # than splitting, and most of these tests have the captain create children.
        self.db.set_attachment_status("impl-att", "detached", None)
        user = auth_store.create_user(
            self.db, "greg@example.com", "greg",
            auth_tokens.hash_password("hunter2222"),
        )
        self.human = {
            "Authorization": "Bearer "
            + auth_tokens.create_access_token(
                auth_tokens.signing_secret(self.db), user["id"]
            )
        }
        self.lead = {
            "Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "lead-att")
        }
        self.impl = {
            "Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "impl-att")
        }
        self.client.headers.update(self.human)
        self._original_runtime = server.runtime
        server.runtime = self.runtime
        appointed = self.client.post(
            "/api/conversations/parent/lead", json={"attachment_id": "lead-att"}
        )
        self.assertEqual(appointed.status_code, 200)

    def tearDown(self):
        server.runtime = self._original_runtime
        self.client.close()
        self.db.close()
        self.directory.cleanup()

    def test_machine_identity_includes_line_and_lead(self):
        principal = resolve_principal(
            self.db, auth_store.ensure_api_token(self.db, "lead-att")
        )
        self.assertEqual(principal.conv_id, "parent")
        self.assertEqual(principal.attachment_id, "lead-att")
        self.assertTrue(principal.is_lead)

    def test_a_captain_can_fetch_its_current_pack_but_a_worker_cannot(self):
        briefing = self.client.get("/api/conversations/parent/briefing", headers=self.lead)
        self.assertEqual(briefing.status_code, 200, briefing.text)
        self.assertIn("## Captain pack", briefing.json()["briefing"])
        denied = self.client.get("/api/conversations/parent/briefing", headers=self.impl)
        self.assertEqual(denied.status_code, 403)

    def fake_spawn(self, calls):
        """Route attaches must not spawn real processes; stub the server hook."""
        original = server._start_attachment

        async def stubbed(att, **kwargs):
            calls.append(att["id"])
            return att

        server._start_attachment = stubbed
        self.addCleanup(setattr, server, "_start_attachment", original)

    def test_attach_suffixes_a_live_handle_from_a_related_line(self):
        self.fake_spawn([])
        child = self.client.post(
            "/api/conversations/parent/children",
            json={"name": "Child"},
            headers=self.lead,
        )
        child_id = child.json()["conversation"]["id"]
        taken = self.client.post(
            f"/api/conversations/{child_id}/attachments",
            json={"name": "ASTRA", "adapter": "raw", "command": "sh", "cwd": "/tmp"},
        )
        self.assertEqual(taken.status_code, 200, taken.text)
        self.assertEqual(taken.json()["name"], "ASTRA-2")  # presets double as handles
        distinct = self.client.post(
            f"/api/conversations/{child_id}/attachments",
            json={"name": "astra-child", "adapter": "raw", "command": "sh", "cwd": "/tmp"},
        )
        self.assertEqual(distinct.status_code, 200, distinct.text)

    def test_independent_roots_may_reuse_a_live_handle(self):
        self.db.create_conversation("root2", "Root2")
        self.fake_spawn([])
        reused = self.client.post(
            "/api/conversations/root2/attachments",
            json={"name": "astra", "adapter": "raw", "command": "sh", "cwd": "/tmp"},
        )
        self.assertEqual(reused.status_code, 200, reused.text)

    def test_linking_refuses_a_tree_wide_live_handle_collision(self):
        self.db.create_conversation("root2", "Root2")
        self.db.create_conversation("root3", "Root3")
        self.db.add_attachment("clash-a", "root2", "clash", "fake", ["fake"], "/tmp")
        self.db.add_attachment("clash-b", "root3", "CLASH", "fake", ["fake"], "/tmp")
        merged = self.client.put(
            "/api/conversations/root3/parent", json={"parent_id": "root2"}
        )
        self.assertEqual(merged.status_code, 409, merged.text)
        self.assertIn("clash", merged.json()["detail"].lower())
        self.db._exec("UPDATE attachments SET name='quieter' WHERE id='clash-b'")
        linked = self.client.put(
            "/api/conversations/root3/parent", json={"parent_id": "root2"}
        )
        self.assertEqual(linked.status_code, 200, linked.text)
        self.assertEqual(linked.json()["parent_id"], "root2")
        # Re-saving the same parent is what the management dialog sends; the
        # subtrees overlap completely and must not read as a collision.
        relinked = self.client.put(
            "/api/conversations/root3/parent", json={"parent_id": "root2"}
        )
        self.assertEqual(relinked.status_code, 200, relinked.text)

    def test_linking_under_a_non_root_parent_checks_the_ancestors(self):
        self.db.create_conversation("proot", "PRoot")
        self.db.create_conversation("pchild", "PChild")
        self.db.create_conversation("nomad", "Nomad")
        self.client.put("/api/conversations/pchild/parent", json={"parent_id": "proot"})
        self.db.add_attachment("att-1", "proot", "worker", "fake", ["fake"], "/tmp")
        self.db.add_attachment("att-2", "nomad", "worker", "fake", ["fake"], "/tmp")
        # The new parent's own subtree is clear; its ANCESTOR holds "worker"
        # and joins the tree with the link, so the link must be refused.
        blocked = self.client.put(
            "/api/conversations/nomad/parent", json={"parent_id": "pchild"}
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertIn("worker", blocked.json()["detail"])
        self.db._exec("UPDATE attachments SET name='wanderer' WHERE id='att-2'")
        moved = self.client.put(
            "/api/conversations/nomad/parent", json={"parent_id": "pchild"}
        )
        self.assertEqual(moved.status_code, 200, moved.text)

    def test_repointing_a_parented_line_is_refused_until_unlinked(self):
        self.db.create_conversation("root2", "Root2")
        self.db.create_conversation("root3", "Root3")
        linked = self.client.put(
            "/api/conversations/root3/parent", json={"parent_id": "root2"}
        )
        self.assertEqual(linked.status_code, 200, linked.text)
        # A parent is set once or cleared, never re-pointed.
        repointed = self.client.put(
            "/api/conversations/root3/parent", json={"parent_id": "root3X"}
        )
        self.assertEqual(repointed.status_code, 409, repointed.text)
        self.assertIn("unlink", repointed.json()["detail"])
        # Unlink releases the set-once: an independent line may link anew.
        unlinked = self.client.put("/api/conversations/root3/parent", json={"parent_id": None})
        self.assertEqual(unlinked.status_code, 200, unlinked.text)
        self.assertIsNone(unlinked.json()["parent_id"])
        relinked = self.client.put(
            "/api/conversations/root3/parent", json={"parent_id": "root2"}
        )
        self.assertEqual(relinked.status_code, 200, relinked.text)

    def test_fresh_session_does_not_inherit_lead(self):
        self.db.add_attachment("fresh", "parent", "astra-new", "fake", ["fake"], "/tmp")
        principal = resolve_principal(
            self.db, auth_store.ensure_api_token(self.db, "fresh")
        )
        self.assertFalse(principal.is_lead)

    def test_revocation_drops_descendant_powers_on_the_next_request(self):
        child = self.client.post(
            "/api/conversations/parent/children",
            json={"name": "Child"},
            headers=self.lead,
        )
        self.assertEqual(child.status_code, 201)
        child_id = child.json()["conversation"]["id"]
        self.client.post(
            "/api/conversations/parent/lead", json={"attachment_id": None}
        )
        denied = self.client.get(
            f"/api/conversations/{child_id}", headers=self.lead
        )
        self.assertEqual(denied.status_code, 403)

    def test_websocket_connected_to_parent_receives_event_when_child_created(self):
        class DummyWebSocket:
            def __init__(self):
                self.sent = []

            async def send_json(self, payload):
                self.sent.append(payload)

        ws = DummyWebSocket()
        self.runtime.sockets.setdefault("parent", set()).add(ws)
        response = self.client.post(
            "/api/conversations/parent/children",
            json={"name": "Child"},
            headers=self.lead,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ws.sent, [{"type": "conversations_changed"}])

    def test_a_file_relayed_to_a_process_is_readable_by_that_process_alone(self):
        posted = self.client.post(
            "/api/conversations/parent/files", data={"title": "brief"},
            files=[("file", ("brief.png", png(), "image/png"))],
        )
        file_id = posted.json()["files"][0]["id"]
        self.db.create_conversation("other", "Other")
        self.db.add_attachment("other-att", "other", "kimi", "fake", ["fake"], "/tmp")
        stranger = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "other-att")}
        url = f"/api/media/{file_id}/original"
        self.assertEqual(self.client.get(url, headers=stranger).status_code, 403)
        copy = self.db.add_message("other", "astra", "agent", f"read this: http://h/api/media/{file_id}/original")
        self.db._exec("UPDATE messages SET audience_attachment_id='other-att' WHERE id=?", (copy["id"],))
        self.assertEqual(self.client.get(url, headers=stranger).status_code, 200)
        self.db.add_attachment("other-att-2", "other", "glm", "fake", ["fake"], "/tmp")
        bystander = {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, "other-att-2")}
        self.assertEqual(self.client.get(url, headers=bystander).status_code, 403)

    def test_implementer_cannot_post_media_on_an_unrelated_line(self):
        self.db.create_conversation("other", "Other")
        posted = self.client.post(
            "/api/conversations/other/files",
            data={"title": "nope"},
            files=[("file", ("a.png", png(), "image/png"))],
            headers=self.impl,
        )
        self.assertEqual(posted.status_code, 403)

    def test_cycle_is_refused(self):
        child = create_child_conversation(self.db, "parent", "child", "Child")
        self.assertTrue(would_cycle(self.db, "parent", "child"))
        self.assertFalse(would_cycle(self.db, "child", "parent"))
        self.assertEqual(child["parent_id"], "parent")

    def test_archive_with_children_is_409_purge_requires_archive(self):
        self.client.post(
            "/api/conversations/parent/children",
            json={"name": "Kid"},
            headers=self.lead,
        )
        archived = self.client.delete("/api/conversations/parent")
        self.assertEqual(archived.status_code, 409)

    def test_a_person_can_archive_the_whole_tree_deepest_first(self):
        kid = self.client.post("/api/conversations/parent/children", json={"name": "Kid"},
                               headers=self.lead).json()["conversation"]
        grandkid = self.client.post(f"/api/conversations/{kid['id']}/children",
                                    json={"name": "Grandkid"}).json()["conversation"]
        self.db.add_attachment("gk-att", grandkid["id"], "luna", "fake", ["fake"], "/tmp")
        self.runtime.live["gk-att"] = SimpleNamespace(stop=self._noop)
        archived = self.client.delete("/api/conversations/parent?include_children=true")
        self.assertEqual(archived.status_code, 200, archived.text)
        body = archived.json()
        self.assertEqual(body["archived_ids"], [grandkid["id"], kid["id"], "parent"])
        self.assertEqual(body["stopped"], ["luna"])
        for line_id in body["archived_ids"]:
            self.assertIsNotNone(self.db.get_conversation(line_id)["archived_at"])

    async def _noop(self):
        return None

    def test_reports_do_not_wake_and_are_parent_pulled(self):
        child = self.client.post(
            "/api/conversations/parent/children",
            json={"name": "Kid"},
            headers=self.lead,
        ).json()["conversation"]
        self.db.add_attachment(
            "child-lead", child["id"], "astra-child", "fake", ["fake"], "/tmp"
        )
        self.client.post(
            f"/api/conversations/{child['id']}/lead",
            json={"attachment_id": "child-lead"},
        )
        child_headers = {
            "Authorization": "Bearer "
            + auth_store.ensure_api_token(self.db, "child-lead")
        }
        deliveries = []

        async def capture(messages):
            deliveries.append(messages)

        self.db.set_attachment_status("lead-att", "running", None)
        self.runtime.live["lead-att"] = type("A", (), {"deliver": capture, "att": {}})()
        posted = self.client.post(
            f"/api/conversations/{child['id']}/reports",
            json={"body": "blocked on ISBN"},
            headers=child_headers,
        )
        self.assertEqual(posted.status_code, 201)
        self.assertEqual(deliveries, [])
        listed = self.client.get(
            "/api/conversations/parent/reports", headers=self.lead
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["body"], "blocked on ISBN")
        self.assertEqual(listed.json()[0]["child_conv_id"], child["id"])
        self.assertEqual(listed.json()[0]["author_attachment_id"], "child-lead")

    def test_same_line_machine_message_posts_as_agent(self):
        posted = self.client.post(
            "/api/conversations/parent/messages",
            json={"body": "hello line"},
            headers=self.impl,
        )
        self.assertEqual(posted.status_code, 200)
        self.assertEqual(posted.json()["sender_type"], "agent")
        self.assertEqual(posted.json()["sender"], "grok")

    def test_unrelated_line_is_hidden_from_implementer_list(self):
        self.db.create_conversation("secret", "Secret")
        listed = self.client.get("/api/conversations", headers=self.impl)
        ids = {row["id"] for row in listed.json()}
        self.assertIn("parent", ids)
        self.assertNotIn("secret", ids)

    def test_human_still_lists_every_line(self):
        self.db.create_conversation("secret", "Secret")
        listed = self.client.get("/api/conversations", headers=self.human)
        ids = {row["id"] for row in listed.json()}
        self.assertIn("secret", ids)
        self.assertIn("parent", ids)

    def test_get_lead_and_capabilities(self):
        lead = self.client.get("/api/conversations/parent/lead")
        self.assertEqual(lead.json(), {"attachment_id": "lead-att"})
        caps = self.client.get("/api/capabilities", headers=self.lead)
        self.assertEqual(caps.status_code, 200)
        body = caps.json()
        self.assertEqual(body["role"], "lead")
        self.assertIn("create_child", body["actions"])
        impl = self.client.get("/api/capabilities", headers=self.impl).json()
        self.assertEqual(impl["role"], "implementer")
        self.assertNotIn("create_child", impl["actions"])

    def test_appointing_a_live_manager_rings_it_at_once(self):
        deliveries = []

        async def capture(messages):
            deliveries.append(messages)

        self.db.set_attachment_status("impl-att", "running", None)
        self.runtime.live["impl-att"] = SimpleNamespace(deliver=capture, att={})
        appointed = self.client.post(
            "/api/conversations/parent/lead", json={"attachment_id": "impl-att"})
        self.assertEqual(appointed.status_code, 200)
        [notice] = [m for m in self.db.list_messages("parent")
                    if m["body"].startswith("☏ @grok is now this line's captain")]
        self.assertEqual(notice["audience_attachment_id"], "impl-att")
        self.assertEqual([m["body"] for batch in deliveries for m in batch][-1], notice["body"])

    def test_appointing_a_captain_wakes_the_workers_already_on_the_line_with_their_pack(self):
        from partyline.role_delivery import bind_role_delivery

        woken = {}

        def adapter_for(att_id):
            async def capture(messages):
                woken.setdefault(att_id, []).extend(m["body"] for m in messages)
            return SimpleNamespace(deliver=capture, att={})

        # Two workers joined before any captain existed: no worker pack at join.
        self.db.add_attachment("w2-att", "parent", "sol", "fake", ["fake"], "/tmp")
        self.db.set_attachment_status("w2-att", "running", None)
        self.db.set_attachment_status("lead-att", "running", None)
        self.client.post("/api/conversations/parent/lead", json={"attachment_id": None})
        self.db.set_attachment_status("impl-att", "running", None)
        for att_id in ("lead-att", "impl-att", "w2-att"):
            self.runtime.live[att_id] = adapter_for(att_id)
        worker = {"id": "w2-att", "digest_rider": lambda: ""}
        bind_role_delivery(self.db, worker)
        self.assertEqual(worker["role_briefing"], "")  # nothing to brief: no captain yet

        appointed = self.client.post(
            "/api/conversations/parent/lead", json={"attachment_id": "lead-att"})
        self.assertEqual(appointed.status_code, 200)
        [notice] = [m for m in self.db.list_messages("parent")
                    if m["body"].startswith("☏ workers @")]
        self.assertIn("astra is now this line's captain", notice["body"])
        self.assertIsNone(notice["audience_attachment_id"])  # public: it names every worker
        self.assertIn("@grok", notice["body"])
        self.assertIn("@sol", notice["body"])
        self.assertIn("wait for your captain's @mention before editing anything", notice["body"])
        self.assertIn(notice["body"], woken["impl-att"])
        self.assertIn(notice["body"], woken["w2-att"])
        self.assertNotIn(notice["body"], woken.get("lead-att", []))  # the captain is not a worker
        # The rider computes `captained` fresh, so this wake carries the worker pack.
        digest = worker["digest_rider"]()
        self.assertIn("## Worker pack", digest)
        self.assertIn("act only on your captain's @mention", digest)
        self.assertIn("you are a worker on a captained line", digest)

    def test_appointing_a_captain_with_no_live_workers_posts_no_worker_notice(self):
        self.db.set_attachment_status("lead-att", "running", None)
        self.client.post("/api/conversations/parent/lead", json={"attachment_id": None})

        async def capture(messages):
            pass

        self.runtime.live["lead-att"] = SimpleNamespace(deliver=capture, att={})
        appointed = self.client.post(
            "/api/conversations/parent/lead", json={"attachment_id": "lead-att"})
        self.assertEqual(appointed.status_code, 200)
        self.assertEqual([m for m in self.db.list_messages("parent")
                          if m["body"].startswith("☏ workers @")], [])

    def test_reappointing_the_sitting_captain_is_a_no_op(self):
        deliveries = []

        async def capture(messages):
            deliveries.append(messages)

        self.db.set_attachment_status("impl-att", "running", None)
        self.runtime.live["impl-att"] = SimpleNamespace(deliver=capture, att={})
        for _ in range(3):
            self.assertEqual(self.client.post(
                "/api/conversations/parent/lead", json={"attachment_id": "impl-att"}).status_code, 200)

        rings = [m for m in self.db.list_messages("parent")
                 if "@grok is now this line's captain" in m["body"]]
        self.assertEqual(len(rings), 1)

    def test_a_replaced_captain_is_told_at_once(self):
        told = []

        async def capture(messages):
            told.extend(m["body"] for m in messages)

        self.db.set_attachment_status("lead-att", "running", None)
        self.runtime.live["lead-att"] = SimpleNamespace(deliver=capture, att={})
        appointed = self.client.post(
            "/api/conversations/parent/lead", json={"attachment_id": "impl-att"})
        self.assertEqual(appointed.status_code, 200)
        [notice] = [m for m in self.db.list_messages("parent")
                    if "no longer this line's captain" in m["body"]]
        self.assertEqual(notice["audience_attachment_id"], "lead-att")
        self.assertIn("@grok is now", notice["body"])
        self.assertIn(notice["body"], told)
        self.assertFalse(self.db.get_attachment("lead-att")["is_lead"])

    def test_appointing_a_manager_that_is_not_live_is_silent(self):
        self.db.set_attachment_status("impl-att", "exited", None)
        appointed = self.client.post(
            "/api/conversations/parent/lead", json={"attachment_id": "impl-att"})
        self.assertEqual(appointed.status_code, 200)
        self.assertEqual([m for m in self.db.list_messages("parent")
                          if "@grok is now this line's captain" in m["body"]], [])

    def test_a_child_is_born_with_its_goal_and_context(self):
        created = self.client.post(
            "/api/conversations/parent/children",
            json={"name": "renderer", "goal": "render spreads 1-3",
                  "topic": "cwd /tmp/book; budget $1; no upscale"},
            headers=self.lead,
        )
        self.assertEqual(created.status_code, 201)
        child = created.json()["conversation"]
        self.assertEqual(child["goal"], "render spreads 1-3")
        self.assertEqual(child["topic"], "cwd /tmp/book; budget $1; no upscale")
        notices = [m["body"] for m in self.db.list_messages(child["id"])]
        self.assertEqual(notices, [
            "☏ working directory: /tmp",
            "☏ topic set by @astra: cwd /tmp/book; budget $1; no upscale",
            "☏ goal set by @astra: render spreads 1-3",
        ])
        self.assertEqual(
            [m["source_attachment_id"] for m in self.db.list_messages(child["id"])],
            ["lead-att", "lead-att", "lead-att"],
        )

    def test_a_child_without_a_brief_hears_only_where_it_works(self):
        created = self.client.post(
            "/api/conversations/parent/children", json={"name": "scratch"}, headers=self.lead)
        self.assertEqual(created.status_code, 201)
        child = created.json()["conversation"]
        self.assertEqual(child["cwd"], "/tmp")  # inherited: the parent's captain works there
        self.assertEqual([m["body"] for m in self.db.list_messages(child["id"])],
                         ["☏ working directory: /tmp"])

    def test_human_can_link_an_existing_line_as_a_child(self):
        self.db.create_conversation("book", "Book")
        linked = self.client.put(
            "/api/conversations/book/parent", json={"parent_id": "parent"}
        )
        self.assertEqual(linked.status_code, 200)
        self.assertEqual(linked.json()["parent_id"], "parent")
        refused = self.client.put(
            "/api/conversations/book/parent",
            json={"parent_id": "parent"},
            headers=self.impl,
        )
        self.assertEqual(refused.status_code, 403)

    def test_ancestor_lead_can_appoint_a_child_manager(self):
        child = self.client.post(
            "/api/conversations/parent/children",
            json={"name": "Kid"},
            headers=self.lead,
        ).json()["conversation"]
        self.db.add_attachment(
            "kid-mgr", child["id"], "astra-kid", "fake", ["fake"], "/tmp"
        )
        appointed = self.client.post(
            f"/api/conversations/{child['id']}/lead",
            json={"attachment_id": "kid-mgr"},
            headers=self.lead,
        )
        self.assertEqual(appointed.status_code, 200)
        self.assertEqual(appointed.json()["attachment_id"], "kid-mgr")

    def test_non_lead_cannot_repoint_a_live_manager(self):
        self.db.set_attachment_status("lead-att", "running", None)
        refused = self.client.post(
            "/api/conversations/parent/lead",
            json={"attachment_id": "impl-att"},
            headers=self.impl,
        )
        self.assertEqual(refused.status_code, 403)

    def test_a_machine_cannot_appoint_a_captain_even_after_the_captain_detaches(self):
        """No natural-language handoff: a line with no captain waits for a person."""
        self.db.set_attachment_status("lead-att", "detached", None)
        refused = self.client.post(
            "/api/conversations/parent/lead",
            json={"attachment_id": "impl-att"},
            headers=self.impl,
        )
        self.assertEqual(refused.status_code, 403)
        appointed = self.client.post(
            "/api/conversations/parent/lead", json={"attachment_id": "impl-att"})
        self.assertEqual(appointed.status_code, 200)  # the person may

    def test_machine_cannot_appoint_a_foreign_line_after_its_lead_detaches(self):
        self.db.create_conversation("other", "Other")
        self.db.add_attachment("other-mgr", "other", "astra-other", "fake", ["fake"], "/tmp")
        refused = self.client.post(
            "/api/conversations/other/lead",
            json={"attachment_id": "other-mgr"},
            headers=self.impl,
        )
        self.assertEqual(refused.status_code, 403)

    def _child_with_lead(self, name="Kid"):
        """A child line whose own lead can escalate to this parent."""
        child = self.client.post(
            "/api/conversations/parent/children",
            json={"name": name},
            headers=self.lead,
        ).json()["conversation"]
        self.db.add_attachment(
            "child-lead", child["id"], "astra-child", "fake", ["fake"], "/tmp"
        )
        self.client.post(
            f"/api/conversations/{child['id']}/lead",
            json={"attachment_id": "child-lead"},
        )
        headers = {
            "Authorization": "Bearer "
            + auth_store.ensure_api_token(self.db, "child-lead")
        }
        return child, headers

    def _notify(self, child, headers, body):
        return self.client.post(
            f"/api/conversations/{child['id']}/reports",
            json={"body": body, "notify": True},
            headers=headers,
        )

    def test_a_notify_with_no_manager_is_kept_and_stays_deliverable(self):
        """Storing an escalation is not the same as anyone being told.

        With no lead on the parent there is nobody to wake. The report must
        still be preserved — and must not be recorded as delivered, or the
        one-pending-notify index would use it to suppress every wake that
        followed, muting this child for good.
        """
        child, headers = self._child_with_lead()
        self.client.post("/api/conversations/parent/lead", json={"attachment_id": None})

        stored = self._notify(child, headers, "blocked on the shared fix")

        self.assertEqual(stored.status_code, 201)
        self.assertEqual(stored.json()["body"], "blocked on the shared fix")
        self.assertIsNone(
            stored.json()["notified_at"],
            "no manager was woken, so the report must not claim it was",
        )

    def test_a_later_notify_retries_a_wake_that_never_happened(self):
        # The recovery path: once a manager exists, the next escalation from
        # the same child announces the coalesced report instead of joining a
        # silence that nobody asked for.
        child, headers = self._child_with_lead()
        self.client.post("/api/conversations/parent/lead", json={"attachment_id": None})
        self._notify(child, headers, "first, unheard")

        deliveries = []

        class Adapter:
            att = {"runtime_owner": None}

            async def deliver(self, messages):
                deliveries.append(messages)
                return True

        self.client.post(
            "/api/conversations/parent/lead", json={"attachment_id": "lead-att"}
        )
        self.db.set_attachment_status("lead-att", "running", None)
        self.runtime.live["lead-att"] = Adapter()

        second = self._notify(child, headers, "second, please read")

        self.assertEqual(second.status_code, 201)
        self.assertIsNotNone(second.json()["notified_at"])
        self.assertEqual(second.json()["body"], "second, please read")
        self.assertGreater(second.json()["revision"], 1, "it coalesced rather than stacking")
        self.assertTrue(deliveries, "the manager was finally woken")

    def test_a_delivered_notify_still_goes_quiet_until_acknowledged(self):
        # The retry must not become a wake per report: once the manager has
        # been told, further escalations stay silent until the ack.
        child, headers = self._child_with_lead()
        deliveries = []

        class Adapter:
            att = {"runtime_owner": None}

            async def deliver(self, messages):
                deliveries.append(messages)
                return True

        self.db.set_attachment_status("lead-att", "running", None)
        self.runtime.live["lead-att"] = Adapter()

        first = self._notify(child, headers, "one")
        after_first = len(deliveries)
        second = self._notify(child, headers, "two")

        self.assertIsNotNone(first.json()["notified_at"])
        self.assertEqual(len(deliveries), after_first, "no second wake before the ack")
        self.assertEqual(second.json()["notified_at"], first.json()["notified_at"])
        self.assertEqual(second.json()["body"], "two", "the newest text is what waits")

    def test_one_wake_while_the_first_is_still_being_delivered(self):
        """Concurrent escalations must not each wake the manager.

        Every caller sees `notified_at IS NULL` until the first wake finishes,
        so without an in-flight claim they all decide a wake is owed. The
        first delivery is held open here to make that window wide.
        """
        child, headers = self._child_with_lead()
        released = threading.Event()
        deliveries = []

        class BlockingAdapter:
            att = {"runtime_owner": None}

            async def deliver(self, messages):
                deliveries.append(messages)
                await asyncio.get_running_loop().run_in_executor(None, released.wait)
                return True

        self.db.set_attachment_status("lead-att", "running", None)
        self.runtime.live["lead-att"] = BlockingAdapter()

        results = []
        threads = [
            threading.Thread(
                target=lambda i=i: results.append(
                    self._notify(child, headers, f"update {i}").status_code
                )
            )
            for i in range(6)
        ]
        for thread in threads:
            thread.start()
        # Let the others pile up behind the held delivery before releasing it.
        time.sleep(0.4)
        released.set()
        for thread in threads:
            thread.join(timeout=15)

        self.assertEqual([code for code in results if code != 201], [])
        self.assertEqual(len(deliveries), 1, "the manager was woken once, not once per report")

    def test_a_late_expired_attempt_cannot_disturb_a_newer_claim(self):
        # A lease that ran out can still return. Fenced on the claim value, its
        # release and its completion both no-op rather than clearing or
        # finishing a wake that now belongs to someone else.
        child, headers = self._child_with_lead()
        self.client.post("/api/conversations/parent/lead", json={"attachment_id": None})
        stored = self._notify(child, headers, "first").json()

        current = reports.get(self.db, stored["id"])["notifying_at"]
        stale = (current or 0.0) - 1000.0

        reports.release_wake_claim(self.db, stored["id"], stale)
        self.assertEqual(
            reports.get(self.db, stored["id"])["notifying_at"],
            current,
            "a stale release must not hand away a newer claim",
        )
        reports.mark_notified(self.db, stored["id"], stale)
        self.assertIsNone(
            reports.get(self.db, stored["id"])["notified_at"],
            "a stale attempt must not complete a wake it no longer owns",
        )

    def test_a_manager_that_is_not_running_is_not_delivery(self):
        # Routing only ever delivers to a `running` attachment with a live,
        # matching activation. Anything short of that must leave the report
        # retryable rather than recorded as announced.
        child, headers = self._child_with_lead()

        class Adapter:
            att = {"runtime_owner": None}

            async def deliver(self, messages):
                raise AssertionError("a manager that cannot be reached was written to")

        for label, status, live in (
            ("still starting", "starting", True),
            ("exited but still in live", "exited", True),
            ("running with no adapter", "running", False),
        ):
            with self.subTest(case=label):
                self.runtime.live.pop("lead-att", None)
                self.db.set_attachment_status("lead-att", status, None)
                if live:
                    self.runtime.live["lead-att"] = Adapter()
                stored = self._notify(child, headers, f"escalate: {label}")

                self.assertEqual(stored.status_code, 201)
                self.assertIsNone(
                    stored.json()["notified_at"],
                    "an unreachable manager must not count as notified",
                )
                self.assertIsNone(
                    stored.json()["notifying_at"],
                    "and the claim must be handed back for the next attempt",
                )

    def test_notify_wakes_once_then_coalesces_until_ack(self):
        child = self.client.post(
            "/api/conversations/parent/children",
            json={"name": "Kid"},
            headers=self.lead,
        ).json()["conversation"]
        self.db.add_attachment(
            "child-lead", child["id"], "astra-child", "fake", ["fake"], "/tmp"
        )
        self.client.post(
            f"/api/conversations/{child['id']}/lead",
            json={"attachment_id": "child-lead"},
        )
        child_headers = {
            "Authorization": "Bearer "
            + auth_store.ensure_api_token(self.db, "child-lead")
        }
        deliveries = []

        class Adapter:
            att = {"runtime_owner": None}

            async def deliver(self, messages):
                deliveries.append(messages)
                return True

        self.db.set_attachment_status("lead-att", "running", None)
        self.runtime.live["lead-att"] = Adapter()
        first = self.client.post(
            f"/api/conversations/{child['id']}/reports",
            json={"body": "blocked", "notify": True},
            headers=child_headers,
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(len(deliveries), 1)
        second = self.client.post(
            f"/api/conversations/{child['id']}/reports",
            json={"body": "still blocked", "notify": True},
            headers=child_headers,
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(first.json()["revision"], 1)
        self.assertEqual(second.json()["revision"], 2)
        ack = self.client.post(
            f"/api/conversations/parent/reports/{first.json()['id']}/ack",
            json={"revision": 2},
            headers=self.lead,
        )
        self.assertIsNotNone(ack.json()["acknowledged_at"])
        third = self.client.post(
            f"/api/conversations/{child['id']}/reports",
            json={"body": "new blocker", "notify": True},
            headers=child_headers,
        )
        self.assertEqual(third.status_code, 201)
        self.assertEqual(len(deliveries), 2)
        pointer = wake_message("astra", third.json()["id"])
        self.assertEqual(deliveries[-1][-1]["body"], pointer)
        self.assertNotIn("new blocker", pointer)

    def test_notify_wake_ignores_mentions_in_report_text_and_child_name(self):
        child = self.client.post(
            "/api/conversations/parent/children",
            json={"name": "Kid @all @grok"},
            headers=self.lead,
        ).json()["conversation"]
        self.db.add_attachment(
            "child-lead", child["id"], "astra-child", "fake", ["fake"], "/tmp"
        )
        self.client.post(
            f"/api/conversations/{child['id']}/lead",
            json={"attachment_id": "child-lead"},
        )
        lead_deliveries, sib_deliveries = [], []

        class Adapter:
            def __init__(self, bucket):
                self.att = {"runtime_owner": None}
                self.bucket = bucket

            async def deliver(self, messages):
                self.bucket.append(messages)
                return True

        self.db.set_attachment_status("lead-att", "running", None)
        self.db.set_attachment_status("impl-att", "running", None)
        self.runtime.live["lead-att"] = Adapter(lead_deliveries)
        self.runtime.live["impl-att"] = Adapter(sib_deliveries)
        posted = self.client.post(
            f"/api/conversations/{child['id']}/reports",
            json={"body": "blocked @all @grok please", "notify": True},
            headers={
                "Authorization": "Bearer "
                + auth_store.ensure_api_token(self.db, "child-lead")
            },
        )
        self.assertEqual(posted.status_code, 201)
        self.assertEqual(len(lead_deliveries), 1)
        self.assertEqual(len(sib_deliveries), 0)
        wake = lead_deliveries[0][-1]["body"]
        self.assertEqual(wake, wake_message("astra", posted.json()["id"]))
        self.assertNotIn("@all", wake)
        self.assertNotIn("@grok", wake)
        listed = self.client.get(
            "/api/conversations/parent/reports", headers=self.lead
        ).json()
        self.assertEqual(listed[0]["body"], "blocked @all @grok please")

    def test_same_handle_from_a_child_still_wakes_the_parent_lead(self):
        child = create_child_conversation(self.db, "parent", "kid", "Kid")
        self.db.add_attachment(
            "child-astra", child["id"], "astra", "fake", ["fake"], "/tmp"
        )
        deliveries = []

        class Adapter:
            att = {"runtime_owner": None}

            async def deliver(self, messages):
                deliveries.append(messages)
                return True

        self.db.set_attachment_status("lead-att", "running", None)
        self.runtime.live["lead-att"] = Adapter()
        principal = resolve_principal(
            self.db, auth_store.ensure_api_token(self.db, "child-astra")
        )
        stored = self.db.add_message("parent", "astra", "agent", "@astra from the child")
        stored = {**stored, **stamp_source(self.db, stored["id"], principal)}
        asyncio.run(self.runtime.route_mentions("parent", stored))
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0][-1]["source_attachment_id"], "child-astra")
        self.assertEqual(deliveries[0][-1]["source_conv_id"], "kid")

    def test_http_parent_link_refuses_a_cycle(self):
        child = create_child_conversation(self.db, "parent", "kid", "Kid")
        cycled = self.client.put(
            "/api/conversations/parent/parent", json={"parent_id": child["id"]}
        )
        self.assertEqual(cycled.status_code, 400)

    def test_purge_refuses_a_parent_that_still_has_children(self):
        child = self.client.post(
            "/api/conversations/parent/children",
            json={"name": "Kid"},
            headers=self.lead,
        ).json()["conversation"]
        self.assertEqual(self.client.delete("/api/conversations/parent").status_code, 409)
        self.assertEqual(
            self.client.delete(f"/api/conversations/{child['id']}/purge").status_code,
            409,
        )
        unlinked = self.client.put(
            f"/api/conversations/{child['id']}/parent", json={"parent_id": None}
        )
        self.assertEqual(unlinked.status_code, 200)
        archived = self.client.delete("/api/conversations/parent")
        self.assertEqual(archived.status_code, 200)
        purged = self.client.delete("/api/conversations/parent/purge")
        self.assertEqual(purged.status_code, 200)

    def test_attachment_id_scope_matches_the_line(self):
        self.db.create_conversation("other", "Other")
        self.db.add_attachment("other-att", "other", "x", "fake", ["fake"], "/tmp")
        principal = resolve_principal(
            self.db, auth_store.ensure_api_token(self.db, "impl-att")
        )
        with self.assertRaises(HTTPException) as raised:
            deny_unless_attachment(self.db, principal, "other-att", "read")
        self.assertEqual(raised.exception.status_code, 403)
        deny_unless_attachment(self.db, principal, "impl-att", "read")

    def test_implementer_cannot_type_into_a_peer_process(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        principal = resolve_principal(self.db, auth_store.ensure_api_token(self.db, "impl-att"))
        request = SimpleNamespace(state=SimpleNamespace(principal=principal))
        adapter = SimpleNamespace(send_key=AsyncMock())
        self.runtime.live["lead-att"] = adapter
        try:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(server.attachment_key(request, "lead-att", server.KeyIn(key="enter")))
            self.assertEqual(raised.exception.status_code, 403)
            adapter.send_key.assert_not_called()
        finally:
            self.runtime.live.pop("lead-att", None)

    def test_lead_lists_children_and_implementer_cannot_read_them(self):
        created = self.client.post(
            "/api/conversations/parent/children",
            json={"name": "Kid"},
            headers=self.lead,
        ).json()["conversation"]
        listed = self.client.get(
            "/api/conversations/parent/children", headers=self.lead
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["id"], created["id"])
        self.assertEqual(
            self.client.get(
                f"/api/conversations/{created['id']}", headers=self.lead
            ).status_code,
            200,
        )
        hidden = self.client.get(
            f"/api/conversations/{created['id']}", headers=self.impl
        )
        self.assertEqual(hidden.status_code, 403)

    def test_machine_message_stamps_source_identity(self):
        posted = self.client.post(
            "/api/conversations/parent/messages",
            json={"body": "hello line"},
            headers=self.impl,
        )
        self.assertEqual(posted.json()["source_attachment_id"], "impl-att")
        self.assertEqual(posted.json()["source_conv_id"], "parent")

    def test_stale_ack_leaves_an_unseen_notify_update_pending(self):
        child = self.client.post(
            "/api/conversations/parent/children",
            json={"name": "Kid"},
            headers=self.lead,
        ).json()["conversation"]
        self.db.add_attachment(
            "child-lead", child["id"], "astra-child", "fake", ["fake"], "/tmp"
        )
        self.client.post(
            f"/api/conversations/{child['id']}/lead",
            json={"attachment_id": "child-lead"},
        )
        child_headers = {
            "Authorization": "Bearer "
            + auth_store.ensure_api_token(self.db, "child-lead")
        }
        first = self.client.post(
            f"/api/conversations/{child['id']}/reports",
            json={"body": "blocked", "notify": True},
            headers=child_headers,
        ).json()
        self.assertEqual(first["revision"], 1)
        updated = self.client.post(
            f"/api/conversations/{child['id']}/reports",
            json={"body": "still blocked", "notify": True},
            headers=child_headers,
        ).json()
        self.assertEqual(updated["id"], first["id"])
        self.assertEqual(updated["revision"], 2)
        stale = self.client.post(
            f"/api/conversations/parent/reports/{first['id']}/ack",
            json={"revision": 1},
            headers=self.lead,
        )
        self.assertEqual(stale.status_code, 409)
        listed = self.client.get(
            "/api/conversations/parent/reports", headers=self.lead
        ).json()
        self.assertIsNone(listed[0]["acknowledged_at"])
        self.assertEqual(listed[0]["body"], "still blocked")
        self.assertEqual(listed[0]["revision"], 2)
        fresh = self.client.post(
            f"/api/conversations/parent/reports/{first['id']}/ack",
            json={"revision": 2},
            headers=self.lead,
        )
        self.assertEqual(fresh.status_code, 200)
        self.assertIsNotNone(fresh.json()["acknowledged_at"])

    def test_concurrent_notifies_keep_one_pending_row(self):
        child = self.client.post(
            "/api/conversations/parent/children",
            json={"name": "Kid"},
            headers=self.lead,
        ).json()["conversation"]
        self.db.add_attachment(
            "child-lead", child["id"], "astra-child", "fake", ["fake"], "/tmp"
        )
        self.client.post(
            f"/api/conversations/{child['id']}/lead",
            json={"attachment_id": "child-lead"},
        )
        child_headers = {
            "Authorization": "Bearer "
            + auth_store.ensure_api_token(self.db, "child-lead")
        }
        failures = []

        def post(index):
            response = self.client.post(
                f"/api/conversations/{child['id']}/reports",
                json={"body": f"update {index}", "notify": True},
                headers=child_headers,
            )
            if response.status_code != 201:
                failures.append(response.status_code)

        threads = [threading.Thread(target=post, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(failures, [])
        listed = self.client.get(
            "/api/conversations/parent/reports", headers=self.lead
        ).json()
        pending = [
            row
            for row in listed
            if row["notify"] and row["acknowledged_at"] is None
        ]
        self.assertEqual(len(pending), 1)
        self.assertGreaterEqual(pending[0]["revision"], 1)
