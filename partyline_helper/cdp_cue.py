"""A visible cue for page input Partyline dispatched: Chrome's own inspector overlay, never the page's DOM.

`Overlay.highlight*` is drawn by the browser over the page's pixels: no node, no pointer or keyboard event, no
change to hit tests or the accessibility tree, nothing a site can see. It is drawn only from the code that
dispatches input, after the input went out, on tasks of its own: an answer, failure or revoked grant of the
cue never delays, retries or changes the action. Only this page session's tab is drawn on, and only while
visible. The overlay maps coordinates differently from input at a device scale above 1, so the first cue at
each pixel ratio measures the mapping with a probe; a cue that cannot be placed exactly is not drawn.

Every cue command of a page goes out one at a time, each after the reply (or failure, or transport timeout) of
the one before, so a hide can never run before a paint it follows. `dirty` means Chrome may be showing a
highlight of ours: set before any highlight is sent, cleared only by a hide that succeeded. A new cue
replaces the old one or, drawing nothing, hides it; a one-shot timer armed at dispatch hides it; a failed hide
is tried once more; a navigation hides it; detaching clears it. Commands in flight are never cancelled: a
newer generation just stops a cue before its next command.
"""
import asyncio
import base64
import io
import json

from .cdp_cue_js import FOCUSED, METRICS
from .cdp_cue_pixels import contrast, probe_scale
from .cdp_page_dialogs import PageDialog

POINTER_SECONDS = 2.5  # how long the pointer stays after the last input
RING_SECONDS = 0.8  # how long the click ring replaces the pointer
TARGET_SECONDS = 2.0  # how long a target or focus box stays
FAILURES = 3  # refusals in a row before this page stops trying (a Chrome without the overlay domain)
HIDE_RETRY = 1.0  # seconds before a failed hide is tried once more
PROBES = 3  # unreadable probes per pixel ratio before that ratio is given up
ARROW = ((0, 0), (14, 16), (6, 16), (0, 22))  # CSS pixels from the tip, drawn at 1.6 times this size
ARROW_SIZE = 1.6
RING = 44  # CSS pixels across
WHITE = {"r": 255, "g": 255, "b": 255, "a": 1}
POINTER = {"color": {"r": 255, "g": 0, "b": 128, "a": 0.95}, "outlineColor": WHITE}
RING_COLORS = {"color": {"r": 0, "g": 150, "b": 255, "a": 0.32},
               "outlineColor": {"r": 0, "g": 70, "b": 200, "a": 1}}
BOX = {"showInfo": False, "showStyles": False, "showRulers": False, "showAccessibilityInfo": False,
       "contentColor": {"r": 0, "g": 150, "b": 255, "a": 0.28},
       "borderColor": {"r": 255, "g": 0, "b": 128, "a": 0.95}}


class Stale(Exception):
    """A newer cue or a navigation took over before this command was sent."""


