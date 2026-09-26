import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from partyline import windows_fence as fence


class WindowsFencePolicyTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.allowed = self.root / 'allowed'
        self.allowed.mkdir()
        self.protected = self.root / 'protected'
        self.protected.mkdir()
        (self.protected / 'data').write_text('protected')
        self.token = MagicMock()
        self.calls = []
        for name, replacement in (
            ('create_token', MagicMock(return_value=(self.token, 'unique-sid'))),
            ('edit_grant', MagicMock(side_effect=lambda p, *a, **kw: self.calls.append((p, kw)))),
            ('can_access', MagicMock(return_value=False)),
        ):
            change = patch.object(fence, name, replacement)
            setattr(self, name, change.start())
            self.addCleanup(change.stop)

    def test_grants_do_not_touch_protected_paths_and_cleanup_includes_new_children(self):
        scope = fence.WindowsFence([self.allowed], [self.protected])
        self.assertTrue(all(p == self.allowed for p, _ in self.calls))
        child = self.allowed / 'new'
        child.write_text('new')
        scope.close()
        scope.close()
        self.assertIn((child, {'remove': True}), self.calls)
        self.token.Close.assert_called_once()

    def test_parent_delete_permission_refuses_launch_and_cleans_grants(self):
        self.can_access.side_effect = lambda token, path, right: path == self.root and right == 0x40
        with self.assertRaisesRegex(OSError, 'ancestor'):
            fence.WindowsFence([self.allowed], [self.protected])
        self.token.Close.assert_called_once()
        self.assertIn((self.allowed, {'remove': True}), self.calls)

    def test_any_protected_write_permission_refuses_launch(self):
        for right in fence.WRITE_RIGHTS:
            self.can_access.side_effect = (
                lambda token, path, bit, wanted=right: path.name == 'data' and bit == wanted
            )
            with self.assertRaisesRegex(OSError, 'cannot protect'):
                fence.WindowsFence([self.allowed], [self.protected])

    def test_broad_grant_is_rejected_before_permissions_change(self):
        with self.assertRaisesRegex(OSError, 'contains a protected'):
            fence.WindowsFence([self.root], [self.protected])
        self.create_token.assert_not_called()
        with self.assertRaisesRegex(OSError, 'existing directory'):
            fence.WindowsFence([self.root / 'missing'], [self.protected])

    def test_carveout_inside_a_protected_tree_can_be_writable(self):
        carveout = self.protected / 'line'
        carveout.mkdir()
        self.can_access.side_effect = lambda token, path, right: path == carveout
        scope = fence.WindowsFence([carveout], [self.protected])
        scope.close()

    @unittest.skipIf(os.name == 'nt', 'symlink creation can require Windows developer mode')
    def test_walk_does_not_follow_links_into_other_trees(self):
        (self.allowed / 'alias').symlink_to(self.protected, target_is_directory=True)
        self.assertEqual(list(fence.paths(self.allowed)), [self.allowed])

    def test_cleanup_failure_is_reported(self):
        scope = fence.WindowsFence([self.allowed], [self.protected])
        self.edit_grant.side_effect = OSError('permission changed')
        with self.assertRaisesRegex(OSError, 'cleanup failed'):
            scope.close()

    def test_component_boundaries_are_not_prefixes(self):
        self.assertFalse(fence.contains(self.allowed, self.root / 'allowed-other'))
