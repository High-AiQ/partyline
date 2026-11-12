"""Which Claude transcripts the adapter holds descriptors for, and when it lets go.

kqueue holds one descriptor per exact file, and a directory vnode does not report
appends to its existing children. A Mac with a long Claude history has thousands of
old transcripts, and every live Claude adapter used to hold all of them for its whole
life. Two facts bound that:

* While searching, a transcript can hold this activation's token only if the search
  would read it (``ClaudeSession._may_hold_our_token``: the pinned name, or written
  since spawn). The watch admits those files and every project directory, so a new
  file (a re-exec's randomly named session, a first pinned write) is reported by its
  directory and gets its own descriptor then; a search that finds nothing re-plans, so
  a file that has just become recent is held for its next append.
* An append to an *old* file is reported only to a descriptor already holding it, so the
  existing sessions a CLI started here can continue (the newest ``OLD_SESSIONS_HELD`` in
  this working directory's own project directory) are held too. Beyond that set the scan
  is authoritative on every wake, and a wake that finds nothing is followed by one later
  look (`_await_transcript`; it arms nothing). A session outside both sets that takes our
  token with the CLI silent on its pty is found on the next wake of any kind.
* Once a transcript is claimed nothing else is read, so the watch narrows to that file.
"""

from pathlib import Path
import os
import re


def projects_glob() -> str:
    return os.path.expanduser("~/.claude/projects/*/*.jsonl")


OLD_SESSIONS_HELD = 64  # the newest of the working directory's own older sessions


def project_name(cwd: str) -> str:
    """The project directory Claude Code files a working directory's sessions under."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


class ClaudeWatch:
    def _admit(self, path) -> bool:
        path = Path(path)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return False
        return self._may_hold_our_token(str(path), mtime) or path.name in self._older_sessions(path.parent)

    def _older_sessions(self, directory: Path) -> frozenset:
        """Names of this working directory's newest sessions that predate this process.

        These are the existing sessions a CLI started here can continue, and an append to
        an old file is reported only to a descriptor already holding it. The set is
        re-ranked only when the directory itself changes.
        """
        if directory.name != project_name(self.att["cwd"]):
            return frozenset()
        cache = self.__dict__.setdefault("_older_cache", {})
        try:
            stamp = os.stat(directory).st_mtime_ns
            if cache.get(directory, (None,))[0] != stamp:
                with os.scandir(directory) as stream:
                    older = [(entry.stat().st_mtime, entry.name) for entry in stream
                             if entry.name.endswith(".jsonl")
                             and not self._may_hold_our_token(entry.name, entry.stat().st_mtime)]
                cache[directory] = (stamp, frozenset(
                    name for _, name in sorted(older, reverse=True)[:OLD_SESSIONS_HELD]))
        except OSError:
            return frozenset()
        return cache[directory][1]

    def _watch_what_matters_now(self) -> None:
        """A search that found nothing: hold any file it has become possible to find in."""
        if self._watch_events is not None and hasattr(self._watch_events, "arm"):
            self._watch_events.arm()