class Cue:
    """The one cue of a page session; every method is safe to call and returns at once."""

    def __init__(self, page, later=None):
        self.page, self.enabled = page, True
        self.later = later or (lambda delay, *call: asyncio.get_running_loop().call_later(delay, *call))
        self.scales, self.misses, self.failures, self.generation, self.epoch = {}, {}, 0, 0, 0
        self.tasks, self.timers, self.view, self.dirty, self.lock = set(), [], None, False, asyncio.Lock()
        self.revision = 0  # counts navigations of any kind, so a cue can tell the page moved
        self.expired = None  # the generation whose time ran out: it may not paint any more

    def mark(self):
        """The document and navigation count a cue belongs to: take it before the input is dispatched."""
        return self.page.epoch, self.revision

    def click(self, x, y, mark=None):
        """The click ring at a viewport point (CSS pixels, as the input was sent), then the pointer. `mark`
        is `mark()` from before the input was dispatched: if the page navigated since (a new document, or a
        fragment or history change), the point means nothing there and nothing is drawn."""
        self.start(lambda gen: self.point(gen, x, y, True), mark=mark)

    def move(self, x, y, mark=None):
        """The pointer alone, for input with a point but no click (a wheel step, a drag's end)."""
        self.start(lambda gen: self.point(gen, x, y, False), mark=mark)

    def target(self, backend, mark=None):
        """A box on the element the action reaches, for input with no pointer click (a value, a key)."""
        self.start(lambda gen: self.box(gen, {"backendNodeId": backend}), mark=mark)

    def focus(self, ident=None, moved=False, mark=None):
        """A box on `ident`, the element the pre-input probe proved the keys go to (released afterwards), or
        on the focus they moved to when `moved`. With neither, nothing is drawn and the old cue is hidden."""
        if not self.start(lambda gen: self.focused(gen, ident, moved), ident, mark):
            self.release(ident)

    def release(self, ident):
        if ident:
            self.start_task(self.free(ident))

    async def free(self, ident):
        try:
            await self.send("Runtime.releaseObject", {"objectId": ident})
        except Exception:  # the page may be gone, and with it the object
            pass

    def cancel(self):
        """Forget the cue (the page stopped or navigated): timers die, no new command is started for it."""
        self.generation += 1
        for timer in self.timers:
            timer.cancel()
        self.timers.clear()

    def dismiss(self):
        """The document changed or scrolled to another place: take down what Chrome may still be drawing."""
        self.revision += 1
        self.cancel()
        if self.dirty and self.page.live:
            self.start_task(self.hide())

    def start_task(self, coroutine):
        try:
            task = asyncio.get_running_loop().create_task(coroutine)
        except RuntimeError:  # no running loop: nothing can be drawn
            coroutine.close()
            return False
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return True

    def start(self, draw, release=None, mark=None):
        if not self.enabled or self.failures >= FAILURES or not self.page.live:
            return False
        if mark is not None and mark != self.mark():
            return False  # the page navigated since the input went out (which already hid the old cue)
        self.cancel()
        self.epoch = self.page.epoch
        return self.start_task(self.run(self.generation, draw, release))

    async def run(self, gen, draw, release):
        try:
            if await self.ready(gen):
                await draw(gen)
                self.failures = 0
        except Stale:
            pass
        except Exception:  # a cue is never worth an error: not a refusal, a lost page or a closed socket
            self.failures += 1
        if self.dirty and gen == self.generation and not self.timers:
            await self.hide()  # nothing replaced the old cue and no timer will take it down
        if release:
            await self.free(release)

    def attached(self):
        check = getattr(self.page.browser, "is_attached", None)
        return check(self.page.session) if check else True

    def guard(self):
        """Consent and a live page, but not the document an action began in: a cue outlives it."""
        self.page.guard(document=False)
        if self.page.page_dialog:
            raise PageDialog(self.page.page_dialog)

    async def send(self, method, params=None, gen=None, paint=False):
        """One command, after the reply of the one before; `gen` stops it if a newer cue took over."""
        async with self.lock:
            if gen is not None and (gen != self.generation or (paint and gen == self.expired)):
                raise Stale()  # a newer cue took over, or this one's time ran out before it was painted
            if method == "Overlay.hideHighlight" and not self.dirty:
                return {}
            self.guard()
            self.dirty = self.dirty or paint  # painted from the moment it is sent, answered or not
            reply = await self.page.browser.call(method, params or {}, self.page.session, self.guard)
            if method == "Overlay.hideHighlight":
                self.dirty = False
            return reply

    async def ready(self, gen):
        """The viewport numbers when this page may be drawn on now; None when it may not."""
        page = self.page
        if not (page.live and page.page_state == "alive" and not page.page_dialog and page.initialized
                and self.attached()):
            return None
        reply = await self.send("Runtime.evaluate", {"expression": METRICS, "returnByValue": True}, gen)
        try:
            visible, ratio, pinch, width, height = json.loads(reply["result"]["value"])
        except (KeyError, TypeError, ValueError):
            return None
        if page.epoch != self.epoch:
            return None  # the document changed: a point of the old one means nothing in the new one
        if visible is not True or abs(pinch - 1) > 0.01 or not ratio > 0:
            return None  # a hidden tab, or pinch zoom, which input and overlay map differently
        self.view = (ratio, width, height)
        return self.view

    async def paint(self, gen, method, params):
        await self.send("Overlay.enable", gen=gen)
        await self.send(method, params, gen, paint=True)

    async def draw(self, gen, method, params, seconds, then=None):
        """Paint, and keep the cue for `seconds`; the timers are armed at dispatch, before any command is
        sent, and a cue whose time ran out before its paint went out is never painted."""
        for delay, step in ((then and RING_SECONDS, then), (seconds, self.expire)):
            if delay:
                self.timers.append(self.later(delay, self.fire, gen, step))
        await self.paint(gen, method, params)

    def fire(self, gen, step):
        if gen == self.generation and self.page.live:
            self.start_task(self.step(gen, step))

    async def step(self, gen, step):
        try:
            await step(gen)
        except Exception:  # Stale, or the overlay is gone with the page
            pass

    async def expire(self, gen):
        self.expired = gen
        await self.hide()

    async def hide(self, gen=None, again=True):
        try:
            if self.page.live and self.attached():
                await self.send("Overlay.hideHighlight")
        except Exception:  # still dirty: once more, then the next cue or a navigation takes it down
            if again and self.page.live:
                self.timers.append(self.later(HIDE_RETRY, self.fire, self.generation,
                                              lambda g: self.hide(g, False)))

    async def scale(self, gen, ratio):
        """Screenshot pixels per overlay unit at this pixel ratio, measured once; None if it cannot be. The
        probe is what differs between a screenshot without it and one with it, whatever the page's colours;
        an unreadable one (an animating page) is retried a few times, then given up."""
        if ratio in self.scales:
            return self.scales[ratio]
        tries = self.misses.get(ratio, 0)
        if tries >= PROBES:
            return None
        await self.send("Overlay.enable", gen=gen)
        await self.send("Overlay.hideHighlight")
        before = await self.shot(gen)
        color = contrast(io.BytesIO(before), tries % 2)
        probe = {"x": 16, "y": 16, "width": 16, "height": 16, "color": color}
        try:
            await self.send("Overlay.highlightRect", probe, gen, paint=True)
            after = await self.shot(gen)
        finally:
            await self.send("Overlay.hideHighlight")
        measured = probe_scale(io.BytesIO(before), io.BytesIO(after), 16)
        if measured:
            self.scales[ratio] = measured
        else:
            self.misses[ratio] = tries + 1
        return measured

    async def shot(self, gen):
        reply = await self.send("Page.captureScreenshot", {
            "format": "png", "clip": {"x": 0, "y": 0, "width": 160, "height": 160, "scale": 1}}, gen)
        return base64.b64decode(reply["data"])

    def place(self, x, y, factor):
        """Overlay units of a viewport point: the page pixels the input used, times the measured mapping."""
        ratio, width, height = self.view
        if not (0 <= x <= width and 0 <= y <= height):
            return None
        return x * ratio / factor, y * ratio / factor

    async def point(self, gen, x, y, click):
        factor = await self.scale(gen, self.view[0])
        if not factor:
            return
        spot = self.place(x, y, factor)
        if spot is None:
            return
        unit = self.view[0] / factor
        if click:
            half = RING / 2 * unit
            rect = {"x": spot[0] - half, "y": spot[1] - half, "width": RING * unit, "height": RING * unit}
            whole = {key: round(value) for key, value in rect.items()}  # the protocol takes whole units
            await self.draw(gen, "Overlay.highlightRect", {**whole, **RING_COLORS}, POINTER_SECONDS,
                            then=lambda g: self.arrow(g, spot, unit, False))
        else:
            await self.arrow(gen, spot, unit, True)

    async def arrow(self, gen, spot, unit, fresh):
        if self.page.epoch != self.epoch:
            raise Stale()
        scale = ARROW_SIZE * unit
        quad = [value for dx, dy in ARROW for value in (spot[0] + dx * scale, spot[1] + dy * scale)]
        if fresh:
            await self.draw(gen, "Overlay.highlightQuad", {"quad": quad, **POINTER}, POINTER_SECONDS)
        else:
            await self.paint(gen, "Overlay.highlightQuad", {"quad": quad, **POINTER})

    async def box(self, gen, node):
        await self.draw(gen, "Overlay.highlightNode", {"highlightConfig": BOX, **node}, TARGET_SECONDS)

    async def focused(self, gen, ident, moved):
        if moved:  # Tab: the focus the keys moved to, read after their replies, so after their effect
            reply = await self.send("Runtime.evaluate", {"expression": FOCUSED}, gen)
            ident = reply.get("result", {}).get("objectId")
        if not ident:
            return
        try:
            await self.box(gen, {"objectId": ident})
        finally:
            if moved:
                await self.free(ident)
