"""Request-local cancellation and evidence checks for workflow input."""

from contextvars import ContextVar
from threading import Event

from .cdp_transport import CDPError

_active = ContextVar("workflow_action_cancelled", default=None)


def document(page):
    return f"{page.identity}:{page.epoch}"


def changed(message, status):
    counter = message.get("workflow_counter")
    return counter is not None and status and status().get("event_counter") != counter


def cancelled(message):
    flag = message.get("_workflow_cancelled")
    return flag is not None and flag.is_set()


def cdp_guard():
    flag = _active.get()
    if flag is not None and flag.is_set():
        raise CDPError("workflow action cancelled")


class WorkflowAction:
    def __init__(self, message):
        self.id = message["request_id"]
        self.cancelled = Event()

    def activate(self, message):
        return _active.set(message.get("_workflow_cancelled"))

    def reset(self, token):
        _active.reset(token)
