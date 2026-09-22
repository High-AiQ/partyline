"""Per-activation identity: environment and receipts that name one run.

An activation is the process this server spawned for one attachment, and
several facts belong to it alone: extra environment that isolates the
CLI's state per attachment, the freshness boundary that separates a
resumed process's new records from replayed history, and the staged
startup-delivery receipt. They live in this mixin so the base runtime
stays small and every adapter inherits the same notions.
"""

from __future__ import annotations


class Activation:
    """Hooks and state scoped to one running activation of an adapter."""

    def spawn_env(self) -> dict[str, str]:
        """Extra environment for the spawned process, by activation.

        Adapters that isolate per-attachment CLI state — a vendor home of
        their own — declare it here instead of editing ``os.environ`` or
        duplicating the pty spawn in ``start()``.
        """
        return {}

    def _fresh(self, iso_ts) -> bool:
        """Return whether a transcript record belongs to this running process."""
        if not self.att.get("resume"):
            return True
        if not iso_ts:
            return False
        try:
            from datetime import datetime
            timestamp = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return False
        return timestamp >= self.spawned_at - 5

    def mark_startup_delivery_received(self) -> None:
        """A staged startup digest appeared as structured process input."""
        if self._startup_delivery_result is None and not self._stopping:
            self._startup_delivery_result = True
            self._startup_delivery.set()

    async def wait_startup_delivery_received(self) -> bool:
        """Wait for structured receipt, or for the process to exit first."""
        await self._startup_delivery.wait()
        return self._startup_delivery_result is True
