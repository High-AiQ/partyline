"""Drive the partyline UI in a real browser, for screenshots and UI tests.

The point of this module is that nobody — human or agent — should have to ship a
frontend change they have not seen. It starts a server on a throwaway port and
database, seeds it over the HTTP API, and hands back a Playwright page.

Use as a library:

    from scripts.uishot import ui_session

    with ui_session(lines=["alpha", "beta"]) as ui:
        ui.page.click(".conv-row:first-child .conv-more")
        ui.shot("menu-open")

Or from the command line, which captures a standard set of states:

    uv run python -m scripts.uishot                 # writes to /tmp/partyline-ui/
    uv run python -m scripts.uishot --out ./shots   # somewhere else

Never point this at a real database: `PARTYLINE_DB` is always a temp file, and
the port is chosen by the OS so several of these can run at once.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STARTUP_TIMEOUT = 30.0
VIEWPORT = {"width": 1280, "height": 800}


def free_port() -> int:
    """Ask the OS for a port nobody is using, rather than guessing one."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _die_with_parent():
    """Ask the kernel to kill this server if its parent dies.

    The `finally` below handles a normal exit or an exception, but not the
    parent being killed outright — a timed-out test run, a Ctrl-C, an agent
    whose turn was cut short. Without this, those leak a live server on a
    random port that outlives everything and is a nuisance to find later.
    Linux only; harmless where it is unavailable.
    """
    try:
        import ctypes

        PR_SET_PDEATHSIG = 1
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except Exception:
        pass


def _post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url, method="POST", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        return json.load(response)


@dataclass
class UiSession:
    """A live server, a browser page pointed at it, and a screenshot sink."""

    page: object
    base_url: str
    out_dir: Path
    shots: list[Path] = field(default_factory=list)
    server: object = None      # the Popen, so a test can kill the wire

    def stop_server(self):
        """Kill the server out from under the page, as a crash would."""
        self.server.terminate()
        self.server.wait(timeout=10)

    def shot(self, name: str, *, clip=None, full_page=False) -> Path:
        path = self.out_dir / f"{name}.png"
        self.page.screenshot(path=str(path), clip=clip, full_page=full_page)
        self.shots.append(path)
        return path

    def element_shot(self, name: str, selector: str) -> Path:
        """Screenshot one element, for looking closely at a single component."""
        path = self.out_dir / f"{name}.png"
        self.page.locator(selector).screenshot(path=str(path))
        self.shots.append(path)
        return path

    def settle(self):
        """Wait for the rail to have rendered its lines.

        Deliberately not `networkidle`: the page holds a WebSocket open for as
        long as it is connected, so the network is never idle and that wait can
        only ever time out. Wait for a concrete condition instead.
        """
        self.page.wait_for_function(
            "() => { const n = document.querySelector('#convs');"
            " return n && (n.querySelector('.conv-row') || n.children.length === 0); }")

    def open_row_menu(self, index=0):
        """Hover a line row, then open its ⋯ menu, and return the menu locator.

        The hover is not decoration. `.conv-actions` is `pointer-events:none`
        until its row is hovered, and Playwright hit-tests the click point
        *before* it moves the mouse — so a bare click on the ⋯ resolves to the
        row button underneath and retries until it times out.
        """
        rows = self.page.locator(".conv-row")
        row = rows.nth(index) if index >= 0 else rows.last
        row.scroll_into_view_if_needed()
        row.hover()
        button = row.locator(".conv-more")
        self.page.wait_for_function(
            "el => getComputedStyle(el.closest('.conv-actions')).pointerEvents === 'auto'",
            arg=button.element_handle())
        button.click()
        menu = self.page.locator(".conv-menu:not([hidden])")
        menu.wait_for(state="visible")
        return menu


# Injected when a caller asks for still frames. CSS animations are the reason
# two captures of the same build can differ: a screenshot taken 20ms into the
# menu's 120ms fade catches a different opacity each run. Freezing them is not
# cosmetic — it is what makes a byte comparison mean anything.
FREEZE_ANIMATIONS = """
*, *::before, *::after {
  animation-duration: 0s !important;
  animation-delay: 0s !important;
  transition-duration: 0s !important;
  transition-delay: 0s !important;
}
"""


