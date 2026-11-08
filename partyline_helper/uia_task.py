"""Keep bounded UI Automation reads off the helper's message loop."""
import asyncio
import contextlib

from websockets.exceptions import ConnectionClosed

from .uia_action_worker import ActionWorker, audit


class WindowTask:
    def __init__(self, session):
        self.session = session
        self.task = None
        self.read_task = None
        self.actions = ActionWorker(session)

    def busy(self):
        return any(task and not task.done() for task in (self.task, self.read_task))

    async def submit(self, request_id):
        if self.busy():
            await self.session.send("window_elements", request_id=request_id,
                                    elements_unavailable="window read already in progress")
            return
        self.task = asyncio.create_task(self._read(request_id))

    async def submit_action(self, message):
        previous = self.actions.task and not self.actions.task.done()
        if self.busy() or previous:
            error = ("previous action still running in the app" if previous and self.actions.abandoned
                     else "window operation already in progress")
            result = {"status": "failed", "error": error}
            grant = self.session.window.grant or {}
            props = self.session.window.elements.get(message.get("element_id"), {})
            try:
                audit(self.session, grant, message, props, result)
            except OSError:
                result = {"status": "failed", "error": "audit unavailable"}
            await self.session.send("window_element_result", request_id=message["request_id"], **result)
            return
        self.task = asyncio.create_task(self._action(message))

    async def _action(self, message):
        try:
            result = await self.actions.perform(message)
            await self.session.send("window_element_result", request_id=message["request_id"], **result)
        except ConnectionClosed:
            pass

    async def _read(self, request_id):
        try:
            try:
                self.read_task = asyncio.create_task(self.session.window.snapshot())
                result = await asyncio.wait_for(asyncio.shield(self.read_task), 33)
            except TimeoutError:
                self.session.window.abandon_read()
                result = {"elements_unavailable": "timeout", "truncated": True}
            except (ValueError, KeyError, TypeError, RuntimeError, OSError):
                result = {"elements_unavailable": "window read failed"}
            await self.session.send("window_elements", request_id=request_id, **result)
        except ConnectionClosed:
            pass

    async def close(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        if self.read_task:
            self.read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.read_task
