"""Keep bounded UI Automation reads off the helper's message loop."""
import asyncio
import contextlib

from websockets.exceptions import ConnectionClosed

from .uia_action_worker import ActionWorker, audit
from .timing import Timing
from .window_gone import explain
from .workflow_dispatch import WorkflowAction


READ_TIMEOUT = 33  # seconds; START_LIMIT + BUDGET + KILL_SLACK must stay below it


def read_options(message):
    """The only fields of a read request the helper honours."""
    if isinstance(message.get("inspect"), str):
        return {"inspect": message["inspect"][:128]}
    dependency = message.get("dependency_scope")
    if isinstance(dependency, dict):
        scope = {key: dependency[key][:200] for key in ("root", "name", "control_type", "action")
                 if isinstance(dependency.get(key), str)}
        if all(scope.get(key) for key in ("root", "name", "action")):
            return {"dependency_scope": scope}
    scope = message.get("query_scope")
    if isinstance(scope, dict):
        return {"query_scope": {key: value[:200] for key, value in scope.items()
                                if key in ("query", "control_type") and isinstance(value, str)}}
    cursor = message.get("cursor")
    if not (isinstance(cursor, str) and cursor):
        return {}
    options = {"cursor": cursor[:64]}
    if message.get("tolerate_events") is True:
        options["tolerate_events"] = True
    return options


class WindowTask:
    def __init__(self, session):
        self.session = session
        self.operation_lock = asyncio.Lock()
        self.task = None
        self.read_task = None
        self.actions = ActionWorker(session)
        self.workflow = None

    def busy(self):
        return any(task and not task.done() for task in (self.task, self.read_task))

    async def submit(self, request_id, options=None, message=None):
        if self.busy():
            await self.session.send("window_elements", request_id=request_id,
                                    elements_unavailable="window read already in progress")
            return
        self.task = asyncio.create_task(self._read(request_id, options, message, Timing()))

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
        if message.get("workflow_source"):
            self.workflow = operation = WorkflowAction(message)
            message = {**message, "_workflow_cancelled": operation.cancelled}
        self.task = asyncio.create_task(self._action(message, Timing()))

    def cancel_workflow(self, request_id):
        if self.workflow and self.workflow.id == request_id:
            self.workflow.cancelled.set()

    async def _action(self, message, queued=None):
        workflow = self.workflow
        token = workflow.activate(message) if workflow else None
        try:
            async with self.operation_lock:
                await self._action_locked(message, queued)
        finally:
            if workflow:
                workflow.reset(token)
                self.workflow = None

    async def _action_locked(self, message, queued=None):
        timing = queued or Timing()
        timing.values["task_queue_ms"] = timing.elapsed(timing.started)
        from .screen_access_audit import begin_window_call, end_window_call
        active = begin_window_call(self.session, message.get("agent", ""),
                                   message.get("line_name") or message.get("line"))
        audited = False
        try:
            from .window_look import check
            try:
                check(self.session.window, message)
            except ValueError as exc:
                await self.session.send("window_element_result", request_id=message["request_id"],
                                        status="failed", error=explain(self.session.window, str(exc)))
                return
            chrome = getattr(self.session, "chrome", None)
            result = await chrome.action(self.session.window, message) if chrome else None
            if result is None and message.get("workflow_source") == "cdp":
                result = {"status": "failed", "reason": "workflow_source", "source": "uia"}
            if result is None and message.get("action") == "set_files":
                result = {"status": "failed", "error": "CDP unavailable; use the Open dialog path instead"}
            if result is None:
                result = await self.actions.perform(message)
                result.setdefault("source", "uia")
            elif chrome:
                from .screen_access_audit import audit_window
                audit_window(self.session, "uia_action", message.get("agent", ""),
                             result.get("status", "failed"), message.get("line"))
                audited = True
            result.setdefault("timing", {}).update(timing.values)
            if "error" in result:
                result["error"] = explain(self.session.window, result["error"])
            await self.session.send("window_element_result", request_id=message["request_id"], **result)
        except ConnectionClosed:
            pass
        except (ValueError, OSError):
            if chrome and not audited:
                from .screen_access_audit import audit_window
                audit_window(self.session, "uia_action", message.get("agent", ""), "failed",
                             message.get("line"))
            await self.session.send("window_element_result", request_id=message["request_id"],
                                    status="unconfirmed", error="Chrome command interrupted")
        finally:
            end_window_call(active)

    async def snapshot(self, options, message):
        chrome = getattr(self.session, "chrome", None)
        result = await chrome.read(self.session.window, options, message or {}) if chrome else None
        if result is None:
            access = self.session.window
            workflow_read = (message or {}).get("workflow_read") is True
            generation = access.gate.generation if workflow_read else None
            result = await access.snapshot(options)
            result["source"] = "uia"
            if workflow_read:
                result["workflow_document"] = str(generation)
                if access.gate.revoked.is_set() or generation != access.gate.generation:
                    result["changed"] = True
            if chrome and self.session.window in chrome.reasons:
                result["source_reason"] = chrome.reasons[self.session.window]
        if chrome:
            result.update(chrome.metadata(self.session.window))
        return result

    async def _read(self, request_id, options=None, message=None, queued=None):
        async with self.operation_lock:
            await self._read_locked(request_id, options, message, queued)

    async def _read_locked(self, request_id, options=None, message=None, queued=None):
        timing = queued or Timing()
        timing.values["task_queue_ms"] = timing.elapsed(timing.started)
        from .screen_access_audit import begin_window_call, end_window_call
        active = begin_window_call(self.session, (message or {}).get("agent", ""),
                                   (message or {}).get("line_name") or (message or {}).get("line"))
        try:
            await self._read_call(request_id, options, message, timing)
        finally:
            end_window_call(active)

    async def _read_call(self, request_id, options=None, message=None, timing=None):
        timing = timing or Timing()
        try:
            try:
                self.read_task = asyncio.create_task(self.snapshot(options, message))
                result = await asyncio.wait_for(asyncio.shield(self.read_task), READ_TIMEOUT)
            except TimeoutError:
                self.session.window.abandon_read()
                chrome = getattr(self.session, "chrome", None)
                if chrome and chrome.sources.get(self.session.window) == "cdp":
                    self.read_task.cancel()  # CDP is cancellable; a UIA COM thread is not
                result = {"elements_unavailable": "timeout", "truncated": True}
            except (ValueError, KeyError, TypeError, RuntimeError, OSError):
                result = {"elements_unavailable": "window read failed"}
            result.setdefault("timing", {}).update(timing.values)
            if "elements_unavailable" in result:
                result["elements_unavailable"] = explain(self.session.window, result["elements_unavailable"])
            from .screen_access_audit import audit_window
            try:
                audit_window(self.session, "uia_read", (message or {}).get("agent", ""),
                             "read" if result.get("elements_unavailable") is None else "failed",
                             (message or {}).get("line"))
            except OSError:
                result = {"elements_unavailable": "audit unavailable"}
            await self.session.send("window_elements", request_id=request_id, **result)
        except ConnectionClosed:
            pass

    def cancel(self):
        """Cancel queued and in-flight reads/actions before any awaited teardown."""
        if self.workflow:
            self.workflow.cancelled.set()
        for task in (self.task, self.read_task):
            if task:
                task.cancel()

    async def close(self):
        self.cancel()
        for task in (self.task, self.read_task):
            if task:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
