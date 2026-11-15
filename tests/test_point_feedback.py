"""Point feedback uses event barriers, actionable tree IDs, bounded reads, and one diagnostic crop."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from partyline.screen_point_changes import apply, delta
from partyline.screen_tree import Snapshot
from partyline_helper.point_feedback import Feedback
from partyline_helper.point_landing import describe_hit
from tests.test_helper_window_click import ClickFixture
from tests.test_point_landing import ServerLandingTests as LandingFixture


def rows(expanded=False):
    items = [{"id": "root", "control_type": "Window", "name": "Fixture"},
             {"id": "trigger", "parent": "root", "control_type": "ComboBox", "name": "Choices",
              "expand_state": "expanded" if expanded else "collapsed"}]
    if expanded:
        items += [{"id": "list", "parent": "root", "control_type": "List", "name": "Options"},
                  {"id": "option", "parent": "list", "control_type": "ListItem", "name": "A",
                   "actions": ["select"]}]
    return {"elements": items, "snapshot_id": "tree", "event_counter": 5, "captured_event_counter": 5}


class RouteTests(ClickFixture):
    async def test_both_routes_return_the_settled_tree_after_popup_opened(self):
        for cdp in (False, True):
            self.access.grant["process"] = "chrome.exe" if cdp else "editor.exe"
            self.snapshot = self.take()
            self.shares.chrome.page.return_value = self.page if cdp else None
            reader = AsyncMock(side_effect=[rows(), rows(True), rows(True)])
            if cdp:
                self.page.snapshot = reader
            else:
                self.access.snapshot = reader
            result = await self.click()
            self.assertEqual("completed", result["status"])
            self.assertEqual("quiet", result["settle"])
            self.assertEqual(rows(True), result["point_observation"]["after"])

    async def test_observation_failure_never_changes_delivered_input_outcome(self):
        self.access.snapshot.side_effect = RuntimeError("provider failed")
        result = await self.click()
        self.assertEqual("completed", result["status"])
        self.assertIn("elements_unavailable", result["point_observation"]["after"])


class BarrierTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, cdp=True):
        self.now, self.count = 0, 1
        gate = SimpleNamespace(generation=1, revoked=SimpleNamespace(is_set=lambda: False))
        events = SimpleNamespace(status=lambda: {"event_counter": self.count},
                                 settle=Mock(return_value="quiet"))
        self.access = SimpleNamespace(grant={}, gate=gate, snapshot=AsyncMock(return_value=rows()),
                                      event_state=events)
        self.page = SimpleNamespace(snapshot=AsyncMock(return_value=rows()),
                                    access=SimpleNamespace(event_status=events.status),
                                    quiet=SimpleNamespace(wait=AsyncMock(return_value="quiet")))
        return Feedback(self.access, self.page if cdp else None, 10, lambda: self.now)

    async def test_real_events_during_wait_then_quiet_are_reported_as_quiet(self):
        feedback = self.fixture()
        await feedback.start()
        async def settle(**kwargs):
            self.count += 1
            return "quiet"
        self.page.quiet.wait.side_effect = settle
        result = await feedback.finish({"status": "completed"})
        self.assertEqual("quiet", result["settle"])
        self.assertEqual(2, result["settled_event_counter"])

    async def test_event_during_final_capture_restarts_quiet_wait_without_polling(self):
        feedback = self.fixture()
        await feedback.start()
        calls = []
        async def snapshot():
            calls.append(1)
            if len(calls) == 2:
                self.count += 1
            return rows(True)
        self.page.snapshot.side_effect = snapshot
        result = await feedback.finish({"status": "completed"})
        self.assertEqual("quiet", result["settle"])
        self.assertEqual(2, self.page.quiet.wait.await_count)
        self.assertEqual(3, len(calls))

    async def test_deadline_returns_last_observation_and_explicit_churn_on_both_routes(self):
        for cdp in (True, False):
            feedback = self.fixture(cdp)
            await feedback.start()
            def deadline(*args, cdp=cdp, **kwargs):
                self.assertEqual(10, kwargs["deadline" if cdp else "budget"])
                self.now = 10
                return "deadline"
            self.page.quiet.wait.side_effect = deadline
            self.access.event_state.settle.side_effect = deadline
            result = await feedback.finish({"status": "completed"})
            self.assertEqual("changing", result["settle"])
            self.assertEqual("still changing after 10000 ms", result["settle_note"])
            self.assertEqual(rows(), result["point_observation"]["after"])

    async def test_revocation_during_capture_returns_no_content(self):
        feedback = self.fixture()
        await feedback.start()
        async def revoke():
            self.access.grant = None
            return rows(True)
        self.page.snapshot.side_effect = revoke
        result = await feedback.finish({"status": "completed"})
        self.assertNotIn("point_observation", result)

    async def test_timeout_before_input_is_read_only_and_bounded(self):
        feedback = self.fixture()
        self.page.snapshot.side_effect = TimeoutError
        await feedback.start()
        self.assertIn("elements_unavailable", feedback.before)
        self.now = 10
        result = await feedback.finish({"status": "unconfirmed"})
        self.assertEqual("changing", result["settle"])

    async def test_continuations_include_popup_after_the_first_tree_part(self):
        feedback = self.fixture()
        first, second = rows(), rows(True)
        first.update(next_cursor="next", truncated=True)
        second["elements"] = second["elements"][2:]
        self.page.snapshot.side_effect = [first, second]
        result = await feedback.snapshot()
        self.assertEqual(4, len(result["elements"]))
        self.assertFalse(result["truncated"])
        self.page.snapshot.assert_awaited_with({"cursor": "next", "tolerate_events": True})

    async def test_changed_continuation_retains_only_the_known_partial_tree(self):
        feedback = self.fixture()
        first = rows()
        first["next_cursor"] = "next"
        self.page.snapshot.side_effect = [first, {"elements_unavailable": "inconsistent"}]
        result = await feedback.snapshot()
        self.assertTrue(result["truncated"])
        self.assertEqual(first["elements"], result["elements"])

    async def test_failure_and_broken_barrier_do_not_replace_input_status(self):
        feedback = self.fixture()
        await feedback.start()
        failed = {"status": "failed"}
        self.assertEqual(failed, await feedback.finish(failed))
        self.page.quiet.wait.side_effect = OSError
        result = await feedback.finish({"status": "completed"})
        self.assertEqual("completed", result["status"])
        self.assertIn("unavailable", result["changes"])


class DeltaTests(unittest.TestCase):
    def tree(self, raw):
        tree = Snapshot("s", 0)
        tree.add(raw["elements"])
        return tree

    def test_options_and_state_use_actionable_ids_and_keep_the_after_tree(self):
        hub = SimpleNamespace(spaces={}, clock=lambda: 0, change_versions={}, remember=Mock())
        result = {"point_observation": {"before": rows(), "after": rows(True)}}
        self.assertTrue(apply(hub, "g", result))
        tree = hub.remember.call_args.args[1]
        option = tree.nodes[tree.by_helper["option"]]
        self.assertIn(f'[{option.id}] ListItem "A"', result["changes"])
        self.assertEqual("option", option.helper)
        self.assertIn("collapsed→expanded", result["changes"])
        self.assertNotIn("point_observation", result)
        self.assertTrue(result["changes_observed"])

    def test_disappearance_partial_and_limit_are_explicit(self):
        before, after = self.tree(rows(True)), self.tree(rows())
        self.assertIn("disappeared:", delta(before, after))
        after.note = "partial"
        self.assertNotIn("disappeared:", delta(before, after))
        self.assertIn("partial observation", delta(before, after))
        full = rows()
        full["elements"] += [{"id": f"n{i}", "control_type": "Button", "name": str(i)} for i in range(25)]
        text = delta(self.tree(rows()), self.tree(full))
        self.assertEqual(21, len(text.splitlines()))
        self.assertIn("more: 5", text)

    def test_absent_or_unavailable_observations_never_claim_unchanged(self):
        hub = SimpleNamespace(spaces={})
        self.assertFalse(apply(hub, "g", {}))
        hub.clock = lambda: 0
        result = {"point_observation": {"before": {"elements_unavailable": "timeout"}, "after": rows()}}
        self.assertFalse(apply(hub, "g", result))
        self.assertEqual("unavailable: timeout", result["changes"])

    def test_root_ownership_handles_non_browser_children_frames_and_covering_windows(self):
        api = SimpleNamespace(root=lambda h: {10: 10, 11: 10, 99: 99}.get(h, 0),
                              describe=lambda h, g: {"hwnd": h, "class": "NativeContent"})
        for hit, expected in ((10, "granted_window"), (11, "granted_page"), (99, "other_window")):
            result = describe_hit(api, hit, 10)
            self.assertEqual(expected, result["landed_in"])
            self.assertEqual(hit == 99, "warning" in result)


class CropTests(LandingFixture):
    async def test_text_delta_requires_read_permission_without_blocking_authorized_input(self):
        from fastapi import HTTPException
        await self.ready()
        self.click_answer = {"status": "completed", "settle": "quiet",
                             "point_observation": {"before": rows(), "after": rows(True)}}

        def permission(db, principal, conv_id, scope):
            if scope == "read":
                raise HTTPException(403, "read")
        with patch("partyline.screen_window_click.deny_unless", permission):
            response = (await self.click()).json()
        self.assertEqual("completed", response["status"])
        self.assertEqual("unavailable: read permission required", response["changes"])
        self.assertNotIn("point_observation", response)
        self.assertNotIn("Options", str(response))

    async def test_changing_reply_has_one_crop_and_clear_delta_needs_none(self):
        await self.ready()
        self.click_answer = {"status": "completed", "settle": "changing",
                             "point_observation": {"before": rows(), "after": rows(True)}}
        response = (await self.click()).json()
        self.assertIn("landing_thumb", response)
        self.assertNotIn("screenshot", response)
        self.assertIn("appeared:", response["changes"])
        self.click_answer["settle"] = "unchanged"
        response = (await self.click()).json()
        self.assertNotIn("landing_thumb", response)

    async def test_ended_grant_never_publishes_an_observation(self):
        # Exchange strips results on ended grants before the observation is processed.
        await self.ready()
        with patch.object(self.hub.elements, "exchange", AsyncMock(return_value={
                "status": "completed", "grant_ended": True})):
            response = (await self.click()).json()
        self.assertNotIn("changes", response)
