#!/usr/bin/env python3
"""Host-specific OpenCode probe; its preset path needs local adaptation."""

import os
from pathlib import Path
import sys

from probe_common import probe_attachment
from partyline.adapters.bundled.opencode.v2 import PartylineAdapter


PRESET = os.environ.get(
    "PARTYLINE_OPENCODE_V2_PRESET",
    str(Path.home() / ".local/share/partyline/opencode-v2-presets/glm-flash"),
)
if sys.argv[1:2] and sys.argv[1] in {"debug", "--help", "-h", "--version"}:
    os.execvpe(PRESET, [PRESET, *sys.argv[1:]], os.environ)

attachment = probe_attachment()
adapter = PartylineAdapter.__new__(PartylineAdapter)
adapter.att = attachment
os.environ.update(adapter.mcp_env())
os.execvpe(PRESET, [PRESET, *sys.argv[1:]], os.environ)
