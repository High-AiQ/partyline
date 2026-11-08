"""Local tools on the helper: per-session consent, the add-on connection, audit and every kill switch.

The server only routes: a call runs here only while this computer holds a live local grant, and the grant
dies on any revoke below even if the server is gone. Grants are in memory; nothing is pre-granted.
"""
import asyncio
import contextlib
import json
import math

from websockets.exceptions import ConnectionClosed

from . import tools_consent, tools_media
from .terminal import display_text
from .tools_addon import AddonClient, AddonError, spec_for
from .tools_audit import ToolAudit, entry

TOOLS_VERSION = 1
MESSAGES = ("tools_request", "tool_call", "tool_cancel", "tools_revoked")
RENEW = 5            # seconds between lease renewals to the add-on
LOST = 3             # failed renewals in a row before the add-on counts as gone
IDLE = 15 * 60       # a session with no call for this long ends (Greg: 15 minutes)
COOLDOWN = 10 * 60   # after a kill on this computer the agent may not ask again (Greg: 10 minutes)
MAX_RESULT = 64 * 1024
GONE = {"app": "the End button was pressed in the app", "lease": "the add-on's lease lapsed",
        "unknown": "the add-on no longer knows the session"}


class Tools:
    def __init__(self, session):
        self.session = session
        self.addon_for = AddonClient
        self.audit = ToolAudit()
        self.cooldown_until = -math.inf
        self.tasks = set()
        self.reset()

    def reset(self):
        self.grant = self.prompt = self.inputs = self.prompt_id = None
        self.calls, self.held = {}, set()
        self.last_activity = 0.0

    @property
    def prompting(self):
        return self.prompt is not None and not self.prompt.done()

    async def withdraw(self):
        """Cancel a pending question and wait until it is really gone, so a new request is not refused."""
        self.prompt.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.prompt

    def spawn(self, coroutine):
        task = asyncio.ensure_future(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def send(self, kind, **fields):
        with contextlib.suppress(ConnectionClosed):
            await self.session.send(kind, **fields)

    async def revoked(self, session_id, reason, scope_only=False):
        """Tell the server a request was refused or a session ended. `scope_only` marks the refusal of an
        extra scope on a session that is still live, so the server must not end that session."""
        fields = {"scope_only": True} if scope_only else {}
        await self.send("tools_revoked", session_id=session_id, reason=reason, **fields)

    def log(self, kind, op, entry, code=None):
        g = self.grant
        with contextlib.suppress(OSError):
            self.audit.append(kind, g["id"] if g else "-", g["agent"] if g else "-", op, entry, code)

    async def dispatch(self, message):
        kind = message["type"]
        if kind == "tools_request":
            await self.request(message)
        elif kind == "tool_call":
            self.spawn(self.run_call(message))
        elif kind == "tool_cancel":
            await self.cancel(message.get("call_id"))
        elif kind == "tools_revoked":
            if self.prompting and self.prompt_id == message.get("session_id"):
                await self.withdraw()
                print("\nLocal tools request withdrawn.", flush=True)
            if self.grant and self.grant["id"] == message.get("session_id"):
                reason = display_text(message.get("reason"))
                await self.drop(f"revoked from Partyline ({reason})", local=False, tell=False)

    async def request(self, message):
        session_id = str(message.get("session_id"))
        spec = spec_for(message.get("tool"))
        scope_only = message.get("scope_only") is True
        live = self.grant is not None and self.grant["id"] == session_id
        if spec is None:
            return await self.revoked(session_id, "this computer has no adapter for that tool")
        if self.prompting:
            return await self.revoked(session_id, "prompt pending", scope_only and live)
        if scope_only != live or (not scope_only and self.grant):
            return await self.revoked(session_id, "another session is active" if self.grant else
                                      "no live session to add render checks to")
        wait = self.cooldown_until - self.session.clock()
        if wait > 0 and not scope_only:
            return await self.revoked(session_id, f"stopped on this computer; the agent may ask again in "
                                      f"{math.ceil(wait / 60)} min")
        self.prompt_id = session_id
        self.prompt = asyncio.create_task(self.ask(message, spec, scope_only))

    async def ask(self, message, spec, scope_only):
        session_id, agent = str(message["session_id"]), display_text(message.get("requested_by"))
        addon = self.grant["addon"] if scope_only else self.addon_for(spec)
        try:
            info = await addon.info()
        except AddonError as exc:
            print(f"Local tools unavailable: {exc}", flush=True)
            return await self.revoked(session_id, str(exc), scope_only)
        print(f"\nLOCAL TOOLS REQUEST\nRequested by: {agent}\nTool: {spec.label}", flush=True)
        if scope_only:
            yes = ticked = await tools_consent.ask_scope(self.session.terminal, spec, message)
        else:
            yes, ticked = await tools_consent.ask(self.session.terminal, spec, message, info)
        if not yes:
            print("Local tools declined.", flush=True)
            return await self.revoked(session_id, "Local consent declined or timed out", scope_only)
        if scope_only:
            self.grant["checker"] = self.grant["checker"] or ticked
            self.log("event", "session", f"render checks {'allowed' if ticked else 'not allowed'}")
            return await self.send("tools_granted", session_id=session_id, checker=self.grant["checker"])
        await self.open(session_id, agent, spec, addon, ticked, info)

    async def open(self, session_id, agent, spec, addon, ticked, info):
        try:
            self.start_keys()  # fail closed: no kill-switch listener, no session
        except (RuntimeError, ImportError, OSError, ValueError) as exc:
            print(f"Local tools unavailable: {exc}", flush=True)
            return await self.revoked(session_id, f"kill switch unavailable: {exc}")
        try:
            opened = await addon.open_session(session_id, agent, ticked)
        except AddonError as exc:
            self.stop_keys()
            print(f"Local tools unavailable: {exc}", flush=True)
            return await self.revoked(session_id, str(exc))
        self.grant = grant = {"id": session_id, "agent": agent, "spec": spec, "addon": addon,
                              "checker": ticked}
        self.last_activity = self.session.clock()
        loop = asyncio.get_running_loop()
        status = self.session.status
        status.stop_tools = lambda: loop.call_soon_threadsafe(self.kill, "ended from the tray menu")
        status.tools_active = True
        if status.state == "paired":
            status.set("tools")
        self.spawn(self.renew_loop(grant))
        self.spawn(self.idle_loop(grant))
        self.log("event", "session", f"granted (render checks: {'yes' if ticked else 'no'})")
        print(f"LOCAL TOOLS ACTIVE — {agent} can run Python in {spec.label}. Ctrl+Alt+Esc or the "
              "tray menu ends it.", flush=True)
        await self.send("tools_granted", session_id=session_id, checker=ticked, info={
            "tool": spec.label, "file": info.get("file") or "", "backup": opened.get("backup") or ""})

    def start_keys(self):
        loop = asyncio.get_running_loop()
        self.inputs = self.session.control.make_inputs(self.session.desktop)
        self.inputs.listen(lambda *event: loop.call_soon_threadsafe(self.key_event, *event))

    def stop_keys(self):
        inputs, self.inputs = self.inputs, None
        if inputs:
            inputs.stop()
        self.held.clear()

    def key_event(self, name, injected, down):
        if not self.grant:
            return
        if not down:
            self.held.discard(name)
            return
        self.held.add(name)
        if name == "esc" and {"ctrl", "alt"} <= self.held:
            self.kill("Ctrl+Alt+Esc pressed")

    def kill(self, reason):
        """A person on this computer ended it: the agent may not ask again for COOLDOWN seconds."""
        if self.grant:
            self.spawn(self.drop(reason, local=True))

    async def drop(self, reason, local, tell=True):
        grant, self.grant = self.grant, None
        if not grant:
            return False
        if self.prompting and asyncio.current_task() is not self.prompt:
            await self.withdraw()  # a render-check question about a session that no longer exists
        if local:
            self.cooldown_until = self.session.clock() + COOLDOWN
        me = asyncio.current_task()
        for call_id, task in list(self.calls.items()):
            with contextlib.suppress(AddonError):
                await grant["addon"].cancel(grant["id"], call_id)
            if task is not me:
                task.cancel()
        self.calls.clear()
        self.stop_keys()
        with contextlib.suppress(AddonError):
            await grant["addon"].close_session(grant["id"])
        status = self.session.status
        status.tools_active, status.stop_tools = False, None
        if status.state == "tools":
            status.set("paired")
        with contextlib.suppress(OSError):
            self.audit.append("event", grant["id"], grant["agent"], "session", f"revoked ({reason})")
        print(f"LOCAL TOOLS REVOKED: {reason}", flush=True)
        if tell:
            await self.revoked(grant["id"], reason)
        return True

    async def end(self, reason):
        """The helper's connection ended: the session ends with it."""
        if self.prompting:
            await self.withdraw()
        await self.drop(reason, local=False, tell=False)

    async def renew_loop(self, grant):
        failures = 0
        while self.grant is grant:
            await self.session.sleep(RENEW)
            if self.grant is not grant:
                return
            try:
                gone, failures = await grant["addon"].renew(grant["id"]), 0
            except AddonError:
                failures += 1
                gone = "unreachable" if failures >= LOST else None
            if gone is not None:
                text = GONE.get(gone, f"the add-on is {gone}")
                await self.drop(text[0].upper() + text[1:], local=gone == "app")
                return

    async def idle_loop(self, grant):
        while self.grant is grant:
            wait = IDLE - (self.session.clock() - self.last_activity)
            if wait <= 0:
                await self.drop("idle for 15 minutes", local=False)
                return
            await self.session.sleep(wait)

    async def cancel(self, call_id):
        task, grant = self.calls.get(call_id), self.grant
        if grant and task:
            with contextlib.suppress(AddonError):
                await grant["addon"].cancel(grant["id"], call_id)
            task.cancel()

    async def run_call(self, message):
        call_id, grant = message.get("call_id"), self.grant
        op, args = message.get("op"), message.get("args")
        try:
            timeout = min(180.0, max(1.0, float(message.get("timeout") or 20)))
        except (TypeError, ValueError):
            timeout = 20.0
        problem = ("no active local tools session" if not grant or grant["id"] != message.get("session_id")
                   else "unsupported operation" if op not in grant["spec"].ops
                   else "arguments must be an object" if not isinstance(args, dict) else None)
        if problem:
            return await self.send("tool_result", call_id=call_id, ok=False, error=problem)
        self.calls[call_id] = asyncio.current_task()
        self.last_activity = self.session.clock()
        code = args.get("code") if isinstance(args.get("code"), str) else None
        try:
            self.audit.append("call", grant["id"], grant["agent"], op, entry(op, args, code), code)
        except OSError as exc:  # fail closed: a script that cannot be logged is not run
            self.calls.pop(call_id, None)
            return await self.send("tool_result", call_id=call_id, ok=False,
                                   error=f"the local audit log cannot be written ({exc.__class__.__name__})")
        try:
            answer = await grant["addon"].call(grant["id"], call_id, op, args, timeout)
        except AddonError as exc:
            answer = {"error": str(exc)}
        except asyncio.CancelledError:
            self.log("event", op, "cancelled")
            raise
        finally:
            self.calls.pop(call_id, None)
            self.last_activity = self.session.clock()
        result = answer.get("result")
        if result is not None and len(json.dumps(result)) > MAX_RESULT:
            result, answer = None, {"error": "the result is too large"}
        if tools_media.has_image(op, result):
            return await tools_media.deliver(self, grant, call_id, op, result)
        self.log("result", op, "ok" if result is not None else f"failed: {answer.get('error')}")
        if result is None:
            return await self.send("tool_result", call_id=call_id, ok=False, error=str(answer.get("error")),
                                   busy=bool(answer.get("busy")))
        await self.send("tool_result", call_id=call_id, ok=True, result=result)
