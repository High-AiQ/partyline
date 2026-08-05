"""Unit coverage for the cockpit preflight.

The checks that matter here are the ones that answer "is the thing on disk
actually the thing that was built" — a question with a real wrong answer that
has already cost a restart. They are pure functions over a directory, so they
are tested against temp directories rather than a git fixture.
"""

import sys
import json
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cockpit import (  # noqa: E402
    Finding,
    check_bundle_present,
    check_tree_clean,
    referenced_assets,
    resolve_line,
    restart_needed,
    schedule_restart_plan,
)
from partyline.contracts import ConversationResponse


class StaticTree:
    """A throwaway checkout with a `partyline/static/` in a chosen state."""

    def __init__(self, index_html=None, assets=()):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        static = self.root / "partyline" / "static"
        (static / "assets").mkdir(parents=True)
        if index_html is not None:
            (static / "index.html").write_text(index_html)
        for name in assets:
            (static / "assets" / name).write_text("/* built */")

    def __enter__(self):
        return self.root

    def __exit__(self, *exc):
        self.dir.cleanup()


INDEX = ('<!DOCTYPE html><html><head>'
         '<script type="module" src="/assets/index-ABC123.js"></script>'
         '<link rel="stylesheet" href="/assets/index-DEF456.css">'
         '</head><body><div id="root"></div></body></html>')


class ReferencedAssetsTest(unittest.TestCase):
    def test_it_finds_every_hashed_asset_the_page_asks_for(self):
        with StaticTree(INDEX) as root:
            found = referenced_assets(root / "partyline" / "static")
        self.assertEqual(sorted(found), ["index-ABC123.js", "index-DEF456.css"])

    def test_a_missing_index_is_no_references_rather_than_a_crash(self):
        with StaticTree(index_html=None) as root:
            self.assertEqual(referenced_assets(root / "partyline" / "static"), [])

    def test_it_ignores_urls_that_are_not_assets(self):
        page = '<link href="https://fonts.googleapis.com/css2?family=X"><script src="/assets/a.js">'
        with StaticTree(page) as root:
            self.assertEqual(referenced_assets(root / "partyline" / "static"), ["a.js"])


class BundlePresentTest(unittest.TestCase):
    def test_a_complete_bundle_passes(self):
        with StaticTree(INDEX, ["index-ABC123.js", "index-DEF456.css"]) as root:
            self.assertEqual(check_bundle_present(root, "workbench"), [])

    def test_no_built_frontend_at_all_is_reported(self):
        with StaticTree(index_html=None) as root:
            findings = check_bundle_present(root, "cockpit")
        self.assertEqual(len(findings), 1)
        self.assertIn("no built frontend", findings[0].problem)
        self.assertIn("npm", findings[0].fix)

    def test_a_referenced_asset_that_is_missing_is_reported(self):
        """The blank-page case: the server starts, the HTML is served, and the
        browser silently fails to fetch a script nobody committed."""
        with StaticTree(INDEX, ["index-ABC123.js"]) as root:
            findings = check_bundle_present(root, "cockpit")
        self.assertEqual(len(findings), 1)
        self.assertIn("index-DEF456.css", findings[0].problem)
        self.assertNotIn("index-ABC123.js", findings[0].problem)

    def test_the_label_names_which_checkout_is_wrong(self):
        with StaticTree(index_html=None) as root:
            self.assertIn("cockpit", check_bundle_present(root, "cockpit")[0].problem)
            self.assertIn("workbench", check_bundle_present(root, "workbench")[0].problem)


class TreeCleanTest(unittest.TestCase):
    """`check_tree_clean` shells out to git; these stub it to pin the flags."""

    def setUp(self):
        import scripts.cockpit as cockpit

        self.cockpit = cockpit
        self.real_git = cockpit.git
        self.calls = []

    def tearDown(self):
        self.cockpit.git = self.real_git

    def stub(self, output):
        def fake(*args, **kwargs):
            self.calls.append(args)
            return output
        self.cockpit.git = fake

    def test_the_workbench_counts_untracked_files(self):
        # A new source file nobody committed cannot reach the cockpit, which is
        # the whole thing this script exists to catch.
        self.stub("?? frontend/src/lib/new.js")
        self.assertTrue(check_tree_clean(Path("/tmp"), "workbench", untracked=True))
        self.assertNotIn("--untracked-files=no", self.calls[0])

    def test_the_cockpit_ignores_untracked_files(self):
        # It is a deployment target: it accumulates logs and databases, and a
        # stray cockpit.log must not look like unfinished work.
        self.stub("")
        self.assertEqual(check_tree_clean(Path("/tmp"), "cockpit", untracked=False), [])
        self.assertIn("--untracked-files=no", self.calls[0])

    def test_a_modified_tracked_file_stops_either_checkout(self):
        self.stub(" M partyline/server.py")
        for untracked in (True, False):
            self.assertTrue(check_tree_clean(Path("/tmp"), "cockpit", untracked=untracked))


