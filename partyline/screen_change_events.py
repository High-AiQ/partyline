"""Per-window change versions and event-driven dependency waits."""
import asyncio


class ChangeEvents:
    def __init__(self):
        self.change_versions = {}
        self.change_notifications = {}

    def changed(self, grant_id):
        """Invalidate the grant's tree without resetting its stable ids, and wake dependency waits."""
        self.change_versions[grant_id] = self.change_versions.get(grant_id, 0) + 1
        event = self.change_notifications.setdefault(grant_id, asyncio.Event())
        event.set()
        self.change_notifications[grant_id] = asyncio.Event()

    def end_changes(self, grant_id):
        self.change_versions.pop(grant_id, None)
        if event := self.change_notifications.pop(grant_id, None):
            event.set()

    async def wait_changed(self, grant_id, version, delay):
        """One event-driven wait for a dependent condition, never a polling interval."""
        if self.change_versions.get(grant_id, 0) != version:
            return True
        event = self.change_notifications.setdefault(grant_id, asyncio.Event())
        if event.is_set() or self.change_versions.get(grant_id, 0) != version:
            return True
        try:
            async with asyncio.timeout(delay):
                await event.wait()
            return True
        except TimeoutError:
            return False
