"""Account for new recovery objects as retained storage, not reclaimed bytes."""

import os

from .storage_survey import Budget


class RecoveryAccounting:
    def __init__(self):
        self.before = {}
        self._reachable = {}

    def watch(self, common):
        common = os.path.realpath(common)
        # Include recovery refs and removed worktree metadata as well as objects.
        if common not in self.before:
            self.before[common] = Budget(seconds=float('inf')).size(common)

    def reachable(self, common):
        from .storage_git_objects import reachable
        common = os.path.realpath(common)
        if common not in self._reachable:
            self._reachable[common] = reachable(common)
        return self._reachable[common]

    def growth(self):
        return sum(Budget(seconds=float('inf')).size(path) - size
                   for path, size in self.before.items())
