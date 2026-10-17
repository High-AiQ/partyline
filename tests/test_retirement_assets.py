"""Retirement preserves assets and excludes overlapping service mutations."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from partyline.media import MediaStore
from partyline.media_files import prepared_files
from partyline.retirement_force import admission
from tests import test_retirement_force as base


class RetirementAssetsTest(unittest.TestCase):
    setUp = base.ForcedRetirementTest.setUp
    child = base.ForcedRetirementTest.child
    preview = base.ForcedRetirementTest.preview
    force = base.ForcedRetirementTest.force
    retire = base.ForcedRetirementTest.retire

    def test_uploaded_original_and_message_survive_force(self):
        child = self.child()
        media = MediaStore(self.db, self.directory.name + "/media")
        message = self.db.add_message(child["id"], "person", "human", "deliverable")
        stored = media.store(child["id"], message["id"],
                             prepared_files([(b"durable asset", "result.txt", "text/plain")]), None, None)
        before = media.file_for(stored[0].id, "original")
        self.assertEqual(self.preview(child).json()["lines"][0]["uploads_preserved"], 1)
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(Path(before[0]).read_bytes(), b"durable asset")
        self.assertEqual(len(media.list_conversation(child["id"])), 1)
        self.assertTrue(any(m["body"] == "deliverable" for m in self.db.list_messages(child["id"])))
        audit = self.db._exec("SELECT id FROM retirement_audit").fetchone()[0]
        self.db.delete_conversation(child["id"])
        self.assertIsNotNone(self.db._exec("SELECT id FROM retirement_audit WHERE id=?", (audit,)).fetchone())

    def test_private_temporary_directory_is_reaped(self):
        child = self.child()
        self.db.add_attachment("worker", child["id"], "worker", "fake", ["fake"], child["cwd"])
        self.db._exec("UPDATE attachments SET status='detached' WHERE id='worker'")
        root = Path(self.directory.name) / "partyline" / "instance"
        path = root / "worker"
        path.mkdir(parents=True)
        (path / "asset").write_bytes(b"unique")
        with patch("partyline.attachment_tmp.base_dir", return_value=root):
            self.assertEqual(self.preview(child).json()["lines"][0]["temporary_directories"], [str(path)])
            response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(path.exists())

    def test_admission_blocks_child_creation_goal_changes_and_archive(self):
        child = self.child()
        with admission(self.db, child["id"], False):
            with self.assertRaises(HTTPException):
                with admission(self.db, child["id"], False):
                    self.fail("overlap admitted")
            response = self.client.post(f"/api/conversations/{child['id']}/children",
                                        json={"name": "new"}, headers=self.human)
            self.assertEqual(response.status_code, 409)
            response = self.client.put(f"/api/conversations/{child['id']}/goal",
                                       json={"goal": "new"}, headers=self.captain)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(self.retire(child["id"]).status_code, 409)
        self.assertFalse(self.db.retiring_lines)
        self.assertEqual(self.force(child).status_code, 200)

    def test_failed_validation_releases_admission_guard(self):
        child = self.child()
        response = self.retire(child["id"], force_discard=True, preview_token="invalid")
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.db.retiring_lines)
        self.assertTrue(os.path.isdir(child["cwd"]))

    def test_default_recursive_retirement_checks_descendant_dirty_state(self):
        child = self.child()
        grand = self.child("grand", child["id"])
        Path(grand["cwd"], "asset").write_bytes(b"unfinished")
        self.db._exec("UPDATE conversations SET goal='pending' WHERE id=?", (grand["id"],))
        response = self.retire(child["id"], include_children=True, clear_goal=True)
        self.assertEqual(response.status_code, 409)
        self.assertIn("uncommitted_changes", response.text)
        self.assertEqual(self.db.get_conversation(grand["id"])["goal"], "pending")
        response = self.retire(child["id"], include_children=True, clear_goal=True, discard=True)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.db.get_conversation(grand["id"])["goal"], "")
        self.assertFalse(os.path.isdir(grand["cwd"]))

    def test_force_refuses_over_limit_state_before_snapshot(self):
        child = self.child()
        token = self.preview(child).json()["preview_token"]
        Path(child["cwd"], "asset").write_bytes(b"oversized")
        with patch("partyline.retirement_git.MAX_BYTES", 1), \
                patch("partyline.retirement_force.snapshot") as snapshot:
            response = self.retire(child["id"], force_discard=True, preview_token=token)
        self.assertEqual(response.status_code, 409)
        snapshot.assert_not_called()
        self.assertTrue(Path(child["cwd"], "asset").is_file())

    def test_shared_checkout_is_never_removed(self):
        self.db.create_conversation("shared", "Shared")
        self.db._exec("UPDATE conversations SET parent_id='root',cwd=? WHERE id='shared'", (self.repo,))
        child = self.db.get_conversation("shared")
        Path(self.repo, "asset").write_bytes(b"keep")
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["worktree_removed"])
        self.assertEqual(Path(self.repo, "asset").read_bytes(), b"keep")

    def test_ignored_dependency_metadata_has_separate_bounded_budget(self):
        child = self.child()
        Path(child["cwd"], ".gitignore").write_text("dependencies/\n")
        directory = Path(child["cwd"], "dependencies")
        directory.mkdir()
        for i in range(3):
            (directory / str(i)).write_bytes(b"dependency")
        with patch("partyline.retirement_git.MAX_FILES", 1):
            response = self.preview(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["lines"][0]["git"]["ignored"]["count"], 3)
        for limit in ("MAX_IGNORED_FILES", "MAX_IGNORED_BYTES"):
            with patch(f"partyline.retirement_git.{limit}", 1):
                self.assertEqual(self.preview(child).status_code, 409)

    def test_subtree_limits_are_enforced_before_building_an_unbounded_plan(self):
        child = self.child()
        grand = self.child("grand", child["id"])
        for line in (child, grand):
            Path(line["cwd"], "asset").write_bytes(b"dirty")
        with patch("partyline.retirement_preview.MAX_FILES", 1):
            response = self.preview(child, recursive=True)
        self.assertEqual(response.status_code, 409)
        self.assertIn("subtree exceeds", response.text)
