"""Every test run gets its own database and media directory, before anything imports the server.

``partyline/server.py`` opens ``PARTYLINE_DB`` (or ``~/.partyline.db``) at
import time. Five test modules used to paper over that with
``os.environ.setdefault("PARTYLINE_DB", "/tmp/partyline-test-<x>.db")`` —
whichever imported first won, the path was fixed, and two suites running at
once on one machine (two worktrees, two agents) shared the file: one's new
migration dropped a table the other's tests still expected. Isolation is the
test package's job, done once, per process, in a directory that dies with it.
"""

import atexit
import os
import shutil
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="partyline-tests-")
os.environ["PARTYLINE_DB"] = os.path.join(_SANDBOX, "partyline.db")
os.environ["PARTYLINE_MEDIA_DIR"] = os.path.join(_SANDBOX, "media")
atexit.register(shutil.rmtree, _SANDBOX, True)