@contextlib.contextmanager
def ui_session(lines=(), *, out_dir="/tmp/partyline-ui", headless=True, viewport=None,
               handle="screenshot", freeze_animations=False):
    """Start a throwaway partyline, open it in a browser, yield a UiSession.

    `lines` are conversation names to create before the page loads, so the UI
    has something to render. `handle` is the name typed into the connect gate.
    Everything is torn down on exit, including the server process and the temp
    database.
    """
    from playwright.sync_api import sync_playwright

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    descriptor, db_path = tempfile.mkstemp(suffix=".db", prefix="partyline-ui-")
    os.close(descriptor)
    os.unlink(db_path)  # let the server create it, so migrations run on a fresh file

    env = dict(os.environ, PARTYLINE_DB=db_path, PARTYLINE_PORT=str(port),
               PARTYLINE_HOST="127.0.0.1")
    server = subprocess.Popen([sys.executable, "-m", "partyline.server"], cwd=REPO_ROOT,
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              preexec_fn=_die_with_parent)
    try:
        _await_server(base_url, server)
        for name in lines:
            _post(f"{base_url}/api/conversations", {"name": name})

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            page = browser.new_page(viewport=viewport or VIEWPORT)
            page.goto(base_url)
            # The app is behind a handle gate, and the handle lives in
            # localStorage — a fresh browser context always starts gated.
            page.wait_for_selector("#gateName")
            page.fill("#gateName", handle)
            page.click("#gateForm button[type=submit]")
            page.wait_for_selector("#convs")
            if lines:
                page.wait_for_selector(".conv-row")
            if freeze_animations:
                page.add_style_tag(content=FREEZE_ANIMATIONS)
            session = UiSession(page=page, base_url=base_url, out_dir=out, server=server)
            session.settle()
            try:
                yield session
            finally:
                browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
        # Popen does not close the pipe it opened; without this every session
        # leaks a file descriptor and warns about it under -W error.
        if server.stdout is not None:
            server.stdout.close()
        with contextlib.suppress(OSError):
            os.unlink(db_path)


def _await_server(base_url: str, server: subprocess.Popen):
    """Poll until the server answers, or fail with its output rather than a timeout."""
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if server.poll() is not None:
            output = server.stdout.read().decode(errors="replace") if server.stdout else ""
            raise RuntimeError(f"server exited before it was ready:\n{output}")
        try:
            with urllib.request.urlopen(f"{base_url}/api/version", timeout=1):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    server.kill()
    raise RuntimeError(f"server did not come up within {STARTUP_TIMEOUT}s")


# -- the standard state set ------------------------------------------------
LINES = ["alpha line", "beta line", "gamma line", "delta line", "epsilon line",
         "zeta line", "eta line", "theta line"]


def capture_all(out_dir="/tmp/partyline-ui", *, freeze_animations=False) -> list[Path]:
    """Capture the states a sidebar change should always be checked against."""
    with ui_session(LINES, out_dir=out_dir, freeze_animations=freeze_animations) as ui:
        page = ui.page
        ui.shot("01-sidebar-idle")

        first = page.locator(".conv-row").first
        first.hover()
        ui.shot("02-row-hovered")

        ui.open_row_menu(0)
        ui.shot("03-menu-open-first-row")
        ui.element_shot("04-menu-closeup", ".conv-menu")

        # Hovering an item is where the old menu died: prove it survives, and
        # capture what the hover state actually looks like.
        page.locator(".conv-menu button").first.hover()
        ui.shot("05-menu-item-hovered")

        page.keyboard.press("Escape")
        # The last row is the clipping case: its menu used to fall outside the
        # scrolling rail entirely.
        ui.open_row_menu(-1)
        ui.shot("06-menu-open-last-row")

        page.keyboard.press("Escape")
        ui.open_row_menu(0)
        page.locator(".conv-menu .delete").click()
        page.wait_for_selector("#modal:not([hidden]), .modal, dialog[open]", timeout=5000)
        ui.shot("07-delete-confirm")

        # The overlay swallows clicks until the modal is dismissed, and Escape
        # is not wired to it — use the modal's own close control.
        page.locator(".modal .close").click()
        page.locator(".overlay").wait_for(state="detached")
        archive = page.locator("#archiveSection summary")
        if archive.count():
            archive.click()
            ui.shot("08-archive-expanded")

        return list(ui.shots)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    out = "/tmp/partyline-ui"
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    shots = capture_all(out)
    for path in shots:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
