"""An empty merged orphan is removed by the server outside the CLI fence."""

from pathlib import Path
import shutil
import unittest

from tests.test_retirement_safety import SafetyFixture, _git


class EmptyOrphanRetirementTest(SafetyFixture, unittest.TestCase):
    def empty_orphan(self):
        child = self.child()
        cwd = Path(child['cwd'])
        metadata = _git('rev-parse', '--absolute-git-dir', cwd=str(cwd)).stdout.strip()
        shutil.rmtree(metadata)
        # .git is a dangling link file; only an empty fence mount remains.
        (cwd / 'node_modules').mkdir()
        return child, cwd

    def test_preview_and_retirement_remove_merged_empty_dangling_worktree(self):
        child, cwd = self.empty_orphan()
        response = self.preview(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(cwd.exists(), 'preview must not remove files')
        response = self.retire(child['id'])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(cwd.exists(), response.text)

    def test_unmerged_empty_orphan_still_refuses_without_fenced_rm_advice(self):
        child = self.child()
        _git('commit', '--allow-empty', '-qm', 'not merged', cwd=child['cwd'])
        metadata = _git('rev-parse', '--absolute-git-dir', cwd=child['cwd']).stdout.strip()
        shutil.rmtree(metadata)
        response = self.preview(child)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertNotIn('rm -rf', response.text)

    def test_plain_task_container_retires_its_empty_dangling_workspace(self):
        child = self.child()
        cwd = Path(child['cwd'])
        metadata = _git('rev-parse', '--absolute-git-dir', cwd=str(cwd)).stdout.strip()
        # A plain task container under a non-repository captain directory.
        _git('worktree', 'remove', '--force', str(cwd), cwd=self.repo)
        parent = Path(self.directory.name) / 'projects'
        parent.mkdir()
        cwd = parent / '.partyline-worktrees' / 'task'
        cwd.mkdir(parents=True)
        nested = cwd / 'argon-frontend'
        branch = 'line/task'
        _git('worktree', 'add', '-qb', branch, str(nested), cwd=self.repo)
        metadata = _git('rev-parse', '--absolute-git-dir', cwd=str(nested)).stdout.strip()
        shutil.rmtree(metadata)
        (nested / 'node_modules').mkdir()
        head = _git('rev-parse', 'HEAD', cwd=self.repo).stdout.strip()
        self.db._exec('UPDATE conversations SET cwd=? WHERE id=?', (str(cwd), child['id']))
        self.db._exec('INSERT INTO task_workspaces VALUES(?,?,?,?,?)',
                      (child['id'], self.repo, str(nested), branch, head))
        child = self.db.get_conversation(child['id'])
        response = self.preview(child)
        self.assertEqual(response.status_code, 200, response.text)
        response = self.retire(child['id'])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(cwd.exists(), response.text)

    def test_pruned_checkout_still_checks_unmerged_private_mirror_tip(self):
        from unittest.mock import patch
        from partyline import git_fence

        child = self.child()
        cwd = Path(child['cwd'])
        base = _git('rev-parse', 'main', cwd=self.repo).stdout.strip()
        _git('commit', '--allow-empty', '-qm', 'private unmerged work', cwd=str(cwd))
        tip = _git('rev-parse', 'HEAD', cwd=str(cwd)).stdout.strip()
        _git('update-ref', 'refs/heads/line/mid', base, cwd=self.repo)
        metadata = _git('rev-parse', '--absolute-git-dir', cwd=str(cwd)).stdout.strip()
        shutil.rmtree(metadata)
        common = _git('rev-parse', '--absolute-git-dir', cwd=self.repo).stdout.strip()
        with patch.object(git_fence, 'FENCE_ROOT', str(Path(self.directory.name) / 'fence')):
            mirror = Path(git_fence._mirror_dir(common, child['id']))
            ref = mirror / 'refs/heads/line/mid'
            ref.parent.mkdir(parents=True)
            ref.write_text(tip + '\n')
            response = self.preview(child)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertTrue(cwd.exists())
