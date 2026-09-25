"""Keep startup dialogs from receiving a process briefing as their answer."""

from __future__ import annotations

import asyncio


class StartupPromptGuard:
    """Serialize the first paste behind any configured terminal dialog."""

    def _startup_prompt_init(self) -> None:
        self._startup_prompt_delivery = asyncio.Event()
        self._startup_paste_lock = asyncio.Lock()
        self._startup_prompt_result: bool | None = None
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
        screen = self.screen_text().casefold()
        for name, phrases in self._startup_prompts().items():
            if any(phrase.casefold() in screen for phrase in phrases):
                return name
        return None

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
        while prompt := self.startup_prompt():
            if self._startup_prompt_result is False or self._stopping or not self.alive():
                return False
            if prompt != reported:
                attention = self.att.get("startup_attention")
                if attention:
                    await attention(prompt.replace("_", " "))
                reported = prompt
            await asyncio.sleep(1.0)
        return not self._stopping and self._startup_prompt_result is not False and self.alive()

    def abort_startup_prompt(self) -> None:
        """Unblock startup waiters after exit without claiming any delivery."""
        self._startup_prompt_result = False
        self._startup_prompt_delivery.set()

    async def wait_startup_delivery(self) -> bool:
        """Hold wakes queued while the initial briefing is blocked by a dialog."""
        await self._startup_prompt_delivery.wait()
        async with self._startup_paste_lock:
            return self._startup_prompt_result is True
