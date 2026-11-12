"""A throwaway Partyline world for measuring the context it puts into processes.

Temp database only. It holds a root captain, a task with an implementer and a
reviewer, a sub-captain, a plain participant, and a backlog of retired task lines,
so every role sees what it would see in a busy week.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time

from partyline.auth_guard import Principal
from partyline.db import Db
from partyline.machine_scope import capability_state

GOAL = ("Cut the context partyline itself puts into every attached process. " * 12).strip()


def git(cwd: str, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],
                   cwd=cwd, capture_output=True, check=True)


class World:
    """Rows are created directly: the measuring code reads them, never a live server."""

    def __init__(self, retired: int = 14):
        self.dir = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.dir.name, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "root")
        self.db = Db(os.path.join(self.dir.name, "measure.db"))
        db = self.db
        db.create_conversation("root", "partyline dev")
        db._exec("UPDATE conversations SET cwd=?,goal=? WHERE id='root'", (self.repo, GOAL))
        self.attach("cap", "root", "fable-api-oc", lead=True, adapter="opencode-v2")
        for name, caps in (("terra", True), ("luna", False), ("sonnet", False), ("opus", False)):
            db.save_preset(name, name, name, "fake", "fake", can_manage=caps, implements=not caps)
        self.task("task1", retired=False)
        for index in range(retired):
            self.task(f"old{index}", retired=True)
        db.create_conversation("sub", "sub-captain", "manager_tree")
        db._exec("UPDATE conversations SET parent_id='root',cwd=? WHERE id='sub'", (self.repo,))
        self.attach("subcap", "sub", "sub-captain", lead=True, adapter="claude")
        self.attach("worker", "sub", "sub-worker", adapter="codex")

    def attach(self, ident, conv, name, *, lead=False, adapter="opencode-v2", status="running"):
        self.db.add_attachment(ident, conv, name, adapter, [adapter], self.repo, f"owner-{ident}")
        self.db._exec("UPDATE attachments SET is_lead=?,status=? WHERE id=?",
                      (int(lead), status, ident))

    def task(self, conv, *, retired):
        db = self.db
        db.create_conversation(conv, f"task {conv}", "manager_tree")
        db._exec("UPDATE conversations SET parent_id='root',cwd=?,goal=? WHERE id=?",
                 (self.repo, GOAL, conv))
        impl, rev = f"impl-{conv}", f"rev-{conv}"
        status = "done" if retired else "implementing"
        self.attach(impl, conv, f"impl-{conv[:6]}", status="exited" if retired else "running")
        self.attach(rev, conv, f"review-{conv[:6]}", status="exited" if retired else "running")
        db._exec("INSERT INTO task_reviews(conv_id,root_id,implementer_id,implementer_preset,"
                 "reviewer_id,policy,tag,created_at,mode,status,what,location,findings) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (conv, "root", impl, "opus", rev, "adversarial", conv[:6], time.time(), "full", status,
                  "ship the change " * 20, "partyline/x.py " * 10, "finding " * 60))
        if retired:
            db._exec("UPDATE conversations SET archived_at=?,accepted_sha=? WHERE id=?",
                     (time.time(), "9f3c1a07d2b84e65a1c0" * 2, conv))

    def principal(self, att_id: str) -> Principal:
        att = self.db.get_attachment(att_id)
        return Principal(kind="machine", name=att["name"], conv_id=att["conv_id"],
                         attachment_id=att_id, is_lead=bool(att["is_lead"]))

    def state(self, att_id: str) -> dict:
        return capability_state(self.db, self.principal(att_id))

    def close(self):
        self.db.close()
        self.dir.cleanup()
