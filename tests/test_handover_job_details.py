"""A live job is listed with its command and working directory, or with why they are unknown."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from partyline import job_details
from partyline.handover_jobs import jobs_text


def job(**fields):
    return {'pid': 7, 'host_pid': 70, 'command': 'sleep 30', 'cwd': '/work', 'files': [],
            'unknown': '', **fields}


class JobDetailsTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith('linux'), 'reads /proc')
    def test_a_real_child_reports_its_command_and_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            proc = subprocess.Popen(['sleep', '30'], cwd=folder)
            self.addCleanup(proc.wait)
            self.addCleanup(proc.kill)
            command, cwd, why = job_details.describe(proc.pid)
        self.assertEqual(command, 'sleep 30')
        self.assertEqual(os.path.realpath(cwd), os.path.realpath(folder))
        self.assertEqual(why, '')

    def test_macos_reads_ps_and_lsof(self):
        answers = {'ps': 'node server.js --port 3000\n', 'lsof': 'p42\nfcwd\nn/Users/me/app\n'}
        with patch.object(job_details.sys, 'platform', 'darwin'), \
             patch.object(job_details, '_run', lambda command: answers[command[0]]):
            self.assertEqual(job_details.describe(42), ('node server.js --port 3000', '/Users/me/app', ''))

    def test_an_unreadable_job_says_why_instead_of_a_bare_question_mark(self):
        with patch.object(job_details.sys, 'platform', 'darwin'), \
             patch.object(job_details, '_run', lambda command: None):
            command, cwd, why = job_details.describe(42)
        self.assertEqual((command, cwd), (None, None))
        self.assertIn('exited', why)
        text = jobs_text([job(command=command, cwd=cwd, unknown=why)])
        self.assertNotIn('?', text)
        self.assertIn('command unknown', text)
        self.assertIn('cwd=unknown', text)
        self.assertIn('unknown because', text)

    def test_windows_has_a_command_but_no_working_directory(self):
        with patch.object(job_details.sys, 'platform', 'win32'), \
             patch.object(job_details, '_run', lambda command: 'python.exe worker.py\r\n'):
            command, cwd, why = job_details.describe(42)
        self.assertEqual((command, cwd), ('python.exe worker.py', None))
        self.assertIn('Windows', why)

    def test_a_known_job_reads_cleanly_and_a_long_command_is_clipped(self):
        self.assertNotIn('unknown', jobs_text([job()]))
        self.assertLessEqual(len(job_details._clip('x' * 900)), job_details.COMMAND_CHARS)


if __name__ == '__main__':
    unittest.main()
