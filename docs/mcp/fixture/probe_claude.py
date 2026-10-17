#!/home/gmccarthy/code/partyline/.venv/bin/python
"""Host-specific Claude probe launcher; paths and preset need local adaptation."""

import os
import sys

from probe_common import probe_attachment
from partyline.adapters.bundled.claude.adapter import PartylineAdapter


attachment = probe_attachment()
adapter = PartylineAdapter.__new__(PartylineAdapter)
adapter.att = attachment
command = ["claude", "--model", "claude-haiku-5-5", "--effort", "high",
           "--dangerously-skip-permissions", *sys.argv[1:]]
command = adapter.mcp_argv(command)
os.execvpe(command[0], command, os.environ)
