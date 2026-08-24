"""Private Claude Code adapter; tails the CLI's JSONL transcript."""

import asyncio
import glob
import json
import os
import shlex
import uuid

from partyline.adapters.base import Adapter as BaseAdapter
from partyline.adapters.compaction import is_compaction_record

# A session that recorded our claim token recorded it near the top, in the
# briefing or the first wake. Bounding the scan keeps a stranger's
# multi-megabyte transcript from being read in full on every poll.
SCAN_BYTES = 512 * 1024


class PartylineAdapter(BaseAdapter):
    kind = "claude"

    # Transcripts currently being tailed, so two adapters cannot follow one
    # session. It needs no lock: a claim token names exactly one activation,
    # so the set is read and written without awaiting in between.
    _CLAIMED: set[str] = set()

    _transcript: str = ""
    _nonce: str = ""

    @property
    def _claim_token(self) -> str:
        """The one string that names this activation and no other.

        Identity cannot be inferred — not from spawn order, session order, or
        any clock (review of #124 broke three such schemes). So it is stated
        instead: a token is pasted into this pty with the briefing and with
        every wake until a transcript is claimed, and the session that
        records it is ours by construction.

        The token is per-activation, not per-attachment. An attachment id is
        stable across resumes, so every transcript this attachment ever wrote
        still carries it — including the stale session a dropped pin left
        behind, which would then be adopted by the very search meant to
        replace it. A fresh nonce each time the adapter runs makes only this
        activation's own sessions eligible.
        """
        if not self._nonce:
            self._nonce = uuid.uuid4().hex[:12]
        return f"[partyline-claim: {self.att['id']}/{self._nonce}]"

    def briefing(self) -> str:
        return f"{super().briefing()}\n\n{self._claim_token}"

    def format_digest(self, messages: list[dict]) -> str:
        """A wake, carrying the claim token until a transcript is claimed.

        Once claimed the token stops being appended: it exists to name an
        unidentified session, and a wake is the agent's to read, not a place
        to leave bookkeeping lying around.
        """
        text = super().format_digest(messages)
        return text if self._transcript else f"{text}\n\n{self._claim_token}"

    async def stop(self):
        self._CLAIMED.discard(self._transcript)
        await super().stop()

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or ["claude"]
        if self.resume:
            cmd += ["--resume", self.att["id"]]
        elif "--session-id" not in cmd:
            cmd += ["--session-id", self.att["id"]]
        hook_url = self.att.get("hook_url")
        if hook_url and "--settings" not in cmd:
            cmd += ["--settings", json.dumps(self._hook_settings(hook_url))]
        return cmd

    @staticmethod
    def _hook_settings(hook_url: str) -> dict:
        """Process-scoped harness receipts plus the existing attention hook.

        ``UserPromptSubmit`` / ``Stop`` are the paired turn boundaries. The
        same curl posts the event JSON; ``SubagentStop`` is omitted so a child
        finishing cannot clear the parent jack.
        """
        curl = (f"curl -s -m 5 -X POST {shlex.quote(hook_url)}"
                " -H 'Content-Type: application/json' --data-binary @-")
        handler = [{"hooks": [{"type": "command", "command": curl}]}]
        return {"hooks": {
            "Notification": handler,
            "UserPromptSubmit": handler,
            "Stop": handler,
        }}

    def transcript_glob(self) -> str:
        return os.path.expanduser(f"~/.claude/projects/*/{self.att['id']}.jsonl")

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

    def _recorded_our_token(self, path: str) -> bool:
        """Whether this transcript recorded the token we pasted into our pty.

        Nothing else writes this pty, and no other attachment pastes this
        token, so a match is proof rather than inference — and it holds
        however the sessions interleave, whatever order the scan runs in, and
        however many attachments share a working directory. An ``@all`` wake
        that reaches two resumed attachments carries a different token into
        each, which is what digest text alone could not do.
        """
        try:
            with open(path, encoding="utf-8", errors="replace") as file:
                scanned = 0
                for line in file:
                    scanned += len(line)
                    if scanned > SCAN_BYTES:
                        return False
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("cwd") and record["cwd"] != self.att["cwd"]:
                        return False
                    if record.get("type") != "user":
                        continue
                    content = (record.get("message") or {}).get("content")
                    if isinstance(content, str) and self._claim_token in content:
                        return True
        except OSError:
            return False
        return False

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
        sweep = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
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
                self._CLAIMED.add(path)
                self._transcript = path
                return path
        # The one branch with no proof behind it is the only one a claim can
        # usefully guard.
        if (self.resume and pinned and pinned not in self._CLAIMED
                and self._written_since_spawn(pinned)):
            self._CLAIMED.add(pinned)
            self._transcript = pinned
            return pinned
        return None

    async def _await_transcript(self) -> str | None:
        """Poll until this process's transcript appears, or the CLI dies.

        Giving up here used to end the adapter while the CLI kept running:
        the attachment stayed live and mentionable, its cursor kept
        advancing, and nothing it said could reach the line again. A CLI that
        is slow, updating, or re-execing is not a CLI that will never speak,
        so the 45s mark warns once and the search goes on for as long as the
        process is alive. Silence is never a verdict.
        """
        waited, warned = 0.0, False
        while self.alive():
            await asyncio.sleep(1.0)
            waited += 1.0
            if path := self._find_transcript():
                if warned:
                    await self.post(
                        "system", "system",
                        f"{self.att['name']}: transcript found after "
                        f"{int(waited)}s — the line is reachable again.",
                    )
                return path
            if self.resume:
                continue
            if waited in (12.0, 24.0):
                os.write(self.master, b"\r")
                await asyncio.sleep(1.0)
                await self.send_keys(self.briefing())
            elif waited > 45.0 and not warned:
                warned = True
                await self.post(
                    "system", "system",
                    f"{self.att['name']}: no transcript after 45s — still watching, "
                    f"but nothing it says can reach the line until one appears. "
                    f"If this persists, run the CLI manually once in "
                    f"{self.att['cwd']}, then re-attach.",
                )
        return None

    async def _run(self):
        await asyncio.sleep(5.0)
        if not self.alive():
            return
        # No cross-adapter lock. Serializing discovery meant one CLI stuck on
        # a login or trust prompt held every later attachment's briefing
        # hostage for as long as it lived, and the claim token removes the
        # reason for it: no two adapters can match the same transcript.
        if not self.resume:
            await self.send_keys(self.briefing())
        path = await self._await_transcript()
        if path is None:
            return

        seen: set[str] = set()

        async def handle(obj):
            if is_compaction_record("claude", obj):
                return
            if obj.get("isSidechain") or obj.get("type") != "assistant":
                return
            if not self._fresh(obj.get("timestamp")):
                return
            uid = obj.get("uuid")
            if uid and uid in seen:
                return
            if uid:
                seen.add(uid)
            content = (obj.get("message") or {}).get("content") or []
            texts = [block.get("text", "") for block in content
                     if isinstance(block, dict) and block.get("type") == "text"]
            body = "\n\n".join(text for text in texts if text.strip())
            if body.strip():
                await self.post(self.att["name"], "agent", body)

        await self._tail_jsonl(path, handle)
