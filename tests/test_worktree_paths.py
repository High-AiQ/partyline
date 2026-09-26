import unittest

from partyline.worktree_paths import branch_name, managed_root


class WorktreePathTest(unittest.TestCase):
    def test_native_windows_uses_private_ref_directory_and_handles_separators(self):
        for path in ('C:/projects/game/.partyline-worktrees/art',
                     'C:\\projects\\game\\.partyline-worktrees\\art\\'):
            self.assertEqual(branch_name(path, 'win32'), 'line/art/work')
            self.assertEqual(managed_root(path, 'win32'), 'C:/projects/game')

    def test_posix_names_and_literal_backslashes_are_preserved(self):
        self.assertEqual(branch_name('/repo/.partyline-worktrees/art/', 'linux'), 'line/art')
        self.assertEqual(managed_root('/a\\b/.partyline-worktrees/art', 'linux'), '/a\\b')
        self.assertIsNone(managed_root('/a/.partyline-worktrees-other/art', 'linux'))
