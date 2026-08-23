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

from scripts.ui_auth import (
    authorization_headers,
    browser_auth_script,
    post_json,
    register_test_account,
)
REPO_ROOT = Path(__file__).resolve().parent.parent
STARTUP_TIMEOUT = 30.0
VIEWPORT = {"width": 1280, "height": 800}
# A common phone, and comfortably below the 900px breakpoint where the three
# columns stop fitting and the rails become drawers.
NARROW_VIEWPORT = {"width": 390, "height": 844}
# The same phone with its keyboard up. A soft keyboard shortens the viewport
# rather than covering it, so this is what `100dvh` has to survive.
KEYBOARD_VIEWPORT = {"width": 390, "height": 420}


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


@dataclass
class UiSession:
    """A live server, a browser page pointed at it, and a screenshot sink."""

    page: object
    base_url: str
    out_dir: Path
    auth_headers: dict[str, str]
    auth_credentials: tuple[str, str]
    shots: list[Path] = field(default_factory=list)
    server: object = None      # the Popen, so a test can kill the wire
    # Settle animations before each shot. On for parity captures, where a
    # half-played fade is a false difference; off for ordinary screenshots,
    # which should show the app exactly as it behaves.
    still_frames: bool = False

    def settle_animations(self):
        if self.still_frames:
            self.page.evaluate(SETTLE_ANIMATIONS)

    def stop_server(self):
        """Kill the server out from under the page, as a crash would."""
        self.server.terminate()
        self.server.wait(timeout=10)

    def shot(self, name: str, *, clip=None, full_page=False) -> Path:
        self.settle_animations()
        path = self.out_dir / f"{name}.png"
        self.page.screenshot(path=str(path), clip=clip, full_page=full_page)
        self.shots.append(path)
        return path

    def element_shot(self, name: str, selector: str) -> Path:
        """Screenshot one element, for looking closely at a single component."""
        self.settle_animations()
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


# Run before every still frame. Screenshots are the reason two captures of the
# same build can differ: a shot taken 20ms into the menu's 120ms fade catches a
# different opacity each run.
#
# The obvious fix — CSS forcing `animation-duration: 0s` — is wrong, and looked
# right for a while. `.msg` arrives with `animation: arrive .28s both`, and a
# zero-duration animation with `fill-mode: both` pins it to its *opening*
# frame, so the whole feed rendered faded. The capture would have been
# self-consistent and quietly unrepresentative of the app.
#
# So: finish what can finish, and pin what cannot. Finite animations and
# transitions jump to their end state, which is the state a person sees.
# Infinite ones — the live-line LED pulse, a ringing jack — have no end, so
# they are paused at a fixed frame instead.
SETTLE_ANIMATIONS = """
() => {
  for (const animation of document.getAnimations()) {
    const iterations = animation.effect?.getTiming?.().iterations;
    if (iterations === Infinity) {
      animation.pause();
      animation.currentTime = 0;
    } else {
      animation.finish();
    }
  }
}
"""


@contextlib.contextmanager
def ui_session(lines=(), *, out_dir="/tmp/partyline-ui", headless=True, viewport=None,
               handle="screenshot", freeze_animations=False):
    """Start a throwaway partyline, open it in a browser, yield a UiSession.

    `lines` are conversation names to create before the page loads, so the UI
    has something to render. `handle` names the throwaway account registered
    for the browser session.
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
        tokens, credentials = register_test_account(base_url, handle)
        for name in lines:
            post_json(f"{base_url}/api/conversations", {"name": name}, tokens["access_token"])

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(viewport=viewport or VIEWPORT)
            context.add_init_script(browser_auth_script(tokens))
            page = context.new_page()
            page.goto(base_url)
            page.wait_for_selector("#convs")
            if lines:
                page.wait_for_selector(".conv-row")
            session = UiSession(page=page, base_url=base_url, out_dir=out,
                                auth_headers=authorization_headers(tokens),
                                auth_credentials=credentials,
                                server=server,
                                still_frames=freeze_animations)
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

# A fixed instant, so a captured feed renders the same clock face today as it
# will tomorrow. Real messages carry server time, which would make every
# screenshot differ from every other one and drown a parity check in noise.
FIXED_SENT_AT = 1_700_000_000

# One process message exercising everything the renderer can do, because the
# markdown pipeline is the most intricate rendering in the app and the states
# below it used to leave it completely uncovered.
AGENT_BODY = """## Migration status

Ported the pure libraries to **TypeScript**. Notes for @greg and @sol:

