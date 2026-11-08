"""Run a UIA action away from the message loop and enforce the dispatch barrier."""
import asyncio
import json
import threading

from .uia_action import prepare
from .uia_patterns import ActionRefused, argument, number
from .uia_snapshot import MAX_TEXT
from .uia_window_identity import live


STATE_KEYS = ("name", "value", "toggle", "enabled", "selected", "expand_state", "range_value",
              "h_scroll_percent", "v_scroll_percent", "window_state")


def provider_factory(hwnd):  # pragma: no cover - Windows COM provider
    import comtypes
    from .uia_windows import WindowsProvider
    comtypes.CoInitialize()
    return WindowsProvider(hwnd)


def run_action(access, grant, generation, message, factory=provider_factory):
    observed, foreground_samples = {}, []
    try:
        provider = factory(grant["hwnd"])
        arg = argument(message)
        path = getattr(access, "paths", {}).get(message["element_id"])
        node, _ = prepare(provider, message["element_id"], message["action"], arg, path)

        windows = access.list_windows()
        if windows is None:
            raise ValueError("secure desktop active")
        if not any(item["hwnd"] == grant["hwnd"] and item["pid"] == grant["pid"] for item in windows):
            raise ValueError("window closed")
        if grant.get("marker") and not live(grant):
            raise ValueError("window closed")
        fresh, _ = prepare(provider, message["element_id"], message["action"], arg, path)
        call = provider.action_call(fresh, message["action"], arg)
        windows = access.list_windows()
        if windows is None:
            raise ValueError("secure desktop active")
        if (not any(item["hwnd"] == grant["hwnd"] and item["pid"] == grant["pid"] for item in windows)
                or (grant.get("marker") and not live(grant))):
            raise ValueError("window closed")
        def invoke():
            current = access.list_windows()
            if current is None:
                raise ValueError("secure desktop active")
            if (not any(item["hwnd"] == grant["hwnd"] and item["pid"] == grant["pid"] for item in current)
                    or (grant.get("marker") and not live(grant))):
                raise ValueError("window closed")
            if access.gate.revoked.is_set():
                raise ValueError("revoked")
            before = provider.foreground()
            if access.gate.revoked.is_set():
                raise ValueError("revoked")
            try:
                return call()
            finally:
                after = provider.foreground()
                foreground_samples.extend((before, after))
                changed = before != after
                observed.update(foreground_changed=changed,
                                target_came_forward=bool(changed and after == grant["hwnd"]))

        _, revoked_during = access.gate.dispatch(generation, invoke)
        if revoked_during or access.gate.revoked.is_set() or access.gate.generation != generation:
            return {"status": "completed", "revoked_during": True, "state_unavailable": "consent revoked",
                    **observed}
        if message["action"] == "window_close":
            return {"status": "completed", "revoked_during": False, "close_requested": True,
                    "window_closed": not provider.current(), **observed}
        try:
            state = provider.properties(node)
            provider.state(node, state)
            if provider.password(node):
                state.pop("value", None)
            element = {key: state[key] for key in STATE_KEYS if key in state}
            if message["action"] in ("window_move", "window_resize"):
                element["bounds"] = list(provider.bounds(node))
            for key in ("name", "value"):
                if key in element:
                    element[key] = str(element[key] or "")[:MAX_TEXT]
            element["role"] = state.get("control_type")
            if access.gate.revoked.is_set() or access.gate.generation != generation:
                return {"status": "completed", "revoked_during": True, "state_unavailable": "consent revoked",
                        **observed}
            late = provider.foreground()
            if access.gate.revoked.is_set() or access.gate.generation != generation:
                return {"status": "completed", "revoked_during": True, "state_unavailable": "consent revoked",
                        **observed}
            before, immediate = foreground_samples
            changed = before != immediate or before != late
            observed.update(foreground_changed=changed,
                            target_came_forward=bool(changed and grant["hwnd"] in (immediate, late)))
            return {"status": "completed", "revoked_during": revoked_during, "element": element, **observed}
        except Exception:
            return {"status": "completed", "revoked_during": revoked_during,
                    "state_unavailable": "could not re-read element", **observed}
    except ValueError as exc:
        reason = str(exc)
        allowed = ("revoked", "secure desktop active", "window closed")
        known = isinstance(exc, ActionRefused) or reason in allowed
        return {"status": "failed", "error": reason if known else "UI Automation failed", **observed}
    except Exception:
        return {"status": "failed", "error": "UI Automation failed", **observed}
    finally:
        if factory is provider_factory:  # pragma: no cover - Windows COM apartment
            import comtypes
            comtypes.CoUninitialize()


