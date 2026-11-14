"""Server-side helper version comparison: a newer server flags an older helper, never the reverse."""
import unittest

from partyline import helper_release


class HelperReleaseTests(unittest.TestCase):
    def test_parse_accepts_plain_dotted_numbers_only(self):
        self.assertEqual(helper_release.parse("2.89.0"), (2, 89, 0))
        self.assertEqual(helper_release.parse(" 3.1 "), (3, 1, 0))
        self.assertEqual(helper_release.parse("4"), (4, 0, 0))
        for value in ("unknown", "", "2.89.0.dev1", "v2.89.0", "1.2.3.4", None, 5):
            self.assertIsNone(helper_release.parse(value))

    def test_a_hostile_version_is_ignored_not_converted(self):
        for value in ("9" * 5000, "1." + "9" * 10, "9" * 10, "١٢٣"):
            self.assertIsNone(helper_release.parse(value), value[:12])
        self.assertEqual(helper_release.parse("999999999.1"), (999999999, 1, 0))

    def test_older_and_legacy_helpers_are_flagged(self):
        self.assertTrue(helper_release.update_available("0.9.9", "1.0.0"))
        self.assertTrue(helper_release.update_available("2.117.0", "1.0.0"))
        self.assertFalse(helper_release.update_available("1.0.0", "1.0.0"))
        self.assertFalse(helper_release.update_available("1.1.0", "1.0.0"))
        self.assertFalse(helper_release.update_available("unknown", "1.0.0"))
        self.assertFalse(helper_release.update_available("2.0.0", "not-a-version"))

    def test_helper_version_is_the_default(self):
        from partyline_helper import __version__
        self.assertFalse(helper_release.update_available(__version__))

    def test_the_installer_url_names_the_exact_version_in_tag_and_file(self):
        info = helper_release.installer_info("1.2.0")
        self.assertEqual(info["filename"], "PartylineHelper-Setup-1.2.0.exe")
        self.assertEqual(info["url"], "https://github.com/High-AiQ/partyline/releases/download/"
                                      "helper-v1.2.0/PartylineHelper-Setup-1.2.0.exe")
        self.assertEqual((info["version"], info["releases_url"]),
                         ("1.2.0", "https://github.com/High-AiQ/partyline/releases"))
        self.assertNotIn("latest", info["url"])

    def test_the_installer_defaults_to_the_shipped_helper_version(self):
        from partyline_helper import __version__
        info = helper_release.installer_info()
        self.assertEqual(info["version"], __version__)
        self.assertTrue(info["url"].endswith(f"/helper-v{__version__}/PartylineHelper-Setup-{__version__}.exe"))


if __name__ == "__main__":
    unittest.main()
