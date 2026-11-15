"""One update attempt per connection or published-release event; never a timer-based retry."""
import asyncio
import contextlib
import platform
import os
import uuid
import threading

from websockets.exceptions import ConnectionClosed

from . import __version__
from .config import save_config
from .update_download import prepare
from .update_preferences import enabled, read, set_enabled, failed_version
from . import update_recovery as recovery
from . import update_supervisor as supervisor
from .update_cleanup import installer as remove_installer
from . import update_timing as budget

PAUSED = {"status": "paused", "reason": "helper updating",
          "retry_hint": "Wait for window access resumed, then read fresh state before retrying an action."}


class Updates:
    def __init__(self, session, fetch=prepare, launch=supervisor.launch, exit_process=os._exit):
        self.session, self.fetch, self.launch = session, fetch, launch
        self.exit_process = exit_process
        self.task = None
        self.recovering = recovery.path().exists()
        self.installing = False
        self.ack = None
        self.latest = None
        self.enabled = enabled()
        self.session.status.auto_update = self.enabled

    async def paused_request(self, message):
        replies = {"read_window_elements": "window_elements",
                   "window_element_action": "window_element_result",
                   "window_eval": "window_element_result", "window_click": "window_element_result",
                   "snapshot_window": "window_snapshot", "action": "action_result",
                   "snap": "error", "get_preview": "error", "start_share": "share_declined",
                   "control_request": "control_declined", "screen_windows": "screen_windows_result",
                   "attach_window": "attach_window_result"}
        kind = message["type"]
        if not self.installing or kind not in replies:
            return False
        await self.session.send(replies[kind], request_id=message.get("request_id"),
                                share_id=message.get("share_id"), **PAUSED)
        return True

    async def setting(self, value):
        self.enabled = set_enabled(value)
        self.session.status.auto_update = self.enabled
        self.session.status.changed()
        await self.session.send("auto_update_changed", enabled=self.enabled)
        if self.enabled and self.latest:
            self.offer(self.latest)

    def offer(self, update):
        self.latest = update
        self.session.status.set_update(update)
        if (self.enabled and update.get("version") != read().get("failed_update")
                and platform.system() == "Windows" and not self.installing and not self.recovering
                and (self.task is None or self.task.done())):
            self.task = asyncio.create_task(self.attempt(update))

    async def download(self, update):
        cancelled, downloaded = threading.Event(), None
        def work():
            nonlocal downloaded
            downloaded = self.fetch(update, __version__)
            if cancelled.is_set():
                remove_installer(downloaded)
                return None
            return downloaded
        try:
            return await asyncio.to_thread(work)
        except asyncio.CancelledError:
            cancelled.set()
            remove_installer(downloaded)
            raise

    async def attempt(self, update):
        session = self.session
        installer, active = None, []
        try:
            installer = await self.download(update)
            if installer is None or not self.enabled:
                remove_installer(installer)
                return
            version = update["version"]
            self.installing = True
            session.status.attention(f"Installing Partyline Helper {version}; window access is paused")
            self.ack = asyncio.get_running_loop().create_future()
            await session.send("helper_updating", version=version)
            await asyncio.wait_for(self.ack, budget.ACK)
            data = recovery.snapshot(session, version)
            accesses = [session.window, *(entry["access"] for entry in session.windows.grants.values())]
            active = [(access, access.grant) for access in accesses if not access.gate.revoked.is_set()]
            await recovery.quiesce(session)
            for entry in session.windows.grants.values():
                entry["access"].preserve_update = True
            session.window_access_audit.append("", "local", "helper_update", "helper", version, "installing")
            # Persist everything before starting a supervisor that could outlive this helper.
            data["event"] = "Local\\PartylineHelperUpdate-" + uuid.uuid4().hex
            save_config(data, recovery.path())
            self.launch(installer, version, name=data["event"])
            # no-poll (b): a single exit deadline also ends abandoned COM/picker executor threads.
            self.exit_timer = asyncio.get_running_loop().call_later(budget.EXIT, self.exit_process, 0)
            session.status.request_quit()
        except (OSError, ValueError, TimeoutError, RuntimeError, asyncio.CancelledError) as exc:
            was_installing, self.installing = self.installing, False
            recovery.path().unlink(missing_ok=True)
            remove_installer(installer)
            if was_installing or isinstance(exc, (ValueError, RuntimeError)):
                with contextlib.suppress(OSError):
                    failed_version(update.get("version"))
            with contextlib.suppress(OSError):
                session.window_access_audit.append("", "local", "helper_update", "helper", "", "failed")
            session.status.attention(f"Partyline Helper update failed: {exc}")
            for entry in session.windows.grants.values():
                entry["access"].preserve_update = False
            for access, grant in active:
                if access.grant is grant and grant and not await access.check(grant):
                    access.gate.grant()
            with contextlib.suppress(ConnectionClosed):
                await session.send("helper_update_failed")
            if isinstance(exc, asyncio.CancelledError):
                raise

    async def restore(self, grants):
        data = read(recovery.path())
        failed = supervisor.result().get("failed") is True
        if failed:
            failed_version(data.get("version"))
        restored = await recovery.restore(self.session, grants, data)
        self.recovered = data
        await self.session.send("helper_update_restored", grants=restored, failed=failed)

    def finished(self):
        data = getattr(self, "recovered", None)
        if data is None:
            return
        self.recovered = None
        self.recovering = False
        failed = supervisor.result().get("failed") is True
        self.session.status.attention("Partyline Helper update failed; previous version restored" if failed
                                      else f"Partyline Helper updated to {__version__}")
        self.session.window_access_audit.append("", "local", "helper_update", "helper", __version__,
                                                "rolled back" if failed else "installed")
        if data.get("event") and not failed:
            supervisor.signal(data["event"])
        recovery.path().unlink(missing_ok=True)
        (recovery.path().parent / "updates" / "result.json").unlink(missing_ok=True)
        from .update_prompts import replay
        self.prompt_task = asyncio.create_task(replay(data.get("prompts", []), session=self.session))
        if data.get("choose_window"):
            self.session.windows.spawn(self.session.windows.choose())

    async def close(self):
        tasks = [task for task in (self.task, getattr(self, "restore_task", None),
                                   getattr(self, "prompt_task", None))
                 if task and task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def message(self, message):
        kind = message["type"]
        if kind in ("helper_release_published", "ping"):
            if isinstance(message.get("helper_update"), dict):
                self.offer(message["helper_update"])
            if kind == "ping":
                await self.session.send("pong")
        elif kind == "set_auto_update":
            await self.setting(message["enabled"] is True)
        elif kind == "helper_update_paused":
            if self.ack and not self.ack.done():
                self.ack.set_result(True)
        elif kind == "helper_update_restore":
            self.restore_task = asyncio.create_task(self.restore(message["grants"]))
        elif kind == "helper_update_finished":
            self.finished()


MESSAGES = {"helper_release_published", "set_auto_update", "helper_update_paused",
            "helper_update_restore", "helper_update_finished", "ping"}
