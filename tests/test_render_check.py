"""Render checks: the Decisions client (thresholds, abstain, errors, budget) and the consent behind it."""

import asyncio
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from partyline import local_tools_audit, local_tools_media, render_check
from partyline.mcp import tools_check
from partyline.mcp.client import ApiError
from partyline.render_check import Decisions, Unavailable
from tests import test_local_tools_media as media_tests
from tests.test_local_tools_media import png
from tests.test_local_tools_server import REQUEST, FlowCase, until

CHECK = "/api/conversations/line/local-tools/render-check"


def yes(p, name="q1"):
    return {"type": "predicate", "name": name, "probability": p}


def pick(value, confidence, name="variant"):
    return {"type": "choice", "name": name, "choice": value, "confidence": confidence}


def reply(*answers, tokens=1500):
    return {"model": "gpt-6-luna", "answers": list(answers), "usage": {"input_tokens": tokens}}


class Scripted:
    """A transport that answers from a list (an exception in it is raised) and remembers every request."""

    def __init__(self, *replies, repeat=None):
        self.replies, self.repeat, self.requests = list(replies), repeat, []

    def __call__(self, body):
        self.requests.append(body)
        item = self.replies.pop(0) if self.replies else self.repeat
        if isinstance(item, BaseException):
            raise item
        return item


def run(coroutine):
    return asyncio.run(coroutine)


def verdicts(result):
    return [(f["media"], f["verdict"]) for f in result["frames"]]


class Thresholds(unittest.TestCase):
    def check(self, probability, key="k"):
        post = Scripted(reply(yes(probability)))
        result = run(
            render_check.check(
                [("a", png())], ["The lamp intersects the table."], decisions=Decisions(key, post=post)
            )
        )
        return result["frames"][0]

    def test_flag_at_a_fifth_pass_at_a_twentieth_and_uncertain_between(self):
        self.assertEqual(self.check(0.2)["verdict"], "flag")  # the boundary flags
        self.assertEqual(self.check(0.19)["verdict"], "uncertain")
        self.assertEqual(self.check(0.051)["verdict"], "uncertain")
        self.assertEqual(self.check(0.05)["verdict"], "pass")  # and so does this one
        self.assertEqual(self.check(0.0)["verdict"], "pass")
        self.assertEqual(self.check(1.0)["verdict"], "flag")
        self.assertEqual(self.check(0.7)["answers"][0]["probability"], 0.7)

    def test_only_a_clean_probability_can_pass(self):
        for answer in (
            None,
            {"type": "predicate", "name": "q1"},
            {"type": "choice", "name": "q1", "probability": 0},
            {"type": "predicate", "name": "q1", "probability": "0"},
            {"type": "predicate", "name": "q1", "probability": True},
            {"type": "predicate", "name": "q1", "probability": float("nan")},
            {"type": "predicate", "name": "q1", "probability": -0.1},
            {"type": "predicate", "name": "q1", "probability": 1.5},
            {"type": "predicate", "name": "q1", "probability": 0, "refusal": "no"},
            "pass",
            0,
        ):
            verdict, probability = render_check.read_predicate(answer)
            self.assertEqual((verdict, probability), ("uncertain", None), answer)

    def test_one_flagged_question_flags_the_frame_and_the_worst_answer_wins(self):
        post = Scripted(reply(yes(0.0), yes(0.5, "q2"), yes(0.01, "q3")))
        result = run(render_check.check([("a", png())], ["x", "y", "z"], decisions=Decisions("k", post=post)))
        frame = result["frames"][0]
        self.assertEqual([a["verdict"] for a in frame["answers"]], ["pass", "flag", "pass"])
        self.assertEqual(frame["verdict"], "flag")
        self.assertEqual(result["look"], ["a"])

    def test_a_missing_answer_for_a_question_is_uncertain_not_a_pass(self):
        post = Scripted(reply(yes(0.0)))  # q2 was asked and not answered
        result = run(render_check.check([("a", png())], ["x", "y"], decisions=Decisions("k", post=post)))
        self.assertEqual(result["frames"][0]["verdict"], "uncertain")
        for broken in ({}, {"answers": "no"}, {"answers": [1, None]}, {"answers": [{"name": 3}]}, []):
            post = Scripted(broken)
            frame = run(render_check.check([("a", png())], ["x"], decisions=Decisions("k", post=post)))[
                "frames"
            ][0]
            self.assertEqual(frame["verdict"], "uncertain" if isinstance(broken, dict) else "unchecked")