- schemas own the boundary
- `latestJacks()` keeps the *live wins* rule
- see [the contract](https://example.com/contracts)

| module | lines |
|---|---|
| room | 226 |
| wire | 178 |

> A flaky test is worse than an uncovered line.

```js
const jacks = latestJacks(room.attachments);
```
"""

SEED_ROOM = """
(seed) => {
  const room = window.partyline.room;
  for (const attachment of seed.attachments) room.upsertAttachment(attachment);
  room.messages = seed.messages;
}
"""


def seed_room(page):
    """Put a known feed and a known board on the line, deterministically.

    Deliberately injected through `window.partyline` rather than sent over the
    wire: the transport is covered by the browser tests, and what a parity
    check needs is the *rendering* pinned to bytes — same ids, same clock, same
    order, every run.
    """
    jack = lambda name, status, created: {           # noqa: E731 - a fixture, not logic
        "id": f"att-{name}", "name": name, "adapter": "codex", "command": ["codex"],
        "cwd": "/tmp/project", "status": status, "created_at": created,
        "cwd_git": {"sha": "d87b3ae", "dirty": name == "sol"},
    }
    message = lambda mid, sender, kind, body: {      # noqa: E731
        "id": mid, "sender": sender, "sender_type": kind,
        "body": body, "created_at": FIXED_SENT_AT, "files": [],
    }
    page.evaluate(SEED_ROOM, {
        "attachments": [jack("sol", "running", 1), jack("terra", "exited", 2)],
        "messages": [
            message("m1", "greg", "human",
                    "# not a heading\n"
                    "- not a bullet\n"
                    "> not a quote\n"
                    "but *this* is italic, **this** is bold, `npm run verify` is code, @sol"),
            message("m2", "sol", "agent", AGENT_BODY),
            message("m3", "system", "system", "@terra joined the line"),
        ],
    })
    page.wait_for_selector(".msg .body table")


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
        # The dialog asks the server which processes are live before it can warn
        # about them, so the modal exists a beat before it is finished. Shooting
        # on the modal alone catches "Loading…" some runs and the loaded state
        # others — which is a difference in the capture, not in the app.
        page.locator(".modal .live-list").wait_for(state="visible", timeout=5000)
        ui.shot("07-delete-confirm")

        # The overlay swallows clicks until the modal is dismissed, and Escape
        # is not wired to it — use the modal's own close control.
        page.locator(".modal .close").click()
        page.locator(".overlay").wait_for(state="detached")
        archive = page.locator("#archiveSection summary")
        if archive.count():
            archive.click()
            ui.shot("08-archive-expanded")
            archive.click()

        # ── the line itself ──
        # Everything above this point is the rail. The feed, the board and the
        # mention popover are where the message renderer, the jack rules and
        # the autocomplete actually show up, and they were unwatched.
        # Wait for the line's own detail fetch before seeding. `open()` clears
        # the room and refills it asynchronously, so a seed that lands first is
        # silently overwritten. Waiting on a *rendered* proxy is not enough —
        # the empty feed looks identical before and after the load, which is
        # how this first showed up as an empty mention popover rather than an
        # error. Wait on the response itself.
        is_detail = lambda response: (                    # noqa: E731
            "/api/conversations/" in response.url and response.request.method == "GET")
        with page.expect_response(is_detail):
            page.locator(".conv-row .conv").first.click()
        page.wait_for_selector("#composer")
        seed_room(page)
        ui.shot("09-feed-populated")
        ui.element_shot("10-message-process", ".msg:nth-of-type(2)")
        ui.element_shot("11-message-human", ".msg:nth-of-type(1)")
        ui.element_shot("12-board-jacks", "#jacks")

        # The popover ranks live processes above dead ones above humans, which
        # is a rule with consequences: mentioning a dead handle does nothing.
        composer = page.locator("#input")
        composer.click()
        composer.type("@")
        page.wait_for_selector("#mentionPop .opt")
        ui.shot("13-mention-popover")
        page.keyboard.press("Escape")

        # ── narrow ──
        # Last, and in the same session: switching the viewport is one-way for
        # these captures, because every state above was composed for three
        # columns. Below the breakpoint the rails become drawers over the line,
        # and that layout needs the same regression net as the desktop one —
        # the centre column silently collapsing to zero width is exactly the
        # kind of thing a person only notices on a phone they are not holding.
        page.set_viewport_size(NARROW_VIEWPORT)
        page.wait_for_timeout(250)
        ui.shot("14-narrow-line")

        page.locator(".drawer-toggle.lines").click()
        page.wait_for_timeout(350)
        ui.shot("15-narrow-rail-drawer")

        # Click the strip of backdrop the drawer does not cover: the drawer is
        # 320px of a 390px screen, so the left edge is the drawer itself.
        page.locator(".drawer-backdrop").click(position={"x": 375, "y": 400})
        page.wait_for_timeout(350)
        page.locator(".drawer-toggle.jacks").click()
        page.wait_for_timeout(350)
        ui.shot("16-narrow-board-drawer")

        # An on-screen keyboard does not overlay the page, it shortens the
        # viewport — which is the case `100dvh` exists for, and the one where a
        # `vh`-sized layout pushes the composer off the bottom of the screen.
        # Half height stands in for a keyboard being up.
        page.locator(".drawer-backdrop").click(position={"x": 20, "y": 400})
        page.wait_for_timeout(300)
        page.set_viewport_size(KEYBOARD_VIEWPORT)
        page.locator("#input").click()
        page.wait_for_timeout(300)
        ui.shot("17-narrow-keyboard-up")

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
