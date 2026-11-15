"""Finding the page area of a Chrome window: renderer choice, fallbacks, errors and snapshot agreement."""
import unittest
from types import SimpleNamespace

from partyline_helper.cdp_transport import CDPError
from partyline_helper.page_area import CHROME, read_metrics, window_area
from partyline_helper.page_windows import PageSources
from partyline_helper.point_cdp import page_frame
from partyline_helper.window_snapshot import WindowSnapshots

PAGE = (100, 200, 1300, 1000)  # 1200 x 800 screen pixels: a 600 x 400 viewport at two pixels per CSS pixel
PANEL = (1300, 200, 1700, 1000)
SPLIT = (700, 200, 1300, 1000)  # a second pane of 600 x 800
BOUNDS = {"left": 50, "top": 60, "width": 700, "height": 520, "windowState": "normal"}
THIN = {"left": 50, "top": 60, "width": 604, "height": 440, "windowState": "normal"}  # 4-pixel frame at 2x


class FakePage:
    def __init__(self, viewport=(600, 400, 1, 2), bounds=BOUNDS):
        self.viewport, self.bounds, self.calls, self.fail = list(viewport), bounds, [], False

    async def call(self, method, params=None):
        self.calls.append(method)
        if self.fail:
            raise CDPError("target closed")
        if method == "Browser.getWindowForTarget":
            return {"windowId": 1, "bounds": self.bounds}
        return {"result": {"value": self.viewport}}


def sources(renderers=(), documents=(), scale=2.0):
    return PageSources(renderers=lambda hwnd: list(renderers), documents=lambda hwnd: list(documents),
                       scale=lambda hwnd: scale)


class RendererChoiceTests(unittest.IsolatedAsyncioTestCase):
    async def frame(self, found, point=None, **page):
        return await page_frame(FakePage(**page), 7, point, sources(found))

    async def test_an_empty_renderer_is_not_a_page(self):
        with self.assertRaises(CDPError) as error:
            await self.frame([(5, 5, 5, 5)])
        self.assertIn("could not be read", str(error.exception))

    async def test_one_renderer_is_the_page_and_the_zoom_check_still_applies(self):
        self.assertEqual((100, 200, 2.0, PAGE), await self.frame([PAGE]))
        with self.assertRaises(CDPError) as error:
            await self.frame([PAGE], viewport=(600, 300, 1, 2))
        self.assertIn("pinch-zoomed or resized", str(error.exception))
        with self.assertRaises(CDPError) as error:
            await self.frame([PAGE], viewport=(600, 400, 1.5, 2))
        self.assertIn("pinch-zoomed", str(error.exception))

    async def test_of_several_the_one_of_the_viewports_size_that_holds_the_point_is_the_page(self):
        self.assertEqual(PAGE, (await self.frame([PANEL, PAGE], (500, 500)))[3])
        self.assertEqual(PAGE, (await self.frame([PAGE, PANEL], (500, 500)))[3])

    async def test_several_of_the_same_size_are_told_apart_by_the_point(self):
        found = [PAGE, (100, 1100, 1300, 1900)]
        self.assertEqual(PAGE, (await self.frame(found, (500, 500)))[3])
        self.assertEqual((100, 1100, 1300, 1900), (await self.frame(found, (500, 1500)))[3])

    async def test_the_size_may_differ_within_the_tolerance_only(self):
        near = (100, 200, 1310, 1000)  # 0.8% wider
        self.assertEqual(near, (await self.frame([PANEL, near], (500, 500)))[3])
        with self.assertRaises(CDPError) as error:
            await self.frame([PANEL, (100, 200, 1400, 1000)], (500, 500))  # 8% wider
        self.assertEqual("found 2 renderer windows, none matching the viewport", str(error.exception))

    async def test_a_point_on_no_renderer_of_the_size_is_a_point_on_the_browsers_controls(self):
        with self.assertRaises(CDPError) as error:
            await self.frame([PAGE, PANEL], (50, 50))
        self.assertEqual(CHROME, str(error.exception))

    async def test_when_the_point_does_not_choose_between_equals_it_is_ambiguous(self):
        twin = (100, 200, 1300, 1000)
        with self.assertRaises(CDPError) as error:
            await self.frame([PAGE, twin, PANEL], (500, 500))
        self.assertEqual("found 3 renderer windows, several matching the viewport", str(error.exception))
        with self.assertRaises(CDPError) as error:  # a snapshot has no point to tell two equals apart
            await self.frame([PAGE, (100, 1100, 1300, 1900)])
        self.assertIn("several matching", str(error.exception))
        self.assertEqual(PAGE, (await self.frame([PAGE, PANEL]))[3])  # one of the size needs no point

    async def test_none_of_the_size_names_the_count(self):
        with self.assertRaises(CDPError) as error:
            await self.frame([PANEL, SPLIT, (0, 0, 50, 50)], (500, 500))
        self.assertEqual("found 3 renderer windows, none matching the viewport", str(error.exception))

    async def test_the_scale_comes_from_the_device_pixel_ratio(self):
        self.assertEqual(PAGE, (await self.frame([PANEL, PAGE], (500, 500)))[3])
        with self.assertRaises(CDPError):
            await self.frame([PANEL, PAGE], (500, 500), viewport=(600, 400, 1, 1))


class FallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_without_renderers_the_ui_automation_document_is_the_page(self):
        page = FakePage()
        frame = await page_frame(page, 7, (500, 500), sources([], [(0, 0, 90, 90), PAGE]))
        self.assertEqual((100, 200, 2.0, PAGE), frame)
        self.assertNotIn("Browser.getWindowForTarget", page.calls)

    async def test_one_document_is_the_page_and_the_zoom_check_applies_to_it(self):
        self.assertEqual(PAGE, (await page_frame(FakePage(), 7, None, sources([], [PAGE])))[3])
        with self.assertRaises(CDPError) as error:
            await page_frame(FakePage(viewport=(600, 400, 2, 2)), 7, None, sources([], [PAGE]))
        self.assertIn("pinch-zoomed", str(error.exception))

    async def test_documents_that_are_empty_or_the_wrong_size_fall_through_to_the_cdp_bounds(self):
        page = FakePage(bounds=THIN)
        self.assertEqual((104, 196, 2.0, (104, 196, 1304, 996)),
                         await page_frame(page, 7, None, sources([], [(5, 5, 5, 5)])))
        self.assertIn("Browser.getWindowForTarget", page.calls)
        # one document, but not the page's size
        page = FakePage(bounds=THIN)
        self.assertEqual((104, 196, 2.0, (104, 196, 1304, 996)),
                         await page_frame(page, 7, None, sources([], [PANEL])))
        for broken in ((5, 5), None, "x"):
            frame = await page_frame(FakePage(), 7, None, sources([], [broken, PAGE]))
            self.assertEqual(PAGE, frame[3])

    async def test_documents_that_fit_nothing_and_no_bounds_name_the_count(self):
        with self.assertRaises(CDPError) as error:
            await page_frame(FakePage(), 7, None, sources([], [(5, 5, 5, 5)]))
        self.assertEqual("found 0 renderer windows and no page document", str(error.exception))
        with self.assertRaises(CDPError) as error:
            await page_frame(FakePage(), 7, None, sources([], [PANEL]))
        self.assertEqual("found 0 renderer windows and 1 page document, none matching the viewport",
                         str(error.exception))

    async def test_several_documents_none_matching_name_both_counts(self):
        with self.assertRaises(CDPError) as error:
            await page_frame(FakePage(), 7, (500, 500), sources([], [PANEL, SPLIT]))
        self.assertEqual("found 0 renderer windows and 2 page documents, none matching the viewport",
                         str(error.exception))

    async def test_without_renderers_or_documents_the_cdp_window_bounds_give_the_page(self):
        # 700 x 520 DIPs at two pixels per DIP is 1400 x 1040: a 100-pixel side is more than a frame
        with self.assertRaises(CDPError) as error:
            await page_frame(FakePage(), 7, None, sources())
        self.assertEqual("found 0 renderer windows and no page document", str(error.exception))
        page = FakePage(bounds=THIN)
        frame = await page_frame(page, 7, (500, 500), sources())
        # the window is 1208 x 880 screen pixels at (100, 120): a 4-pixel frame at each side and below
        self.assertEqual((104, 196, 2.0, (104, 196, 1304, 996)), frame)

    async def test_the_cdp_fallback_refuses_what_it_cannot_trust(self):
        metrics = read_metrics({"result": {"value": [600, 400, 1, 2]}})
        thin = {"left": 50, "top": 60, "width": 604, "height": 440}
        self.assertIsNotNone(window_area(thin, 2.0, metrics))
        self.assertIsNone(window_area({**thin, "windowState": "minimized"}, 2.0, metrics))
        self.assertIsNone(window_area({**thin, "width": 700}, 2.0, metrics))  # a frame that is not thin
        self.assertIsNone(window_area({**thin, "width": 590}, 2.0, metrics))  # narrower than the viewport
        self.assertIsNone(window_area({**thin, "height": 300}, 2.0, metrics))  # shorter than the viewport
        # a panel docked at the bottom would put the page's origin inside the browser's controls
        docked = read_metrics({"result": {"value": [1200, 400, 1, 1]}})
        self.assertIsNone(window_area({"left": 0, "top": 0, "width": 1216, "height": 900}, 1.0, docked))
        plain = {"left": 0, "top": 0, "width": 1216, "height": 500}  # 92 DIPs of controls above the page
        self.assertEqual((8, 92, 1208, 492), window_area(plain, 1.0, docked))
        self.assertIsNone(window_area({"left": 1}, 2.0, metrics))
        self.assertIsNone(window_area({**thin, "left": "x"}, 2.0, metrics))
        for broken in (None, {"bounds": None}):
            page = FakePage()
            page.bounds = broken
            with self.assertRaises(CDPError):
                await page_frame(page, 7, None, sources())

    async def test_a_failing_page_or_scale_is_an_error_not_a_guess(self):
        page = FakePage(bounds={"left": 50, "top": 60, "width": 604, "height": 440})
        with self.assertRaises(CDPError):
            await page_frame(page, 7, None, sources(scale=None))
        with self.assertRaises(CDPError):
            await page_frame(page, 7, None, PageSources(renderers=lambda h: [], documents=lambda h: [],
                                                        scale=lambda h: (_ for _ in ()).throw(OSError())))
        page.fail = True
        with self.assertRaises(CDPError) as error:
            await page_frame(page, 7, None, sources())
        self.assertEqual("target closed", str(error.exception))

    async def test_an_unreadable_viewport_is_refused_first(self):
        for value in ("bad", [0, 400, 1, 2], [600, 400, 1, 0], [600, 400, 0, 2], None):
            page = FakePage()
            page.viewport = value
            with self.assertRaises(CDPError) as error:
                await page_frame(page, 7, None, sources([PAGE]))
            self.assertIn("could not be read", str(error.exception))
        self.assertEqual(PAGE, (await page_frame(FakePage(viewport=(1200, 800, 1)), 7, None,
                                                 sources([PAGE])))[3])  # no ratio: one pixel per CSS pixel


class SnapshotAgreementTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_snapshot_maps_the_page_with_the_same_sources_as_the_click(self):
        page = SimpleNamespace(live=True, page_state="alive", call=FakePage().call)
        chrome = SimpleNamespace(pages={"access": {"t": page}}, selected={"access": "t"})
        clicks = SimpleNamespace(sources=sources([PANEL, PAGE]))
        snapshots = WindowSnapshots(SimpleNamespace(chrome=chrome, clicks=clicks), backend=object())
        grant = {"hwnd": 7, "process": "chrome.exe"}
        self.assertEqual((100, 200, 2.0), await snapshots.page("access", grant))
        clicks.sources = sources([PANEL, SPLIT])  # nothing the size of the page: no marks on the page
        self.assertIsNone(await snapshots.page("access", grant))


if __name__ == "__main__":
    unittest.main()