class Choices(unittest.TestCase):
    def compare(self, answer, key="k"):
        post = Scripted(reply(answer))
        result = run(
            render_check.check(
                [("a", png()), ("b", png())],
                [],
                compare="Which matches the brief?",
                decisions=Decisions(key, post=post),
            )
        )
        return result, post

    def test_a_confident_pick_names_the_media(self):
        result, post = self.compare(pick("B", 0.7))
        self.assertEqual((result["compare"]["verdict"], result["compare"]["choice"]), ("choice", "b"))
        self.assertEqual(result["compare"]["variants"], {"A": "a", "B": "b"})
        self.assertEqual(result["look"], ["b"])
        asked = post.requests[0]["questions"][0]
        self.assertEqual([c["value"] for c in asked["choices"]], ["A", "B", "abstain"])
        self.assertEqual(result["frames"], [])

    def test_abstain_a_refusal_low_confidence_or_an_unknown_value_is_uncertain(self):
        for answer in (
            pick("abstain", 0.99),
            pick("B", 0.69),
            pick("C", 0.99),
            pick("B", None),
            pick("B", True),
            pick(None, 0.9),
            {"type": "choice", "name": "variant", "refusal": "x"},
            {"type": "predicate", "name": "variant", "probability": 0.9},
            None,
        ):
            result, _ = self.compare(answer)
            self.assertEqual(result["compare"]["verdict"], "uncertain", answer)
            self.assertIsNone(result["compare"]["choice"])
            self.assertEqual(result["look"], ["a", "b"])  # nothing chosen: look at every variant

    def test_variants_are_labelled_in_the_request_and_a_reference_follows_them(self):
        post = Scripted(reply(pick("A", 0.9)))
        run(
            render_check.check(
                [("a", png()), ("b", png())],
                [],
                compare="Which?",
                reference=png(),
                decisions=Decisions("k", post=post),
            )
        )
        content = post.requests[0]["input"][0]["content"]
        self.assertEqual(
            [c["data"]["image"] for c in content if c["type"] == "input_json"], ["A", "B", "reference"]
        )
        self.assertEqual(len([c for c in content if c["type"] == "input_image"]), 3)

    def test_compare_over_a_single_image_is_not_asked(self):
        post = Scripted()
        result = run(
            render_check.check([("a", png())], ["x"], compare="Which?", decisions=Decisions("k", post=post))
        )
        self.assertIsNone(result["compare"])


