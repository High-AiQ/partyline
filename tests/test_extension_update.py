"""An automatic update never chooses remote debugging while the extension reconnects by itself."""
import asyncio
import contextlib
import functools
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from partyline.file_events import file_events
from partyline_helper import chrome_operations, native_host
from partyline_helper.cdp_transport import CDPError
from partyline_helper.extension_transport import ExtensionTransport
from tests.cdp_fakes import Fixture
from tests.test_late_native_host import Extension


class Deadline:
    """An async context manager standing in for asyncio.timeout: the bound is a fake, never real time."""
    def __init__(self, seconds):
        self.seconds = seconds

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class UpdateSequenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        config = Path(self.root.name) / "helper.json"
        for target in ("partyline_helper.native_host.config_path", "partyline_helper.instance.config_path"):
            patcher = patch(target, return_value=config)
            patcher.start()
            self.addCleanup(patcher.stop)
        # Remote debugging is ON in Chrome, so any attempt to use it would be a real, observable prompt.
        for target in ("partyline_helper.cdp_transport.discover",):
            patcher = patch(target, return_value="ws://127.0.0.1:9222/devtools/browser/x")
            patcher.start()
            self.addCleanup(patcher.stop)
        self.remote = patch.object(chrome_operations, "BrowserConnection",
                                   side_effect=AssertionError("remote debugging was chosen"))
        self.remote.start()
        self.addCleanup(self.remote.stop)
        self.waits = 0

        @contextlib.asynccontextmanager
        async def silent(path):  # the endpoint file does not change during the read's brief wait
            async def wait():
                self.waits += 1
                raise TimeoutError
            yield type("Watcher", (), {"wait": staticmethod(wait)})
        patcher = patch.object(chrome_operations, "await_extension", functools.partial(
            chrome_operations.await_extension, events=silent, deadline=Deadline))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.hosts, self.armed, self.connected = [], asyncio.Event(), asyncio.Event()

    @contextlib.asynccontextmanager
    async def events(self, path):
        async with file_events(path) as watcher:
            self.armed.set()
            yield watcher

    async def start_host(self):
        extension = Extension()
        task = asyncio.create_task(native_host.run(extension.stdin, extension))
        self.hosts.append((extension, task))
        return extension, task

    async def new_helper(self):
        """A freshly started helper: its first transport comes from `preferred`, as in production."""
        f = Fixture()
        self.addAsyncCleanup(f.close)
        f.chrome.browser = f.browser = chrome_operations.preferred(f.chrome.report)
        f.chrome.auto_transport = True
        f.session.status.listeners.append(lambda _state: self.connected.set()
                                          if "extension connected" in f.session.status.chrome else None)
        return f

    async def update_sequence(self, orderly):
        # A running 1.6 host and extension, greeted by the old helper.
        extension, host = await self.start_host()
        await extension.until(lambda: len(extension.hellos) == 1)
        old = ExtensionTransport()
        self.assertTrue(await old.ensure())
        await extension.until(lambda: len(extension.hellos) == 2)
        await old.close()  # `stop` on the old helper
        extension.close()  # the installer replaces the host's files; Chrome closes its port
        await asyncio.wait_for(host, 5)
        if not orderly:  # a 1.6.x-style host was killed: its endpoint file stays, naming a dead process
            native_host.endpoint_path().write_text(json.dumps(
                {"port": 1, "token": "t" * 64, "pid": 2 ** 22 + 1, "version": "1.6.1"}))
        extension.stdin.close()
        self.assertIsNone(native_host.discover())
        # The new helper starts before the extension is back, and a person reads the page.
        f = await self.new_helper()
        self.assertIsInstance(f.chrome.browser, ExtensionTransport)  # the extension is known: never Allow
        for _ in range(3):
            self.assertIsNone(await f.chrome.read(f.access, {}, {}))
            self.assertIn("Partyline Chrome is reconnecting", f.chrome.reasons[f.access])
            self.assertEqual(f.chrome.browser.transport, "extension")
        self.assertEqual(self.waits, 1)  # only the first read of the outage waited, briefly
        # The worker's alarm reconnects: Chrome starts the new host, with no click anywhere.
        watch = asyncio.create_task(chrome_operations.watch_extension(f.chrome, self.events))
        self.addAsyncCleanup(lambda: asyncio.gather(watch, return_exceptions=True))
        await self.armed.wait()
        again, host = await self.start_host()
        await self.connected.wait()
        self.assertEqual(f.chrome.browser.state, "connected")
        self.assertEqual(f.chrome.browser.transport, "extension")
        self.assertEqual([h["helper_connected"] for h in again.hellos], [False, True])
        again.close()
        await asyncio.wait_for(host, 5)
        again.stdin.close()
        watch.cancel()

    async def test_stop_host_exit_new_helper_and_reconnect_never_use_remote_debugging(self):
        await self.update_sequence(orderly=True)

    async def test_a_host_that_dies_without_a_word_leaves_the_same_outcome(self):
        await self.update_sequence(orderly=False)

    async def test_a_new_helper_session_reattaches_to_a_host_and_extension_that_stayed_up(self):
        # The helper's server link drops (a session change, sleep) and its next session starts: the host and
        # Chrome's port are untouched, so the extension must be greeted again with no click and no new host.
        extension, host = await self.start_host()
        self.addCleanup(extension.stdin.close)
        self.addCleanup(extension.close)  # a failing test must not leave the host blocked on Chrome's pipe
        await extension.until(lambda: len(extension.hellos) == 1)
        first = await self.new_helper()
        self.assertTrue(await first.browser.ensure())
        await extension.until(lambda: len(extension.hellos) == 2)
        await asyncio.wait_for(first.chrome.close(), 5)
        second = await self.new_helper()
        self.assertTrue(await asyncio.wait_for(second.browser.ensure(), 5))
        await asyncio.wait_for(extension.until(
            lambda: [h["helper_connected"] for h in extension.hellos] == [False, True, True]), 5)
        self.assertEqual(second.browser.state, "connected")
        self.assertEqual(len(self.hosts), 1)  # the same host and Chrome port served both sessions
        extension.close()
        await asyncio.wait_for(host, 5)
        extension.stdin.close()

    async def test_a_host_still_up_after_a_refused_attempt_is_reached_by_the_next_read(self):
        extension, host = await self.start_host()
        self.addCleanup(extension.stdin.close)
        self.addCleanup(extension.close)
        await extension.until(lambda: len(extension.hellos) == 1)
        f = await self.new_helper()
        f.chrome.browser.state = "refused"  # a failed attempt left this behind; the endpoint never changes
        self.assertTrue(await f.chrome.browser.ensure())
        self.assertEqual(f.chrome.browser.state, "connected")
        extension.close()
        await asyncio.wait_for(host, 5)
        extension.stdin.close()

    async def test_an_extension_never_seen_keeps_remote_debugging_as_the_default(self):
        self.remote.stop()
        self.addCleanup(self.remote.start)
        self.assertNotIsInstance(chrome_operations.preferred(lambda *a: None), ExtensionTransport)
        native_host.endpoint_path().with_name("chrome-native.lock").write_text("")  # a host once ran
        self.assertIsInstance(chrome_operations.preferred(lambda *a: None), ExtensionTransport)


