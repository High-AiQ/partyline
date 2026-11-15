"""Thread-safe grant event clock; notification coalescing cannot delay this clock."""
import threading
import time
from collections import OrderedDict

MAX_SOURCES = 512  # distinct event sources kept; a source that keeps firing is one entry


class EventState:
    def __init__(self, clock=time.time, monotonic=time.monotonic):
        self.lock = threading.Condition()
        self.monotonic = monotonic
        self.last_change = None
        self.clock = clock
        self.count, self.last = 0, None
        self.supported = False
        self.subscription = None
        self.sources = OrderedDict()  # source -> count of its latest event, oldest first
        self.last_unplaced = 0  # count of the latest event that came with no source
        self.evicted = 0  # latest count among sources dropped for room

    def changed(self, source=None):
        """`source` is the sender's runtime id when the handler could name it."""
        with self.lock:
            self.count += 1
            self.last = self.clock()
            self.last_change = self.monotonic()
            if source is None:
                self.last_unplaced = self.count
            else:
                self.sources.pop(source, None)
                self.sources[source] = self.count
                while len(self.sources) > MAX_SOURCES:
                    self.evicted = max(self.evicted, self.sources.popitem(last=False)[1])
            self.lock.notify_all()

    def latest(self):
        """Each kept source's latest event count; the latest count among sources dropped for room or
        raised with no source: after either, no kept ancestry can be vouched for."""
        with self.lock:
            return dict(self.sources), max(self.evicted, self.last_unplaced)

    def sources_since(self, counter):
        """The distinct sources of events after `counter`; `unplaced` or `overflow` mean some are unknown."""
        with self.lock:
            found = []
            for source, count in reversed(self.sources.items()):
                if count <= counter:
                    break
                found.append(source)
            return {"sources": found, "unplaced": self.last_unplaced > counter,
                    "overflow": self.evicted > counter}

    def status(self):
        with self.lock:
            subscription = self.subscription
            return {"event_counter": self.count, "last_event_time": self.last,
                    "events_supported": self.supported, "event_sources_supported": True,
                    "subscription_live": bool(self.supported and subscription and subscription.live)}

    def settle(self, since, quiet=0.02, budget=0.2):
        """Only observed events start a quiet deadline; new events wake and extend it, up to budget."""
        deadline = self.monotonic() + budget
        with self.lock:
            if not self.supported or not self.subscription or not self.subscription.live:
                return "unsupported"
            if self.count == since:
                return "unchanged"
            while True:
                now = self.monotonic()
                if now >= deadline:
                    return "deadline"
                remaining = self.last_change + quiet - now
                if remaining <= 0:
                    return "quiet"
                # no-poll (d): condition notification resets the quiet deadline after a real UIA event.
                self.lock.wait(min(remaining, deadline - now))