class Failures(unittest.TestCase):
    def test_an_api_error_leaves_every_frame_unchecked_with_the_reason(self):
        post = Scripted(
            Unavailable("the decision service answered HTTP 500"), repeat=AssertionError("asked again")
        )
        result = run(
            render_check.check([("a", png()), ("b", png())], ["x"], decisions=Decisions("k", post=post))
        )
        self.assertEqual(verdicts(result), [("a", "unchecked"), ("b", "unchecked")])
        self.assertEqual(result["frames"][1]["reason"], "the decision service answered HTTP 500")
        self.assertEqual(result["look"], ["a", "b"])
        self.assertEqual((len(post.requests), result["calls"]), (1, 0))  # a failing service is not hammered

    def test_frames_answered_before_a_failure_keep_their_verdicts(self):
        post = Scripted(reply(yes(0.0)), OSError("boom"))
        result = run(
            render_check.check([("a", png()), ("b", png())], ["x"], decisions=Decisions("k", post=post))
        )
        self.assertEqual(verdicts(result), [("a", "pass"), ("b", "unchecked")])
        self.assertIn("OSError", result["frames"][1]["reason"])
        self.assertEqual(result["look"], ["b"])

    def test_a_response_that_is_not_an_object_is_unchecked(self):
        for bad in (None, [], "ok", 3):
            result = run(
                render_check.check([("a", png())], ["x"], decisions=Decisions("k", post=Scripted(bad)))
            )
            self.assertEqual(result["frames"][0]["verdict"], "unchecked", bad)

    def test_no_key_means_nothing_is_sent_and_every_frame_is_unchecked(self):
        post = Scripted()
        result = run(render_check.check([("a", png())], ["x"], decisions=Decisions("", post=post)))
        self.assertEqual(verdicts(result), [("a", "unchecked")])
        self.assertIn("no decision-model key", result["frames"][0]["reason"])
        self.assertEqual(post.requests, [])

    def test_the_budget_is_spent_before_each_request_and_runs_out_to_unchecked(self):
        budget = [2]

        def spend():
            if budget[0] <= 0:
                return False
            budget[0] -= 1
            return True

        post = Scripted(repeat=reply(yes(0.0)))
        result = run(
            render_check.check(
                [(n, png()) for n in "abcd"], ["x"], decisions=Decisions("k", post=post), spend=spend
            )
        )
        self.assertEqual(
            verdicts(result), [("a", "pass"), ("b", "pass"), ("c", "unchecked"), ("d", "unchecked")]
        )
        self.assertIn("budget is used up", result["frames"][2]["reason"])
        self.assertEqual((len(post.requests), result["calls"]), (2, 2))

    def test_a_withdrawn_scope_stops_the_run_before_the_next_request(self):
        live = [True]

        def transport(body):
            live[0] = False  # the person stops render checks mid-run
            return reply(yes(0.0))

        result = run(
            render_check.check(
                [("a", png()), ("b", png())],
                ["x"],
                decisions=Decisions("k", post=transport),
                allowed=lambda: None if live[0] else "render checks were switched off during the call",
            )
        )
        self.assertEqual(verdicts(result), [("a", "pass"), ("b", "unchecked")])
        self.assertEqual(result["frames"][1]["reason"], "render checks were switched off during the call")

    def test_an_unreadable_image_is_unchecked_and_the_others_still_run(self):
        post = Scripted(reply(yes(0.0)))
        result = run(
            render_check.check([("bad", b"junk"), ("ok", png())], ["x"], decisions=Decisions("k", post=post))
        )
        self.assertEqual(verdicts(result), [("bad", "unchecked"), ("ok", "pass")])
        self.assertEqual(result["frames"][0]["reason"], "the image could not be read")

    def test_an_unreadable_reference_stops_everything(self):
        post = Scripted()
        result = run(
            render_check.check([("a", png())], ["x"], reference=b"junk", decisions=Decisions("k", post=post))
        )
        self.assertEqual(verdicts(result), [("a", "unchecked")])
        self.assertEqual(post.requests, [])

    def test_a_compare_over_an_unreadable_image_is_unchecked(self):
        post = Scripted()
        result = run(
            render_check.check(
                [("a", png()), ("bad", b"junk")], [], compare="Which?", decisions=Decisions("k", post=post)
            )
        )
        self.assertEqual(result["compare"]["verdict"], "unchecked")
        self.assertEqual(result["look"], ["a", "bad"])


