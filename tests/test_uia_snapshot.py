"""Window UIA privacy and traversal tests on a fake tree and clock."""
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from partyline_helper.uia_access import WindowAccess
from partyline_helper.uia_process import read
from partyline_helper.uia_snapshot import snapshot


class Provider:
    def __init__(self, nodes):
        self.nodes = nodes
        self.reads = []

    def root(self):
        return 0

    def same_window(self, node):
        return self.nodes[node].get("same", True)

    def password(self, node):
        return self.nodes[node].get("password", False)

    def current(self):
        return True

    def bounds(self, node):
        return self.nodes[node]["rect"]

    def children(self, node):
        return self.nodes[node].get("children", [])

    def properties(self, node):
        self.reads.append(node)
        n = self.nodes[node]
        return {"name": n.get("name", ""), "automation_id": "a" * 200, "value": n.get("value", ""),
                "control_type": "Edit", "enabled": True, "focused": False,
                "offscreen": n.get("hidden", False), "patterns": ["Value"]}


class SnapshotTests(unittest.TestCase):
    def test_filter_redaction_and_frame_coordinates(self):
        tree = Provider([
            {"rect": (0, 0, 200, 200), "children": [1, 2, 3]},
            {"rect": (110, 60, 150, 80), "name": "password", "password": True, "value": "secret"},
            {"rect": (201, 60, 210, 80), "name": "other", "same": False},
            {"rect": (90, 60, 120, 80), "name": "hidden", "hidden": True},
        ])
        frame = (dict(x=100, y=50, width=100, height=100), 200, 100)
        result = snapshot(tree, frame, clock=lambda: 0)
        elements = result["elements"]
        self.assertFalse(result["truncated"])
        self.assertEqual([1, 2, 3], [e["id"] for e in elements])
        self.assertEqual([110, 60, 150, 80], elements[1]["bounds"])
        self.assertEqual([20, 10, 100, 30], elements[1]["frame_bounds"])
        self.assertNotIn("value", elements[1])
        self.assertTrue(elements[2]["offscreen"])
        self.assertEqual([0, 1, 3], tree.reads)
        self.assertEqual(160, len(elements[1]["automation_id"]))

    def test_count_depth_and_time_limits(self):
        tree = Provider([{"rect": (0, 0, 10, 10), "children": [1]},
                         {"rect": (0, 0, 10, 10), "children": [2]},
                         {"rect": (0, 0, 10, 10)}])
        self.assertTrue(snapshot(tree, clock=lambda: 0, limit=1)["truncated"])
        self.assertTrue(snapshot(tree, clock=lambda: 0, depth_limit=1)["truncated"])
        clock = iter([0, 0, 1])
        self.assertTrue(snapshot(tree, clock=lambda: next(clock))["truncated"])

    def test_unavailable_timeout_and_failure(self):
        self.assertIn("elements_unavailable", read(1, platform="linux"))
        def failed(*args, **kwargs):
            raise OSError()
        self.assertIn("elements_unavailable", read(1, popen=failed, platform="win32"))
        def succeeded(args, **kwargs):
            _, _, path, _ = json.loads(args[-1])
            Path(path).write_text('{"elements": []}', encoding="utf-8")
            return SimpleNamespace(poll=lambda: 0, returncode=0)
        self.assertEqual({"elements": []}, read(1, popen=succeeded, platform="win32"))

    def test_deadline_starts_after_initialization_and_kills_hung_worker(self):
        now = [0.0]
        killed = []
        def sleep(delay):
            now[0] += delay
        def popen(args, **kwargs):
            _, _, _, ready = json.loads(args[-1])
            def poll():
                if killed:
                    return -1
                if now[0] >= 3:
                    Path(ready).touch()
                return None
            return SimpleNamespace(poll=poll, kill=lambda: killed.append(now[0]), wait=lambda: None)
        answer = read(1, popen=popen, platform="win32", clock=lambda: now[0], sleep=sleep)
        self.assertEqual("timeout", answer["elements_unavailable"])
        self.assertTrue(answer["truncated"])
        self.assertEqual(1, len(killed))
        self.assertGreaterEqual(killed[0], 5)
        self.assertLess(killed[0], 5.1)

    def test_initialization_timeout_kills_worker(self):
        ticks = iter([0, 31])
        process = Mock()
        process.poll.side_effect = [None, -1]
        result = read(1, popen=lambda *a, **k: process, platform="win32", clock=lambda: next(ticks),
                      sleep=lambda _: None)
        self.assertEqual("timeout", result["elements_unavailable"])
        process.kill.assert_called_once()


