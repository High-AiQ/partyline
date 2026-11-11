"""Installers must never run as unrestricted server subprocesses."""

import os
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from partyline.review_install_sandbox import (
    DependencyError, _kill_session, install_argv, local_cache, run_installer)


class InstallerSandboxTest(unittest.TestCase):
    def test_linux_mounts_only_checkout_and_caches_writable(self):
        with patch('partyline.review_install_sandbox.sys.platform', 'linux'), \
                patch('partyline.review_install_sandbox.os.access', return_value=True), \
                patch('partyline.review_install_sandbox.os.path.isdir', return_value=False):
            argv = install_argv('/review/tree', ('npm', 'ci', '--ignore-scripts'), '/cache')
        self.assertEqual(argv[:4], ['/usr/bin/bwrap', '--ro-bind', '/', '/'])
        self.assertEqual(argv.count('--bind'), 2)
        self.assertIn('/cache', argv)
        index = argv.index('--bind')
        self.assertEqual(argv[index + 1:index + 3], ['/review/tree', '/review/tree'])
        self.assertEqual(argv[-3:], ['npm', 'ci', '--ignore-scripts'])
        # a grandchild that calls setsid dies with the sandbox's pid namespace
        self.assertIn('--unshare-pid', argv)
        self.assertIn('--die-with-parent', argv)

    def test_darwin_denies_writes_except_checkout_and_caches(self):
        with patch('partyline.review_install_sandbox.sys.platform', 'darwin'), \
                patch('partyline.review_install_sandbox.os.access', return_value=True), \
                patch('partyline.review_install_sandbox.os.path.isdir', return_value=False):
            argv = install_argv('/review/tree', ('npm', 'ci'), '/cache')
        self.assertIn('(deny file-write*)', argv[2])
        self.assertIn('(subpath "/review/tree")', argv[2])

    def test_untrusted_cache_symlink_is_rejected_before_creating_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            checkout, outside = os.path.join(folder, 'review'), os.path.join(folder, 'outside')
            gitdir = os.path.join(folder, 'worktrees', 'review')
            os.makedirs(gitdir)
            os.mkdir(checkout)
            os.mkdir(outside)
            with open(os.path.join(gitdir, 'gitdir'), 'w', encoding='utf-8') as marker:
                marker.write(os.path.join(checkout, '.git'))
            os.symlink(outside, os.path.join(gitdir, 'partyline-package-cache'))
            with patch('partyline.review_install_sandbox._worktree_gitdir', return_value=gitdir):
                with self.assertRaisesRegex(DependencyError, 'cache traverses a symlink'):
                    local_cache(checkout, 'tmp')
            self.assertEqual(os.listdir(outside), [])

    def test_installer_has_no_terminal_or_server_process_group(self):
        process = MagicMock(pid=123, returncode=0)
        process.communicate.return_value = ('ok', '')
        with patch('partyline.review_install_sandbox.subprocess.Popen', return_value=process) as popen:
            result = run_installer(['npm'], cwd='/review', env={}, timeout=300)
        self.assertEqual(result.stdout, 'ok')
        self.assertIs(popen.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        process.communicate.assert_called_once_with(timeout=300)

    def test_timeout_kills_process_group_before_reporting(self):
        process = MagicMock(pid=123)
        process.communicate.side_effect = subprocess.TimeoutExpired('npm', 300)
        with patch('partyline.review_install_sandbox.subprocess.Popen', return_value=process), \
                patch('partyline.review_install_sandbox._kill_session', return_value=True) as kill:
            with self.assertRaises(subprocess.TimeoutExpired):
                run_installer(['npm'], cwd='/review', env={}, timeout=300)
        kill.assert_called_once_with(123)
        process.wait.assert_called_once_with(timeout=5)

    def test_timeout_terminates_other_groups_in_same_session(self):
        listing = subprocess.CompletedProcess([], 0, '123\n124\n125\n', '')
        with patch('partyline.review_install_sandbox.os.killpg') as killpg, \
                patch('partyline.review_install_sandbox.subprocess.run', return_value=listing), \
                patch('partyline.review_install_sandbox.os.getsid', side_effect=[123, 123, 999]), \
                patch('partyline.review_install_sandbox.os.kill') as kill:
            _kill_session(123)
        killpg.assert_called_once_with(123, signal.SIGKILL)
        self.assertEqual([call.args[0] for call in kill.call_args_list], [123, 124])

    def test_timeout_reports_when_session_cleanup_cannot_be_verified(self):
        process = MagicMock(pid=123)
        process.communicate.side_effect = subprocess.TimeoutExpired('npm', 300)
        with patch('partyline.review_install_sandbox.subprocess.Popen', return_value=process), \
                patch('partyline.review_install_sandbox._kill_session', return_value=False):
            with self.assertRaisesRegex(DependencyError, 'timed out.*entire session'):
                run_installer(['npm'], cwd='/review', env={}, timeout=300)
        process.wait.assert_called_once_with(timeout=5)

    def test_unavailable_sandbox_fails_closed(self):
        with patch('partyline.review_install_sandbox.sys.platform', 'linux'), \
                patch('partyline.review_install_sandbox.os.access', return_value=False):
            with self.assertRaisesRegex(DependencyError, 'cannot safely run'):
                install_argv('/review/tree', ('npm', 'ci'), '/cache')
