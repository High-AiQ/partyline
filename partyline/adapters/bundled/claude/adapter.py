"""Private Claude Code adapter; tails the CLI's JSONL transcript."""

import asyncio
import glob
import json
import os
import shlex
import sys
import weakref

from partyline.adapters.base import Adapter as BaseAdapter
from partyline.adapters.events import watch_files
from partyline.adapters.bundled.claude.session import ClaudeSession
from partyline.adapters.bundled.claude.watch import ClaudeWatch, projects_glob
from partyline.adapters.compaction import compaction_hooks_declared, is_compaction_record
from partyline.adapters.session_seed import seed_claude_home
from partyline.adapters.session_pin import pinned_session
from partyline.mcp_attach import claude_command


class PartylineAdapter(ClaudeWatch, ClaudeSession, BaseAdapter):
    kind = "claude"
    jsonl_paste_receipts = True

    # Transcripts currently being tailed, mapped to their claimant, so two
    # adapters cannot follow one session. No lock: a claim token names one
    # activation, so it is read and written without awaiting in between.
    # Claimants are held weakly: a CLI that quit on its own is dropped without
    # ``stop()``, and must neither block a successor nor be kept alive here.
    _CLAIMED: "weakref.WeakValueDictionary[str, PartylineAdapter]" = (
        weakref.WeakValueDictionary())

    _transcript: str = ""

    def spawn_env(self):
        env = {}
        if home := seed_claude_home():
            env['CLAUDE_CONFIG_DIR'] = home
        if limit := int(self.att.get("auto_compact_tokens") or 0):
            env['CLAUDE_CODE_AUTO_COMPACT_WINDOW'] = str(limit)  # plain token count
        return env

    def mcp_argv(self, cmd: list[str]) -> list[str]:
        return claude_command(cmd, self.att)

    async def stop(self):
        if self._CLAIMED.get(self._transcript) is self:
            del self._CLAIMED[self._transcript]
        await super().stop()

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or ["claude"]
        if self.resume:
            cmd += ["--resume", pinned_session(self.att)]
        elif "--session-id" not in cmd:
            cmd += ["--session-id", pinned_session(self.att)]
        hook_url = self.att.get("hook_url")
        if hook_url and "--settings" not in cmd:
            settings = self._hook_settings(hook_url, compaction_hooks_declared(self.att))
            cmd += ["--settings", json.dumps(settings)]
        if not self.resume:
            # Claude snapshots this system prompt with the session and reapplies
            # it on resume. Keep the user-facing briefing for after startup dialogs.
            if "--append-system-prompt" in cmd:
                position = cmd.index("--append-system-prompt") + 1
                cmd[position] += "\n\n" + self.briefing()
            else:
                cmd += ["--append-system-prompt", self.briefing()]
        return self.mcp_argv(cmd)

    @staticmethod
    def _hook_settings(hook_url: str, with_compaction: bool = False) -> dict:
        """Process-scoped harness receipts plus the existing attention hook.

        ``UserPromptSubmit`` / ``Stop`` are the paired turn boundaries. The
        same curl posts the event JSON; ``SubagentStop`` is omitted so a child
        finishing cannot clear the parent jack. With the ``compaction_hooks``
        capability, ``PreCompact`` (matchers auto and manual) reports every
        compaction to the same endpoint, and ``SessionStart(compact)`` GETs
        the re-briefing: its stdout is appended to the model's context, so
        that hook stays a printing command curl on every platform — an http
        hook cannot add anything to context.
        """
        curl = (f"curl -s -m 5 -X POST {shlex.quote(hook_url)}"
                " -H 'Content-Type: application/json' --data-binary @-")
        handler = [{"hooks": [{"type": "command", "command": curl}]}]
        if sys.platform == 'win32':
            handler = [{"hooks": [{"type": "http", "url": hook_url, "timeout": 5}]}]
        hooks = {
            "Notification": handler,
            "UserPromptSubmit": handler,
            "Stop": handler,
        }
        if with_compaction:
            hooks["PreCompact"] = [
                {"matcher": "auto", "hooks": handler[0]["hooks"]},
                {"matcher": "manual", "hooks": handler[0]["hooks"]},
            ]
            # SessionStart(compact) prints the re-briefing to stdout, and the
            # harness folds that into context — a printing curl everywhere.
            rebrief = f"curl -s -m 5 {shlex.quote(hook_url + '/rebrief')}"
            hooks["SessionStart"] = [
                {"matcher": "compact", "hooks": [{"type": "command", "command": rebrief}]}]
        return {"hooks": hooks}

    def _written_since_spawn(self, path: str) -> bool:
        """Whether anything has written this file since this process started.

        Weak evidence, and the only kind available to a resumed attachment
        before its first wake: it says *someone* wrote the file, not that we
        did. A pinned file untouched since we spawned belongs to a process
        that is no longer writing it, and tailing it would be mute but
        reported ready. No allowance is taken — mtime and ``spawned_at`` are
        one host clock, so slack only lets the previous process's last write
        vouch for the new one.
        """
        try:
            return os.path.getmtime(path) >= self.spawned_at
        except OSError:
            return False

    def _claimed_by_another(self, path: str) -> bool:
        """Whether a live adapter other than this one is tailing ``path``."""
        owner = self._CLAIMED.get(path)
        return owner is not None and owner is not self and owner.alive()

    def _find_transcript(self) -> str | None:
        """The session carrying this activation's token, pinned or not.

        ``build_command`` pins the session id so the transcript's name is
        known before the CLI writes it — but the process partyline spawns is
        not always the process that runs. A ``claude update`` at attach makes
        the CLI re-exec itself with a normalized argv, dropping the pin and
        opening a randomly-named session instead (2026-08-24: opus attached
        this way and could not speak for 42 minutes).

        The pinned name is searched first for speed, never for authority:
        content proof decides everywhere, so a leftover session cannot win by
        being called the right thing or by having been touched at the right
        moment. Only a resumed attachment, which has nothing to match until
        its first wake, falls back to the pinned file on the weaker evidence
        that something has written it since we spawned — and only after no
        token-bearing session was found, so proof outranks the fallback
        rather than being skipped by it.
        """
        pinned = next(iter(glob.glob(self.transcript_glob())), "")
        sweep = glob.glob(projects_glob())
        seen = set()
        for path in ([pinned] if pinned else []) + sweep:
            if path in seen:
                continue
            seen.add(path)
            # A claim never outranks proof, so none is consulted here. The
            # pinned path is named after the attachment and so is stable
            # across activations: re-activate the same attachment and the new
            # CLI writes its new nonce into the very path an exited
            # activation claimed, and a claim that outlived its claimant
            # would mute exactly the case this adapter recovers. Releasing it
            # on the claimant's death would need a liveness registry —
            # something to get wrong, and twice already had been. Carrying
            # our token is the same evidence and needs nothing, and two live
            # adapters can never collide because no two activations share a
            # token.
            if self._recorded_our_token(path):
                self._CLAIMED[path] = self
                self._transcript = path
                self.narrow_watch(path)
                # The token in the file is this activation's proof; speech
                # may flow. The pinned fallback below cannot prove, so it
                # leaves the gate closed until a wake records the token.
                self._mark_claim_proven()
                return path
        # The one branch with no proof behind it is the only one a claim can
        # usefully guard.
        if (self.resume and pinned and not self._claimed_by_another(pinned)
                and self._written_since_spawn(pinned)):
            self._CLAIMED[pinned] = self
            self._transcript = pinned
            self.narrow_watch(pinned)
            return pinned
        return None

    async def _await_transcript(self) -> str | None:
        """Wait for this process's transcript creation, or for CLI exit.

        Giving up here used to end the adapter while the CLI kept running:
        the attachment stayed live and mentionable, its cursor kept
        advancing, and nothing it said could reach the line again. A CLI that
        is slow, updating, or re-execing is not a CLI that will never speak,
        so the 45s mark warns once and the search goes on for as long as the
        process is alive. Silence is never a verdict.
        """
        started = self.event_time()
        waited, warned = 0.0, False
        while self.alive():
            waited = self.event_time() - started
            if path := self._find_transcript():
                self._report_cli_session(path)
                if warned:
                    await self.post(
                        "system", "system",
                        f"{self.att['name']}: transcript found after "
                        f"{int(waited)}s — the line is reachable again.",
                    )
                return path
            if waited >= 45.0 and not warned:
                warned = True
                await self.post(
                    "system", "system",
                    f"{self.att['name']}: no transcript after 45s — still watching, "
                    f"but nothing it says can reach the line until one appears. "
                    f"If this persists, run the CLI manually once in "
                    f"{self.att['cwd']}, then re-attach.",
                )
            await self.wait_for_change(None if warned else max(0, 45.0 - waited))
        return None

    @watch_files(lambda self: [self.transcript_glob(), projects_glob()], admit=ClaudeWatch._admit)
    async def _run(self):
        await asyncio.sleep(5.0)
        if not self.alive():
            return
        # No cross-adapter lock. Serializing discovery meant one CLI stuck on
        # a login or trust prompt held every later attachment's briefing
        # hostage for as long as it lived, and the claim token removes the
        # reason for it: no two adapters can match the same transcript.
        if not self.resume:
            if not await self.send_startup_briefing():
                return
        else:
            # A resumed transcript may already prove this activation owns the
            # session. Check before looking at the screen so an old dialog
            # phrase quoted in terminal chat cannot hold queued wakes.
            path = self._find_transcript()
            if not await self.release_startup_delivery():
                return
        if not self.resume:
            path = None
        if path is None:
            path = await self._await_transcript()
        if path is None:
            return

        self._report_cli_session(path)
        seen: set[str] = set()

        async def handle(obj):
            if is_compaction_record("claude", obj):
                return
            if obj.get("isSidechain") or obj.get("type") != "assistant" or self.harness_filler(obj):
                return
            if not self._fresh(obj.get("timestamp")):
                return
            content = (obj.get("message") or {}).get("content") or []
            if any(
                isinstance(block, dict) and block.get("type") == "tool_use"
                for block in content
            ):
                return
            uid = obj.get("uuid")
            if uid and uid in seen:
                return
            if uid:
                seen.add(uid)
            texts = [block.get("text", "") for block in content
                     if isinstance(block, dict) and block.get("type") == "text"]
            body = "\n\n".join(text for text in texts if text.strip())
            if body.strip():
                await self.post(self.att["name"], "agent", body)

        await self._tail_jsonl(path, handle)
