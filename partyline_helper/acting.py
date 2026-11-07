"""Agent actions: a queue apart from the receive loop, confined injection and the post-action frame."""
import asyncio
import contextlib
import math
import platform
from collections import defaultdict, deque

from websockets.exceptions import ConnectionClosed

from .actions import validate
from .keys import label

QUIET = 0.5          # seconds an XTest echo of the agent's key may take to reach the listener
SETTLE = 0.3         # wait before the post-action frame
MIN_INTERVAL = 0.05  # hard local ceiling of 20 actions/s; the server's limits are tighter
DRAG_STEPS, DRAG_STEP = 10, 0.02
CONTROL_CODES = {"\n": "enter", "\r": "enter", "\t": "tab"}  # pynput types these as named keys


def xtest_echoes(names):
    """The unflagged events pynput's X11 controller causes for these presses.

    Every injected press reaches the listener flagged (_on_fake_event). Named keys (enter,
    tab, modifiers, ...) are also sent with XTest, whose RECORD echo arrives unflagged, in
    either order. Characters go by XSendEvent, flagged, with Shift carried in the event
    state, so they add no unflagged echo and no Shift press.
    """
    return [name for name in names if len(name) > 1]


class Acting:
    """Mixed into Control: runs actions one at a time while dispatch keeps reading messages."""

    def setup_actions(self):
        self.pending, self.runner, self.tasks = deque(), None, set()

    def reset_actions(self):
        # Takeback is armed by the agent's first injected move; until then the person (who has just clicked
        # Yes in the consent dialog and moves the mouse away) cannot revoke by drifting or typing.
        self.target, self.injecting, self.clicked, self.began = None, False, False, False
        self.armed = False
        self.last_action = -math.inf
        self.expected = defaultdict(deque)  # key name -> deadlines of its outstanding injections

    def spawn(self, coroutine):
        task = asyncio.ensure_future(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def send_result(self, request_id, ok, **fields):
        with contextlib.suppress(ConnectionClosed):
            await self.session.send("action_result", request_id=request_id, ok=ok, **fields)

    def enqueue(self, message):
        self.pending.append(message)
        if self.runner is None or self.runner.done():
            self.runner = asyncio.create_task(self.run_actions())

    async def run_actions(self):
        while self.pending:
            message = self.pending.popleft()
            try:
                await self.act(message)
            except ConnectionClosed:
                self.pending.clear()  # nobody is left to answer
                return
            except Exception as exc:  # never die with requests stranded: fail closed instead
                print(f"Agent action failed: {exc}", flush=True)
                self.kill(f"agent control failed: {exc}")
                self.discard(f"agent control failed ({exc})")
                await self.send_result(message.get("request_id"), False, error=f"failed: {exc}",
                                       started=self.began)

    def discard(self, reason):
        """Refuse every queued action: revocation and stops never wait behind them."""
        while self.pending:
            message = self.pending.popleft()
            self.spawn(self.send_result(message.get("request_id"), False,
                                        error=f"discarded: {reason}", started=False))

    def live(self, share_id):
        share = self.session.share
        return self.granted and share is not None and share["share_id"] == share_id

    def expect(self, names):
        deadline = self.session.clock() + QUIET
        for name in names:
            self.expected[name].append(deadline)

    def agent_key(self, name, injected):
        """True when a key-down event is the agent's own injection.

        Flagged events are the agent's and expect nothing. Windows and macOS flag every
        injection, so there any unflagged press is the person's. On X11 an unflagged press is
        accepted only as the one XTest echo of a named key the agent pressed, each until its
        own deadline.
        """
        if injected:
            return True
        if self.flags_injected:
            return False
        waiting, now = self.expected[name], self.session.clock()
        while waiting and waiting[0] <= now:
            waiting.popleft()
        if not waiting:
            return False
        waiting.popleft()
        return True

    @contextlib.contextmanager
    def injection(self, mouse):
        # The drift watcher pauses only while the agent moves the mouse itself.
        self.injecting, self.began = mouse, True
        try:
            yield self.inputs
        finally:
            self.injecting = False

    def move(self, inputs, x, y):
        self.target = (x, y)  # before injecting, so the watcher never sees a stale target
        self.armed = True  # the baseline is the agent's own point, never the pointer at the grant
        inputs.move(x, y)

    async def act(self, message):
        request_id, self.began = message.get("request_id"), False
        try:
            detail = await self.perform(message)
        except ValueError as exc:
            print(f"Agent action {'interrupted' if self.began else 'refused'}: {exc}", flush=True)
            await self.send_result(request_id, False, error=str(exc), started=self.began)
            return
        print(f"Agent {self.agent}: {detail}", flush=True)
        x, y = self.session.desktop.pointer()
        await self.send_result(request_id, True, pointer=dict(x=x, y=y))
        await self.session.sleep(SETTLE)
        try:
            await self.session.frame(request_id, force=True)
        except (RuntimeError, OSError, ValueError) as exc:  # the action ran; only its frame failed
            print(f"Post-action frame failed: {exc}", flush=True)
            await self.session.send("error", request_id=request_id, message=f"capture failed: {exc}")

    def check(self, message):
        share = self.session.share
        if not self.live(message.get("share_id")):
            raise ValueError(f"agent control is not granted (revoked: {self.revoked})" if self.revoked
                             else "agent control is not granted")
        if self.drifted():
            self.kill("the pointer was moved on the computer")
            raise ValueError("agent control was revoked: the pointer was moved on the computer")
        return share["region"]

    async def perform(self, message):
        region, share_id = self.check(message), message.get("share_id")
        action = validate(message.get("action"), region, platform.system())
        kind, (x, y) = action["kind"], action.get("at", (None, None))
        if kind in ("type", "key") and not self.clicked:
            raise ValueError("click inside the shared region first so keys reach the right window")
        now = self.session.clock()
        if now - self.last_action < MIN_INTERVAL:
            raise ValueError("action rate limit")
        self.last_action = now
        if kind == "drag":
            await self.drag(share_id, action["start"], action["end"])
            return f"drag {action['start']} to {action['end']}"
        if kind == "type":
            await self.type(share_id, action["text"])
            return f"type {len(action['text'])} characters"
        with self.injection(kind != "key") as inputs:
            if kind == "key":
                self.expect(xtest_echoes(action["keys"]))
                inputs.key(action["keys"])
                return f"key {label(action['keys'])}"
            self.move(inputs, x, y)
            if kind == "click":
                inputs.click(action["button"], action["count"])
                self.clicked = True
                return f"{'double-' if action['count'] == 2 else ''}click {action['button']} at ({x}, {y})"
            if kind == "scroll":
                inputs.scroll(*action["delta"])
                return f"scroll {action['delta']} at ({x}, {y})"
        return f"move to ({x}, {y})"

    async def type(self, share_id, text):
        # One character at a time, yielding between them so the kill switch is heard mid-text.
        with self.injection(False) as inputs:
            for index, char in enumerate(text):
                if not self.live(share_id):
                    raise ValueError(f"agent control was revoked after {index} of {len(text)} characters")
                self.expect(xtest_echoes([CONTROL_CODES.get(char, char)]))
                inputs.type(char)
                await asyncio.sleep(0)

    async def drag(self, share_id, start, end):
        with self.injection(True) as inputs:
            self.move(inputs, *start)
            inputs.press("left")
            try:
                for step in range(1, DRAG_STEPS + 1):
                    await self.session.sleep(DRAG_STEP)
                    if self.live(share_id) and self.drifted():
                        self.kill("the pointer was moved on the computer")
                    if not self.live(share_id):
                        raise ValueError("agent control was revoked during the drag")
                    self.move(inputs, round(start[0] + (end[0] - start[0]) * step / DRAG_STEPS),
                              round(start[1] + (end[1] - start[1]) * step / DRAG_STEPS))
            finally:
                inputs.release("left")
        self.clicked = True
