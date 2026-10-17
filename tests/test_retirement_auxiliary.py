"""Forced retirement removes debris; dirty auxiliary work has a bounded lifecycle."""

import asyncio
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from partyline.conversation_purge import execute_purge
from partyline.media import MediaStore
from tests import test_retirement_force as base


class RetirementAuxiliaryTest(unittest.TestCase):
    setUp = base.ForcedRetirementTest.setUp
    child = base.ForcedRetirementTest.child
    preview = base.ForcedRetirementTest.preview
    force = base.ForcedRetirementTest.force
    retire = base.ForcedRetirementTest.retire

    def auxiliary(self, child, dirty=False):
        sha = base._git("rev-parse", "HEAD", cwd=self.repo).stdout.strip()
        paths = {}
        for folder, table in ((".review", "review_worktrees"), (".scratch", "scratch_worktrees")):
            path = os.path.join(self.repo, folder, sha)
            base._git("worktree", "add", "--detach", path, sha, cwd=self.repo)
            self.db._exec(f"INSERT INTO {table}(path,conv_id,sha,created_at) VALUES(?,?,?,0)",
                          (path, child["id"], sha))
            if dirty:
                Path(path, "unfinished").write_text("retain")
            paths[table] = path
        return paths

    def preserved_count(self):
        return self.db._exec("SELECT count(*) FROM retirement_preserved_paths").fetchone()[0]

    def test_clean_auxiliary_worktrees_are_pruned_and_stale_exemptions_cleared(self):
        child = self.child()
        paths = self.auxiliary(child)
        for path in paths.values():
            self.db._exec("INSERT INTO retirement_preserved_paths VALUES(?,'old')", (path,))
        line = self.preview(child).json()["lines"][0]
        self.assertTrue(all(not rows for rows in line["auxiliary_worktrees_preserved"].values()))
        self.assertEqual({p for rows in line["auxiliary_worktrees_pruned"].values() for p in rows},
                         set(paths.values()))
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["preserved_paths"], [])
        self.assertEqual(self.preserved_count(), 0)
        for table, path in paths.items():
            self.assertFalse(os.path.exists(path))
            self.assertEqual(self.db._exec(f"SELECT count(*) FROM {table}").fetchone()[0], 0)

    def test_dirty_auxiliary_work_is_preserved_reported_and_purge_releases_exemptions(self):
        child = self.child()
        paths = self.auxiliary(child, dirty=True)
        response = self.force(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(set(response.json()["preserved_paths"]), set(paths.values()))
        self.assertEqual(self.preserved_count(), 2)
        audit = json.loads(self.db._exec("SELECT evidence FROM retirement_audit").fetchone()[0])
        for table, path in paths.items():
            self.assertIn(path, audit["plan"]["lines"][0]["auxiliary_worktrees_preserved"][table])
            self.assertEqual(Path(path, "unfinished").read_text(), "retain")
        media = MediaStore(self.db, self.directory.name + "/media")
        asyncio.run(execute_purge(self.runtime, media, self.db, self.db.get_conversation(child["id"])))
        self.assertEqual(self.preserved_count(), 0)
        for path in paths.values():
            self.assertFalse(os.path.exists(path))

    def test_repeated_retirement_reassesses_paths_without_accumulating_exemptions(self):
        child = self.child()
        paths = self.auxiliary(child, dirty=True)
        for _ in range(2):
            self.assertEqual(self.force(child).status_code, 200)
            self.assertEqual(self.preserved_count(), 2)
            self.db.restore_conversation(child["id"])
        for path in paths.values():
            Path(path, "unfinished").unlink()
        self.assertEqual(self.force(child).status_code, 200)
        self.assertEqual(self.preserved_count(), 0)
        for path in paths.values():
            self.assertFalse(os.path.exists(path))

    def test_explicit_scratch_drop_clears_exemption(self):
        from partyline.scratch_worktrees import drop_scratch_worktree

        child = self.child()
        paths = self.auxiliary(child, dirty=True)
        self.assertEqual(self.force(child).status_code, 200)
        sha = os.path.basename(paths["scratch_worktrees"])
        drop_scratch_worktree(self.db, child["id"], sha)
        self.assertEqual(self.preserved_count(), 1)
        self.assertFalse(os.path.exists(paths["scratch_worktrees"]))

    def test_failed_snapshot_creates_no_sweep_exemptions(self):
        child = self.child()
        self.auxiliary(child, dirty=True)
        with patch("partyline.retirement_force.snapshot", side_effect=HTTPException(409, "snapshot failed")):
            self.assertEqual(self.force(child).status_code, 409)
        self.assertEqual(self.preserved_count(), 0)

    def test_newly_dirty_auxiliary_work_invalidates_preview(self):
        child = self.child()
        paths = self.auxiliary(child)
        token = self.preview(child).json()["preview_token"]
        Path(paths["review_worktrees"], "unfinished").write_text("new")
        response = self.retire(child["id"], force_discard=True, preview_token=token)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(os.path.isdir(child["cwd"]))
        self.assertEqual(Path(paths["review_worktrees"], "unfinished").read_text(), "new")

    def test_failed_auxiliary_cleanup_stops_recursive_retirement(self):
        child = self.child()
        grand = self.child("grand", child["id"])
        self.auxiliary(grand)
        with patch("partyline.retirement_auxiliary.remove_review_path", return_value=False):
            response = self.force(child, include_children=True)
        self.assertEqual(response.status_code, 409)
        self.assertIn("auxiliary worktree cleanup failed", response.text)
        self.assertEqual(response.json()["archived_ids"], [])
        self.assertTrue(os.path.isdir(child["cwd"]))

    def test_legacy_temp_sweep_runs_once_for_recursive_force(self):
        child = self.child()
        self.child("grand", child["id"])
        with patch("partyline.retirement_force.reap_legacy_temp") as sweep:
            self.assertEqual(self.force(child, include_children=True).status_code, 200)
        sweep.assert_called_once_with(self.db)
