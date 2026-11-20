"""The visible cue of page input: Chrome's overlay, drawn after the input, never part of it."""
import asyncio
import io
import json
import unittest
from types import SimpleNamespace

from PIL import Image, ImageDraw

from partyline_helper import cdp_cue, point_ops
from partyline_helper.cdp_transport import CDPError
from partyline_helper.cdp_cue_pixels import contrast, probe_scale
from tests.cdp_fakes import Fixture
from tests.screen_helper_fakes import checkpoint

FRAME = (0, 0, 1.0, (0, 0, 10000, 10000))  # screen pixels are page pixels
CLICK = {"button": "left", "clicks": 1}


class Timers:
    """Stands in for the loop's one-shot timers: a test fires them, nothing waits."""

    def __init__(self):
        self.pending = []

    def later(self, delay, call, *args):
        item = SimpleNamespace(delay=delay, call=call, args=args, cancelled=False)
        item.cancel = lambda: setattr(item, "cancelled", True)
        self.pending.append(item)
        return item

    def fire(self, index):
        item = self.pending[index]
        item.call(*item.args)


class CueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.f = Fixture(cues=True)
        self.addAsyncCleanup(self.f.close)
        socket = self.f.socket
        socket.states[2]["aria_disabled"] = False  # the link
        socket.nodes.append(dict(nodeId="4", parentId="1", backendDOMNodeId=4, role={"value": "textbox"},
                                 name={"value": "Name"}))
        socket.states[4] = dict(tag="INPUT", type="text", hit=True, value="")
        self.rows = await self.f.read()
        self.page = self.f.chrome.pages[self.f.access]["a"]
        self.timers = Timers()
        self.page.cue.later = self.timers.later
        self.page.quiet.wait = lambda: asyncio.sleep(0, "quiet")

    def calls(self, *prefix):
        return [m for m in self.f.socket.calls if m["method"].startswith(prefix or ("",))]

    def drawn(self):
        return [m for m in self.calls("Overlay.highlight") if m["params"].get("width") != 16]

    async def drawing(self):
        for _ in range(500):  # event-loop turns, not time: every fake answers in one
            if not self.page.cue.tasks:
                return
            await asyncio.sleep(0)
        for task in self.page.cue.tasks:
            task.print_stack()
        self.fail("a cue never finished drawing")

    def element(self, kind):
        return next(row["id"] for row in self.rows["elements"] if row["control_type"] == kind)

    async def act(self, kind, action, **extra):
        result = await self.f.chrome.action(self.f.access, dict(action=action, element_id=self.element(kind),
                                                                **extra))
        await self.drawing()
        return result

    async def test_reading_and_page_events_that_no_agent_caused_draw_nothing(self):
        for method in ("DOM.childNodeInserted", "Page.frameResized", "Input.dragIntercepted"):
            self.f.socket.event(method, session="a")
        await self.f.read()
        await checkpoint()
        await self.drawing()
        self.assertEqual([], self.calls("Overlay."))

    async def test_a_dispatched_click_shows_a_ring_at_the_input_point_then_the_pointer_then_hides(self):
        result = await self.act("Hyperlink", "invoke")
        self.assertEqual("completed", result["status"])
        self.assertNotIn("cue", json.dumps(result))  # the answer is the action's, never the cue's
        methods = [m["method"] for m in self.f.socket.calls]
        press = methods.index("Input.dispatchMouseEvent")
        first = next(i for i, name in enumerate(methods) if name.startswith("Overlay."))
        self.assertLess(press, first)  # the cue follows the input
        (ring,) = self.drawn()
        shape = (ring["method"], ring["params"]["x"], ring["params"]["y"], ring["params"]["width"])
        self.assertEqual(("Overlay.highlightRect", 28, -2, 44), shape)
        delays = [t.delay for t in self.timers.pending]
        self.assertEqual([cdp_cue.RING_SECONDS, cdp_cue.POINTER_SECONDS], delays)
        self.timers.fire(0)  # the ring ends: the pointer takes its place at the same point
        await self.drawing()
        quad = self.drawn()[-1]
        self.assertEqual(("Overlay.highlightQuad", [50, 20]), (quad["method"], quad["params"]["quad"][:2]))
        self.timers.fire(1)
        await self.drawing()
        self.assertEqual("Overlay.hideHighlight", self.calls("Overlay.")[-1]["method"])

    async def test_semantic_input_with_no_click_shows_its_target_and_no_ring(self):
        for action, extra in (("set_value", dict(value="Ada")), ("press", dict(key="enter"))):
            with self.subTest(action=action):
                self.f.socket.calls.clear()
                await self.act("Edit", action, **extra)
                (box,) = self.drawn()
                self.assertEqual(("Overlay.highlightNode", 4),
                                 (box["method"], box["params"]["backendNodeId"]))
                self.assertFalse([m for m in self.calls("Overlay.highlightRect")
                                  if m["params"].get("width") != 16])
                self.assertFalse([m for m in self.calls("Input.dispatchMouseEvent")])

    async def test_a_cue_that_never_answers_or_fails_never_delays_or_changes_the_action(self):
        socket = self.f.socket
        send = socket.send

        async def silent(raw):
            if json.loads(raw)["method"].startswith(("Overlay.", "Page.captureScreenshot")):
                return  # Chrome never answers
            await send(raw)
        socket.send = silent
        link = self.element("Hyperlink")
        result = await self.f.chrome.action(self.f.access, dict(action="invoke", element_id=link))
        self.assertEqual("completed", result["status"])
        self.assertEqual("quiet", result["settle"])
        self.assertEqual(2, len(self.calls("Input.dispatchMouseEvent")))  # never repeated

    async def test_a_refused_overlay_is_not_retried_and_a_page_stops_trying_after_a_few(self):
        socket = self.f.socket
        send = socket.send

        async def refuse(raw):
            message = json.loads(raw)
            if message["method"].startswith("Overlay."):
                socket.calls.append(message)
                socket.queue.put_nowait({"id": message["id"], "error": {"code": -32601, "message": "no"}})
                return
            await send(raw)
        socket.send = refuse
        for _ in range(cdp_cue.FAILURES + 2):
            result = await self.act("Hyperlink", "invoke")
            self.assertEqual("completed", result["status"])
        self.assertEqual(cdp_cue.FAILURES, len(self.calls("Overlay.enable")))

    async def test_the_probe_corrects_a_device_scale_and_an_unmeasurable_mapping_draws_nothing(self):
        self.f.socket.ratio, self.f.socket.overlay_scale = 1.5, 2.25  # the overlay draws at ratio squared
        await self.act("Hyperlink", "invoke")
        ring = self.drawn()[0]["params"]
        self.assertEqual((19, 29), (ring["x"], ring["width"]))  # 50 * 1.5 / 2.25 less half of 44 units
        self.assertEqual([2.25], list(self.page.cue.scales.values()))
        self.page.cue.scales.clear()
        self.f.socket.calls.clear()
        self.f.socket.overlay_scale = 0  # the probe is not in the screenshot
        for _ in range(cdp_cue.PROBES + 2):
            await self.act("Hyperlink", "invoke")
        self.assertEqual([], self.drawn())
        self.assertEqual(cdp_cue.PROBES, len(self.calls("Page.captureScreenshot")) // 2)  # then given up
        self.f.socket.overlay_scale = 2.25  # a page that stopped animating is measured again at once
        self.page.cue.misses.clear()
        await self.act("Hyperlink", "invoke")
        self.assertEqual("Overlay.highlightRect", self.drawn()[0]["method"])

    async def test_the_probe_is_found_by_what_changed_so_any_page_colour_is_measured(self):
        for color in ("magenta", (255, 0, 255), "black", "white", (128, 128, 128)):
            with self.subTest(color=color):
                self.f.socket.page_color = color
                self.page.cue.scales.clear()
                self.page.cue.misses.clear()
                self.f.socket.calls.clear()
                await self.act("Hyperlink", "invoke")
                self.assertEqual(["Overlay.highlightRect"], [m["method"] for m in self.drawn()])
                self.assertEqual([1], list(self.page.cue.scales.values()))

    async def test_a_hidden_tab_a_pinch_zoomed_page_and_a_detached_extension_tab_are_never_drawn_on(self):
        self.f.socket.visible["a"] = False
        await self.act("Hyperlink", "invoke")
        self.f.socket.visible["a"] = True
        self.f.browser.is_attached = lambda session: False
        await self.act("Hyperlink", "invoke")
        self.assertEqual([], self.calls("Overlay."))

    async def test_a_point_outside_the_viewport_is_not_drawn(self):
        self.page.cue.click(900, 20)
        await self.drawing()
        self.assertEqual([], self.drawn())

    async def test_navigation_and_a_changed_document_cancel_the_cue_and_stop_a_drawing_in_flight(self):
        await self.act("Hyperlink", "invoke")
        self.assertTrue(self.page.cue.dirty)
        self.f.socket.event("Page.frameNavigated", session="a", frame={"id": "main", "url": "https://x.test/"})
        await checkpoint()
        await self.drawing()
        self.assertFalse(self.page.cue.dirty)  # taken down, not just forgotten
        self.assertTrue(all(t.cancelled for t in self.timers.pending))
        self.f.socket.calls.clear()
        self.page.cue.click(10, 10)
        self.page.epoch += 1  # the document changed before the cue could be drawn
        await self.drawing()
        self.assertEqual([], self.drawn())

    async def test_a_revoked_grant_draws_nothing_and_a_stopped_page_drops_its_timers(self):
        await self.act("Hyperlink", "invoke")
        self.f.chrome.revoke(self.f.access)
        self.assertTrue(all(t.cancelled for t in self.timers.pending))
        self.f.socket.calls.clear()
        self.page.cue.click(10, 10)
        await self.drawing()
        self.assertEqual([], self.calls("Overlay."))

    def freed(self):
        return [m["params"] for m in self.calls("Runtime.releaseObject") if "objectId" in m["params"]]

    async def test_pointer_operations_cue_their_point_and_the_keyboard_its_focus(self):
        await point_ops.by_cdp("click", self.page, FRAME, [(30, 40)], CLICK, lambda: None)
        await self.drawing()
        self.assertEqual(("Overlay.highlightRect", 8, 18), (self.drawn()[-1]["method"],
                                                            self.drawn()[-1]["params"]["x"],
                                                            self.drawn()[-1]["params"]["y"]))
        await point_ops.by_cdp("scroll", self.page, FRAME, [(60, 70)], {"dx": 0, "dy": -1}, lambda: None)
        await self.drawing()
        self.assertEqual("Overlay.highlightQuad", self.drawn()[-1]["method"])  # a pointer, no ring
        await point_ops.by_cdp("drag", self.page, FRAME, [(5, 5), (80, 90)], {}, lambda: None)
        await self.drawing()
        self.assertEqual([80, 90], self.drawn()[-1]["params"]["quad"][:2])
        self.f.socket.focus_object = "field"
        await point_ops.by_cdp("type", self.page, FRAME, [], {"text": "x"}, lambda: None)
        await self.drawing()
        self.assertEqual(("Overlay.highlightNode", "field"), (self.drawn()[-1]["method"],
                                                              self.drawn()[-1]["params"]["objectId"]))
        self.assertEqual([{"objectId": "field"}], self.freed())
        await point_ops.by_cdp("key", self.page, FRAME, [], {"names": ["enter"]}, lambda: None)
        await self.drawing()
        self.assertEqual("Overlay.highlightNode", self.drawn()[-1]["method"])

    async def test_a_refused_native_select_is_not_boxed_and_a_sent_one_is(self):
        self.f.socket.options = [dict(label=c, value=c) for c in "ABC"]
        self.f.socket.states[3].update(selected_index=0, value="A")
        rows = await self.f.read()
        combo = next(row["id"] for row in rows["elements"] if row["control_type"] == "ComboBox")
        result = await self.f.chrome.action(self.f.access, dict(action="select", element_id=combo, value="Z"))
        await self.drawing()
        self.assertEqual("failed", result["status"])
        self.assertEqual([], self.calls("Input."))  # nothing was sent, so nothing is shown
        self.assertEqual([], self.calls("Overlay."))
        await self.f.chrome.action(self.f.access, dict(action="select", element_id=combo, value="B"))
        await self.drawing()
        self.assertEqual(["Overlay.highlightNode"], [m["method"] for m in self.drawn()])

    async def test_typing_boxes_the_field_the_probe_proved_even_if_the_page_moves_the_focus(self):
        socket = self.f.socket
        socket.focus_object = "name"

        def hook(message):
            if message["method"] == "Input.insertText":
                socket.focus_object = "other"  # the page moved the focus when the text arrived
        socket.hook = hook
        await point_ops.by_cdp("type", self.page, FRAME, [], {"text": "x"}, lambda: None)
        await self.drawing()
        self.assertEqual("name", self.drawn()[-1]["params"]["objectId"])
        socket.hook = None
        socket.focus_object = "first"  # Tab moves the focus on purpose: show where it went
        socket.hook = lambda message: setattr(socket, "focus_object", "second") \
            if message["method"] == "Input.dispatchKeyEvent" else None
        await point_ops.by_cdp("key", self.page, FRAME, [], {"names": ["tab"]}, lambda: None)
        await self.drawing()
        self.assertEqual("second", self.drawn()[-1]["params"]["objectId"])
        freed = {p["objectId"] for p in self.freed()}
        self.assertEqual({"name", "first", "second"}, freed)

    async def test_a_refused_or_failed_key_operation_draws_nothing_and_releases_the_element(self):
        socket = self.f.socket
        socket.focus_object, socket.focus_state = None, "password"
        with self.assertRaises(CDPError):
            await point_ops.by_cdp("type", self.page, FRAME, [], {"text": "x"}, lambda: None)
        socket.focus_object = "field"
        socket.focus_state = "password"
        socket.states[4]["type"] = "password"
        with self.assertRaises(CDPError):  # a probe that is not an element is a refusal (fail closed)
            socket.focus_object = None
            await point_ops.by_cdp("type", self.page, FRAME, [], {"text": "x"}, lambda: None)
        await self.drawing()
        self.assertEqual([], self.calls("Input."))
        self.assertEqual([], self.drawn())

    def withhold(self, *prefixes):
        """The socket records these commands and never answers them; `answer` does, later."""
        socket = self.f.socket
        send = socket.send
        self.waiting = []

        async def hold_back(raw):
            message = json.loads(raw)
            if message["method"].startswith(prefixes) and message.get("params", {}).get("width") != 16:
                socket.calls.append(message)
                self.waiting.append(message["id"])
                return
            await send(raw)
        socket.send = hold_back

    def answer(self, error=False):
        """Chrome finally replies to the oldest withheld command, or it is lost (a transport failure)."""
        ident = self.waiting.pop(0)
        self.f.socket.queue.put_nowait({"id": ident, **({"error": {"code": -32000, "message": "lost"}}
                                                        if error else {"result": {}})})

    async def spin(self):
        for _ in range(50):
            await asyncio.sleep(0)

    async def test_keys_never_wait_for_the_cue(self):
        socket = self.f.socket
        socket.focus_object = "name"
        self.withhold("Overlay.", "Page.captureScreenshot", "Runtime.releaseObject")
        self.page.cue.click(30, 40)
        await self.spin()
        for op, args in (("type", {"text": "x"}), ("key", {"names": ["a"]})):
            result = await point_ops.by_cdp(op, self.page, FRAME, [], args, lambda: None)
            self.assertTrue(result)  # the input completed with the cue's commands still outstanding
        self.assertTrue(self.calls("Input.insertText") and self.calls("Input.dispatchKeyEvent"))

    async def test_cue_commands_go_out_one_at_a_time_a_hide_never_overtakes_a_paint(self):
        self.withhold("Overlay.highlightRect")
        self.page.cue.click(30, 40)
        await self.spin()
        painted = [m["method"] for m in self.calls("Overlay.")]
        self.assertEqual("Overlay.highlightRect", painted[-1])  # sent, painted, not answered
        self.assertTrue(self.page.cue.dirty)
        self.assertTrue(self.timers.pending)  # the hide is armed at dispatch, not at the answer
        await point_ops.by_cdp("key", self.page, FRAME, [], {"names": ["esc"]}, lambda: None)  # no focus
        await self.spin()
        self.assertEqual(painted, [m["method"] for m in self.calls("Overlay.")])  # nothing overtook it
        self.answer(error=True)  # the answer is lost: still painted as far as anyone knows
        await self.drawing()
        self.assertEqual("Overlay.hideHighlight", self.calls("Overlay.")[-1]["method"])
        self.assertFalse(self.page.cue.dirty)

    async def test_a_failed_hide_is_tried_once_more_then_left_to_the_next_cue(self):
        await self.act("Hyperlink", "invoke")
        self.withhold("Overlay.hideHighlight")
        self.timers.fire(1)  # the hide timer
        await self.spin()
        self.answer(error=True)
        await self.drawing()
        self.assertTrue(self.page.cue.dirty)
        retry = [t for t in self.timers.pending if t.delay == cdp_cue.HIDE_RETRY and not t.cancelled]
        self.assertEqual(1, len(retry))
        self.timers.fire(self.timers.pending.index(retry[0]))
        await self.spin()
        self.answer(error=True)
        await self.drawing()
        self.assertTrue(self.page.cue.dirty)
        self.assertEqual([], [t for t in self.timers.pending if t.delay == cdp_cue.HIDE_RETRY][1:])

    async def test_a_cue_that_expired_before_its_paint_went_out_is_never_painted(self):
        await self.act("Hyperlink", "invoke")  # measures the pixel ratio once
        await self.drawing()
        self.f.socket.calls.clear()
        self.withhold("Overlay.enable")
        self.page.cue.click(30, 40)
        await self.spin()
        self.assertTrue(self.waiting)  # the paint is waiting for the overlay to be enabled
        last = [i for i, t in enumerate(self.timers.pending) if t.delay == cdp_cue.POINTER_SECONDS][-1]
        self.timers.fire(last)
        await self.spin()
        self.answer()  # Chrome finally answers, after the deadline
        await self.drawing()
        self.assertEqual([], self.drawn())
        self.assertFalse(self.page.cue.dirty)

    async def test_a_point_sent_into_a_document_that_navigated_before_the_reply_is_not_drawn(self):
        socket = self.f.socket
        page = self.page

        def hook(message):
            params = message["params"]
            if message["method"] == "Input.dispatchMouseEvent" and params["type"].endswith("Released"):
                page.epoch += 1  # the navigation arrived before the release was answered
        socket.hook = hook
        await point_ops.by_cdp("click", page, FRAME, [(30, 40)], CLICK, lambda: None)
        await self.drawing()
        self.assertEqual([], self.drawn())
        socket.hook = None
        await point_ops.by_cdp("click", page, FRAME, [(30, 40)], CLICK, lambda: None)  # the new document
        await self.drawing()
        self.assertEqual(["Overlay.highlightRect"], [m["method"] for m in self.drawn()])

    async def test_a_point_sent_before_a_fragment_navigation_is_not_drawn_on_the_destination(self):
        socket = self.f.socket
        page = self.page
        await self.act("Hyperlink", "invoke")  # the old cue is up
        await self.drawing()
        socket.calls.clear()

        def hook(message):
            params = message["params"]
            if message["method"] == "Input.dispatchMouseEvent" and params["type"].endswith("Released"):
                socket.event("Page.navigatedWithinDocument", session="a", frameId=page.main_frame,
                             url="https://x.test/#b")  # the in-page link scrolled before the reply
        socket.hook = hook
        await point_ops.by_cdp("click", page, FRAME, [(30, 40)], CLICK, lambda: None)
        await self.drawing()
        self.assertEqual([], self.drawn())  # nothing painted over the destination section
        self.assertFalse(page.cue.dirty)  # and the cue that was up came down

    async def test_a_ring_over_a_page_that_scrolls_within_its_document_is_taken_down(self):
        await self.act("Hyperlink", "invoke")
        epoch = self.page.epoch
        self.f.socket.calls.clear()
        self.f.socket.event("Page.navigatedWithinDocument", session="a", frameId="other", url="https://x.test/#a")
        await checkpoint()
        await self.drawing()
        self.assertEqual([], self.calls("Overlay."))  # a frame that is not the page's
        self.f.socket.event("Page.navigatedWithinDocument", session="a", frameId=self.page.main_frame,
                            url="https://x.test/#b")
        await checkpoint()
        await self.drawing()
        self.assertEqual(["Overlay.hideHighlight"], [m["method"] for m in self.calls("Overlay.")])
        self.assertEqual(epoch, self.page.epoch)  # the document is the same one: actions stay valid

    async def test_cleanup_is_not_refused_because_the_action_began_in_an_older_document(self):
        await self.act("Hyperlink", "invoke")
        self.page.operation_epoch = self.page.epoch  # an action is under way ...
        self.f.socket.event("Page.frameNavigated", session="a", frame={"id": "main", "url": "https://x.test/"})
        await checkpoint()
        await self.drawing()  # ... and its document just went: the hide still goes out
        self.assertEqual("Overlay.hideHighlight", self.calls("Overlay.")[-1]["method"])
        self.assertFalse(self.page.cue.dirty)

    async def test_a_new_cue_that_draws_nothing_still_clears_the_old_one(self):
        await self.act("Hyperlink", "invoke")
        self.assertTrue(self.page.cue.dirty)
        self.f.socket.calls.clear()
        await point_ops.by_cdp("key", self.page, FRAME, [], {"names": ["esc"]}, lambda: None)  # no focus
        await self.drawing()
        self.assertEqual([], self.drawn())
        self.assertEqual("Overlay.hideHighlight", self.calls("Overlay.")[-1]["method"])
        self.assertFalse(self.page.cue.dirty)
        self.f.socket.calls.clear()
        self.page.cue.click(5000, 5000)  # outside the viewport: not drawn, and nothing left to clear
        await self.drawing()
        self.assertEqual([], self.calls("Overlay.highlight"))

    async def test_a_cue_replaced_by_one_that_draws_is_not_hidden_in_between(self):
        await self.act("Hyperlink", "invoke")
        self.f.socket.calls.clear()
        self.page.cue.click(30, 40)
        await self.drawing()
        self.assertEqual(["Overlay.highlightRect"], [m["method"] for m in self.drawn()])
        self.assertEqual([], self.calls("Overlay.hideHighlight"))

    async def test_a_refused_point_operation_is_not_cued(self):
        self.f.socket.focus_state = "password"
        with self.assertRaises(CDPError):
            await point_ops.by_cdp("type", self.page, FRAME, [], {"text": "x"}, lambda: None)
        await self.drawing()
        self.assertEqual([], self.calls("Overlay."))


class ProbeTests(unittest.TestCase):
    def png(self, box=None, page="white", fill=(255, 0, 255)):
        image = Image.new("RGB", (160, 160), page)
        if box:
            ImageDraw.Draw(image).rectangle(box, fill=fill)
        out = io.BytesIO()
        image.save(out, "PNG")
        return io.BytesIO(out.getvalue())

    def measure(self, box, **page):
        return probe_scale(self.png(**page), self.png(box, **page), 16)

    def test_the_scale_is_the_probe_s_left_edge_over_its_overlay_position(self):
        for scale in (1, 1.5, 2.25, 4):
            edge = round(16 * scale)
            with self.subTest(scale=scale):
                box = [edge, edge, 2 * edge - 1, 2 * edge - 1]
                self.assertAlmostEqual(scale, self.measure(box), delta=.1)

    def test_the_page_s_own_colours_never_matter_only_what_the_probe_changed(self):
        for page in ("white", "black", "magenta", (255, 0, 255), "red"):
            with self.subTest(page=page):
                fill = contrast(self.png(page=page))
                color = (fill["r"], fill["g"], fill["b"])
                self.assertAlmostEqual(1, self.measure([16, 16, 31, 31], page=page, fill=color), delta=.1)

    def test_a_probe_the_size_of_the_page_s_colour_or_a_changing_page_is_not_a_measurement(self):
        self.assertIsNone(probe_scale(self.png(), self.png([16, 16, 31, 31], fill="white"), 16))  # no change
        self.assertIsNone(probe_scale(self.png(), self.png([0, 0, 0, 0]), 16))  # one pixel at the corner
        self.assertIsNone(probe_scale(self.png(), self.png([150, 150, 159, 159]), 16))  # off the scale range
        self.assertIsNone(probe_scale(self.png(), self.png([16, 16, 47, 31]), 16))  # twice as wide as tall
        self.assertIsNone(probe_scale(self.png(), self.png([40, 16, 60, 36]), 16))  # edge and width disagree
        small = Image.new("RGB", (9, 9))
        out = io.BytesIO()
        small.save(out, "PNG")
        self.assertIsNone(probe_scale(self.png(), io.BytesIO(out.getvalue()), 16))  # a different clip


if __name__ == "__main__":
    unittest.main()
