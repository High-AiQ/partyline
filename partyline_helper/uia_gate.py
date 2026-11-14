"""Dispatch barrier for a single consent generation, independent of the message loop."""
import threading
from contextlib import nullcontext


class DispatchGate:
    def __init__(self):
        self.lock = threading.Lock()
        self.generation = 0
        self.revoked = threading.Event()
        self.revoked.set()

    def grant(self):
        if not self.lock.acquire(blocking=False):
            return None
        try:
            self.generation += 1
            self.revoked.clear()
            return self.generation
        finally:
            self.lock.release()

    def invalidate(self):
        # Refuse new work immediately, even while a pattern call holds the lock.
        self.revoked.set()
        if self.lock.acquire(blocking=False):
            try:
                self.generation += 1
            finally:
                self.lock.release()

    def dispatch(self, generation, call, timing=None):
        with timing.phase("gate_lock_ms") if timing else nullcontext():
            self.lock.acquire()
        try:
            if self.revoked.is_set() or self.generation != generation:
                raise ValueError("revoked")
            try:
                result = call()
            finally:
                if self.revoked.is_set():
                    self.generation += 1
            return result, self.revoked.is_set()
        finally:
            self.lock.release()
