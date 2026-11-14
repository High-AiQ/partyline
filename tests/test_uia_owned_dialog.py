"""Cross-process owned dialogs remain bounded by image, class and ownership."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image

from partyline_helper.uia_popups import PopupEvents, sender_in_scope
from partyline_helper.uia_action_worker import audit
from partyline_helper.uia_press import target_hwnd
from partyline_helper.uia_snapshot import snapshot
from partyline_helper.window_grab_owned import compose
from tests.test_uia_dropdown import run
from tests.uia_dropdown_fakes import Chrome, Node


class OwnedDialogTests(unittest.TestCase):
    def setUp(self):
        self.app = Chrome()
        self.app.user32.pids[5] = 20
        self.app.user32.owners[5] = 1
        self.app.user32.visible.add(5)
        self.app.scope.image_path = lambda pid: {10: r"C:\Chrome\chrome.exe",
                                                 20: r"c:\chrome\CHROME.EXE"}.get(pid)
        self.dialog = Node(5, 5, 50032, "Open")
        self.field = Node(50, 0, 50004, "File name", ("Value",), value="")
        for node in (self.dialog, self.field):
            node.props["ProcessId"] = 20
        self.dialog.kids = [self.field]
        self.app.handles[5] = self.dialog

    def test_owned_dialog_snapshot_and_action(self):
        self.assertTrue(self.app.scope.accepts(5))
        names = [item["name"] for item in snapshot(self.app, clock=lambda: 0)["elements"]]
        self.assertIn("popup: Open", names)
        self.assertIn("File name", names)
        path = r"\\server\share\picture.png"
        self.assertEqual("completed", run(self.app, self.field, "set_value", value=path)["status"])
        self.assertEqual(path, self.field.state["value"])

    def test_rejects_wrong_image_class_missing_cycle_and_hidden(self):
        scope, user = self.app.scope, self.app.user32
        scope.image_path = lambda pid: str(pid)
        self.assertFalse(scope.accepts(5))
        scope.image_path = lambda pid: "same"
        scope.class_name = lambda hwnd: "Chrome_WidgetWin_1"
        self.assertFalse(scope.accepts(5))
        scope.class_name = lambda hwnd: "#32770"
        user.owners[5] = 0
        self.assertFalse(scope.accepts(5))
        user.owners[5] = 5
        self.assertFalse(scope.accepts(5))
        user.owners[5] = 1
        user.visible.remove(5)
        self.assertFalse(scope.accepts(5))

    def test_event_sender_and_lifecycle(self):
        app = self.app
        app.walker = SimpleNamespace(GetParentElement=lambda node: (
            self.dialog if node is self.field else None))
        self.assertTrue(sender_in_scope(app, self.field))
        calls = []
        events = PopupEvents(app.scope, lambda: calls.append(True))
        app.user32.visible.remove(5)
        events.event(5, 0)
        self.assertEqual([True], calls)

    def test_dialog_key_target_and_audit(self):
        app = self.app
        app.walker = SimpleNamespace(GetParentElement=lambda node: (
            self.dialog if node is self.field else None))
        app.popup_nodes[(5,)] = 5
        app.popup_nodes[(50,)] = 5
        messages = SimpleNamespace(belongs=lambda hwnd, top: hwnd == top == 5)
        self.assertEqual(5, target_hwnd(app, self.field, messages))
        sink = Mock()
        audit(SimpleNamespace(tools=SimpleNamespace(audit=sink)), {}, {"action": "invoke"},
              {"scope_window": "Open"}, {"status": "completed"})
        self.assertIn('"scope_window":"Open"', sink.append.call_args.args[-1])

    def test_composition_includes_dialog_bounds_without_desktop_pixels(self):
        image = compose([((10, 10, 12, 12), Image.new("RGB", (2, 2), "red")),
                         ((13, 9, 15, 11), Image.new("RGB", (2, 2), "blue"))])
        self.assertEqual((5, 3), image.size)
        self.assertEqual((0, 0, 0), image.getpixel((2, 1)))
        self.assertEqual((0, 0, 255), image.getpixel((3, 0)))
