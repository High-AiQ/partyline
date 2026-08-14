"""Private Claude Code adapter; tails the CLI's JSONL transcript."""

import asyncio
import glob
import json
import os
import shlex

from partyline.adapters.base import Adapter as BaseAdapter


class PartylineAdapter(BaseAdapter):
    kind = "claude"

    def build_command(self) -> list[str]:
        cmd = list(self.att["command"]) or ["claude"]
        if self.resume:
            cmd += ["--resume", self.att["id"]]
        elif "--session-id" not in cmd:
            cmd += ["--session-id", self.att["id"]]
        hook_url = self.att.get("hook_url")
        if hook_url and "--settings" not in cmd:
            curl = (f"curl -s -m 5 -X POST {shlex.quote(hook_url)}"
                    " -H 'Content-Type: application/json' --data-binary @-")
            settings = {"hooks": {"Notification": [{"hooks": [
                {"type": "command", "command": curl}
            ]}]}}
            cmd += ["--settings", json.dumps(settings)]
        return cmd

    def transcript_glob(self) -> str:
        return os.path.expanduser(f"~/.claude/projects/*/{self.att['id']}.jsonl")

    async def _run(self):
        await asyncio.sleep(5.0)
        if not self.alive():
            return
        if not self.resume:
            await self.send_keys(self.briefing())

        path, waited = None, 0.0
        while path is None:
            await asyncio.sleep(1.0)
            waited += 1.0
            hits = glob.glob(self.transcript_glob())
            if hits:
                path = hits[0]
            elif not self.alive():
                return
            elif self.resume:
                continue
            elif waited in (12.0, 24.0):
                os.write(self.master, b"\r")
                await asyncio.sleep(1.0)
                await self.send_keys(self.briefing())
            elif waited > 45.0:
                await self.post(
                    "system", "system",
                    f"@{self.att['name']}: no transcript after 45s; run the CLI manually "
                    f"once in {self.att['cwd']}, then re-attach.",
                )
                return

        seen: set[str] = set()

        async def handle(obj):
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