class Sent(unittest.TestCase):
    def test_check_reports_every_image_it_attempted_in_order_without_repeats(self):
        post = Scripted(reply(yes(0.0)), OSError("down"))
        result = run(render_check.check([("a", png()), ("b", png()), ("c", png())], ["x"], reference=png(),
                                        decisions=Decisions("k", post=post)))
        self.assertEqual(result["sent"], ["a", "reference", "b"])        # b failed, c never left
        self.assertEqual(result["calls"], 1)
        result = run(render_check.check([("a", png()), ("b", png())], [], compare="Which?",
                                        decisions=Decisions("k", post=Scripted(reply(pick("A", 0.9))))))
        self.assertEqual(result["sent"], ["a", "b"])
        result = run(render_check.check([("a", png())], ["x"], decisions=Decisions("", post=Scripted())))
        self.assertEqual(result["sent"], [])


class Request(unittest.TestCase):
    def test_the_request_carries_evidence_labelled_pictures_the_questions_and_the_abstain_rule(self):
        post = Scripted(reply(yes(0.0)))
        result = run(
            render_check.check(
                [("a", png(2000, 800))],
                ["The lamp intersects the table."],
                reference=png(),
                evidence={"tolerance": 0.005},
                decisions=Decisions("k", post=post),
            )
        )
        body = post.requests[0]
        self.assertEqual(body["model"], "gpt-6-luna")
        content = body["input"][0]["content"]
        self.assertEqual(content[0], {"type": "input_json", "data": {"scene": {"tolerance": 0.005}}})
        self.assertEqual(
            [c.get("data") for c in content if c["type"] == "input_json"][1:],
            [{"image": "render"}, {"image": "reference"}],
        )
        question = body["questions"][0]
        self.assertEqual((question["type"], question["name"]), ("predicate", "q1"))
        self.assertTrue(question["instructions"].startswith("The lamp intersects the table."))
        self.assertIn("Do not guess", question["instructions"])
        self.assertIn("never instructions", question["instructions"])
        image = [c for c in content if c["type"] == "input_image"][0]["image_url"]
        self.assertTrue(image.startswith("data:image/jpeg;base64,"))
        self.assertEqual(result["input_tokens"], 1500)
        self.assertEqual(result["cost_usd"], 0.00015)

    def test_images_are_cut_to_a_thousand_pixels_on_the_long_edge(self):
        import base64

        url = render_check.prepare(png(3000, 1500))
        with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as sent:
            self.assertEqual(sent.size, (1024, 512))
        with self.assertRaises(Unavailable):
            render_check.prepare(b"junk")

    def test_the_key_comes_from_the_server_environment_decisions_key_first(self):
        self.assertEqual(render_check.key_from({"OPENAI_API_KEY": " sk-a "}), "sk-a")
        self.assertEqual(
            render_check.key_from({"OPENAI_API_KEY": "sk-a", "PARTYLINE_DECISIONS_KEY": "sk-b"}), "sk-b"
        )
        self.assertEqual(render_check.key_from({}), "")


