import unittest

from partyline.attachment_commands import validated_attachment_command


class AttachmentCommandTest(unittest.TestCase):
    def setUp(self):
        self.adapters = {"fake"}
        self.metadata = {
            "fake": {"command": ["fake", "--default"], "requires": ["fake"]}
        }

    def resolve(self, raw, *, found=True):
        lookup = (lambda _executable: "/bin/fake") if found else (lambda _executable: None)
        return validated_attachment_command(
            "fake", raw, self.adapters, self.metadata, lookup
        )

    def test_shell_splitting_and_blank_default_match_attach_semantics(self):
        self.assertEqual(self.resolve('fake --label "two words"'), [
            "fake", "--label", "two words",
        ])
        self.assertEqual(self.resolve("  "), ["fake", "--default"])

    def test_malformed_shell_command_is_a_readable_validation_error(self):
        with self.assertRaisesRegex(ValueError, "invalid command: No closing quotation"):
            self.resolve("fake 'unfinished")

    def test_unknown_adapter_missing_default_and_missing_requirement_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "adapter must be one of"):
            validated_attachment_command("missing", "x", self.adapters, self.metadata)

        self.metadata["fake"]["command"] = []
        with self.assertRaisesRegex(ValueError, "needs an explicit command"):
            self.resolve("")

        with self.assertRaisesRegex(ValueError, "not on PATH"):
            self.resolve("fake", found=False)


if __name__ == "__main__":
    unittest.main()
