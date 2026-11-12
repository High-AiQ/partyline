"""Claude session identity and durable transcript discovery."""

import glob
import os


def pinned_transcript_glob(att: dict) -> str:
    home = os.path.expanduser(os.environ.get('CLAUDE_CONFIG_DIR', '~/.claude'))
    return os.path.join(home, 'projects', '*', f"{glob.escape(att['id'])}.jsonl")


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
