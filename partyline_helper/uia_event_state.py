"""Thread-safe grant event clock; notification coalescing cannot delay this clock."""
import threading
import time


class EventState:
    def __init__(self, clock=time.time, monotonic=time.monotonic):
        self.lock = threading.Condition()
        self.monotonic = monotonic
        self.last_change = None
        self.clock = clock
        self.count, self.last = 0, None
        self.supported = False
        self.subscription = None

    def changed(self):
        with self.lock:
            self.count += 1
            self.last = self.clock()
            self.last_change = self.monotonic()
            self.lock.notify_all()

    def status(self):
        with self.lock:
            subscription = self.subscription
            return {"event_counter": self.count, "last_event_time": self.last,
                    "events_supported": self.supported,
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
