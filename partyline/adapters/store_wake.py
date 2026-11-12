"""One-shot settlement of filesystem events that precede SQLite commits."""


class StoreWake:
    def __init__(self, adapter):
        self.adapter = adapter
        # A notification may already be queued before the first scan starts.
        self.read_at = 0
        self.deadline = None

    def observed(self):
        return self.adapter._changes.version

    def read(self, observed, changed, *, error=False):
        event = observed != self.read_at
        self.read_at = observed
        if error or changed:
            self.deadline = None
        elif event:
            # no-poll (b): one later look per notification that preceded a commit.
            self.deadline = self.adapter.event_time() + 0.05
        elif self.deadline is not None and self.adapter.event_time() >= self.deadline:
            self.deadline = None

    def delay(self):
        if self.deadline is None:
            return None
        return max(0, self.deadline - self.adapter.event_time())
