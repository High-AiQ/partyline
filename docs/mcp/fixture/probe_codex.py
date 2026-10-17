#!/usr/bin/env python3
"""Host-specific Codex probe launcher; paths and model need local adaptation."""

import os
import sys

from probe_common import codex_command, probe_attachment


if sys.argv[1:2] in (["--help"], ["-h"], ["--version"]):
    os.execvpe("codex", ["codex", *sys.argv[1:]], os.environ)

attachment = probe_attachment()
command = codex_command(attachment, sys.argv[1:])
os.execvpe(command[0], command, os.environ)