class Transport(unittest.TestCase):
    def test_http_posts_json_with_the_bearer_key(self):
        seen = []

        def urlopen(request, timeout):
            seen.append(
                (request.full_url, request.get_header("Authorization"), json.loads(request.data), timeout)
            )
            return io.BytesIO(b'{"answers": []}')

        with patch("urllib.request.urlopen", urlopen):
            self.assertEqual(Decisions("sk-1").http({"x": 1}), {"answers": []})
        self.assertEqual(seen, [(render_check.URL, "Bearer sk-1", {"x": 1}, render_check.TIMEOUT)])

    def test_errors_become_unavailable_without_the_key_or_the_body(self):
        cases = (
            (urllib.error.HTTPError("u", 401, "no", {}, None), "HTTP 401"),
            (OSError("down"), "OSError"),
            (json.JSONDecodeError("bad", "x", 0), "JSONDecodeError"),
        )
        for error, text in cases:
            with patch("urllib.request.urlopen", side_effect=error), self.assertRaises(Unavailable) as caught:
                Decisions("sk-secret").http({"x": 1})
            self.assertIn(text, str(caught.exception))
            self.assertNotIn("sk-secret", str(caught.exception))

    def test_an_oversize_request_is_refused_before_it_is_sent(self):
        with patch.object(render_check, "MAX_BODY", 10), patch("urllib.request.urlopen") as sent:
            with self.assertRaisesRegex(Unavailable, "too large"):
                Decisions("k").http({"x": "y" * 50})
        sent.assert_not_called()

    def test_check_sync_and_the_command_line_entry(self):
        post = Scripted(reply(yes(0.5)))
        with (
            patch.object(Decisions, "http", lambda self, body: post(body)),
            patch.dict(os.environ, {"PARTYLINE_DECISIONS_KEY": "k"}),
            tempfile.TemporaryDirectory() as tmp,
        ):
            path = Path(tmp) / "r.png"
            path.write_bytes(png())
            (Path(tmp) / "e.json").write_text('{"a": 1}')
            out = io.StringIO()
            with patch("sys.stdout", out):
                render_check.main(
                    [
                        str(path),
                        "--question",
                        "x",
                        "--evidence",
                        str(Path(tmp) / "e.json"),
                        "--reference",
                        str(path),
                    ]
                )
        shown = json.loads(out.getvalue())
        self.assertEqual(shown["frames"][0]["verdict"], "flag")
        self.assertEqual(post.requests[0]["input"][0]["content"][0]["data"], {"scene": {"a": 1}})
        post = Scripted(reply(yes(0.0)))
        with (
            patch.object(Decisions, "http", lambda self, body: post(body)),
            patch.dict(os.environ, {"OPENAI_API_KEY": "k"}),
        ):
            self.assertEqual(render_check.check_sync([("a", png())], ["x"])["frames"][0]["verdict"], "pass")


class Mcp(unittest.TestCase):
    def test_the_tool_needs_write_validates_and_posts_to_the_route(self):
        self.assertEqual(tools_check.tool_list({"actions": ["read"]}), [])
        self.assertEqual([t["name"] for t in tools_check.tool_list({"actions": ["write"]})], ["render_check"])
        description = tools_check.tool_list({"actions": ["write"]})[0]["description"]
        self.assertIn("PROBLEM STATEMENTS", description)
        self.assertNotIn("Blender", description)
        calls = []
        client = SimpleNamespace(home="line/1", request=lambda *a, **k: calls.append((a, k)) or {"ok": 1})
        state = {"actions": ["write"]}
        args = {"media": ["m1"], "questions": ["x"], "evidence": {"a": 1}}
        tools_check.call(client, "render_check", args, state)
        self.assertEqual(
            calls,
            [(("POST", "/api/conversations/line%2F1/local-tools/render-check", args), {"timeout": 180})],
        )
        for bad in (
            {},
            {"media": []},
            {"media": ["m"], "extra": 1},
            {"media": ["m"], "questions": [1] * 13},
            {"media": ["m"] * 13},
            {"media": [""]},
            {"media": ["m"], "compare": "x" * 501},
        ):
            with self.assertRaises(ValueError):
                tools_check.call(client, "render_check", bad, state)
        with self.assertRaises(ApiError):
            tools_check.call(client, "render_check", args, {"actions": ["read"]})
        with self.assertRaises(ApiError):
            tools_check.call(client, "other", args, state)


