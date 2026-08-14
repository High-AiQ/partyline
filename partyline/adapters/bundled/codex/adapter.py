"""Private Codex adapter; tails matching rollout JSONL events.

The rollout file is created lazily, on the first turn's flush rather than at TUI
boot, and it carries no id we chose — so a fresh attachment has to find it by
working directory and start time. Two TUIs launched in one directory seconds
apart are indistinguishable that way, so discovery is serialized by _DISCOVERY
and every resolved rollout is claimed in _CLAIMED. Without that, the second
attachment latches onto the first one's transcript and reposts its messages
under the wrong handle.
"""

import asyncio
import contextlib
import glob
import json
import os

from partyline.adapters.base import Adapter as BaseAdapter


def _item_text(item: dict) -> str:
    """Flatten a completed item's content parts into their concatenated text."""
    parts = item.get("content") or []
    return "".join(part.get("text") or "" for part in parts if isinstance(part, dict))


class PartylineAdapter(BaseAdapter):
    kind = "codex"

    _CLAIMED: set[str] = set()
    _DISCOVERY = asyncio.Lock()

    async def stop(self):
        self._CLAIMED.discard(getattr(self, "_rollout", "") or "")
        await super().stop()

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or ["codex"]
        if self.resume:
            cmd = [cmd[0], "resume", self.att["cli_session"], *cmd[1:]]
            if prompt := getattr(self, "_startup_prompt", ""):
                cmd.append(prompt)
        return cmd

    def stage_startup_delivery(self, messages: list[dict]) -> bool:
        """Make a continuation part of Codex's interactive resume command.

        Codex creates its resumed rollout lazily, so transcript readiness can
        take minutes. Pasting before then loses input. The CLI's positional
        PROMPT is accepted at process creation and avoids that TUI race.
        """
        if not self.resume or not messages:
            return False
        prompt = self.format_digest(messages)
        if not prompt.strip():
            return False
        self._startup_prompt = prompt
        # The startup prompt is the first real wake after a resume, so output
        # from this turn is no longer leftover speech from before the restart.
        self._silent_until_wake = False
        return True

    def _find_rollout(self) -> str | None:
        pattern = os.path.expanduser("~/.codex/sessions/**/rollout-*.jsonl")
        candidates = [path for path in glob.glob(pattern, recursive=True)
                      if os.path.getmtime(path) >= self.spawned_at - 2]
        for path in sorted(candidates, key=os.path.getmtime, reverse=True):
            if path in self._CLAIMED:
                continue  # another live attachment is already tailing it
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    meta = json.loads(fh.readline())
            except (OSError, json.JSONDecodeError):
                continue
            payload = meta.get("payload") or {}
            if meta.get("type") != "session_meta":
                continue
            if "subagent" in json.dumps(payload.get("source") or {}):
                continue
            if self.resume:
                # A resume forks a fresh rollout off the old session, so the
                # recorded id identifies it exactly — no directory guessing.
                prior = self.att.get("cli_session")
                if prior not in (payload.get("forked_from_id"),
                                 payload.get("session_id"), payload.get("id")):
                    continue
            elif payload.get("cwd") != self.att["cwd"]:
                continue
            self._CLAIMED.add(path)
            self._rollout = path
            return path
        return None

    async def _run(self):
        await asyncio.sleep(6.0)
        if not self.alive():
            return

        # One fresh attachment at a time, from briefing to resolved rollout.
        # Resumes match on the recorded session id instead, so they stay out of
        # the lock — their rollout may not appear for many minutes.
        path = None
        async with (contextlib.nullcontext() if self.resume else self._DISCOVERY):
            waited = 0.0
            if not self.resume:
                await self.send_keys(self.briefing())

            while path is None:
                await asyncio.sleep(1.0)
                waited += 1.0
                path = self._find_rollout()
                if path or not self.alive():
                    break
                if self.resume:
                    continue
                if waited in (20.0, 40.0):
                    os.write(self.master, b"\r")
                    await asyncio.sleep(1.0)
                    await self.send_keys(self.briefing())
                elif waited > 90.0:
                    await self.post(
                        "system", "system",
                        f"@{self.att['name']}: no rollout file after 90s — the CLI is probably "
                        f"on a login/trust/update screen. Run it manually once in "
                        f"{self.att['cwd']}, then re-attach.",
                    )
                    return
        if not path:
            return

        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                cli_session = (json.loads(fh.readline()).get("payload") or {}).get("id")
            if cli_session and self.on_cli_session:
                self.on_cli_session(cli_session)
        except (OSError, json.JSONDecodeError):
            pass

        async def handle(obj):
            if obj.get("type") != "event_msg" or not self._fresh(obj.get("timestamp")):
                return
            payload = obj.get("payload") or {}
            user_text = agent_text = None
            if payload.get("type") == "user_message":
                user_text = payload.get("message") or ""
            elif payload.get("type") == "agent_message":
                agent_text = payload.get("message") or ""
            elif payload.get("type") == "item_completed":
                # Newer Codex builds stopped writing user_message/agent_message
                # events; speech now arrives only as completed items. Both
                # vocabularies stay readable because the CLI on the other side
                # of the pty is whatever version happens to be installed.
                # Commentary-phase items post too: they are how Codex speaks
                # before and during work — acknowledgments, progress notes —
                # and the briefing promises that everything an agent writes
                # reaches the line. Filtering them made an agent's deliberate
                # "starting on it" updates vanish while it believed it had
                # posted them.
                item = payload.get("item") or {}
                if item.get("type") == "UserMessage":
                    user_text = _item_text(item)
                elif item.get("type") == "AgentMessage":
                    agent_text = _item_text(item)
            if user_text is not None and getattr(self, "_startup_prompt", "") in user_text:
                self.mark_startup_delivery_received()
            if agent_text and agent_text.strip():
                await self.post(self.att["name"], "agent", agent_text)

        await self._tail_jsonl(path, handle)
