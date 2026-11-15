"""Audit and one-shot thread completion for UIA workers."""
import asyncio
import json
import threading

from .uia_patterns import argument, number

def audit(session, grant, message, props, result):
    info = {"process": grant.get("process", "unknown"), "role": props.get("control_type", "unknown"),
            "name": props.get("name", "unknown"), "action": message.get("action"),
            "result": result.get("status"), "revoked_during": result.get("revoked_during", False),
            "foreground_changed": result.get("foreground_changed"),
            "target_came_forward": result.get("target_came_forward"),
            "foreground_restored": result.get("foreground_restored", False)}
    if props.get("scope_window"):
        info["scope_window"] = props["scope_window"]
    if message.get("force"):
        info["force"] = True
        info["reported_disabled"] = result.get("reported_disabled", False)
    args = argument(message)
    if isinstance(args, str):
        args = {"option": args}
    params = {} if message.get("action") == "set_value" else {
        key: value for key, value in args.items()
        if number(value) or (isinstance(value, str) and len(value) <= 16)}
    if params:
        info["params"] = params
    if result.get("close_requested"):
        info["window_closed"] = bool(result.get("window_closed"))
    if message.get("action") == "set_value":
        value = message.get("value")
        info["value_length"] = len(value) if isinstance(value, str) else 0
        if isinstance(value, str) and value:
            for key in ("process", "role", "name", "scope_window"):
                if key not in info:
                    continue
                info[key] = str(info[key]).replace(value, "[redacted]")
    if getattr(session, "window_grant_id", None):
        from .screen_access_audit import audit_window
        audit_window(session, "uia_action", message.get("agent", ""), result.get("status", "failed"),
                     message.get("line"))
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
