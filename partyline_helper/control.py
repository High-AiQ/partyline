"""Agent control: a separate local consent, region-confined input and the kill switch."""
import asyncio
import contextlib
import math
import platform

from websockets.exceptions import ConnectionClosed

from .acting import Acting
from partyline.file_events import Changes
from .terminal import display_text

CONTROL_VERSION = 1
DRIFT = 8            # desktop pixels the pointer may move from the agent's position


def border_mode(session, mode):
    """Turn the capture-zone border red ("control") while an agent drives, amber ("share") after."""
    session.status.set({"control": "control", "share": "sharing"}[mode])
    if session.border is not None:
        session.border.set_mode(mode)


def default_inputs(desktop):
    from .inputs import Inputs
    return Inputs(getattr(desktop, "scale", 1.0))


class Control(Acting):
    def __init__(self, session, inputs=None, without_prompt=False):
        self.input_changes = Changes()
        self.session = session
        self.make_inputs = inputs or default_inputs
        self.without_prompt = without_prompt
        # Windows (LLKHF_INJECTED) and macOS (source PID) flag injected keys; X11 XTest does not.
        self.flags_injected = platform.system() in ("Windows", "Darwin")
        self.setup_actions()
        self.reset()

    def reset(self):
        self.share_id = self.agent = self.inputs = self.watcher = self.prompt = None
        self.granted, self.revoked = False, None
        self.held = set()
        self.reset_actions()

    @property
    def prompting(self):
        return self.prompt is not None and not self.prompt.done()

    async def dispatch(self, message):
        kind = message["type"]
        if kind == "control_request":
            await self.request(message)
        elif kind == "control_revoked" and self.share_id == message.get("share_id"):
            if self.prompting:
                self.prompt.cancel()
                print("\nAgent control request withdrawn.", flush=True)
            reason = f"revoked from Partyline ({display_text(message.get('reason'))})"
            if not self.drop(reason):
                self.revoked = self.revoked or reason
        elif kind == "action":
            self.enqueue(message)

    async def answer(self, kind, **fields):
        with contextlib.suppress(ConnectionClosed):
            await self.session.send(kind, share_id=self.share_id, **fields)

    async def request(self, message):
        share = self.session.share
        if not share or not self.session.accepted or message.get("share_id") != share["share_id"]:
            with contextlib.suppress(ConnectionClosed):
                await self.session.send("control_revoked", share_id=message.get("share_id"),
                                        reason="no active share")
            return
        self.share_id = share["share_id"]
        if self.revoked:
            await self.answer("control_revoked", reason=f"already revoked for this share ({self.revoked})")
        elif self.granted:
            await self.answer("control_granted")
        elif self.prompting:
            await self.answer("control_revoked", reason="prompt pending")
        else:
            self.prompt = asyncio.create_task(self.ask(message))
            self.input_changes.notify()
            self.prompt.add_done_callback(lambda _: self.input_changes.notify())

    async def ask(self, message):
        reader = getattr(self.session, "stop_read", None)
        if reader is not None:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        agent = display_text(message.get("requested_by"))
        print(f"\nAGENT CONTROL REQUEST\nRequested by: {agent}\n"
              f"Line: {display_text(message.get('line_name'))}\n"
              "The agent could move the mouse, click, scroll and type inside the shared region. "
              "Window element actions require their own process-specific grant.",
              flush=True)
        if self.without_prompt:
            print("WARNING: --allow-control-without-prompt GRANTED AGENT CONTROL WITHOUT ASKING.", flush=True)
        elif not await self.session.terminal.ask("Allow agent control? [y/N] ", dialog=(
                "Partyline agent control request",
                f"{agent} asks to control the mouse and keyboard inside the shared region "
                f"(line: {display_text(message.get('line_name'))}). Window element actions require "
                "their own process-specific grant.\n\nAfter mouse or keyboard control starts, "
                "moving the mouse or pressing a key takes control back. Ctrl+Alt+Esc revokes mouse and "
                "keyboard control. Window grants have separate Stop controls in the tray."
                "\n\nAllow agent control?")):
            print("Agent control declined.", flush=True)
            await self.answer("control_revoked", reason="Local consent declined or timed out")
            return
        try:
            self.start(agent)
        except (RuntimeError, ImportError, OSError, ValueError) as exc:
            self.release()
            print(f"Agent control unavailable: {exc}", flush=True)
            await self.answer("control_revoked", reason=f"control unavailable: {exc}")
            return
        await self.answer("control_granted")

    def start(self, agent):
        loop = asyncio.get_running_loop()
        self.inputs = self.make_inputs(self.session.desktop)
        # Fail closed: no listener means no kill switch, so no control.
        self.inputs.listen(lambda *event: loop.call_soon_threadsafe(self.key_event, *event),
                           lambda: loop.call_soon_threadsafe(self.pointer_event))
        self.granted, self.agent, self.clicked = True, agent, False
        if getattr(self.session, "window", None) and self.session.window.grant:
            self.session.window.gate.grant()
        self.target, self.armed = None, False  # armed by the agent's first action (see Acting.move)

        print(f"AGENT CONTROL ACTIVE — {agent} can use the mouse and keyboard in the shared region.\n"
              "After mouse or keyboard control starts, move the mouse or press a key to take control back. "
              "Window grants have separate Stop controls in the tray. "
              "Type s Enter to stop pixel sharing.", flush=True)
        border_mode(self.session, "control")

    def release(self, reason="agent control ended"):
        if getattr(self.session, "window", None):
            self.session.window.gate.invalidate()
        self.discard(reason)
        inputs, self.inputs = self.inputs, None
        if inputs:
            inputs.stop()
        watcher, self.watcher = self.watcher, None
        if watcher and watcher is not asyncio.current_task():
            watcher.cancel()

    def drop(self, reason):
        """Revoke for the rest of this share; True when control was active."""
        if not self.granted:
            return False
        self.granted, self.revoked = False, reason
        self.release(f"agent control was revoked ({reason})")
        print(f"AGENT CONTROL REVOKED: {reason}", flush=True)
        border_mode(self.session, "share")
        return True

    def kill(self, reason):
        if self.drop(reason):
            self.spawn(self.answer("control_revoked", reason=reason))

    def end(self, reason):
        """The share ended: control ends with it."""
        if self.prompt:
            self.prompt.cancel()
        if self.granted:
            print(f"Agent control ended: {reason}", flush=True)
            border_mode(self.session, "share")
        self.release(f"the share ended ({reason})")
        self.reset()

    def key_event(self, name, injected, down):
        if not self.granted:
            return
        if not down:
            self.held.discard(name)
            return
        self.held.add(name)
        if name == "esc" and {"ctrl", "alt"} <= self.held:
            self.kill("Ctrl+Alt+Esc pressed")  # at any time, armed or not
        elif self.armed and not self.agent_key(name, injected):
            self.kill("a key was pressed on the computer")

    def drifted(self):
        if not self.armed:
            return False
        x, y = self.session.desktop.pointer()
        return math.hypot(x - self.target[0], y - self.target[1]) > DRIFT

    def pointer_event(self):
        if self.granted and not self.injecting and self.drifted():
            self.kill("the pointer was moved on the computer")
