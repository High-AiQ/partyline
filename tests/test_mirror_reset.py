"""Detached attachments must preserve the shared line branch mirror."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from partyline import fence_paths, fence_workspaces, git_fence
from partyline.db import Db
from tests.test_fence import _git, _identity, _worktree_fixture


class MirrorResetTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.fix = _worktree_fixture(temp.name)
        self.primary = str(Path(self.fix['repo']) / '.partyline-worktrees/demo')
        Path(self.primary).parent.mkdir()
        _git('worktree', 'move', self.fix['line_wt'], self.primary, cwd=self.fix['repo'])
        self.common = Path(git_fence.common_gitdir(git_fence._worktree_gitdir(self.primary)))
        self.review = str(self.root / 'review')
        _git('worktree', 'add', '--detach', self.review, 'HEAD', cwd=self.fix['repo'])
        self.patch = patch.object(git_fence, 'FENCE_ROOT', str(self.root / 'fence'))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.mirror = Path(git_fence.refresh_mirror(
            str(self.common), git_fence._worktree_gitdir(self.primary), 'conv'))
        self.ref = 'refs/heads/line/demo'
        self.base = _git('rev-parse', 'HEAD', cwd=self.primary).stdout.strip()
        _identity('commit', '-q', '--allow-empty', '-m', 'new object', cwd=self.fix['repo'])
        self.tip = _git('rev-parse', 'HEAD', cwd=self.fix['repo']).stdout.strip()

    def refresh(self):
        git_fence.refresh_mirror(str(self.common), git_fence._worktree_gitdir(self.review),
                                 'conv', protected='line/demo')

    def test_detached_refresh_preserves_loose_ref_packed_entry_and_reflog(self):
        (self.mirror / self.ref).write_text(self.tip + '\n')
        packed = f'{self.tip} {self.ref}\n'
        (self.mirror / 'packed-refs').write_text(packed)
        log = self.mirror / 'logs' / self.ref
        log.write_text('mirror commit reflog\n')
        self.refresh()
        self.assertEqual((self.mirror / self.ref).read_text(), self.tip + '\n')
        self.assertEqual((self.mirror / 'packed-refs').read_text(), packed)
        self.assertEqual(log.read_text(), 'mirror commit reflog\n')
        self.assertEqual((self.mirror / 'refs/heads/main').read_text(), self.tip + '\n')
        self.assertEqual((self.mirror / 'logs/refs/heads/main').read_bytes(),
                         (self.common / 'logs/refs/heads/main').read_bytes())

    def test_detached_refresh_preserves_packed_only_branch(self):
        _git('pack-refs', '--all', cwd=self.fix['repo'])
        (self.mirror / self.ref).unlink()
        packed = f'{self.tip} {self.ref}\n'
        (self.mirror / 'packed-refs').write_text(packed)
        self.refresh()
        self.assertEqual(git_fence._read_ref(str(self.mirror), self.ref), self.tip)
        self.assertIn(packed, (self.mirror / 'packed-refs').read_text())
        self.assertEqual(git_fence._read_ref(str(self.common), self.ref), self.base)

    def test_reviewer_write_set_loads_and_passes_primary_line_branch(self):
        db = Db(str(self.root / 'test.db'))
        self.addCleanup(db.close)
        db.create_conversation('conv', 'line')
        db._exec('UPDATE conversations SET cwd=? WHERE id=?', (self.primary, 'conv'))
        att = {'cwd': self.review, 'conv_id': 'conv'}
        fence_workspaces.load(db, att)
        with patch.object(git_fence, 'git_binds', return_value=[]) as binds:
            fence_paths.write_set(att, create=False)
        binds.assert_called_once_with(self.review, 'conv', protected='line/demo')
        self.assertEqual(att['line_branch'], 'line/demo')

    def test_packed_only_mirror_beats_real_loose_branch(self):
        (self.mirror / self.ref).unlink()
        packed = f'{self.tip} {self.ref}\n'
        (self.mirror / 'packed-refs').write_text(packed)
        self.refresh()
        self.assertEqual(git_fence._read_ref(str(self.mirror), self.ref), self.tip)
        self.assertFalse((self.mirror / self.ref).exists())
        self.assertEqual((self.mirror / 'packed-refs').read_text(), packed)

    def test_triggering_head_and_line_branch_are_both_protected(self):
        sibling = self.fix['sibling_wt']
        sibling_ref = 'refs/heads/line/sibling'
        (self.mirror / self.ref).write_text(self.tip + '\n')
        (self.mirror / sibling_ref).write_text(self.tip + '\n')
        git_fence.refresh_mirror(str(self.common), git_fence._worktree_gitdir(sibling),
                                 'conv', protected='line/demo')
        for ref in (self.ref, sibling_ref):
            self.assertEqual(git_fence._read_ref(str(self.mirror), ref), self.tip)

    def test_packed_merge_refreshes_siblings_and_keeps_peeled_tag(self):
        tag = 'refs/tags/annotated'
        (self.common / 'packed-refs').write_text(
            f'# pack-refs with: peeled sorted\n{self.base} {self.ref}\n'
            f'{self.tip} {tag}\n^{self.base}\n')
        (self.mirror / self.ref).unlink()
        (self.mirror / 'packed-refs').write_text(f'{self.tip} {self.ref}\n')
        self.refresh()
        packed = (self.mirror / 'packed-refs').read_text()
        self.assertIn(f'{self.tip} {self.ref}\n', packed)
        self.assertIn(f'{self.tip} {tag}\n^{self.base}\n', packed)

    def test_protected_ref_symlink_is_replaced_without_writing_target(self):
        target = self.root / 'target'
        target.write_text(self.tip + '\n')
        ref = self.mirror / self.ref
        ref.unlink()
        ref.symlink_to(target)
        self.refresh()
        self.assertFalse(ref.is_symlink())
        self.assertEqual(ref.read_text(), self.base + '\n')
        self.assertEqual(target.read_text(), self.tip + '\n')

    def test_symlinked_packed_refs_cannot_supply_a_protected_tip(self):
        _git('pack-refs', '--all', cwd=self.fix['repo'])
        (self.mirror / self.ref).unlink()
        target = self.root / 'packed-target'
        content = f'{self.tip} {self.ref}\n'
        target.write_text(content)
        (self.mirror / 'packed-refs').symlink_to(target)
        self.refresh()
        self.assertEqual(git_fence._read_ref(str(self.mirror), self.ref), self.base)
        self.assertFalse((self.mirror / 'packed-refs').is_symlink())
        self.assertEqual(target.read_text(), content)

    def test_write_set_decision_preserves_detached_leads_line_branch(self):
        from types import SimpleNamespace
        from partyline.write_set_decisions import _machine_decision_error

        db = Db(str(self.root / 'decision.db'))
        self.addCleanup(db.close)
        db.create_conversation('conv', 'captain')
        db.create_conversation('child', 'child')
        db._exec('UPDATE conversations SET cwd=? WHERE id=?', (self.primary, 'conv'))
        db._exec('UPDATE conversations SET parent_id=? WHERE id=?', ('conv', 'child'))
        db.add_attachment('lead', 'conv', 'captain', 'fake', ['fake'], self.review)
        db._exec("UPDATE attachments SET is_lead=1, status='running' WHERE id='lead'")
        (self.mirror / self.ref).write_text(self.tip + '\n')
        log = self.mirror / 'logs' / self.ref
        log.write_text('unpublished commit\n')
        principal = SimpleNamespace(is_lead=True, conv_id='conv', attachment_id='lead')
        request = SimpleNamespace(path=self.review, requester_attachment_id='child-worker')
        self.assertIsNone(_machine_decision_error(db, principal, 'child', request))
        self.assertEqual(git_fence._read_ref(str(self.mirror), self.ref), self.tip)
        self.assertEqual(log.read_text(), 'unpublished commit\n')

    def test_missing_line_cwd_does_not_protect_parent_or_attachment_branch(self):
        db = Db(str(self.root / 'unplaced.db'))
        self.addCleanup(db.close)
        db.create_conversation('parent', 'parent')
        db.create_conversation('child', 'child')
        db._exec('UPDATE conversations SET cwd=? WHERE id=?', (self.primary, 'parent'))
        db._exec('UPDATE conversations SET parent_id=? WHERE id=?', ('parent', 'child'))
        for source in ('parent', 'attachment'):
            with self.subTest(source=source):
                if source == 'attachment':
                    db.add_attachment('worker', 'child', 'worker', 'fake', ['fake'], self.primary)
                att = {'cwd': self.review, 'conv_id': 'child'}
                fence_workspaces.load(db, att)
                self.assertIsNone(att['line_branch'])

    def test_packed_merge_skips_malformed_records(self):
        from partyline.git_fence_packed import merged_packed_refs

        (self.common / 'packed-refs').write_text(
            f'garbage\ninvalid refs/heads/bad\n{self.base} refs/heads/main\n')
        packed = merged_packed_refs(str(self.common), str(self.mirror), set())
        self.assertEqual(packed, f'{self.base} refs/heads/main\n')

    def test_packed_merge_normalizes_unterminated_last_entry(self):
        from partyline.git_fence_packed import merged_packed_refs

        (self.common / 'packed-refs').write_text(f'{self.base} refs/heads/main')
        packed = merged_packed_refs(str(self.common), str(self.mirror), set())
        self.assertEqual(packed, f'{self.base} refs/heads/main\n')

    def test_unterminated_real_protected_entry_is_seeded_on_first_refresh(self):
        _git('pack-refs', '--all', cwd=self.fix['repo'])
        (self.common / 'packed-refs').write_text(f'{self.base} {self.ref}')
        (self.mirror / self.ref).unlink()
        self.refresh()
        self.assertEqual(git_fence._read_ref(str(self.mirror), self.ref), self.base)