class AwaitExtensionTests(unittest.IsolatedAsyncioTestCase):
    """The brief wait: woken by the host's endpoint file, bounded by one deadline, once per outage."""
    def watcher(self, on_wait):
        @contextlib.asynccontextmanager
        async def events(path):
            async def wait():
                on_wait()
            yield type("Watcher", (), {"wait": staticmethod(wait)})
        return events

    async def test_the_hello_wakes_the_wait_and_a_refused_state_is_forgiven(self):
        browser = ExtensionTransport(discovery=lambda: None)
        browser.state = "refused"
        results = iter([False, True])

        async def ensure():
            self.assertEqual(browser.state, "not_enabled")
            return next(results)
        browser.ensure = ensure
        self.assertTrue(await chrome_operations.await_extension(
            browser, self.watcher(lambda: None), Deadline))
        self.assertTrue(browser.waited)

    async def test_a_failed_attempt_never_blocks_the_next_one_for_good_and_a_new_host_resets_the_gap(self):
        now = [100.0]
        browser = ExtensionTransport(discovery=lambda: {"port": 1, "token": "t"})
        browser.clock = lambda: now[0]
        browser.connector = AsyncMock(side_effect=CDPError("Chrome extension not connected"))
        self.assertFalse(await browser.ensure())  # the host was dying: connect failed
        self.assertEqual(browser.state, "refused")
        self.assertFalse(browser.can_attempt())  # a short gap protects reads from a stale host
        now[0] += 10
        self.assertTrue(browser.can_attempt())  # ...and never for good, with no file event or retry request
        self.assertFalse(await browser.ensure())
        self.assertEqual(browser.state, "refused")
        browser.new_host()  # a host rewrote its endpoint
        self.assertEqual((browser.state, browser.can_attempt()), ("not_enabled", True))

    async def test_a_read_after_a_refused_attempt_reconnects_without_any_event(self):
        # The stale-peer outage seen after a session change: a refused attempt used to stick until the
        # endpoint file changed, so a host that stayed up was never tried again.
        now = [100.0]
        browser = ExtensionTransport(discovery=lambda: {"port": 1, "token": "t"})
        browser.clock = lambda: now[0]
        browser.state = "refused"
        browser.next_attempt = 0
        socket = AsyncMock()
        socket.__aiter__.return_value = []
        browser.connector = AsyncMock(return_value=socket)
        browser.call = AsyncMock(return_value={})
        self.assertTrue(await browser.ensure())
        self.assertEqual(browser.state, "connected")

    async def test_a_stopped_endpoint_watch_is_armed_again_by_the_next_operation(self):
        started = []

        async def watch(chrome, events=None):
            started.append(chrome)
        chrome = type("Chrome", (), {"extension_watch": None})()
        chrome_operations.keep_watching(chrome)  # no watch was ever started here: nothing to restart
        self.assertIsNone(chrome.extension_watch)
        with patch.object(chrome_operations, "watch_extension", watch):
            chrome.extension_watch = asyncio.ensure_future(watch(chrome))
            await chrome.extension_watch  # it stopped (an OS notification error)
            first = chrome.extension_watch
            chrome_operations.keep_watching(chrome)
            self.assertIsNot(chrome.extension_watch, first)
            await chrome.extension_watch
            self.assertEqual(len(started), 2)
            running = asyncio.ensure_future(asyncio.Event().wait())
            chrome.extension_watch = running
            chrome_operations.keep_watching(chrome)  # one still running is left alone
            self.assertIs(chrome.extension_watch, running)
            running.cancel()

    async def test_a_failing_window_watch_does_not_take_the_endpoint_watch_with_it(self):
        started, stopped = asyncio.Event(), []

        async def endpoint_watch(chrome):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                stopped.append(True)
                raise

        async def failing():
            await started.wait()
            raise OSError("desktop switch")
        chrome = type("Chrome", (), {"extension_watch": None})()
        shares = type("Shares", (), {"chrome": chrome, "watch": staticmethod(failing)})()
        with patch.object(chrome_operations, "watch_extension", endpoint_watch), patch("builtins.print"):
            task = asyncio.ensure_future(chrome_operations.watch_windows(shares))
            for _ in range(20):
                await asyncio.sleep(0)
            self.assertFalse(task.done())  # the window watch failed; the session's watches are still up
            self.assertFalse(chrome.extension_watch.done())
            self.assertEqual(stopped, [])
            task.cancel()  # the session ends
            await asyncio.gather(task, return_exceptions=True)
            self.assertEqual(stopped, [True])
            self.assertIsNone(chrome.extension_watch)

    async def test_the_deadline_ends_the_wait_and_a_second_read_of_the_outage_does_not_wait(self):
        browser = ExtensionTransport(discovery=lambda: None)

        async def ensure():
            return False
        browser.ensure = ensure

        def expire():
            raise TimeoutError
        self.assertFalse(await chrome_operations.await_extension(browser, self.watcher(expire), Deadline))
        self.assertFalse(await chrome_operations.await_extension(browser, self.watcher(expire), Deadline))
        browser.report("connected")  # the extension is back: the next outage may wait again
        self.assertFalse(browser.waited)
