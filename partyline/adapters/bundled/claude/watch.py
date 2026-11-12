"""Which Claude transcripts the adapter holds descriptors for, and when it lets go.

kqueue holds one descriptor per exact file, and a directory vnode does not report
appends to its existing children. A Mac with a long Claude history has thousands of
old transcripts, and every live Claude adapter used to hold all of them for its whole
life. Two facts bound that:

* While searching, a transcript can hold this activation's token only if the search
  would read it (``ClaudeSession._may_hold_our_token``: the pinned name, or written
  since spawn). The watch admits exactly those files and every project directory, so
  a new file (a re-exec's randomly named session, a first pinned write) is reported
  by its directory and gets its own descriptor then. The scan itself is authoritative
  on every wake, so the one hole is an old, differently named file appended silently,
  which the pty output of the CLI that wrote it wakes the scan for anyway.
* Once a transcript is claimed nothing else is read, so the watch narrows to that file.
"""

import os


def projects_glob() -> str:
    return os.path.expanduser("~/.claude/projects/*/*.jsonl")


class ClaudeWatch:
    def _admit(self, path) -> bool:
        try:
            return self._may_hold_our_token(str(path), os.path.getmtime(path))
        except OSError:
            return False
