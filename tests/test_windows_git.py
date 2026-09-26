import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from partyline.windows_git import write_paths
from partyline.windows_fence import WindowsFence
from partyline.windows_console import WindowsConsole


class WindowsGitPathsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='partyline git ')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name, 'repo').resolve()
        self.root.mkdir()
        if sys.platform == 'win32':
            from partyline.windows_private import secure_directory
            secure_directory(self.root)
        self.git('init', '-q', '-b', 'main')
        (self.root / 'protected').write_text('root')
        self.git('add', '.')
        self.git('-c', 'user.name=fixture', '-c', 'user.email=fixture@example.test',
                 'commit', '-qm', 'root')
        self.work = self.root / '.partyline-worktrees' / 'art'
        self.git('worktree', 'add', '-b', 'line/art/work', str(self.work))
        self.att = {'cwd': str(self.work), 'conv_id': 'fixture'}

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, capture_output=True,
                              text=True, check=True).stdout.strip()

    def test_grants_include_own_refs_and_objects_but_not_shared_refs_or_config(self):
        with patch('partyline.worktree_paths.sys.platform', 'win32'):
            allowed = {Path(path).resolve() for path in write_paths(self.att)}
        self.assertIn(self.work.resolve(), allowed)
        self.assertIn(self.root / '.git' / 'objects', allowed)
        self.assertIn(self.root / '.git' / 'refs' / 'heads' / 'line' / 'art', allowed)
        self.assertNotIn(self.root / '.git', allowed)
        self.assertNotIn(self.root / '.git' / 'refs', allowed)

    def test_unassigned_branch_refuses_instead_of_granting_sibling_directory(self):
        self.git('-C', str(self.work), 'switch', '-c', 'unassigned')
        with patch('partyline.worktree_paths.sys.platform', 'win32'):
            with self.assertRaisesRegex(OSError, 'branch assigned'):
                write_paths(self.att)


@unittest.skipUnless(sys.platform == 'win32', 'native Git filesystem fence')
class NativeWindowsGitTest(WindowsGitPathsTest, unittest.IsolatedAsyncioTestCase):
    async def test_child_commits_without_writing_parent_files_or_refs(self):
        before = self.git('rev-parse', 'main')
        scope = WindowsFence(write_paths(self.att), [self.root])
        code = (
            'import pathlib,subprocess,sys\n'
            'root=pathlib.Path(sys.argv[1]); pathlib.Path("child").write_text("child")\n'
            'def git(*args): return subprocess.run(["git",*args],capture_output=True,text=True)\n'
            'assert git("add","child").returncode==0\n'
            'r=git("-c","user.name=fixture","-c","user.email=fixture@example.test",'
            '"-c","gc.auto=0","commit","-qm","child"); assert r.returncode==0,r.stderr\n'
            'assert git("update-ref","refs/heads/main","HEAD").returncode!=0\n'
            'try:\n (root/"protected").write_text("escaped")\n'
            'except PermissionError: pass\n'
            'else: raise AssertionError("parent checkout writable")\n'
        )
        try:
            console = await WindowsConsole.spawn(
                [sys.executable, '-u', '-c', code, str(self.root)], str(self.work),
                dict(os.environ), 256 * 1024**2, token=scope.token,
            )
            try:
                self.assertEqual(await asyncio.wait_for(console.wait(), 30), 0)
            finally:
                await console.close()
            self.assertEqual(self.git('rev-parse', 'main'), before)
            self.assertNotEqual(self.git('rev-parse', 'line/art/work'), before)
            self.assertEqual((self.root / 'protected').read_text(), 'root')
        finally:
            scope.close()
