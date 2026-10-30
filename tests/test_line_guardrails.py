"""Depth cap, per-line worktrees, sideways staffing, and loud helper errors."""

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import agent_client, auth_store, auth_tokens, server
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.goal import goal_rider, register_goal_route
from partyline.hierarchy_routes import hierarchy_router
from partyline.line_worktree import WORKTREES_DIR, line_cwd, place_child
from partyline.worktree_lifecycle import remove_for_line
from partyline.media import MediaStore
from partyline.runtime import ChatRuntime


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


class GuardrailTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))
        register_goal_route(app, self.runtime)
        self.spawned = []

        async def fake_start(att, **kwargs):
            self.spawned.append(att)
            return att

        register_conversation_routes(
            app, self.runtime, MediaStore(self.db, self.directory.name + "/media"),
            None, {}, {}, fake_start,
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        # The attach route spawns through the server module; point it here.
        self.addCleanup(setattr, server, "runtime", server.runtime)
        self.addCleanup(setattr, server, "_start_attachment", server._start_attachment)
        server.runtime = self.runtime
        server._start_attachment = fake_start
        self.db.create_conversation("root", "Root")
        self.db.add_attachment("root-lead", "root", "terra", "fake", ["fake"], self.directory.name)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='root-lead'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.client.headers.update(self.human)

    def machine(self, att_id):
        return {"Authorization": "Bearer " + auth_store.ensure_api_token(self.db, att_id)}

    def child(self, parent, name, headers=None):
        made = self.client.post(f"/api/conversations/{parent}/children",
                                json={"name": name}, headers=headers or self.human)
        self.assertEqual(made.status_code, 201, made.text)
        return made.json()["conversation"]

    def captain(self, conv_id, name):
        att_id = f"{conv_id}-lead"
        self.db.add_attachment(att_id, conv_id, name, "fake", ["fake"], self.directory.name)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id=?", (att_id,))
        return self.machine(att_id)

    # -- depth ---------------------------------------------------------------

    def test_a_machine_stops_creating_children_at_the_cap_and_a_person_does_not(self):
        mid = self.child("root", "mid", self.machine("root-lead"))
        leaf = self.child(mid["id"], "leaf", self.captain(mid["id"], "sol"))
        deeper = self.client.post(f"/api/conversations/{leaf['id']}/children",
                                  json={"name": "too-deep"},
                                  headers=self.captain(leaf["id"], "luna"))
        self.assertEqual(deeper.status_code, 403, deeper.text)
        self.assertEqual(self.child(leaf["id"], "by-a-person")["parent_id"], leaf["id"])
        caps = self.client.get("/api/capabilities", headers=self.machine(f"{leaf['id']}-lead"))
        self.assertEqual((caps.json()["depth"], caps.json()["max_depth"]), (2, 2))
        self.assertNotIn("create_child", caps.json()["actions"])
        self.assertEqual(goal_rider(self.db, leaf["id"]), "")
        self.assertEqual(goal_rider(self.db, mid["id"]), "")

    # -- sideways staffing -------------------------------------------------------

    def test_a_second_worker_on_a_captained_staffed_line_means_parallel_lines(self):
        payload = {"name": "luna", "adapter": "raw", "command": "sh"}
        mid = self.child("root", "mid", self.machine("root-lead"))
        captain = self.captain(mid["id"], "sol")
        first = self.client.post(f"/api/conversations/{mid['id']}/attachments",
                                 json=payload, headers=captain)
        self.assertEqual(first.status_code, 200, first.text)
        # the captain's second implementer is refused, with the remedy named
        second = self.client.post(f"/api/conversations/{mid['id']}/attachments",
                                  json={**payload, "name": "mimo"},
                                  headers=captain)
        self.assertEqual(second.status_code, 409, second.text)
        self.assertIn("parallel slices mean parallel lines", second.json()["detail"])
        self.assertIn("allow_shared_branch", second.json()["detail"])
        self.assertIn("close the old one first (DELETE /api/attachments/<id>)",
                      second.json()["detail"])
        # the override is the captain's explicit call, and the line hears it
        overridden = self.client.post(
            f"/api/conversations/{mid['id']}/attachments",
            json={**payload, "name": "mimo", "allow_shared_branch": True},
            headers=captain)
        self.assertEqual(overridden.status_code, 200, overridden.text)
        notices = [m["body"] for m in self.db.list_messages(mid["id"])
                   if "shared branch" in m["body"]]
        self.assertEqual(len(notices), 1)
        self.assertIn("@mimo joins a shared branch", notices[0])

    def test_a_person_is_never_refused_but_the_shared_branch_is_flagged(self):
        payload = {"name": "luna", "adapter": "raw", "command": "sh"}
        mid = self.child("root", "mid", self.machine("root-lead"))
        captain = self.captain(mid["id"], "sol")
        self.client.post(f"/api/conversations/{mid['id']}/attachments",
                         json=payload, headers=captain)
        person = self.client.post(f"/api/conversations/{mid['id']}/attachments",
                                  json={**payload, "name": "mimo"})
        self.assertEqual(person.status_code, 200, person.text)
        notices = [m["body"] for m in self.db.list_messages(mid["id"])
                   if "shared branch" in m["body"]]
        self.assertEqual(len(notices), 1)
        self.assertIn("attached by @person", notices[0])

    def test_a_line_without_a_captain_takes_a_second_worker_untouched(self):
        payload = {"name": "luna", "adapter": "raw", "command": "sh"}
        bare = self.child("root", "bare")
        first = self.client.post(f"/api/conversations/{bare['id']}/attachments",
                                 json=payload)
        second = self.client.post(f"/api/conversations/{bare['id']}/attachments",
                                  json={**payload, "name": "mimo"})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual([m for m in self.db.list_messages(bare["id"])
                          if "shared branch" in m["body"]], [])

    def test_a_captain_cannot_attach_to_its_own_line_once_it_has_a_child(self):
        payload = {"name": "grok", "adapter": "raw", "command": "sh"}
        mid = self.child("root", "mid", self.machine("root-lead"))
        person = self.client.post("/api/conversations/root/attachments", json=payload)
        self.assertEqual(person.status_code, 200, person.text)
        sideways = self.client.post("/api/conversations/root/attachments",
                                    json={**payload, "name": "grok2"},
                                    headers=self.machine("root-lead"))
        self.assertEqual(sideways.status_code, 403, sideways.text)
        self.assertIn("work goes down, not sideways", sideways.json()["detail"])
        down = self.client.post(f"/api/conversations/{mid['id']}/attachments", json=payload,
                                headers=self.machine("root-lead"))
        self.assertEqual(down.status_code, 200, down.text)
        self.assertEqual(down.json()["name"], "grok-2")  # the root's grok keeps its handle
        person = self.client.post("/api/conversations/root/attachments",
                                  json={**payload, "name": "grok3"})
        self.assertEqual(person.status_code, 200, person.text)

    def test_successor_is_reserved_for_handover(self):
        import time
        from partyline.captain_handover import offer, accept
        from partyline.captain_handover_completion import confirm, finish_detach
        from partyline.line_depth import live_workers
        from unittest.mock import AsyncMock
        import asyncio

        child = self.child("root", "mid", self.machine("root-lead"))
        payload = {"name": "successor", "adapter": "raw", "command": "sh", "successor": True}
        path = "/api/conversations/root/attachments"
        self.assertEqual(self.client.post(path, json=payload).status_code, 403)
        child_lead = self.captain(child["id"], "child-captain")
        self.assertEqual(self.client.post(path, json=payload, headers=child_lead).status_code, 403)
        lead = self.machine("root-lead")
        attached = self.client.post(path, json=payload, headers=lead)
        self.assertEqual(attached.status_code, 200, attached.text)
        ident = attached.json()["id"]
        self.assertEqual(live_workers(self.db, "root"), [])
        capabilities = self.client.get("/api/capabilities", headers=self.machine(ident))
        self.assertEqual(capabilities.json()["role"], "attachment")
        second = self.client.post(path, json={**payload, "name": "another"}, headers=lead)
        self.assertEqual(second.status_code, 409, second.text)
        self.db._exec("UPDATE attachments SET status='running' WHERE id=?", (ident,))
        now = time.time() + 61
        live = {"root-lead", ident}
        handover, _ = offer(self.db, "root", "root-lead", ident, "notes", live, now=now)
        accept(self.db, "root", ident, handover, live, now=now)
        self.assertFalse(self.db.get_attachment(ident)["is_successor"])
        confirm(self.db, "root", "root-lead", handover, now=now)
        row, _ = confirm(self.db, "root", ident, handover, now=now)
        async def detach(runtime, attachment_id):
            runtime.db._exec("UPDATE attachments SET status='detached' WHERE id=?", (attachment_id,))
        with patch("partyline.captain_handover_completion.detach_attachment",
                   new=AsyncMock(side_effect=detach)):
            asyncio.run(finish_detach(self.runtime, row))
        self.assertIsNone(self.db.get_attachment("root-lead"))

    def test_successor_bypasses_parallel_worker_rule_and_resume_is_capped(self):
        import asyncio
        from fastapi import HTTPException
        from partyline.resource_budget import claim_resume

        lead = self.machine("root-lead")
        path = "/api/conversations/root/attachments"
        payload = {"name": "worker", "adapter": "raw", "command": "sh"}
        self.assertEqual(self.client.post(path, json=payload, headers=lead).status_code, 200)
        refused = self.client.post(path, json={**payload, "name": "other"}, headers=lead)
        self.assertEqual(refused.status_code, 409)
        successor = self.client.post(path, json={**payload, "name": "next", "successor": True}, headers=lead)
        self.assertEqual(successor.status_code, 200, successor.text)
        ident = successor.json()["id"]
        self.db._exec("UPDATE attachments SET status='detached' WHERE id=?", (ident,))
        replacement = self.client.post(path, json={**payload, "name": "next2", "successor": True},
                                       headers=lead)
        self.assertEqual(replacement.status_code, 200, replacement.text)
        with self.assertRaises(HTTPException) as denied:
            asyncio.run(claim_resume(self.db, ident, "owner", 1024))
        self.assertEqual(denied.exception.status_code, 409)

    def test_an_archived_child_no_longer_blocks_its_parent_from_staffing(self):
        payload = {"name": "grok", "adapter": "raw", "command": "sh"}
        child = self.child("root", "finished", self.machine("root-lead"))
        archived = self.client.delete(f"/api/conversations/{child['id']}")
        self.assertEqual(archived.status_code, 200, archived.text)

        attached = self.client.post("/api/conversations/root/attachments", json=payload,
                                    headers=self.machine("root-lead"))

        self.assertEqual(attached.status_code, 200, attached.text)

    def test_a_captain_handed_workers_assigns_them_instead_of_splitting(self):
        # The princess-book incident: grok staffed «delivery» with sol as captain
        # and gemini-flash as worker; sol's pack said "spin up a sub-line", so it
        # made a grandchild and staffed a second gemini-flash there.
        mid = self.child("root", "delivery", self.machine("root-lead"))
        sol = self.captain(mid["id"], "sol")
        worker = self.client.post(f"/api/conversations/{mid['id']}/attachments",
                                  json={"name": "gemini-flash", "adapter": "raw", "command": "sh"},
                                  headers=self.machine("root-lead"))
        self.assertEqual(worker.status_code, 200, worker.text)
        self.db._exec("UPDATE attachments SET status='running' WHERE name='gemini-flash'")
        split = self.client.post(f"/api/conversations/{mid['id']}/children",
                                 json={"name": "gate1"}, headers=sol)
        self.assertEqual(split.status_code, 403, split.text)
        self.assertIn("already has workers (@gemini-flash)", split.json()["detail"])
        self.assertIn("assign them, do not split", split.json()["detail"])
        caps = self.client.get("/api/capabilities", headers=sol).json()
        self.assertNotIn("create_child", caps["actions"])
        self.assertIn("assign", caps["actions"])
        self.assertEqual(goal_rider(self.db, mid["id"]), "")
        # A person may still split it, and once the worker is gone so may the captain.
        self.assertEqual(self.child(mid["id"], "by-a-person")["parent_id"], mid["id"])
        self.db._exec("UPDATE attachments SET status='exited' WHERE name='gemini-flash'")
        self.assertEqual(goal_rider(self.db, mid["id"]), "")
        self.assertIn("create_child",
                      self.client.get("/api/capabilities", headers=sol).json()["actions"])

    # -- worktrees ---------------------------------------------------------------

    def _repo(self):
        repo = os.path.join(self.directory.name, "repo")
        os.makedirs(repo)
        _git("init", "-q", "-b", "main", cwd=repo)
        _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
             "--allow-empty", "-m", "root", cwd=repo)
        return repo

    def _tracked_repo(self):
        """A clone whose main tracks origin/main, plus a second clone to move origin."""
        origin = os.path.join(self.directory.name, "origin.git")
        _git("init", "-q", "--bare", "-b", "main", origin, cwd=self.directory.name)
        repo = os.path.join(self.directory.name, "repo")
        _git("clone", "-q", origin, repo, cwd=self.directory.name)
        _git("checkout", "-q", "-b", "main", cwd=repo)
        _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
             "--allow-empty", "-m", "root", cwd=repo)
        _git("push", "-q", "-u", "origin", "main", cwd=repo)
        other = os.path.join(self.directory.name, "other")
        _git("clone", "-q", origin, other, cwd=self.directory.name)
        return repo, other

    def test_a_captain_hears_the_checkout_state_and_a_stale_base_cuts_no_child(self):
        repo, other = self._tracked_repo()
        self.db._exec("UPDATE attachments SET cwd=? WHERE id='root-lead'", (repo,))
        current = self.child("root", "fresh", self.machine("root-lead"))
        self.assertIn("☏ base checkout:", self.db.list_messages(current["id"])[1]["body"])
        self.assertIn("up to date with origin/main", self.db.list_messages(current["id"])[1]["body"])
        _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
             "--allow-empty", "-m", "upstream moved", cwd=other)
        _git("push", "-q", cwd=other)
        stale = self.client.post("/api/conversations/root/children", json={"name": "late"},
                                 headers=self.machine("root-lead"))
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertIn("1 commit behind origin/main", stale.json()["detail"])
        self.assertIn("ask the person to bring main up to date", stale.json()["detail"])
        # A person may still cut it, and the child hears that its base is stale.
        by_person = self.child("root", "late")
        self.assertIn("STALE", self.db.list_messages(by_person["id"])[1]["body"])
        # Appointing a captain tells the whole line where the checkout stands.
        self.db.add_attachment("root-2", "root", "sol", "fake", ["fake"], repo)
        self.db._exec("UPDATE attachments SET status='running' WHERE id='root-2'")
        async def capture(messages):
            pass

        self.runtime.live["root-2"] = SimpleNamespace(deliver=capture, att={})
        self.assertEqual(self.client.post("/api/conversations/root/lead",
                                          json={"attachment_id": "root-2"}).status_code, 200)
        bodies = [m["body"] for m in self.db.list_messages("root")]
        self.assertTrue(any(b.startswith("☏ checkout: ") and "STALE" in b for b in bodies), bodies)

    def test_a_child_of_a_git_line_is_born_in_its_own_worktree(self):
        repo = self._repo()
        self.db._exec("UPDATE attachments SET cwd=? WHERE id='root-lead'", (repo,))
        child = self.child("root", "Frontend Polish", self.machine("root-lead"))
        expected = os.path.join(repo, WORKTREES_DIR, "frontend-polish")
        self.assertEqual(child["cwd"], expected)
        self.assertTrue(os.path.isdir(os.path.join(expected, ".git")) or os.path.exists(
            os.path.join(expected, ".git")))
        branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=expected).stdout.strip()
        self.assertEqual(branch, "line/frontend-polish")
        with open(os.path.join(repo, ".git/info/exclude")) as fh:
            self.assertIn(f"{WORKTREES_DIR}/", fh.read())
        notice = self.db.list_messages(child["id"])[0]["body"]
        self.assertIn("git worktree on branch line/frontend-polish", notice)
        # A machine attaching there works there, whatever cwd it asks for.
        att = self.client.post(f"/api/conversations/{child['id']}/attachments",
                               json={"name": "luna", "adapter": "raw", "command": "sh",
                                     "cwd": self.directory.name},
                               headers=self.machine("root-lead"))
        self.assertEqual(self.db.get_attachment(att.json()["id"])["cwd"], expected)
        # A second child of the same name gets its own tree and branch.
        again = self.child("root", "frontend-polish", self.machine("root-lead"))
        self.assertEqual(again["cwd"], expected + "-2")
        self.assertEqual(_git("rev-parse", "--abbrev-ref", "HEAD", cwd=again["cwd"]).stdout.strip(),
                         "line/frontend-polish-2")

    def test_a_grandchild_worktree_lives_under_the_top_level_repository(self):
        repo = self._repo()
        self.db._exec("UPDATE attachments SET cwd=? WHERE id='root-lead'", (repo,))
        mid = self.child("root", "mid", self.machine("root-lead"))
        self.assertEqual(mid["cwd"], os.path.join(repo, WORKTREES_DIR, "mid"))
        leaf = self.child(mid["id"], "leaf", self.captain(mid["id"], "sol"))
        self.assertEqual(leaf["cwd"], os.path.join(repo, WORKTREES_DIR, "leaf"))
        self.assertEqual(_git("rev-parse", "--abbrev-ref", "HEAD", cwd=leaf["cwd"]).stdout.strip(),
                         "line/leaf")

    def test_a_purged_line_drops_its_worktree_but_keeps_the_branch(self):
        repo = self._repo()
        self.db._exec("UPDATE attachments SET cwd=? WHERE id='root-lead'", (repo,))
        placed = place_child(self.db, "root", self.db.create_conversation("kid", "kid")["id"])
        self.assertTrue(os.path.isdir(placed["cwd"]))
        remove_for_line(self.db.get_conversation("kid"))
        self.assertFalse(os.path.exists(placed["cwd"]))
        self.assertIn("line/kid", _git("branch", "--list", "line/kid", cwd=repo).stdout)

    def test_an_unplaced_child_is_placed_on_its_first_machine_attach(self):
        repo = self._repo()
        self.db._exec("UPDATE attachments SET cwd=? WHERE id='root-lead'", (repo,))
        self.db.create_conversation("old-kid", "old kid")  # born before placement existed
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='old-kid'")
        att = self.client.post("/api/conversations/old-kid/attachments",
                               json={"name": "grok", "adapter": "raw", "command": "sh"},
                               headers=self.machine("root-lead"))
        self.assertEqual(att.status_code, 200, att.text)
        expected = os.path.join(repo, WORKTREES_DIR, "old-kid")
        self.assertEqual(self.db.get_attachment(att.json()["id"])["cwd"], expected)
        self.assertEqual(self.db.get_conversation("old-kid")["cwd"], expected)
        self.assertIn("git worktree", self.db.list_messages("old-kid")[0]["body"])

    def test_an_unplaced_grandchild_falls_back_to_its_ancestors_not_the_server(self):
        self.db.create_conversation("kid", "kid")
        self.db._exec("UPDATE conversations SET parent_id='root' WHERE id='kid'")
        self.db.create_conversation("grandkid", "grandkid")
        self.db._exec("UPDATE conversations SET parent_id='kid' WHERE id='grandkid'")
        self.db.add_attachment("kid-x", "kid", "x", "fake", ["fake"], self.directory.name)
        self.assertEqual(line_cwd(self.db, "grandkid"), self.directory.name)

    def test_a_plain_project_directory_becomes_a_repository_with_a_worktree_per_child(self):
        from unittest.mock import patch
        plain = os.path.join(self.directory.name, "blank")
        os.makedirs(plain)
        self.db._exec("UPDATE attachments SET cwd=? WHERE id='root-lead'", (plain,))
        with patch("partyline.line_worktree.project_directory", return_value=True):
            child = self.child("root", "scratch")
        self.assertTrue(os.path.isdir(os.path.join(plain, ".git")))
        self.assertEqual(child["cwd"], os.path.join(plain, WORKTREES_DIR, "scratch"))

    def test_a_temporary_or_system_directory_is_never_git_initialised(self):
        from partyline.line_worktree import project_directory
        self.assertFalse(project_directory(self.directory.name))  # under /tmp
        self.assertFalse(project_directory(os.path.expanduser("~")))
        self.assertFalse(project_directory("/"))
        self.assertTrue(project_directory(os.path.expanduser("~/code/some-project")))
        child = self.child("root", "scratch")  # the fixture's cwd is under /tmp: inherited
        self.assertEqual(child["cwd"], self.directory.name)

    def test_a_leaf_captain_may_record_its_own_goal(self):
        mid = self.child("root", "mid", self.machine("root-lead"))
        leaf = self.child(mid["id"], "leaf", self.captain(mid["id"], "sol"))
        put = self.client.put(f"/api/conversations/{leaf['id']}/goal", json={"goal": "prove it"},
                              headers=self.captain(leaf["id"], "luna"))
        self.assertEqual(put.status_code, 200, put.text)
        self.assertEqual(put.json()["goal"], "prove it")

    # -- helper errors -----------------------------------------------------------

    def test_the_helper_prints_the_servers_reason(self):
        connection = os.path.join(self.directory.name, "conn.json")
        with open(connection, "w") as fh:
            json.dump({"api": "http://127.0.0.1:1", "token": "t", "attachment_id": "a",
                       "conversation_id": "c", "handle": "h"}, fh)
        os.chmod(connection, 0o600)
        body = io.BytesIO(json.dumps({"detail": "'grok' is already attached on 'Root'"}).encode())
        error = HTTPError("http://x", 409, "Conflict", {}, body)
        stderr = io.StringIO()
        with patch.object(agent_client, "api_request", side_effect=error), redirect_stderr(stderr):
            code = agent_client.main(["--connection", connection, "request", "GET", "/api/x"])
        self.assertEqual(code, 1)
        self.assertIn("HTTP 409: 'grok' is already attached on 'Root'", stderr.getvalue())
