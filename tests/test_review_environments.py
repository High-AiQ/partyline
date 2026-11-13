"""Settings select only the deepest environment touched in a repository."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline.db import Db
from partyline.review_environments import Environments, entries_for, normalize


class ReviewEnvironmentsTest(unittest.TestCase):
    def test_url_normalization(self):
        self.assertEqual(normalize('git@example.invalid:team/repo.git'),
                         normalize('https://example.invalid/team/repo'))

    def test_path_fallback_and_longest_touched_subpath(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Db(Path(tmp) / 'settings.db')
            self.addCleanup(db.close)
            root = str(Path(tmp) / 'repo')
            for subpath in ('.', 'one', 'one/deep', 'untouched'):
                db._exec('INSERT INTO review_environments VALUES(?,?,?,?,?,?)',
                         (root, subpath, '', subpath, 'person', 0))
            with patch('partyline.review_environments._git') as git:
                git.return_value.returncode = 1
                entries = entries_for(db, root, ['one/deep/file.py', 'one/other.py', 'root.py'])
            self.assertEqual({e.subpath for e in entries}, {'.', 'one', 'one/deep'})

    def test_rejects_escaping_subpath_and_duplicates(self):
        with self.assertRaises(ValueError):
            Environments(entries=[{'repository': 'repo', 'subpath': '../escape'}])
        with self.assertRaises(ValueError):
            Environments(entries=[{'repository': 'git@example.invalid:a/b.git'},
                                  {'repository': 'https://example.invalid/a/b'}])
