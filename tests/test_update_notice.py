"""The tray says once that the helper updated; first installs and plain restarts stay quiet."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline_helper import update_notice
from partyline_helper.status import Status


class UpdateNoticeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = Path(directory.name) / "helper.json"
        patcher = patch.object(update_notice, "config_path", return_value=config)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.status = Status()
        self.shown = []
        self.status.attention_listeners.append(self.shown.append)  # a fake notifier in place of the tray

    def test_first_install_and_same_version_restart_are_silent_and_an_update_fires_once(self):
        self.assertFalse(update_notice.announce_update(self.status, "1.6.2"))  # first install: seeded
        self.assertFalse(update_notice.announce_update(self.status, "1.6.2"))  # plain restart
        self.assertEqual(self.shown, [])
        self.assertTrue(update_notice.announce_update(self.status, "1.6.3"))
        self.assertEqual(self.shown, ["Partyline Helper updated to 1.6.3"])
        self.assertFalse(update_notice.announce_update(self.status, "1.6.3"))  # persisted across restarts
        self.assertEqual(len(self.shown), 1)
        self.assertEqual(update_notice.announced(), "1.6.3")

    def test_numeric_ordering_and_downgrades_unreadable_records(self):
        update_notice.announce_update(self.status, "1.9.0")
        self.assertTrue(update_notice.announce_update(self.status, "1.10.0"))
        self.assertFalse(update_notice.announce_update(self.status, "1.6.0"))  # a rollback is not an update
        self.assertEqual(update_notice.announced(), "1.6.0")
        update_notice.path().write_text("not json")
        self.assertIsNone(update_notice.announced())
        self.assertFalse(update_notice.announce_update(self.status, "1.6.1"))  # reseeded, not announced
        update_notice.path().write_text('{"version": 5}')
        self.assertIsNone(update_notice.announced())

    def test_the_notice_runs_once_when_the_helper_first_reaches_the_server(self):
        calls = []
        self.status.when_ready = lambda: calls.append(1)
        self.status.ready()
        self.status.ready()
        self.assertEqual(calls, [1])
        self.status.when_ready = lambda: 1 / 0
        self.status.ready()  # a failing notice never stops the helper
