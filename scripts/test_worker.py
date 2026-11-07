"""Run one unittest shard and record every test's wall duration."""

from __future__ import annotations

import json
import os
import sys
import time
import unittest

from fastapi import FastAPI

from partyline import server


class TimingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started: dict[str, float] = {}
        self.durations: list[dict[str, float | str]] = []

    def startTest(self, test):
        self.started[test.id()] = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        elapsed = time.perf_counter() - self.started.pop(test.id())
        self.durations.append({"id": test.id(), "seconds": elapsed})
        super().stopTest(test)


def main(names: list[str]) -> int:
    # Pay process-wide import, app-construction, and schema costs before any
    # individual test is charged for them.
    FastAPI()
    server.app.openapi()
    # Load each discovered module separately. loadTestsFromNames deduplicates
    # inherited test methods across concrete subclasses; discovery does not.
    suite = unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromName(name) for name in names
    )
    result = unittest.TextTestRunner(verbosity=1, resultclass=TimingResult).run(suite)
    output = os.environ.get("PARTYLINE_TEST_TIMINGS")
    if output:
        with open(output, "w", encoding="utf-8") as stream:
            json.dump(result.durations, stream)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
