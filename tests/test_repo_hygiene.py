"""No tracked file may carry machine-specific identifiers.

A public repository once shipped a home-directory path and captured chat
transcripts, and the leak was found after merge (docs/lessons.md). This
guard turns the next one into a red test before push instead of a
discovery after it. The terms are assembled from fragments so no tracked
file — including this one — contains a full identifier.
"""

import os
import re
import subprocess
import unittest
from unittest import mock

DENYLIST = {"gmcc" + "arthy", "home" + ".arpa", "partyline" + "-lan"}

SKIP_FILES = {"uv.lock"}
SKIP_PREFIXES = ("partyline/static/",)


def denylist_terms() -> set[str]:
    """Built-in terms plus local extras from PARTYLINE_REPO_DENYLIST."""
    extras = {
        term.strip().lower()
        for term in os.environ.get("PARTYLINE_REPO_DENYLIST", "").split(",")
        if term.strip()
    }
    return {term.lower() for term in DENYLIST} | extras


def tracked_files(skip_files=SKIP_FILES) -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], check=True, capture_output=True
    ).stdout
    paths = [entry.decode() for entry in listed.split(b"\0") if entry]
    return [
        path
        for path in paths
        if path not in skip_files and not path.startswith(SKIP_PREFIXES)
    ]


class RepoHygieneTest(unittest.TestCase):
    def test_the_guard_is_seeded_with_distinct_lowercase_terms(self):
        self.assertTrue(DENYLIST)
        self.assertEqual(len(DENYLIST), 3)
        self.assertTrue(all(term == term.lower() for term in DENYLIST))

    def test_env_extras_extend_the_denylist(self):
        base = {term.lower() for term in DENYLIST}
        self.assertEqual(denylist_terms(), base)
        with mock.patch.dict(
            os.environ, {"PARTYLINE_REPO_DENYLIST": "secret-host, secret.domain"}
        ):
            extended = denylist_terms()
        self.assertEqual(extended, base | {"secret-host", "secret.domain"})

    def test_no_tracked_file_contains_a_denylisted_term(self):
        terms = denylist_terms()
        offenders = []
        for path in tracked_files():
            with open(path, "rb") as handle:
                data = handle.read()
            if b"\0" in data:
                continue  # binary; substring scanning is meaningless
            text = data.decode("utf-8", errors="replace").lower()
            offenders.extend(
                f"{path}: {term}" for term in sorted(terms) if term in text
            )
        self.assertEqual(offenders, [])


CLIENT_NAMES = re.compile(
    r"\b(?:" + "|".join(("K" + "DP", "Kindle " + "Direct", "A\\+ " + "Content", "Ama" + "zon")) + r")\b"
)
CLIENT_SKIP_PREFIXES = SKIP_PREFIXES + ("docs/",)


class NoClientNamesTest(unittest.TestCase):
    """The public repo names no client site or product workflow; fixtures use neutral examples."""

    def test_the_pattern_matches_the_names_it_guards(self):
        samples = ("K" + "DP Bookshelf", "A+ " + "Content", "Ama" + "zon.com", "Kindle " + "Direct Pub")
        for sample in samples:
            self.assertTrue(CLIENT_NAMES.search(sample), sample)
        self.assertIsNone(CLIENT_NAMES.search("Catalog Dashboard, Manage listing content"))

    def test_no_tracked_file_outside_docs_names_a_client(self):
        offenders = []
        for path in tracked_files(skip_files=()):
            if path.startswith(CLIENT_SKIP_PREFIXES):
                continue
            with open(path, "rb") as handle:
                data = handle.read()
            if b"\0" in data:
                continue
            text = data.decode("utf-8", errors="replace")
            offenders.extend(f"{path}: {match}" for match in sorted(set(CLIENT_NAMES.findall(text))))
        self.assertEqual(offenders, [])
