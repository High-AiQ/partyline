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

from partyline import docker_bridge_client as _docker_bridge_client
from partyline import docker_relay as _docker_relay
from partyline import resource_budget as _resource_budget
from partyline import resource_usage as _resource_usage
from partyline.resource_budget import GIB, Host

_SANDBOX = tempfile.mkdtemp(prefix="partyline-tests-")
os.environ["PARTYLINE_DB"] = os.path.join(_SANDBOX, "partyline.db")
# Temp directories never touch the real /tmp either: every attachment's
# TMPDIR is created under the sandbox (finding 5.12).
os.environ["PARTYLINE_TMP_BASE"] = os.path.join(_SANDBOX, "tmp")
# The docker relay directories live under the home directory; tests get their own.
_docker_relay.RELAY_ROOT = os.path.join(_SANDBOX, "docker")
_docker_bridge_client.BRIDGE_ROOT = os.path.join(_SANDBOX, "docker-bridge")
# Pin runtime-derived capacity for every ordinary test. Tests of host discovery
# and admission policy explicitly use their own fake Host values.
PINNED_TEST_HOST = Host(cpus=32, ram_bytes=1024 * GIB)
REAL_HOST_RESOURCES = _resource_budget.host_resources
REAL_SERVER_USAGE = _resource_usage.server_usage_bytes


def _pinned_host_resources():
    return PINNED_TEST_HOST


_resource_budget.host_resources = _pinned_host_resources
# Usage sampling reads /proc; ordinary tests get a flat None instead.
_resource_usage.server_usage_bytes = lambda *args, **kwargs: None
# The media directory follows the database path, so it lands in the sandbox too.
atexit.register(shutil.rmtree, _SANDBOX, True)
