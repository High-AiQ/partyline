"""Window UIA privacy and traversal tests on a fake tree and clock."""
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from partyline_helper.uia_access import WindowAccess
from partyline_helper.uia_process import KILL_SLACK, read
from partyline_helper.uia_snapshot import BUDGET, snapshot


class Provider:
    def __init__(self, nodes):
        self.nodes = nodes
        self.reads = []

    def root(self):
        return 0

    def runtime_id(self, node):
        return [node]

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

    def state(self, node, props):
        """Pattern state is read for an action target only; fakes put it in properties()."""

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
        self.assertEqual(3, len({e["id"] for e in elements}))
        self.assertTrue(all(len(e["id"]) == 16 for e in elements))
        self.assertEqual([110, 60, 150, 80], elements[1]["bounds"])
        self.assertEqual([20, 10, 100, 30], elements[1]["frame_bounds"])
        self.assertNotIn("value", elements[1])
        self.assertTrue(elements[2]["offscreen"])
        self.assertEqual([0, 1, 3], tree.reads)
        self.assertEqual(160, len(elements[1]["automation_id"]))

    def test_long_names_and_values_reach_the_server_up_to_their_caps(self):
        tree = Provider([{"rect": (0, 0, 10, 10), "name": "N" * 2000, "value": "v" * 2000}])
        element = snapshot(tree, clock=lambda: 0)["elements"][0]
        self.assertEqual((1000, 600), (len(element["name"]), len(element["value"])))
        tree = Provider([{"rect": (0, 0, 10, 10), "name": "T" * 500, "value": "v" * 300}])
        element = snapshot(tree, clock=lambda: 0)["elements"][0]
        self.assertEqual((500, 300), (len(element["name"]), len(element["value"])))

    def test_count_visit_and_time_caps_each_leave_a_cursor_state(self):
        tree = Provider([{"rect": (0, 0, 10, 10), "children": [1]},
                         {"rect": (0, 0, 10, 10), "children": [2]},
                         {"rect": (0, 0, 10, 10)}])
        for cap, reason in ((dict(limit=1), "element limit"), (dict(max_visits=2), "visit limit")):
            with self.subTest(cap=cap):
                result = snapshot(tree, clock=lambda: 0, **cap)
                self.assertTrue(result["truncated"])
                self.assertIn(reason, result["truncation"])
                self.assertTrue(result["state"]["stack"])
        clock = iter([0, 0, BUDGET + 1])
        result = snapshot(tree, clock=lambda: next(clock))
        self.assertIn("time budget", result["truncation"])
        self.assertEqual([[[0], result["elements"][0]["id"]]], result["state"]["stack"])
        self.assertFalse(snapshot(tree, clock=lambda: 0)["truncated"])
        self.assertNotIn("state", snapshot(tree, clock=lambda: 0))

    def test_unavailable_timeout_and_failure(self):
        self.assertIn("elements_unavailable", read(1, platform="linux"))
        def failed(*args, **kwargs):
            raise OSError()
        self.assertIn("elements_unavailable", read(1, popen=failed, platform="win32"))
        def succeeded(args, **kwargs):
            path = json.loads(args[-1])[2]
            Path(path).write_text('{"elements": []}', encoding="utf-8")
            return SimpleNamespace(poll=lambda: 0, returncode=0)
        self.assertEqual({"elements": []}, read(1, popen=succeeded, platform="win32"))

    def test_deadline_starts_after_initialization_and_kills_hung_worker(self):
        now = [0.0]
        killed = []
        def sleep(delay):
            now[0] += delay
        def popen(args, **kwargs):
            ready = json.loads(args[-1])[3]
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
        self.assertGreaterEqual(killed[0], 3 + BUDGET + KILL_SLACK)
        self.assertLess(killed[0], 3.1 + BUDGET + KILL_SLACK)

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
