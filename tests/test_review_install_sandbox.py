"""Installers must never run as unrestricted server subprocesses."""

import os
import tempfile
import unittest
from unittest.mock import patch

from partyline.review_install_sandbox import DependencyError, install_argv, local_cache


class InstallerSandboxTest(unittest.TestCase):
    def test_linux_mounts_only_checkout_and_caches_writable(self):
        with patch('partyline.review_install_sandbox.sys.platform', 'linux'), \
                patch('partyline.review_install_sandbox.os.access', return_value=True), \
                patch('partyline.review_install_sandbox.os.path.isdir', return_value=False):
            argv = install_argv('/review/tree', ('npm', 'ci', '--ignore-scripts'))
        self.assertEqual(argv[:4], ['/usr/bin/bwrap', '--ro-bind', '/', '/'])
        self.assertEqual(argv.count('--bind'), 1)
        index = argv.index('--bind')
        self.assertEqual(argv[index + 1:index + 3], ['/review/tree', '/review/tree'])
        self.assertEqual(argv[-3:], ['npm', 'ci', '--ignore-scripts'])

    def test_darwin_denies_writes_except_checkout_and_caches(self):
        with patch('partyline.review_install_sandbox.sys.platform', 'darwin'), \
                patch('partyline.review_install_sandbox.os.access', return_value=True), \
                patch('partyline.review_install_sandbox.os.path.isdir', return_value=False):
            argv = install_argv('/review/tree', ('npm', 'ci'))
        self.assertIn('(deny file-write*)', argv[2])
        self.assertIn('(subpath "/review/tree")', argv[2])

    def test_untrusted_cache_symlink_is_rejected_before_creating_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            checkout, outside = os.path.join(folder, 'review'), os.path.join(folder, 'outside')
            os.mkdir(checkout)
            os.mkdir(outside)
            os.symlink(outside, os.path.join(checkout, '.partyline-package-cache'))
            with self.assertRaisesRegex(DependencyError, 'cache traverses a symlink'):
                local_cache(checkout, 'tmp')
            self.assertEqual(os.listdir(outside), [])

    def test_unavailable_sandbox_fails_closed(self):
        with patch('partyline.review_install_sandbox.sys.platform', 'linux'), \
                patch('partyline.review_install_sandbox.os.access', return_value=False):
            with self.assertRaisesRegex(DependencyError, 'cannot safely run'):
                install_argv('/review/tree', ('npm', 'ci'))
