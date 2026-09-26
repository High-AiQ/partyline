"""Real process exclusion, cancellation, and native Windows byte-range locking."""

import asyncio
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from partyline import runtime_lock


class RuntimeLockTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "runtime.lock"

    def child_probe(self):
        code = (
            "import os,sys; from partyline.runtime_lock import try_lock; "
            "fd=os.open(sys.argv[1],os.O_CREAT|os.O_RDWR,0o600)\n"
            "try:\n try_lock(fd); print('acquired')\n"
            "except BlockingIOError:\n print('blocked')\n"
            "finally:\n os.close(fd)\n"
        )
        result = subprocess.run([sys.executable, "-c", code, str(self.path)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_another_process_is_excluded_until_release(self):
        with runtime_lock.exclusive(self.path):
            self.assertEqual(self.child_probe(), "blocked")
        self.assertEqual(self.child_probe(), "acquired")

    def test_exception_releases_the_lock(self):
        with self.assertRaisesRegex(ValueError, "failure"):
            with runtime_lock.exclusive(self.path):
                raise ValueError("failure")
        self.assertEqual(self.child_probe(), "acquired")

    def test_cancelled_waiter_does_not_unlock_the_owner(self):
        async def exercise():
            entered = asyncio.Event()

            async def wait():
                entered.set()
                async with runtime_lock.exclusive_async(self.path):
                    self.fail("waiter acquired an owned lock")

            with runtime_lock.exclusive(self.path):
                task = asyncio.create_task(wait())
                await entered.wait()
                with patch.object(runtime_lock, "unlock", wraps=runtime_lock.unlock) as unlock:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    unlock.assert_not_called()
                self.assertEqual(self.child_probe(), "blocked")
            async with runtime_lock.exclusive_async(self.path):
                self.assertEqual(self.child_probe(), "blocked")

        asyncio.run(exercise())
        self.assertEqual(self.child_probe(), "acquired")

    def test_database_import_does_not_require_unix_lock_module(self):
        result = subprocess.run(
            [sys.executable, "-c", "import sys; sys.modules['fcntl']=None; from partyline.db import Db"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_windows_uses_the_same_byte_and_normalizes_only_contention(self):
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        self.addCleanup(os.close, descriptor)
        lock = Mock()
        module = SimpleNamespace(locking=lock, LK_NBLCK=2, LK_UNLCK=0)
        with patch.object(runtime_lock.sys, "platform", "win32"), \
                patch.dict(sys.modules, {"msvcrt": module}):
            os.lseek(descriptor, 7, os.SEEK_SET)
            runtime_lock.try_lock(descriptor)
            self.assertEqual(os.lseek(descriptor, 0, os.SEEK_CUR), 0)
            runtime_lock.unlock(descriptor)
            self.assertEqual([call.args for call in lock.call_args_list],
                             [(descriptor, 2, 1), (descriptor, 0, 1)])
            lock.side_effect = OSError(errno.EACCES, "contended")
            with self.assertRaises(BlockingIOError):
                runtime_lock.try_lock(descriptor)
            lock.side_effect = OSError(errno.EBADF, "bad descriptor")
            with self.assertRaises(OSError) as raised:
                runtime_lock.try_lock(descriptor)
            self.assertEqual(raised.exception.errno, errno.EBADF)

    def test_sync_wait_retries_contention_but_propagates_other_errors(self):
        with patch.object(runtime_lock, "try_lock", side_effect=[BlockingIOError(), None]), \
                patch.object(runtime_lock, "unlock"), patch.object(runtime_lock.time, "sleep") as sleep:
            with runtime_lock.exclusive(self.path):
                pass
        sleep.assert_called_once_with(0.01)
        with patch.object(runtime_lock, "try_lock", side_effect=OSError("denied")), \
                patch.object(runtime_lock, "unlock") as unlock:
            with self.assertRaisesRegex(OSError, "denied"), runtime_lock.exclusive(self.path):
                self.fail("acquired after an unexpected error")
        unlock.assert_not_called()
