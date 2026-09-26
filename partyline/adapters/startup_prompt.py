"""Keep startup dialogs from receiving a process briefing as their answer."""

from __future__ import annotations

import asyncio
import re


class StartupPromptGuard:
    """Serialize the first paste behind any configured terminal dialog."""

    def _startup_prompt_init(self) -> None:
        self._startup_prompt_delivery = asyncio.Event()
        self._startup_paste_lock = asyncio.Lock()
        self._startup_prompt_result: bool | None = None
        self._startup_prompt_began = False
        if not self._startup_prompts():
            self._startup_prompt_result = True
            self._startup_prompt_delivery.set()

    def _startup_prompts(self) -> dict[str, list[str]]:
        metadata = self.att.get("adapter_metadata") or {}
        prompts = metadata.get("startup_prompts") or {}
        return {
            str(name): [str(phrase) for phrase in phrases]
            for name, phrases in prompts.items()
            if isinstance(phrases, list)
        }

    def startup_prompt(self) -> str | None:
        lines = [" ".join(line.casefold().split())
                 for line in self.screen_text().splitlines()]
        for name, patterns in self._startup_prompts().items():
            matches = []
            for pattern in patterns:
                try:
                    regex = re.compile(pattern)
                except re.error:
                    matches = []
                    break
                matches.append([index for index, line in enumerate(lines)
                                if regex.search(line)])
            if matches and _distinct_line_matches(matches):
                return name
        return None

    def mark_startup_prompt_began(self) -> None:
        """Stop watching the startup screen once the process starts a turn."""
        self._startup_prompt_began = True

    async def send_startup_briefing(self) -> bool:
        """Wait for a person to dismiss a startup dialog, then paste once."""
        async with self._startup_paste_lock:
            if not await self._wait_for_startup_prompt():
                return False
            await self.send_keys(self.briefing())
            if self._startup_prompt_result is None:
                self._startup_prompt_result = True
                self._startup_prompt_delivery.set()
            return True

    async def release_startup_delivery(self) -> bool:
        """Open queued wakes once a resumed CLI's startup dialog is gone."""
        if self._startup_prompt_delivery.is_set():
            return self._startup_prompt_result is True
        async with self._startup_paste_lock:
            if not await self._wait_for_startup_prompt():
                return False
            self._startup_prompt_result = True
            self._startup_prompt_delivery.set()
            return True

    async def _wait_for_startup_prompt(self) -> bool:
        reported = None
        while self._startup_prompt_polling_allowed() and (prompt := self.startup_prompt()):
            if self._startup_prompt_result is False or self._stopping or not self.alive():
                return False
            if prompt != reported:
                attention = self.att.get("startup_attention")
                if attention:
                    await attention(prompt.replace("_", " "))
                reported = prompt
            await asyncio.sleep(1.0)
        return not self._stopping and self._startup_prompt_result is not False and self.alive()

    def _startup_prompt_polling_allowed(self) -> bool:
        return not (self._claim_proven or self._startup_prompt_began)

    def abort_startup_prompt(self) -> None:
        """Unblock startup waiters after exit without claiming any delivery."""
        self._startup_prompt_result = False
        self._startup_prompt_delivery.set()

    async def wait_startup_delivery(self) -> bool:
        """Hold wakes queued while the initial briefing is blocked by a dialog."""
        await self._startup_prompt_delivery.wait()
        async with self._startup_paste_lock:
            return self._startup_prompt_result is True


def _distinct_line_matches(matches: list[list[int]]) -> bool:
    """Whether every required pattern can claim a different screen line."""
    assigned: set[int] = set()

    def assign(pattern_index: int) -> bool:
        if pattern_index == len(matches):
            return True
        for line_index in matches[pattern_index]:
            if line_index in assigned:
                continue
            assigned.add(line_index)
            if assign(pattern_index + 1):
                return True
            assigned.remove(line_index)
        return False

    return assign(0)
