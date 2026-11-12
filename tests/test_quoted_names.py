"""A handle written only as code is quoted, not addressed."""

import unittest

from partyline.mentions import quoted_names


class QuotedNamesTest(unittest.TestCase):
    def test_only_names_never_written_outside_code_are_quoted(self):
        body = "`@one` and @two, then `@two` again\n```py\n@three\ndef f(): ...\n```\n@four"
        self.assertEqual(quoted_names(body), {"one", "three"})

    def test_an_unclosed_fence_quotes_to_the_end(self):
        self.assertEqual(quoted_names("@a\n```\n@b"), {"b"})
        self.assertEqual(quoted_names("no code, @a"), set())