class WindowConsentTests(unittest.IsolatedAsyncioTestCase):
    async def test_consent_revoke_and_closed(self):
        grant = {"hwnd": 10, "pid": 42, "title": "Editor", "process": "app.exe"}
        items = [grant]
        status = SimpleNamespace(window_title=None, changed=Mock())
        session = SimpleNamespace(status=status, tools=SimpleNamespace(audit=SimpleNamespace(append=Mock())),
                                  share=None, accepted=False, last_uia_frame=None)
        reader = Mock(return_value={"elements": [{"id": 1}], "snapshot_id": "snap", "truncated": False})
        access = WindowAccess(session, picker=lambda: grant, list_windows=lambda: items, reader=reader,
                              platform="win32")
        self.assertEqual("not consented", (await access.snapshot())["elements_unavailable"])
        await access.choose()
        self.assertEqual("Editor", status.window_title)
        self.assertEqual("snap", (await access.snapshot())["snapshot_id"])
        access.revoke()
        self.assertEqual("not consented", (await access.snapshot())["elements_unavailable"])
        await access.choose()
        items.clear()
        self.assertEqual("window closed", (await access.snapshot())["elements_unavailable"])
        self.assertIsNone(status.window_title)

    async def test_secure_desktop_pauses_and_revoke_clears_before_audit(self):
        grant = {"hwnd": 10, "pid": 42, "title": "Editor", "process": "app.exe"}
        windows = [[grant]]
        audit = Mock()
        session = SimpleNamespace(status=SimpleNamespace(window_title=None, changed=Mock()),
                                  tools=SimpleNamespace(audit=audit), share=None, accepted=False,
                                  last_uia_frame=None)
        access = WindowAccess(session, picker=lambda: grant, list_windows=lambda: windows[0],
                              reader=lambda *args: {"elements": [], "snapshot_id": "1"}, platform="win32")
        await access.choose()
        windows[0] = None
        self.assertEqual("secure desktop active", (await access.snapshot())["elements_unavailable"])
        self.assertIs(access.grant, grant)
        windows[0] = [grant]
        self.assertEqual("1", (await access.snapshot())["snapshot_id"])
        def audit_revocation(*args):
            self.assertIsNone(access.grant)
            self.assertIn("Editor (app.exe)", args[-1])
            self.assertIn("not consented", args[-1])
        audit.append.side_effect = audit_revocation
        access.revoke()

    async def test_replacing_a_grant_audits_both_windows(self):
        first = {"hwnd": 10, "pid": 42, "title": "First", "process": "one.exe"}
        second = {"hwnd": 11, "pid": 43, "title": "Second", "process": "two.exe"}
        chosen = iter([first, second])
        audit = Mock()
        session = SimpleNamespace(status=SimpleNamespace(window_title=None, changed=Mock()),
                                  tools=SimpleNamespace(audit=audit))
        access = WindowAccess(session, picker=lambda: next(chosen), list_windows=lambda: [first, second],
                              platform="win32")
        await access.choose()
        await access.choose()
        entries = [call.args[-1] for call in audit.append.call_args_list]
        self.assertEqual(entries, ["granted: First (one.exe)", "revoked (replaced): First (one.exe)",
                                   "granted: Second (two.exe)"])
