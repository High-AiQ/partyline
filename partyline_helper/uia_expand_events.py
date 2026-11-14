"""One structure-event deadline after Expand, never a timer-driven state recheck loop."""
import threading

from .uia_events import UIAEventSubscription

EXPAND_EVENT_SECONDS = 0.25


def structure_call(hwnd, call, subscribe=UIAEventSubscription, event_factory=threading.Event):
    def invoke():
        event = event_factory()
        subscription = subscribe(hwnd, event.set, structure_only=True)
        try:
            started = subscription.start()
            event.clear()  # ignore setup notifications; also retain events delivered during the pattern call
            result = call()
            if started:
                event.wait(EXPAND_EVENT_SECONDS)
            return result
        finally:
            subscription.close()
    return invoke
