"""Deterministic pre-review checks that need no model (finding 2.6).

``referenced-paths`` reads exactly a commit's bytes and reports path-like
JSON references the commit does not track, flagging the ones a gitignore
hides; ``tree_sync_check`` reports a worktree left stale or dirty by an
accept.
"""

import json
import os
import subprocess
import tempfile
import time
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from partyline import auth_store, auth_tokens, server
from partyline.auth_guard import install_auth_guard
from partyline.conversation_routes import register_conversation_routes
from partyline.db import Db
from partyline.hierarchy_routes import hierarchy_router
from partyline.media import MediaStore
from partyline.prereview import register_prereview_route
from partyline.runtime import ChatRuntime


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _identity(*args, cwd):
    return _git("-c", "user.email=t@example.com", "-c", "user.name=t", *args, cwd=cwd)


class PrereviewTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = os.path.join(self.directory.name, "repo")
        os.makedirs(self.repo)
        _git("init", "-q", "-b", "main", cwd=self.repo)
        _identity("commit", "-q", "--allow-empty", "-m", "root", cwd=self.repo)
        self.db = Db(f"{self.directory.name}/partyline.db")
        self.addCleanup(self.db.close)
        self.runtime = ChatRuntime(self.db)
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(hierarchy_router(self.runtime))
        register_prereview_route(app, self.runtime)

        async def fake_start(att, **kwargs):
            return att

        register_conversation_routes(
            app, self.runtime, MediaStore(self.db, self.directory.name + "/media"),
            None, {}, {}, fake_start,
        )
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.addCleanup(setattr, server, "runtime", server.runtime)
        server.runtime = self.runtime
        self.db.create_conversation("root", "Root")
        self.db.add_attachment("root-lead", "root", "terra", "fake", ["fake"], self.repo)
        self.db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='root-lead'")
        user = auth_store.create_user(
            self.db, "person@example.com", "person", auth_tokens.hash_password("hunter2222"))
        self.human = {"Authorization": "Bearer " + auth_tokens.create_access_token(
            auth_tokens.signing_secret(self.db), user["id"])}
        self.captain = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "root-lead")}
        self.client.headers.update(self.human)
        made = self.client.post("/api/conversations/root/children", json={"name": "kid"})
        self.assertEqual(made.status_code, 201, made.text)
        self.kid = made.json()["conversation"]
        self.worktree = self.kid["cwd"]

    def commit_table(self, table, extra_files=None, gitignore=None):
        """Write data/cues.json (+friends) in the worktree and commit them."""
        os.makedirs(os.path.join(self.worktree, "data"), exist_ok=True)
        with open(os.path.join(self.worktree, "data", "cues.json"), "w") as fh:
            json.dump(table, fh)
        for name, content in (extra_files or {}).items():
            path = os.path.join(self.worktree, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(content)
        if gitignore is not None:
            with open(os.path.join(self.worktree, ".gitignore"), "w") as fh:
                fh.write(gitignore)
        _git("add", "-A", cwd=self.worktree)
        _identity("commit", "-q", "-m", "table", cwd=self.worktree)
        return _git("rev-parse", "HEAD", cwd=self.worktree).stdout.strip()

    def check(self, sha, data_paths=("data/",), **body):
        return self.client.post(f"/api/conversations/{self.kid['id']}/prereview", json={
            "sha": sha, "data_paths": list(data_paths),
            "checks": ["referenced-paths"], **body,
        }, headers=self.captain)

    def test_an_untracked_reference_is_reported_and_a_clean_table_passes(self):
        clean = self.commit_table({"cue": {"file": "audio/tracked.ogg"}},
                                  extra_files={"audio/tracked.ogg": "sound"})
        seen = self.check(clean)
        self.assertEqual(seen.status_code, 200, seen.text)
        self.assertTrue(seen.json()["ok"])
        self.assertEqual(seen.json()["missing"], [])
        self.assertEqual(seen.json()["checked"], 1)
        dirty = self.commit_table({"cue": {"file": "audio/ghost.ogg",
                                           "sheet": "sprites/ghost.png"}})
        seen = self.check(dirty)
        self.assertEqual(seen.status_code, 200, seen.text)
        body = seen.json()
        self.assertFalse(body["ok"])
        self.assertEqual(sorted((m["file"], m["ref"]) for m in body["missing"]),
                         [("data/cues.json", "audio/ghost.ogg"),
                          ("data/cues.json", "sprites/ghost.png")])
        self.assertEqual(body["checked"], 2)

    def test_an_ignored_reference_is_flagged_as_ignored(self):
        # the out/ incident: real in the worktree, hidden from every commit
        sha = self.commit_table({"cue": {"file": "out/built.ogg"}},
                                gitignore="out/\n")
        seen = self.check(sha)
        self.assertEqual(seen.status_code, 200, seen.text)
        body = seen.json()
        self.assertFalse(body["ok"])
        self.assertEqual(len(body["missing"]), 1)
        self.assertEqual(body["missing"][0]["ref"], "out/built.ogg")
        self.assertTrue(body["missing"][0]["ignored"])

    def test_urls_and_plain_words_are_not_counted_as_paths(self):
        sha = self.commit_table({
            "url": "https://example.com/sounds/ghost.ogg",
            "scheme": "mailto:someone@example.com",
            "word": "loudly",
            "version": "1.2.3",
            "nested": ["deeper/voice.ogg", 42, {"again": "notes/flute.ogg"}],
        })
        seen = self.check(sha)
        self.assertEqual(seen.status_code, 200, seen.text)
        body = seen.json()
        self.assertEqual(body["checked"], 2)  # the two real-looking paths only
        self.assertEqual(sorted(m["ref"] for m in body["missing"]),
                         ["deeper/voice.ogg", "notes/flute.ogg"])

    def test_outside_the_subtree_and_unknown_checks_are_refused(self):
        stranger = os.path.join(self.directory.name, "stranger")
        os.makedirs(stranger)
        _git("init", "-q", "-b", "main", cwd=stranger)
        # a distinct commit: two same-second empty root commits hash alike
        with open(os.path.join(stranger, "stranger.txt"), "w") as fh:
            fh.write("not this repository's work\n")
        _git("add", "-A", cwd=stranger)
        _identity("commit", "-q", "-m", "stranger work", cwd=stranger)
        sha = _git("rev-parse", "HEAD", cwd=stranger).stdout.strip()
        made = self.check(sha, repository=stranger)
        self.assertEqual(made.status_code, 403, made.text)
        self.assertIn("subtree", made.json()["detail"])
        made = self.check(sha, checks=["vibes"])
        self.assertEqual(made.status_code, 422, made.text)
        self.assertIn("unknown checks", made.json()["detail"])
        made = self.check(sha)
        self.assertEqual(made.status_code, 400, made.text)  # no such commit here

    def test_a_machine_without_read_on_the_line_is_refused(self):
        self.db.add_attachment("root-worker", "root", "dig", "fake", ["fake"], self.repo)
        self.db._exec("UPDATE attachments SET status='running' WHERE id='root-worker'")
        outsider = {"Authorization": "Bearer " + auth_store.ensure_api_token(
            self.db, "root-worker")}
        sha = self.commit_table({"cue": {"file": "audio/tracked.ogg"}},
                                extra_files={"audio/tracked.ogg": "sound"})
        made = self.client.post(f"/api/conversations/{self.kid['id']}/prereview", json={
            "sha": sha, "data_paths": ["data/"], "checks": ["referenced-paths"]},
            headers=outsider)
        self.assertEqual(made.status_code, 403, made.text)

    def test_a_large_commit_and_a_chatty_table_stay_fast(self):
        # a real game repository is ~10k files and a dialogue table has
        # thousands of strings: the check is set lookups in a worker thread,
        # not a scan per string on the event loop
        table = {"lines": [f"word{i:04d}" for i in range(5000)],
                 "dirs": [f"d{i:04d}" for i in range(0, 100)]}
        marks = [f"M 100644 :1 d{i:04d}/f.txt" for i in range(20000)]
        marks.append("M 100644 :1 data/cues.json")
        blob = json.dumps(table).encode()
        stream = (b"blob\nmark :1\ndata " + str(len(blob)).encode() + b"\n" + blob + b"\n"
                  b"commit refs/heads/perf\n"
                  b"author t <t@example.com> 1700000000 +0000\n"
                  b"committer t <t@example.com> 1700000000 +0000\n"
                  b"data 4\nperf\n")
        stream += b"".join(mark.encode() + b"\n" for mark in marks)
        subprocess.run(["git", "fast-import", "--quiet"], cwd=self.repo,
                       input=stream, capture_output=True, check=True)
        sha = _git("rev-parse", "refs/heads/perf", cwd=self.repo).stdout.strip()
        started = time.perf_counter()
        seen = self.check(sha)
        elapsed = time.perf_counter() - started
        self.assertEqual(seen.status_code, 200, seen.text)
        self.assertTrue(seen.json()["ok"], seen.json())
        self.assertEqual(seen.json()["checked"], 100)  # the tracked directory names
        self.assertLess(elapsed, 5.0)  # generous bound: the point is no stall

    def test_a_trailing_slash_reference_is_read_as_a_directory(self):
        sha = self.commit_table({"cue": {"dir": "audio/", "ghost": "nope/"}},
                                extra_files={"audio/cue.ogg": "c"})
        seen = self.check(sha)
        self.assertEqual(seen.status_code, 200, seen.text)
        body = seen.json()
        self.assertFalse(body["ok"])  # nope/ names no tracked directory
        self.assertEqual([m["ref"] for m in body["missing"]], ["nope/"])
        self.assertEqual(body["checked"], 2)

    def test_res_scheme_references_are_checked_through_a_mapped_root(self):
        # Godot tables spell paths res://…: without a mapping the out/ incident
        # passes unnoticed, so res: enters only through res_roots and is
        # resolved under its tree prefix; user:// stays out either way
        sha = self.commit_table({
            "cue": {"file": "res://audio/mapped.ogg", "alt": "user://cache/x.ogg"},
        }, extra_files={"game/audio/mapped.ogg": "sound"})
        seen = self.check(sha, res_roots={"res://": "game/"})
        self.assertEqual(seen.status_code, 200, seen.text)
        self.assertTrue(seen.json()["ok"])
        self.assertEqual(seen.json()["checked"], 1)  # user:// never counted
        sha = self.commit_table({"cue": {"file": "res://audio/missing.ogg"}},
                                extra_files={"game/audio/mapped.ogg": "sound"})
        seen = self.check(sha, res_roots={"res://": "game/"})
        body = seen.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["missing"][0]["ref"], "res://audio/missing.ogg")
        self.assertEqual(body["missing"][0]["file"], "data/cues.json")

    def test_table_relative_and_directory_references_count_as_present(self):
        # tables reference files relative to themselves, and sometimes name a
        # directory: both shapes are normal, neither is a finding
        sha = self.commit_table({
            "beside": {"file": "voice.ogg"},          # data/voice.ogg
            "up": {"file": "../shared/sub.ogg"},      # shared/sub.ogg
            "folder": {"dir": "audio"},               # a tracked directory
        }, extra_files={"data/voice.ogg": "v", "shared/sub.ogg": "s",
                        "audio/cue.ogg": "c"})
        seen = self.check(sha)
        self.assertEqual(seen.status_code, 200, seen.text)
        self.assertTrue(seen.json()["ok"], seen.json())
        self.assertEqual(seen.json()["checked"], 3)

    def test_check_ignore_probes_the_subtree_line_s_own_checkout(self):
        # a cross-repository check must read the ignore rules of the checkout
        # that actually holds the files, not the calling line's other project
        other = os.path.join(self.directory.name, "other")
        os.makedirs(other)
        _git("init", "-q", "-b", "main", cwd=other)
        port = os.path.join(other, ".partyline-worktrees", "port")
        os.makedirs(port)
        self.db.create_conversation("port", "Port")
        self.db._exec("UPDATE conversations SET parent_id=?, cwd=? WHERE id='port'",
                      (self.kid["id"], port))
        with open(os.path.join(other, ".gitignore"), "w") as fh:
            fh.write("out/\n")
        os.makedirs(os.path.join(other, "data"), exist_ok=True)
        with open(os.path.join(other, "data", "cues.json"), "w") as fh:
            json.dump({"cue": {"file": "out/built.ogg"}}, fh)
        _git("add", "-A", cwd=other)
        _identity("commit", "-q", "-m", "table in the other repo", cwd=other)
        sha = _git("rev-parse", "HEAD", cwd=other).stdout.strip()
        seen = self.check(sha, repository=other)
        self.assertEqual(seen.status_code, 200, seen.text)
        body = seen.json()
        self.assertFalse(body["ok"])
        self.assertEqual(len(body["missing"]), 1)
        self.assertTrue(body["missing"][0]["ignored"])


if __name__ == "__main__":
    unittest.main()
