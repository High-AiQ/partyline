"""Drive the extra UIA patterns against the real Win32 controls of tests.windows_uia_window."""
import asyncio
import ctypes
import json
from ctypes import wintypes


def near(actual, expected, slack=3):
    return all(abs(a - b) <= slack for a, b in zip(actual, expected, strict=True))


class Driver:  # pragma: no cover - runs only in the Windows foundations job
    def __init__(self, case, worker, access, window, process, lines):
        self.case, self.worker, self.access = case, worker, access
        self.window, self.process, self.lines = window, process, lines
        self.user32 = ctypes.windll.user32
        self.user32.IsIconic.argtypes = self.user32.IsZoomed.argtypes = [wintypes.HWND]
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.elements = []

    def cursor(self):
        point = wintypes.POINT()
        self.case.assertTrue(self.user32.GetCursorPos(ctypes.byref(point)))
        return point.x, point.y

    def rect(self):
        rect = wintypes.RECT()
        self.case.assertTrue(self.user32.GetWindowRect(self.window["hwnd"], ctypes.byref(rect)))
        return rect.left, rect.top, rect.right, rect.bottom

    def report(self):
        self.process.stdin.write("report\n")
        self.process.stdin.flush()
        return json.loads(self.lines.get(timeout=20))

    async def act(self, item, action, **fields):
        before = self.cursor()
        message = {"element_id": item["id"], "action": action, "share_id": "share", "agent": "test", **fields}
        answer = await self.worker.perform(message)
        self.case.assertEqual(before, self.cursor(), f"{action} moved the cursor")
        if answer.get("status") == "completed" and action != "window_close":
            self.case.assertIsInstance(answer.get("foreground_changed"), bool, (action, answer))
            self.case.assertIsInstance(answer.get("target_came_forward"), bool, (action, answer))
        return answer

    def require(self, item, action):
        """The native control exposes the pattern, so the snapshot must list the action."""
        self.case.assertIn(action, item.get("actions", []), item)

    async def refusal_names_supported_actions(self):
        button = self.find("Button", "Snapshot button")
        answer = await self.act(button, "scroll", direction="down", amount="small")
        self.case.assertEqual("failed", answer["status"], answer)
        self.case.assertIn("it supports: invoke", answer["error"], answer)

    def find(self, control_type, name=None, bounds=None):
        for item in self.elements:
            if item.get("control_type") != control_type or (name and item.get("name") != name):
                continue
            if bounds is None or near(item["bounds"], bounds):
                return item
        self.case.fail(f"no {control_type} {name or ''} in {[e.get('control_type') for e in self.elements]}")

    async def run(self):
        snapshot = await self.access.snapshot()
        self.case.assertIn("elements", snapshot, snapshot)
        self.case.assertFalse(snapshot["truncated"], len(snapshot["elements"]))
        self.elements = snapshot["elements"]
        root = self.elements[0]
        self.case.assertIn("window_close", root["actions"], root)
        await self.refusal_names_supported_actions()
        await self.lists()
        await self.combo_and_trackbar()
        await self.window_actions(root)

    async def lists(self):
        listbox = self.find("List", bounds=self.window["extra"]["listbox"])
        last = self.find("ListItem", "Item 39")
        self.require(self.find("ListItem", "Item 3"), "select")
        answer = await self.act(self.find("ListItem", "Item 3"), "select")
        self.case.assertEqual("completed", answer["status"], answer)
        self.case.assertEqual(3, self.report()["listbox_selected"])
        self.require(last, "scroll_into_view")
        answer = await self.act(last, "scroll_into_view")
        self.case.assertEqual("completed", answer["status"], answer)
        self.case.assertGreater(self.report()["listbox_top"], 0)
        self.require(listbox, "scroll")
        top = self.report()["listbox_top"]
        answer = await self.act(listbox, "scroll", direction="up", amount="large")
        self.case.assertEqual("completed", answer["status"], answer)
        self.case.assertLess(self.report()["listbox_top"], top)
        self.require(listbox, "set_scroll_percent")
        answer = await self.act(listbox, "set_scroll_percent", vertical_percent=100)
        self.case.assertEqual("completed", answer["status"], answer)
        self.case.assertGreater(self.report()["listbox_top"], 0)

    async def combo_and_trackbar(self):
        combo = self.find("ComboBox")
        self.require(combo, "expand")
        answer = await self.act(combo, "expand")
        self.case.assertEqual("completed", answer["status"], answer)
        self.case.assertEqual(1, self.report()["combo_dropped"])
        answer = await self.act(combo, "collapse")
        self.case.assertEqual("completed", answer["status"], answer)
        self.case.assertEqual(0, self.report()["combo_dropped"])
        slider = self.find("Slider")
        self.require(slider, "set_range_value")
        answer = await self.act(slider, "set_range_value", number=101)
        self.case.assertEqual("failed", answer["status"], answer)
        self.case.assertIn("between", answer["error"])
        answer = await self.act(slider, "set_range_value", number=40)
        self.case.assertEqual("completed", answer["status"], answer)
        self.case.assertEqual(40, self.report()["trackbar"])

    async def window_actions(self, root):
        user32, hwnd = self.user32, self.window["hwnd"]
        answer = await self.act(self.find("List"), "window_close")
        self.case.assertEqual("failed", answer["status"], answer)
        self.case.assertIsNone(self.process.poll())
        answer = await self.act(root, "window_move", x=150, y=160)
        self.case.assertEqual("completed", answer["status"], answer)
        self.case.assertTrue(near(self.rect()[:2], (150, 160), 2), self.rect())
        answer = await self.act(root, "window_resize", width=520, height=340)
        self.case.assertEqual("completed", answer["status"], answer)
        left, top, right, bottom = self.rect()
        self.case.assertTrue(near((right - left, bottom - top), (520, 340), 2), self.rect())
        answer = await self.act(root, "window_minimize")
        self.case.assertEqual("completed", answer["status"], answer)
        self.case.assertTrue(user32.IsIconic(hwnd))
        answer = await self.act(root, "window_restore")
        self.case.assertEqual("completed", answer["status"], answer)
        self.case.assertFalse(user32.IsIconic(hwnd))
        answer = await self.act(root, "window_maximize")
        self.case.assertEqual("completed", answer["status"], answer)
        self.case.assertTrue(user32.IsZoomed(hwnd))
        answer = await self.act(root, "window_restore")
        self.case.assertEqual("completed", answer["status"], answer)
        self.case.assertFalse(user32.IsZoomed(hwnd))
        grant = self.access.grant
        answer = await self.act(root, "window_close")
        self.case.assertEqual("completed", answer["status"], answer)
        self.case.assertTrue(answer["close_requested"], answer)
        await asyncio.to_thread(self.process.wait, 20)  # the fixture exits when its window is gone
        reason = await self.access.check(grant)
        self.case.assertEqual("window closed", reason)
        if self.access.grant is grant:  # the 1 s watcher would otherwise end the grant
            self.access.revoke(reason)
        self.case.assertIsNone(self.access.grant)