class RestartNeededTest(unittest.TestCase):
    """`restart_needed` shells out to git for the diff, so these stub it."""

    def setUp(self):
        import scripts.cockpit as cockpit

        self.cockpit = cockpit
        self.real_git = cockpit.git

    def tearDown(self):
        self.cockpit.git = self.real_git

    def stub_diff(self, paths):
        self.cockpit.git = lambda *args, **kwargs: "\n".join(paths)

    def test_no_movement_needs_no_restart(self):
        self.assertFalse(restart_needed(Path("/tmp"), "abc", "abc"))

    def test_an_adapter_only_change_reloads_instead(self):
        self.stub_diff(["partyline/adapters/bundled/raw/adapter.py"])
        self.assertFalse(restart_needed(Path("/tmp"), "abc", "def"))

    def test_a_server_change_needs_a_restart(self):
        self.stub_diff(["partyline/server.py"])
        self.assertTrue(restart_needed(Path("/tmp"), "abc", "def"))

    def test_a_frontend_change_needs_a_restart(self):
        # The bundle is served by the running process, so a new one needs it.
        self.stub_diff(["partyline/static/assets/index-NEW.js"])
        self.assertTrue(restart_needed(Path("/tmp"), "abc", "def"))

    def test_a_mixed_change_needs_a_restart(self):
        self.stub_diff(["partyline/adapters/loader.py", "partyline/server.py"])
        self.assertTrue(restart_needed(Path("/tmp"), "abc", "def"))


class FindingTest(unittest.TestCase):
    def test_a_finding_always_carries_the_fix_as_well_as_the_problem(self):
        # The point of the preflight is that it tells you what to do, not just
        # that something is wrong.
        finding = Finding("the cockpit is behind", "run deploy")
        self.assertTrue(finding.problem and finding.fix)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def read(self):
        return self.payload


class RestartPlanTest(unittest.TestCase):
    conversations = [
        ConversationResponse(
            id="line-1",
            name="Partyline Refactoring",
            created_at=1,
            topic="",
            archived_at=None,
        ),
        ConversationResponse(
            id="line-2",
            name="Other",
            created_at=2,
            topic="",
            archived_at=None,
        ),
    ]

    def test_line_resolution_prefers_an_exact_id_then_a_unique_name(self):
        self.assertEqual(resolve_line(self.conversations, "line-2").id, "line-2")
        self.assertEqual(resolve_line(self.conversations, "partyline refactoring").id, "line-1")
        with self.assertRaisesRegex(ValueError, "no live line"):
            resolve_line(self.conversations, "missing")

    def test_an_ambiguous_name_requires_the_id(self):
        duplicate = self.conversations + [self.conversations[0].model_copy(update={"id": "line-3"})]

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            resolve_line(duplicate, "Partyline Refactoring")

    def test_plan_posts_the_resolved_line_and_debrief(self):
        requests = []
        responses = [
            FakeResponse([line.model_dump() for line in self.conversations]),
            FakeResponse(
                {
                    "conversation_id": "line-1",
                    "token": "offer-token",
                    "attachments": [{"id": "a1", "name": "sol", "adapter": "codex"}],
                    "debrief": "Continue the restart review.",
                }
            ),
        ]

        def open_url(request):
            requests.append(request)
            return responses.pop(0)

        result = schedule_restart_plan(
            "Partyline Refactoring",
            "Continue the restart review.",
            "http://127.0.0.1:8642",
            open_url,
        )

        self.assertEqual(result.token, "offer-token")
        self.assertEqual(requests[0].full_url, "http://127.0.0.1:8642/api/conversations")
        self.assertEqual(requests[1].full_url, "http://127.0.0.1:8642/api/restart-plan")
        self.assertEqual(
            json.loads(requests[1].data),
            {
                "conversation_id": "line-1",
                "debrief": "Continue the restart review.",
            },
        )


if __name__ == "__main__":
    unittest.main()
