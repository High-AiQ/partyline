"""Process-shared ownership locks for Unix and native Windows."""

import asyncio
from contextlib import asynccontextmanager, contextmanager
import errno
import os
import sys
import time


def try_lock(descriptor: int) -> None:
    """Acquire without waiting; normalize only contention to BlockingIOError."""
    if sys.platform == "win32":
        import msvcrt

        # Lock one reserved byte, including on an empty file. Every descriptor
        # must use the same offset; msvcrt locks from its current file position.
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno == errno.EACCES:
                raise BlockingIOError(errno.EAGAIN, "runtime lock is held") from exc
            raise
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock(descriptor: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def _descriptor(path):
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def exclusive(path):
    with _descriptor(path) as descriptor:
        while True:
            try:
                try_lock(descriptor)
                break
            except BlockingIOError:
                time.sleep(0.01)
        try:
            yield
        finally:
            unlock(descriptor)


@asynccontextmanager
async def exclusive_async(path):
    with _descriptor(path) as descriptor:
        while True:
            try:
                try_lock(descriptor)
                break
            except BlockingIOError:
                await asyncio.sleep(0.01)
        # A cancelled waiter closes its descriptor without unlocking a region
        # it never acquired. This matters on Windows, where that is an error.
        try:
            yield
        finally:
            unlock(descriptor)
