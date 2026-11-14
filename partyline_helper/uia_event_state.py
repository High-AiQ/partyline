"""Thread-safe grant event clock; notification coalescing cannot delay this clock."""
import threading
import time


class EventState:
    def __init__(self, clock=time.time):
        self.lock = threading.Lock()
        self.clock = clock
        self.count, self.last = 0, None
        self.supported = False
        self.subscription = None

    def changed(self):
        with self.lock:
            self.count += 1
            self.last = self.clock()

    def status(self):
        with self.lock:
            subscription = self.subscription
            return {"event_counter": self.count, "last_event_time": self.last,
                    "events_supported": self.supported,
                    "subscription_live": bool(self.supported and subscription and subscription.live)}
