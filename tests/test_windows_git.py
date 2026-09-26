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
        if sys.platform == 'win32':
            # Git checks the owners of the gitfile, worktree and metadata too.
            # Elevated CI creates them as Administrators; model a normal user.
            for path in self.root.rglob('*'):
                secure_directory(path, directory=path.is_dir())
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

    def test_forged_common_directory_cannot_grant_another_repository(self):
        from partyline import git_fence
        metadata = Path(git_fence._worktree_gitdir(str(self.work)))
        (metadata / 'commondir').write_text(str(self.root / 'other.git'))
        with patch('partyline.worktree_paths.sys.platform', 'win32'):
            with self.assertRaisesRegex(OSError, 'metadata does not belong'):
                write_paths(self.att)
        (metadata / 'commondir').write_text('../..')


@unittest.skipUnless(sys.platform == 'win32', 'native Git filesystem fence')
class NativeWindowsGitTest(WindowsGitPathsTest, unittest.IsolatedAsyncioTestCase):
    async def test_child_commits_without_writing_parent_files_or_refs(self):
        before = self.git('rev-parse', 'main')
        config = self.root / 'global-config'
        config.write_text('[user]\nname = fixture\nemail = fixture@example.test\n')
        environment = dict(os.environ, GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM='1')
        scope = WindowsFence(write_paths(self.att), [self.root])
        code = (
            'import pathlib,subprocess,sys\n'
            'root=pathlib.Path(sys.argv[1]); pathlib.Path("child").write_text("child")\n'
            'def git(*args): return subprocess.run(["git",*args],capture_output=True,text=True)\n'
            'r=git("add","child"); assert r.returncode==0,r.stderr\n'
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
                environment, 256 * 1024**2, token=scope.token,
            )
            try:
                output = bytearray()
                async def drain():
                    while data := await console.read():
                        output.extend(data)
                reader = asyncio.create_task(drain())
                code = await asyncio.wait_for(console.wait(), 30)
            finally:
                await console.close(preserve_output=True)
            await reader
            self.assertEqual(code, 0, output.decode(errors='replace'))
            self.assertEqual(self.git('rev-parse', 'main'), before)
            self.assertNotEqual(self.git('rev-parse', 'line/art/work'), before)
            self.assertEqual((self.root / 'protected').read_text(), 'root')
        finally:
            scope.close()
