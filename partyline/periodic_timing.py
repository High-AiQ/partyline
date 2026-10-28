"""Bounded, token-free timing of periodic jobs for loop-lag diagnostics."""

from collections import deque
from contextlib import contextmanager
import time

# Only fixed, developer-supplied job names are recorded, never arguments.
_active = {}
_recent = deque(maxlen=128)


@contextmanager
def tick(name):
    marker = object()
    start = time.monotonic()
    _active[marker] = (name, start)
    try:
        yield
    finally:
        _active.pop(marker, None)
        _recent.append((name, start, time.monotonic()))


def slowest(start, end):
    """Return the longest tick overlapping the monitor's delayed interval."""
    candidates = [*list(_recent), *((name, began, end) for name, began in _active.values())]
    overlap = [(name, finished - began) for name, began, finished in candidates
               if began <= end and finished >= start]
    return max(overlap, key=lambda item: item[1], default=None)
