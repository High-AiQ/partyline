"""A bare domain in prose is not a mention; a dotted handle that names a member still rings."""

import unittest

from partyline.mentions import domain_shaped
from tests.test_return_path import Tree

MARK = "did not reach everyone"


class DomainShapeTest(unittest.TestCase):
    def test_a_dot_then_a_letters_only_label_is_domain_shaped(self):
        for name in ("example.com", "docs.dev.io", "example.com."):
            self.assertTrue(domain_shaped(name), name)
        for name in ("sol", "sol.", "ops.bot2", "v1.2", "a.b", "pytest.fixture-2", "dataclass"):
            self.assertFalse(domain_shaped(name), name)


class DomainMentionTest(Tree):
    def delivered(self, att_id):
        return [m["body"] for batch in self.adapters[att_id].delivered for m in batch]

    def warnings(self):
        bodies = [m["body"] for att in self.adapters.values()
                  for batch in att.delivered for m in batch]
        return [body for body in bodies
                if MARK in body or "unknown handle" in body or "reached nobody" in body]

    async def test_a_bare_domain_in_prose_warns_nobody(self):
        await self.say("worker", "The docs are at @example.com, see the page.")

        self.assertEqual(self.warnings(), [])

    async def test_a_dotted_handle_that_matches_a_member_still_rings(self):
        self.attach("ops.bot", "parent")

        await self.say("worker", "@ops.bot please take this")

        self.assertTrue(any("please take this" in body for body in self.delivered("ops.bot")))
        self.assertEqual(self.warnings(), [])

    async def test_an_unknown_non_domain_handle_still_warns(self):
        await self.say("worker", "@nobody-here please take this")

        self.assertTrue(any("@nobody-here: unknown handle" in body
                            for body in self.delivered("worker")))