class CheckFlow(media_tests.RenderHelpers, FlowCase):
    """The route over a real hub and helper: every refusal, and the checks that do run."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.post = Scripted(repeat=reply(yes(0.0)))
        patches = [
            patch.object(Decisions, "http", lambda this, body: self.post(body)),
            patch.dict(os.environ, {"PARTYLINE_DECISIONS_KEY": "sk-test"}),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    async def ids(self, op="render", count=1):
        out = []
        for _ in range(count):
            answer = await self.render(op)
            self.assertEqual(answer.status_code, 200, answer.text)
            out.append(answer.json()["file"]["id"])
        return out

    async def check(self, media, questions=("The lamp intersects the table.",), **more):
        return await self.client.post(CHECK, json={"media": media, "questions": list(questions), **more})

    async def with_checker(self, checker=True):
        await self.connect()
        self.terminal.box_answer = (True, checker)
        await self.grant(checker=checker)

    async def assertRefused(self, answer, *words):
        self.assertEqual(answer.status_code, 409, answer.text)
        for word in words:
            self.assertIn(word, answer.json()["detail"])
        self.assertEqual(self.post.requests, [])  # nothing left the host

    async def test_a_checked_render_returns_verdicts_and_the_audit_names_what_was_sent(self):
        await self.with_checker()
        first, second = await self.ids(count=2)
        self.post.replies = [reply(yes(0.0)), reply(yes(0.9))]
        answer = await self.check([first, second], evidence={"tolerance": 0.005})
        self.assertEqual(answer.status_code, 200, answer.text)
        body = answer.json()
        self.assertEqual(verdicts(body), [(first, "pass"), (second, "flag")])
        self.assertEqual(
            (body["look"], body["calls"], body["budget"]), ([second], 2, {"used": 2, "max": 200})
        )
        self.assertEqual(len(self.post.requests), 2)
        rows = local_tools_audit.rows(self.db, self.item().session_id)
        self.assertEqual(rows[-1]["kind"], "check")
        self.assertIn(f"images sent to the model: {first}, {second}", rows[-1]["entry"])
        self.assertIn('"flag": 1', rows[-1]["entry"])

    async def test_an_exec_only_session_is_refused_naming_the_permission(self):
        await self.with_checker(checker=False)
        (media,) = await self.ids()
        self.assertFalse(self.item().renders[media])
        await self.assertRefused(await self.check([media]), "no render-check permission", "checker=true")

    async def test_declined_escalation_leaves_it_refused_and_accepted_escalation_checks_only_later_renders(
        self,
    ):
        await self.with_checker(checker=False)
        (before,) = await self.ids()
        self.session.terminal.control_answer = False
        await self.client.post(REQUEST, json={"tool": "blender", "checker": True})
        await until(lambda: any("Render checks were not granted" in b for b in self.bodies()))
        await self.assertRefused(await self.check([before]), "no render-check permission")
        self.session.terminal.control_answer = True
        await self.client.post(REQUEST, json={"tool": "blender", "checker": True})
        await until(lambda: self.item().checker)
        await self.assertRefused(await self.check([before]), "rendered before render checks were allowed")
        (after,) = await self.ids()
        self.assertTrue(self.item().renders[after])
        self.assertEqual((await self.check([after])).status_code, 200)
        self.assertEqual(len(self.post.requests), 1)

    async def test_media_that_is_not_a_render_of_this_session_is_refused(self):
        await self.with_checker()
        (shot,) = await self.ids("screenshot")
        await self.assertRefused(await self.check([shot]), shot, "not a render produced in this session")
        await self.assertRefused(await self.check(["f-unknown"]), "f-unknown")
        (mine,) = await self.ids()
        await self.assertRefused(await self.check([mine, shot]), shot)  # one bad id refuses the call
        await self.assertRefused(await self.check([mine], reference=shot), shot)
        self.item().agent = "someone-else"
        await self.assertRefused(await self.check([mine]), "granted to someone-else")

    async def test_a_new_session_cannot_check_an_earlier_sessions_render(self):
        await self.with_checker()
        (old,) = await self.ids()
        await self.client.post("/api/conversations/line/local-tools/end")
        await until(lambda: self.item().status == "revoked")
        await self.assertRefused(await self.check([old]), "not granted")
        await self.grant(checker=True)  # the person agrees to a new session
        await self.assertRefused(await self.check([old]), old, "not a render produced in this session")

    async def test_no_session_at_all_is_refused(self):
        await self.connect()
        await self.assertRefused(await self.check(["x"]), "not granted")

    async def test_withdrawing_render_checks_on_the_computer_refuses_even_earlier_checkable_renders(self):
        await self.with_checker()
        (media,) = await self.ids()
        self.assertTrue(self.session.status.checks_active)
        self.session.status.request_stop_checks()  # the tray item
        await until(lambda: not self.item().checker)
        self.assertFalse(self.session.tools.grant["checker"])
        self.assertFalse(self.session.status.checks_active)
        self.assertTrue(any("switched off" in body for body in self.bodies()))
        await self.assertRefused(await self.check([media]), "no render-check permission")
        (later,) = await self.ids()
        self.assertFalse(self.item().renders[later])  # new renders are not marked checkable
        self.assertEqual((await self.run_code()).status_code, 200)  # Python itself still works

    async def test_a_message_from_the_computer_can_only_switch_render_checks_off(self):
        await self.with_checker(checker=False)
        await self.session.send("tools_granted", session_id=self.item().session_id, checker=True)
        await asyncio.sleep(0)
        self.assertFalse(self.item().checker)

    async def test_withdrawal_during_a_run_leaves_the_rest_unchecked(self):
        await self.with_checker()
        first, second = await self.ids(count=2)

        def transport(body):
            self.item().checker = False  # as if the helper had just said so
            return reply(yes(0.0))

        with patch.object(Decisions, "http", lambda this, body: transport(body)):
            answer = await self.check([first, second])
        self.assertEqual(verdicts(answer.json()), [(first, "pass"), (second, "unchecked")])
        self.assertEqual(
            answer.json()["frames"][1]["reason"], "render checks were switched off during the call"
        )

    async def test_revoking_the_session_during_a_run_stops_it_too(self):
        await self.with_checker()
        first, second = await self.ids(count=2)

        def transport(body):
            self.item().status = "revoked"
            return reply(yes(0.0))

        with patch.object(Decisions, "http", lambda this, body: transport(body)):
            answer = await self.check([first, second])
        self.assertEqual(verdicts(answer.json()), [(first, "pass"), (second, "unchecked")])

    async def test_the_per_session_budget_runs_out_across_calls(self):
        self.hub.tools.limits = self.hub.tools.limits.__class__(render_checks=3)
        await self.with_checker()
        ids = await self.ids(count=2)
        first = (await self.check(ids)).json()
        self.assertEqual(first["budget"], {"used": 2, "max": 3})
        second = (await self.check(ids)).json()
        self.assertEqual(verdicts(second), [(ids[0], "pass"), (ids[1], "unchecked")])
        self.assertIn("budget is used up", second["frames"][1]["reason"])
        third = (await self.check(ids)).json()
        self.assertEqual({v for _, v in verdicts(third)}, {"unchecked"})
        self.assertEqual(len(self.post.requests), 3)

    async def test_a_failed_request_still_audits_the_images_it_tried_to_send(self):
        await self.with_checker()
        first, second = await self.ids(count=2)
        self.post.replies, self.post.repeat = [Unavailable("the decision service answered HTTP 500")], None
        answer = await self.check([first, second], reference=first)
        self.assertEqual((answer.status_code, answer.json()["calls"]), (200, 0))
        self.assertEqual(answer.json()["sent"], [first, "reference"])      # the second was never attempted
        entry = local_tools_audit.rows(self.db, self.item().session_id)[-1]["entry"]
        self.assertIn(f"images sent to the model: {first}, reference", entry)
        self.assertNotIn(second, entry)
        self.assertIn("calls 0", entry)

    async def test_an_api_error_is_unchecked_not_an_http_error(self):
        await self.with_checker()
        ids = await self.ids(count=2)
        self.post.replies, self.post.repeat = [Unavailable("the decision service answered HTTP 429")], None
        answer = await self.check(ids)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual({v for _, v in verdicts(answer.json())}, {"unchecked"})
        self.assertEqual(answer.json()["look"], ids)

    async def test_a_missing_key_is_unchecked_and_sends_nothing(self):
        await self.with_checker()
        ids = await self.ids()
        with patch.dict(os.environ, {"PARTYLINE_DECISIONS_KEY": "", "OPENAI_API_KEY": ""}):
            answer = await self.check(ids)
        self.assertEqual(answer.json()["frames"][0]["verdict"], "unchecked")
        self.assertEqual(self.post.requests, [])

    async def test_compare_and_a_reference_between_renders(self):
        await self.with_checker()
        first, second = await self.ids(count=2)
        self.post.replies = [reply(pick("B", 0.95))]
        answer = await self.client.post(
            CHECK, json={"media": [first, second], "compare": "Which is better?", "reference": first}
        )
        body = answer.json()
        self.assertEqual((body["compare"]["verdict"], body["compare"]["choice"]), ("choice", second))
        self.assertEqual(body["look"], [second])
        images = [c for c in self.post.requests[0]["input"][0]["content"] if c["type"] == "input_image"]
        self.assertEqual(len(images), 3)
        self.assertIn(
            f"images sent to the model: {first}, {second}",
            local_tools_audit.rows(self.db, self.item().session_id)[-1]["entry"],
        )

    async def test_a_session_remembers_only_its_latest_renders_for_checking(self):
        await self.with_checker()
        with patch.object(local_tools_media, "KEEP_RENDERS", 2):
            first, second, third = await self.ids(count=3)
        self.assertEqual(list(self.item().renders), [second, third])
        await self.assertRefused(await self.check([first]), first, "not a render produced in this session")
        self.assertEqual((await self.check([second, third])).status_code, 200)

    async def test_a_render_tells_the_agent_whether_it_can_be_checked(self):
        await self.with_checker()
        self.assertIs((await self.render()).json()["checkable"], True)
        self.assertNotIn("checkable", (await self.render("screenshot")).json())
        self.session.status.request_stop_checks()
        await until(lambda: not self.item().checker)
        self.assertIs((await self.render()).json()["checkable"], False)

    async def test_a_local_kill_clears_the_tray_item_and_ends_the_checks(self):
        await self.with_checker()
        (media,) = await self.ids()
        self.session.status.request_stop_tools()
        await until(lambda: self.item().status == "revoked")
        self.assertFalse(self.session.status.checks_active)
        self.assertIsNone(self.session.status.stop_checks)
        await self.assertRefused(await self.check([media]), "not granted")

    async def test_request_shape_errors_are_plain(self):
        await self.with_checker()
        (media,) = await self.ids()
        await self.assertRefused(
            await self.client.post(CHECK, json={"media": [media]}), "at least one question"
        )
        await self.assertRefused(await self.check([media], compare="Which?"), "2 to 6")
        await self.assertRefused(await self.check([media], evidence={"x": "y" * 17000}), "evidence")
        self.assertEqual((await self.client.post(CHECK, json={"media": []})).status_code, 422)
        self.assertEqual(
            (await self.client.post(CHECK, json={"media": [media], "key": "x"})).status_code, 422
        )

    async def test_media_that_can_no_longer_be_read_is_refused(self):
        await self.with_checker()
        (media,) = await self.ids()
        path, _, _ = self.store.file_for(media, "original")
        path.unlink()
        await self.assertRefused(await self.check([media]), "can no longer be read")

    async def test_the_key_is_in_no_answer_and_no_audit_row(self):
        await self.with_checker()
        (media,) = await self.ids()
        answer = await self.check([media])
        self.assertNotIn("sk-test", answer.text)
        self.assertNotIn("sk-test", json.dumps(local_tools_audit.rows(self.db, self.item().session_id)))
        self.assertNotIn("sk-test", json.dumps(self.post.requests))
