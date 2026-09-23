"""Private Codex adapter; tails matching rollout JSONL events.

Each attachment runs Codex with a ``CODEX_HOME`` of its own under
``~/.partyline/sessions/codex/<attachment-id>``, seeded with the user's
auth and config: the CLI creates every other file it needs there (verified
against codex-cli 0.156), and its rollouts land in a directory no other
attachment writes. A resume links the prior activation's rollout into the
same home so ``codex resume <id>`` resolves it there.

Isolation is the fence; the claim token is the proof. The briefing and
every wake carry ``[partyline-claim: <attachment>/<nonce>]``, and a
rollout is adopted only once it records that token — the paste only this
pty receives — so even a shared sessions directory cannot pair two
same-directory attachments by scan order (the 2026-09-22 write-fence
incident), and the shared tail refuses any file carrying another
attachment's marker.

A resumed turn is not a new rollout (verified against codex-cli 0.156):
``codex resume`` appends the turn in place and projects it into
``thread_history_1.sqlite`` under ``CODEX_HOME``. Resume therefore relays
from that paginated store first (``thread_history.py``), the same way the
opencode adapter tails its session db, and falls back to the rollout tail
only when the store never appears.
"""

import asyncio
import glob
import json
import os

from partyline.adapters.base import Adapter as BaseAdapter
from partyline.fence import manifest_write_paths
from partyline.adapters.bundled.codex.thread_history import tail_thread_history
from partyline.adapters.compaction import is_compaction_record
from partyline.adapters.receipts import BEGAN, ENDED, receipt

HOME_ROOT = os.path.expanduser("~/.partyline/sessions/codex")
SHARED_HOME = os.path.expanduser("~/.codex")
# Read-mostly entries shared from the user's own codex home. Everything
# else — sessions, history, the sqlite state — is created per attachment,
# so concurrent CLIs never write one file or share one wal.
SHARED = ("auth.json", "config.toml", "plugins", "skills")


def _item_text(item: dict) -> str:
    """Flatten a completed item's content parts into their concatenated text."""
    parts = item.get("content") or []
    return "".join(part.get("text") or "" for part in parts if isinstance(part, dict))


class PartylineAdapter(BaseAdapter):
    kind = "codex"

    def codex_home(self) -> str:
        """This attachment's private CODEX_HOME, created and seeded."""
        home = os.path.join(HOME_ROOT, self.att["id"])
        os.makedirs(os.path.join(home, "sessions"), exist_ok=True)
        for name in SHARED:
            link = os.path.join(home, name)
            if os.path.lexists(link):
                continue
            try:
                os.symlink(os.path.join(SHARED_HOME, name), link)
            except OSError:
                pass  # an entry the user does not have is not ours to invent
        if prior := self.att.get("cli_session"):
            self._link_prior_session(home, prior)
        return home

    def _link_prior_session(self, home: str, prior: str) -> None:
        """Make the recorded session resolvable inside this home.

        Sessions recorded before per-attachment homes still live in the
        shared tree; a symlink lets ``codex resume <id>`` find them while
        every new write stays inside this home.
        """
        shared_sessions = os.path.join(SHARED_HOME, "sessions")
        pattern = os.path.join(shared_sessions, "**", f"rollout-*{prior}.jsonl")
        for source in glob.glob(pattern, recursive=True):
            target = os.path.join(home, "sessions",
                                  os.path.relpath(source, shared_sessions))
            if os.path.lexists(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                os.symlink(source, target)
            except OSError:
                pass

    def spawn_env(self) -> dict[str, str]:
        return {"CODEX_HOME": getattr(self, "_home", "") or self.codex_home()}

    def write_paths(self) -> list[str]:
        # The per-attachment CODEX_HOME is where this activation's CLI
        # writes sessions, history, and state; the manifest cannot name it.
        return manifest_write_paths(self.att) + [self.codex_home()]

    async def start(self):
        self._home = self.codex_home()
        await super().start()

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
        """The rollout that records this activation's claim token.

        The home already keeps neighbours out; the token is the proof that
        what we adopted is this pty's session even if isolation ever fails
        — a rollout is only claimed once it has ingested a paste that only
        this activation makes, so two attachments can never pair wrong by
        scan order, and a rollout carrying another attachment's marker is
        skipped rather than adopted. A resume may additionally match by
        recorded lineage, which is exact content: the fork names the
        session it resumed.
        """
        home = getattr(self, "_home", "") or self.codex_home()
        pattern = os.path.join(home, "sessions", "**", "rollout-*.jsonl")
        candidates = []
        for path in glob.glob(pattern, recursive=True):
            # A resumed activation's linked prior session predates this
            # spawn; its lineage match below is exact, so the mtime bound
            # applies only to fresh attachments, where it bounds the scan.
            try:
                recent = self.resume or os.path.getmtime(path) >= self.spawned_at - 2
            except OSError:
                continue
            if recent:
                candidates.append(path)
        for path in sorted(candidates, key=os.path.getmtime, reverse=True):
            if self.foreign_claim(path):
                continue  # another attachment's pty wrote this one
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
                    if not self.recorded_claim(path):
                        continue
            elif payload.get("cwd") != self.att["cwd"]:
                continue
            elif not self.recorded_claim(path):
                continue
            self._rollout = path
            return path
        return None

    async def _run(self):
        await asyncio.sleep(6.0)
        if not self.alive():
            return

        # A resumed turn is projected into CODEX_HOME's thread-history db
        # rather than a fresh rollout. Prefer that store; the rollout tail
        # below stays the fresh-attach path and the resume fallback.
        if self.resume and (thread_id := self.att.get("cli_session")):
            home = getattr(self, "_home", "") or (
                self.codex_home() if self.att.get("id") else ""
            )
            if home and await tail_thread_history(self, home, thread_id):
                return

        # No cross-adapter lock: the claim token means no two adapters can
        # ever match the same rollout, and serializing discovery only ever
        # gagged later attachments behind one CLI stuck on a trust screen.
        waited = 0.0
        if not self.resume:
            await self.send_keys(self.briefing())

        while True:
            path = self._find_rollout()
            if path or not self.alive():
                break
            await asyncio.sleep(1.0)
            waited += 1.0
            if self.resume:
                continue
            if waited in (20.0, 40.0):
                os.write(self.master, b"\r")
                await asyncio.sleep(1.0)
                await self.send_keys(self.briefing())
            elif waited > 90.0:
                await self.post(
                    "system", "system",
                    f"{self.att['name']}: no rollout file after 90s — the CLI is probably "
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
            if is_compaction_record("codex", obj):
                return
            if obj.get("type") != "event_msg" or not self._fresh(obj.get("timestamp")):
                return
            payload = obj.get("payload") or {}
            # The rollout records the harness's own turn boundaries; presence
            # needs them to clear the working badge, and the freshness filter
            # above keeps a resume's backlog from replaying old ones.
            if payload.get("type") == "task_started":
                # A new task while one is open means the old one was aborted:
                # the rollout writes no terminator for it, so the superseding
                # start is its only deterministic end.
                if getattr(self, "_task_open", False):
                    await receipt(self.att, ENDED)
                self._task_open = True
                await receipt(self.att, BEGAN)
                return
            if payload.get("type") == "task_complete":
                self._task_open = False
                await receipt(self.att, ENDED)
                return
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
