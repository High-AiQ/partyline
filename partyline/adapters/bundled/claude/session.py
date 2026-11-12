"""Claude session identity and durable transcript discovery."""

import glob
import json
import os

from partyline.adapters.session_pin import pinned_session
from partyline.adapters.transcript_scan import scan_lines


def pinned_transcript_glob(att: dict) -> str:
    home = os.path.expanduser(os.environ.get('CLAUDE_CONFIG_DIR', '~/.claude'))
    return os.path.join(home, 'projects', '*', f"{glob.escape(pinned_session(att))}.jsonl")


class ClaudeSession:
    """Share pinned-session lookup between activation and task restart."""

    _reported_session_path = ""

    @classmethod
    def session_exists(cls, att: dict) -> bool:
        return any(os.path.isfile(path) for path in glob.glob(pinned_transcript_glob(att)))

    @staticmethod
    def harness_filler(record: dict) -> bool:
        """An assistant line the CLI wrote itself, not the model.

        Resuming after an interrupted turn, Claude Code records a synthetic
        "No response requested." reply. It is nobody's speech, and relaying it
        put a meaningless line in the room on every such resume. A synthetic
        API error stays: that one tells people why the process went quiet.
        """
        message = record.get("message") or {}
        return message.get("model") == "<synthetic>" and not record.get("isApiErrorMessage")

    def transcript_glob(self) -> str:
        return pinned_transcript_glob(self.att)

    def _report_cli_session(self, path: str):
        if self.on_cli_session and path != self._reported_session_path:
            self.on_cli_session(os.path.splitext(os.path.basename(path))[0])
            self._reported_session_path = path

    def _recorded_our_token(self, path: str) -> bool:
        """Whether this transcript recorded the token we pasted into our pty.

        Nothing else writes this pty, and no other attachment pastes this
        token, so a match is proof rather than inference — and it holds
        however the sessions interleave, whatever order the scan runs in, and
        however many attachments share a working directory. An ``@all`` wake
        that reaches two resumed attachments carries a different token into
        each, which is what digest text alone could not do.

        A file unchanged since it was last read holds what it held then, and a
        stranger's session not written since this process started cannot hold
        its token. Without those two tests, every write to any session on the
        machine re-read every transcript there, on the event loop, for as long
        as the search went on. The session named after this attachment is read
        whatever its age: proof beats the clock for the one file that is cheap.
        """
        try:
            stat = os.stat(path)
        except OSError:
            return False
        unmatched = self.__dict__.setdefault("_unmatched", {})
        stamp = (stat.st_mtime_ns, stat.st_size)
        named_ours = os.path.basename(path) == f"{pinned_session(self.att)}.jsonl"
        stale = not named_ours and stat.st_mtime < self.spawned_at - 2
        if stale or unmatched.get(path) == stamp:
            return False
        ours = self._token_record_is_ours(path)
        if ours is False:  # a file that could not be read was not searched: ask again
            unmatched[path] = stamp
        return bool(ours)

    def _token_record_is_ours(self, path: str) -> bool | None:
        try:
            for line in scan_lines(path):
                if self._claim_token not in line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") != "user":
                    continue
                content = (record.get("message") or {}).get("content")
                if isinstance(content, str) and self._claim_token in content:
                    # The token's own record names the directory; a leftover
                    # record from another directory earlier in a long
                    # session says nothing about who wrote the token.
                    return record.get("cwd") in (None, "", self.att["cwd"])
        except OSError:
            return None
        return False

