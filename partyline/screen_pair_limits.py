"""Bound online guessing of short-lived screen pairing codes."""

import time
from collections import deque

WINDOW_SECONDS = 300
ISSUE_LIMIT = 5
IP_CLAIM_LIMIT = 20
GLOBAL_CLAIM_LIMIT = 120
CODE_FAILURE_LIMIT = 3


class PairLimits:
    def __init__(self):
        self.issued: dict[int, deque[float]] = {}
        self.by_ip: dict[str, deque[float]] = {}
        self.global_claims: deque[float] = deque()
        self.failures: dict[str, deque[float]] = {}

    @staticmethod
    def _prune(items, now):
        while items and items[0] <= now - WINDOW_SECONDS:
            items.popleft()

    def _clean(self, groups, now):
        for key, items in list(groups.items()):
            self._prune(items, now)
            if not items:
                del groups[key]

    def issue(self, owner_id: int) -> bool:
        now = time.monotonic()
        self._clean(self.issued, now)
        items = self.issued.setdefault(owner_id, deque())
        if len(items) >= ISSUE_LIMIT:
            return False
        items.append(now)
        return True

    def claim(self, ip: str, code: str) -> bool:
        now = time.monotonic()
        self._prune(self.global_claims, now)
        self._clean(self.by_ip, now)
        self._clean(self.failures, now)
        if (len(self.global_claims) >= GLOBAL_CLAIM_LIMIT
                or len(self.by_ip.get(ip, ())) >= IP_CLAIM_LIMIT
                or len(self.failures.get(code.upper(), ())) >= CODE_FAILURE_LIMIT):
            return False
        self.global_claims.append(now)
        self.by_ip.setdefault(ip, deque()).append(now)
        return True

    def locked(self, code: str) -> bool:
        self._clean(self.failures, time.monotonic())
        return len(self.failures.get(code.upper(), ())) >= CODE_FAILURE_LIMIT

    def failed(self, code: str) -> None:
        self.failures.setdefault(code.upper(), deque()).append(time.monotonic())
