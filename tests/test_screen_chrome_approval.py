"""A line is shown while Chrome waits for the person's Allow click, and only while it does."""
import unittest
from unittest.mock import AsyncMock, Mock

from tests.window_grant_fixtures import WindowGrantFixture


def notices(browser):
    return [call.args[0] for call in browser.send_json.call_args_list
            if call.args[0].get("type") == "chrome_approval"]


class ChromeApprovalTests(WindowGrantFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.page, self.elsewhere = (Mock(send_json=AsyncMock()) for _ in range(2))
        self.runtime.sockets = {"alpha": {self.page}, "beta": {self.elsewhere}}
        self.approvals = self.hub.window_grants.approvals
        await self.grant("a", "Shared page", process="chrome.exe")

    async def report(self, *grant_ids):
        await self.approvals.receive(self.device, {"type": "chrome_approval", "grant_ids": list(grant_ids)})

    async def test_the_owning_line_is_shown_the_waiting_window_and_no_other_line(self):
        await self.report("g1")
        shown, = notices(self.page)
        self.assertEqual(("chrome_approval", "alpha"), (shown["type"], shown["conv_id"]))
        self.assertEqual([("g1", "Shared page", "Computer")],
                         [(n["grant_id"], n["title"], n["device_name"]) for n in shown["notices"]])
        self.assertEqual([], notices(self.elsewhere))

    async def test_it_clears_when_approved_or_refused(self):
        await self.report("g1")
        await self.report()  # the helper reports an answered prompt as an empty set
        self.assertEqual([[]], [n["notices"] for n in notices(self.page)][1:])
        self.assertEqual([], self.approvals.current("alpha"))

    async def test_it_clears_when_the_share_ends(self):
        await self.report("g1")
        await self.hub.window_grants.revoke("g1")
        self.assertEqual([], notices(self.page)[-1]["notices"])
        self.assertEqual([], self.approvals.current("alpha"))

    async def test_it_clears_when_the_computer_disconnects(self):
        await self.report("g1")
        self.hub.devices.pop(self.device["id"])
        await self.approvals.sync(self.device["id"])
        self.assertEqual([], notices(self.page)[-1]["notices"])

    async def test_an_unchanged_report_is_not_pushed_again(self):
        await self.report("g1")
        await self.report("g1")
        self.assertEqual(1, len(notices(self.page)))

    async def test_only_chrome_windows_that_exist_are_shown(self):
        await self.report("g1", "unknown")
        self.assertEqual(["g1"], [n["grant_id"] for n in notices(self.page)[-1]["notices"]])
        await self.hub.window_grants.revoke("g1")
        await self.grant("a", "Editor", grant_id="g2")  # a window of another program is never an Allow prompt
        await self.report("g2")
        self.assertEqual([], self.approvals.current("alpha"))

    async def test_a_malformed_report_shows_nothing_and_keeps_the_helper(self):
        await self.approvals.receive(self.device, {"type": "chrome_approval", "grant_ids": "g1"})
        self.assertEqual([], notices(self.page))

    async def test_a_tab_opened_during_the_prompt_is_told_at_once(self):
        await self.report("g1")
        late = Mock(send_json=AsyncMock())
        await self.approvals.send_current(late, "alpha")
        self.assertEqual(["g1"], [n["grant_id"] for n in notices(late)[0]["notices"]])
        quiet = Mock(send_json=AsyncMock())
        await self.approvals.send_current(quiet, "beta")
        quiet.send_json.assert_not_awaited()

    async def test_a_second_computer_keeps_its_prompt_when_the_first_clears(self):
        from types import SimpleNamespace
        code = self.hub.issue_pair_code(self.owner["id"], "alpha")
        other_id, _, _, _ = self.hub.claim_pair_code(code, "Second", "test")
        second = dict(self.device, id=other_id, name="Second", socket=SimpleNamespace(send_json=AsyncMock()))
        self.hub.devices[other_id] = second
        await self.hub.window_grants.from_helper(second, {"type": "list_share_targets", "request_id": "t2"})
        await self.hub.window_grants.from_helper(second, {
            "type": "window_grant", "request_id": "r2", "grant_id": "g2", "line_id": "alpha",
            "targets_request_id": "t2", "title": "Second page", "process": "chrome.exe", "hwnd": 20})
        await self.report("g1")
        await self.approvals.receive(second, {"type": "chrome_approval", "grant_ids": ["g2"]})
        self.assertEqual({"g1", "g2"}, {n["grant_id"] for n in notices(self.page)[-1]["notices"]})
        await self.report()  # the first computer's prompt is answered
        self.assertEqual(["g2"], [n["grant_id"] for n in notices(self.page)[-1]["notices"]])
        await self.approvals.receive(second, {"type": "chrome_approval", "grant_ids": []})
        self.assertEqual([], notices(self.page)[-1]["notices"])