def audit(session, grant, message, props, result):
    info = {"process": grant.get("process", "unknown"), "role": props.get("control_type", "unknown"),
            "name": props.get("name", "unknown"), "action": message.get("action"),
            "result": result.get("status"), "revoked_during": result.get("revoked_during", False),
            "foreground_changed": result.get("foreground_changed"),
            "target_came_forward": result.get("target_came_forward")}
    params = {} if message.get("action") == "set_value" else {
        key: value for key, value in argument(message).items()
        if number(value) or (isinstance(value, str) and len(value) <= 16)}
    if params:
        info["params"] = params
    if result.get("close_requested"):
        info["window_closed"] = bool(result.get("window_closed"))
    if message.get("action") == "set_value":
        value = message.get("value")
        info["value_length"] = len(value) if isinstance(value, str) else 0
        if isinstance(value, str) and value:
            for key in ("process", "role", "name"):
                info[key] = str(info[key]).replace(value, "[redacted]")
    session.tools.audit.append("action", "window", str(message.get("agent", ""))[:120], "window_action",
                               json.dumps(info, ensure_ascii=False, separators=(",", ":")))


def spawn_worker(function, *args):
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def finish(result, error):
        if not future.done():
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(result)

    def run():
        try:
            result, error = function(*args), None
        except Exception as exc:
            result, error = None, exc
        try:
            loop.call_soon_threadsafe(finish, result, error)
        except RuntimeError:
            pass  # the session has already shut down

    threading.Thread(target=run, daemon=True).start()
    return future


class ActionWorker:
    def __init__(self, session, runner=run_action, timeout=32):
        self.session, self.runner, self.timeout = session, runner, timeout
        self.task = None
        self.abandoned = False

    async def perform(self, message):
        access = self.session.window
        grant = access.grant or {}
        props = access.elements.get(message.get("element_id"), {})
        result = None
        if self.task and not self.task.done():
            result = {"status": "failed", "error": "previous action still running in the app"}
        elif not grant or not props:
            result = {"status": "failed", "error": "stale or unknown element"}
        elif (not self.session.accepted or not self.session.share or not self.session.control.granted
              or message.get("share_id") != self.session.share.get("share_id")
              or access.gate.revoked.is_set()):
            result = {"status": "failed", "error": "revoked"}
        else:
            generation = access.gate.generation
            deadline = asyncio.get_running_loop().time() + self.timeout
            try:
                probe = asyncio.to_thread(self.session.tools.audit.ensure_writable)
                await asyncio.wait_for(probe, self.timeout)
            except (OSError, TimeoutError):
                return {"status": "failed", "error": "audit unavailable"}
            self.abandoned = False
            self.task = spawn_worker(self.runner, access, grant, generation, message)
            try:
                remaining = max(0, deadline - asyncio.get_running_loop().time())
                result = await asyncio.wait_for(asyncio.shield(self.task), remaining)
            except TimeoutError:
                self.abandoned = True
                access.gate.invalidate()
                result = {"status": "timeout", "error": "UI Automation timed out"}
            except Exception:
                result = {"status": "failed", "error": "UI Automation failed"}
            except asyncio.CancelledError:
                access.gate.invalidate()
                try:
                    audit(self.session, grant, message, props, {"status": "unconfirmed"})
                except OSError:
                    pass
                raise
        if (result.get("error") == "window closed" or result.get("window_closed")) and access.grant is grant:
            access.revoke("window closed")
        elif result.get("error") == "secure desktop active":
            access.gate.invalidate()
        try:
            audit(self.session, grant, message, props, result)
        except OSError:
            return {"status": "failed", "error": "audit unavailable"}
        return result
