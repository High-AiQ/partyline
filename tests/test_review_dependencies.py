"""Review dependency provisioning stays local and follows the checked-out lockfiles."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline.review_dependencies import _incompatible_optional, provision
from partyline.review_scope import ReviewError
from partyline.review_install_sandbox import local_cache


class ReviewDependenciesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (self.repo / '.gitignore').write_text('node_modules/\n')
        self.package(self.repo)
        self.package(self.repo / "nested")
        self.git("add", ".")
        self.git("commit", "-qm", "package")
        self.review = self.root / "review"
        self.git("worktree", "add", "--detach", str(self.review), "HEAD")
        (self.repo / "node_modules").mkdir()
        (self.repo / "node_modules" / "host").write_text("host")
        sandbox = patch('partyline.review_dependencies.install_argv',
                        side_effect=lambda _path, cmd, _local: cmd)
        sandbox.start()
        self.addCleanup(sandbox.stop)

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def git_status(self):
        return subprocess.run(['git', 'status', '--porcelain'], cwd=self.review,
                              check=True, text=True, capture_output=True).stdout

    def package(self, path):
        path.mkdir(exist_ok=True)
        (path / "package.json").write_text('{}')
        lock = {"lockfileVersion": 3, "packages": {
            "": {}, "node_modules/package": {"version": "1.0.0"}}}
        (path / "package-lock.json").write_text(json.dumps(lock))

    def installed(self):
        modules = self.repo / 'node_modules'
        (modules / 'package').mkdir()
        hidden = {"lockfileVersion": 3, "packages": {
            "node_modules/package": {"version": "1.0.0"}}}
        (modules / '.package-lock.json').write_text(json.dumps(hidden))

    def test_install_nested_and_checkout_local_writes(self):
        calls = []

        def install(command, cwd, **kwargs):
            calls.append((command, Path(cwd)))
            (Path(cwd) / "node_modules").mkdir()
            return subprocess.CompletedProcess(command, 0, '', '')

        with patch('partyline.review_dependencies.run_installer', side_effect=install):
            provision(str(self.review))
        self.assertEqual({item[1] for item in calls}, {self.review, self.review / 'nested'})
        (self.review / 'node_modules' / 'write').write_text('local')
        self.assertFalse((self.repo / 'node_modules' / 'write').exists())
        self.assertTrue(all(item[0][:2] == ('npm', 'ci') for item in calls))
        self.assertEqual(self.git_status(), '')

    def test_worktree_cleanup_removes_its_package_cache(self):
        cache = Path(local_cache(str(self.review), 'tmp'))
        (cache / 'artifact').write_text('temporary')
        self.git('worktree', 'remove', '--force', str(self.review))
        self.assertFalse(cache.exists())

    def test_matching_install_links_packages_but_keeps_cache_local(self):
        host = self.repo / 'node_modules'
        self.installed()
        (host / '.vite-temp').mkdir()
        done = subprocess.CompletedProcess([], 0, '', '')
        with patch('partyline.review_dependencies.run_installer', return_value=done) as installer:
            provision(str(self.review), [str(self.repo)])
        self.assertEqual(installer.call_count, 1)  # nested package has no install
        modules = self.review / 'node_modules'
        self.assertTrue((modules / 'package').is_symlink())
        (modules / '.vite-temp').mkdir()
        (modules / '.vite-temp' / 'config').write_text('local')
        self.assertFalse((host / '.vite-temp' / 'config').exists())

    def test_source_with_external_link_falls_back_to_install(self):
        self.installed()
        os.symlink(self.root, self.repo / 'node_modules' / 'escape')
        done = subprocess.CompletedProcess([], 0, '', '')
        with patch('partyline.review_dependencies.run_installer', return_value=done) as installer:
            provision(str(self.review), [str(self.repo)])
        self.assertEqual(installer.call_count, 2)
        self.assertFalse((self.review / 'node_modules' / 'escape').exists())

    def test_workspace_link_uses_local_install(self):
        self.installed()
        workspace = self.repo / 'nested'
        os.symlink(workspace, self.repo / 'node_modules' / 'workspace')
        done = subprocess.CompletedProcess([], 0, '', '')
        with patch('partyline.review_dependencies.run_installer', return_value=done) as installer:
            provision(str(self.review), [str(self.repo)])
        self.assertEqual(installer.call_count, 2)

    def test_mismatched_lock_installs_review_version(self):
        (self.repo / 'package-lock.json').write_text('different')
        def install(command, cwd, **kwargs):
            self.assertEqual(json.loads((Path(cwd) / 'package-lock.json').read_text())['lockfileVersion'], 3)
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch('partyline.review_dependencies.run_installer', side_effect=install):
            provision(str(self.review))

    def test_unreadable_source_falls_back(self):
        self.installed()
        done = subprocess.CompletedProcess([], 0, '', '')
        with patch('partyline.review_dependencies._verified_install', side_effect=PermissionError), \
                patch('partyline.review_dependencies.run_installer', return_value=done) as installer:
            provision(str(self.review), [str(self.repo)])
        self.assertEqual(installer.call_count, 2)

    def test_stale_installed_lock_falls_back(self):
        self.installed()
        hidden = self.repo / 'node_modules' / '.package-lock.json'
        data = json.loads(hidden.read_text())
        data['packages']['node_modules/package']['version'] = '0.1.0'
        hidden.write_text(json.dumps(data))
        done = subprocess.CompletedProcess([], 0, '', '')
        with patch('partyline.review_dependencies.run_installer', return_value=done) as installer:
            provision(str(self.review), [str(self.repo)])
        self.assertEqual(installer.call_count, 2)

    def test_installer_disables_scripts_and_has_timeout(self):
        done = subprocess.CompletedProcess([], 0, '', '')
        with patch('partyline.review_dependencies.run_installer', return_value=done) as installer:
            provision(str(self.review))
        for call in installer.call_args_list:
            self.assertIn('--ignore-scripts', call.args[0])
            self.assertEqual(call.kwargs['env']['YARN_ENABLE_SCRIPTS'], '0')
            self.assertEqual(call.kwargs['timeout'], 300)

    def test_other_managers_disable_scripts(self):
        done = subprocess.CompletedProcess([], 0, '', '')
        for lock, contents in (('pnpm-lock.yaml', 'lockfileVersion: 9'),
                               ('yarn.lock', '__metadata:')):
            with self.subTest(lock=lock), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                (folder / 'package.json').write_text('{}')
                (folder / lock).write_text(contents)
                with patch('partyline.review_dependencies.local_cache', return_value=str(folder)), \
                        patch('partyline.review_dependencies.cache_location', return_value=str(folder)), \
                        patch('partyline.review_dependencies.run_installer', return_value=done) as installer:
                    provision(str(folder))
                call = installer.call_args
                self.assertEqual(call.kwargs['env']['YARN_ENABLE_SCRIPTS'], '0')
                if lock.startswith('pnpm'):
                    self.assertIn('--ignore-scripts', call.args[0])
                else:
                    self.assertIn('--immutable', call.args[0])

    def test_missing_optional_is_only_exempt_for_an_incompatible_platform(self):
        with patch('partyline.review_dependencies.platform.system', return_value='Linux'), \
                patch('partyline.review_dependencies.platform.machine', return_value='x86_64'):
            self.assertFalse(_incompatible_optional({'optional': True}))
            self.assertFalse(_incompatible_optional({'optional': True, 'os': ['linux']}))
            self.assertTrue(_incompatible_optional({'optional': True, 'os': ['darwin']}))
            self.assertTrue(_incompatible_optional({'optional': True, 'cpu': ['!x64']}))

    def test_timeout_reports_disabled_scripts(self):
        with patch('partyline.review_dependencies.run_installer',
                   side_effect=subprocess.TimeoutExpired('npm', 300)):
            with self.assertRaisesRegex(ReviewError, 'timed out.*scripts are disabled'):
                provision(str(self.review))

    def test_failure_reports_detail(self):
        failed = subprocess.CompletedProcess([], 1, '', 'offline failure')
        with patch('partyline.review_dependencies.run_installer', return_value=failed):
            with self.assertRaisesRegex(ReviewError, 'offline failure'):
                provision(str(self.review))

    def test_external_symlink_is_rejected(self):
        def install(command, cwd, **kwargs):
            modules = Path(cwd) / 'node_modules'
            modules.mkdir()
            os.symlink(self.repo / 'node_modules', modules / 'escape')
            return subprocess.CompletedProcess(command, 0, '', '')
        with patch('partyline.review_dependencies.run_installer', side_effect=install):
            with self.assertRaisesRegex(ReviewError, 'symlink escapes'):
                provision(str(self.review))
