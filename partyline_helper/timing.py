"""Content-free phase timings; clocks are local monotonic seconds, output is milliseconds."""
import time
from contextlib import contextmanager

clock = time.perf_counter


class Timing:
    def __init__(self, values=None, now=None):
        self.values = values if values is not None else {}
        self.clock = now or clock
        self.started = self.clock()

    def elapsed(self, start):
        return round(max(0, self.clock() - start) * 1000, 3)

    @contextmanager
    def phase(self, name):
        start = self.clock()
        try:
            yield
        finally:
            self.values[name] = round(self.values.get(name, 0) + self.elapsed(start), 3)

    def finish(self, result):
        self.values['total_ms'] = self.elapsed(self.started)
        result['timing'] = self.values
        return result
