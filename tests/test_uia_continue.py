"""Helper-side cursor handling: parts of one walk share IDs, a new snapshot ends them."""
import io
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from partyline_helper.uia_access import MAX_WALKS, WindowAccess
from partyline_helper.uia_process import KILL_SLACK, START_LIMIT, read
from partyline_helper.uia_snapshot import BUDGET
from partyline_helper.uia_task import READ_TIMEOUT, read_options

GRANT = {"hwnd": 10, "pid": 42, "title": "Browser", "process": "chrome.exe"}


def access_with(reader):
    session = SimpleNamespace(status=SimpleNamespace(window_title=None, changed=Mock()),
                              tools=SimpleNamespace(audit=SimpleNamespace(append=Mock())),
                              share=None, accepted=False, last_uia_frame=None)
    return WindowAccess(session, picker=lambda: GRANT, list_windows=lambda: [GRANT], reader=reader,
                        platform="win32")


class CursorTests(unittest.IsolatedAsyncioTestCase):
    async def test_parts_keep_every_id_and_a_new_snapshot_drops_them(self):
        calls = []
        parts = iter([{"elements": [{"id": "a", "control_type": "Window", "name": "W"}], "paths": {"a": []},
                       "snapshot_id": "one", "state": {"stack": [[[0], "a"]]}, "truncated": True},
                      {"elements": [{"id": "b", "control_type": "Button", "name": "B"}], "paths": {"b": [0]},
                       "snapshot_id": "ignored", "truncated": False},
                      {"elements": [{"id": "c"}], "paths": {"c": [1]}, "snapshot_id": "two"}])

        def reader(hwnd, frame, state, deep):
            calls.append((state, deep))
            return next(parts)

        access = access_with(reader)
        await access.choose()
        first = await access.snapshot()
        self.assertEqual("one", first["snapshot_id"])
        self.assertNotIn("state", first)
        second = await access.snapshot({"cursor": first["next_cursor"]})
        self.assertEqual("one", second["snapshot_id"])  # one snapshot, however many parts
        self.assertEqual({"a": [], "b": [0]}, access.paths)
        self.assertEqual({"stack": [[[0], "a"]]}, calls[1][0])
        self.assertEqual([True, True], [deep for _, deep in calls])
        self.assertNotIn("next_cursor", second)
        again = await access.snapshot()
        self.assertEqual("two", again["snapshot_id"])
        self.assertEqual({"c": [1]}, access.paths)
        self.assertEqual({}, access.walks)
        expired = await access.snapshot({"cursor": first["next_cursor"]})
        self.assertEqual("cursor expired; start a new snapshot", expired["elements_unavailable"])

    async def test_cursors_are_bounded_and_revocation_clears_them(self):
        state = {"stack": [[[0], None]]}
        access = access_with(lambda *a: {"elements": [], "state": state, "snapshot_id": "s"})
        await access.choose()
        cursors = [(await access.snapshot())["next_cursor"]]
        for _ in range(MAX_WALKS + 1):
            cursors.append((await access.snapshot({"cursor": cursors[-1]}))["next_cursor"])
        self.assertEqual(MAX_WALKS, len(access.walks))
        self.assertNotIn(cursors[0], access.walks)
        generation = access.generation
        access.abandon_read()  # a late result is dropped, but earlier parts' ids stay actionable
        self.assertEqual(generation + 1, access.generation)
        self.assertEqual(MAX_WALKS, len(access.walks))
        self.assertEqual("s", access.epoch)
        access.walks["x"] = state
        access.revoke()
        self.assertEqual({}, access.walks)

    async def test_a_timed_out_first_part_switches_to_per_parent_reads(self):
        deep = []
        access = access_with(lambda hwnd, frame, state, flag: deep.append(flag) or {
            "elements_unavailable": "timeout"})
        await access.choose()
        await access.snapshot()
        await access.snapshot()
        self.assertEqual([True, False], deep)


class RequestTests(unittest.TestCase):
    def test_a_slow_part_is_killed_before_the_helper_gives_up_on_the_read(self):
        self.assertLess(START_LIMIT + BUDGET + KILL_SLACK, READ_TIMEOUT)

    def test_only_a_text_cursor_is_forwarded(self):
        self.assertEqual({"cursor": "abc"}, read_options({"cursor": "abc", "root": "x", "query": "y"}))
        self.assertEqual({}, read_options({"cursor": 5}))
        self.assertEqual({}, read_options({}))
        self.assertEqual(64, len(read_options({"cursor": "x" * 500})["cursor"]))

    def test_the_frontier_travels_in_a_file_not_the_command_line(self):
        seen = {}

        def popen(args, **kwargs):
            payload = json.loads(args[-1])
            seen["payload"] = payload
            seen["state"] = json.loads(Path(payload[4]).read_text(encoding="utf-8"))
            Path(payload[2]).write_text('{"elements": []}', encoding="utf-8")
            return SimpleNamespace(stdout=io.BytesIO(b"READY\n"), wait=lambda **kw: 0,
                                   poll=lambda: 0, returncode=0)

        state = {"stack": [[[n], None] for n in range(20_000)]}
        self.assertEqual({"elements": []}, read(1, None, state, False, popen=popen, platform="win32"))
        self.assertEqual(state, seen["state"])
        self.assertLess(len(json.dumps(seen["payload"])), 400)
        self.assertEqual(False, seen["payload"][5])
