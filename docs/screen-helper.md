# Native screen helper

Run this program **on the computer whose desktop you want to share**. It makes an
outbound connection to Partyline; it needs no inbound firewall rule or browser
capture extension. Windows 11 is the primary target; macOS and Linux X11 need the
permissions described below. On Windows the installer below needs nothing else; on Linux and
macOS Python 3.11+ and uv are required.

The Partyline dialog ("Computers / Share screen" → "Pair a computer") shows these
commands with your server's address and a pairing code filled in, each with a copy
button. Run them in a terminal **on the computer you want to share, not on the
Partyline server**. After `pair` succeeds the helper prints the full `run` command
for both forms below. Keep the `run` terminal open and answer `y` to each share prompt.

## Windows installer (prototype)

For a person who should never open a terminal: one download, one double-click, then only native dialogs.
In Partyline's **Pair a computer** dialog, a visitor on Windows sees **Download for Windows**
(`https://github.com/High-AiQ/partyline/releases/latest/download/PartylineHelper-Setup.exe`; the
release asset has a fixed name so that link stays valid). Linux and macOS visitors keep the `uvx`
commands described below.

1. Open `PartylineHelper-Setup.exe`. It installs for the current user only (no administrator rights, no UAC
   prompt) to `%LOCALAPPDATA%\Programs\Partyline Helper`, adds a Start-menu entry and an uninstaller
   (Settings → Apps), registers `partyline://` and start-at-login (the same `install` logic as the `uvx`
   route, pointed at the installed exe) and starts the helper.
2. **SmartScreen.** The prototype is not code-signed, so Windows may show "Windows protected your PC".
   Click **More info**, then **Run anyway**. (Edge/Chrome may also ask to keep the download; choose **Keep**.)
   This warning goes away once the installer is signed and has reputation.
3. Back in Partyline click **Pair with installed helper** and answer the dialogs. A round icon appears in the
   system tray.

**Tray icon.** Grey: not connected; green: paired; amber: sharing; red: an agent controls the mouse and keyboard
(the capture border changes colour the same way). The menu has the status, **Stop sharing** and **Quit Partyline
Helper**. Quit ends any share cleanly (the server is told) and the helper returns at the next login.
`run --no-tray` turns the icon off; it is on by default on Windows only.

**Every prompt is a native window**, since the installed program has no console: pairing, share consent, agent
control consent and error messages (a failed pairing, a rejected link, a missing capability). Starting the program
from the Start menu while it already runs, or before pairing, explains that in a dialog.

**Upgrade.** Run the newer installer over the old one. It first runs `PartylineHelper.exe stop`, replaces the
files, re-registers, and starts the helper again. Settings and pairing stay. The same stop also ends an older
`uvx`-installed copy, because both use the lock and pid under `%LOCALAPPDATA%\Partyline`. **Uninstall** stops the
helper and removes the registry entries and files; pairing credentials are left (use "Unpair" through
`PartylineHelper.exe`, or delete `%LOCALAPPDATA%\Partyline\helper.json`), and revoke the computer in Partyline.

**`partyline-helper stop`** (any platform) asks the running helper to exit: it drops a `run.stop` file in the
config directory, which the helper polls twice a second and answers by ending any share, removing the border and
leaving. If the helper (for example an old version that predates this command) does not exit within about five
seconds, the pid in `run.pid` is terminated, and the command waits for the run lock to be released. It prints what
happened and is safe to run when nothing is running. `partyline-helper start` (what the Start menu runs, and what
a bare `partyline-helper` does) starts the helper if it is not running. `version` prints the helper version and
`selfcheck` verifies that every module the helper needs is importable (the CI runs it against the frozen build).

**Why the share dialog never appeared (confirmed on Windows).** A detached helper is started with stdin on the
NUL device. NUL is a character device, so Python's `isatty()` is True for it, the helper believed a terminal was
attached, kept the `[y/N]` prompt, and wrote "Share this region?" into `helper.log` where nobody could answer.
Now `consent_dialog.interactive()` also requires a real console on Windows (`GetConsoleMode` succeeds; NUL, pipes,
no stdin and closed stdin do not), and a background run (`run --log`, login autostart, the frozen exe) always uses
the native dialogs, for share consent and for agent-control consent alike. Earlier suspects, kept as defences:

**Why a dialog could also stay hidden.** The old background helper started a dialog child from a `pythonw`
process that held no foreground rights. Windows blocks `SetForegroundWindow` for such a process, so a normal
window opens behind the browser and at most blinks on the taskbar, with a 60-second timeout that then silently
declines. Two more suspects: the dialog child read its request from stdin, which a windowed process may not have,
so it would decline without ever drawing; and an older copy that predates the native dialogs, left running after
an update (the symptom reported), has no dialog at all. What changed (none of it could be tried on Windows here):

- the request now travels as an argument, and the child watches the helper's pid instead of a stdin pipe;
- the window is centred, topmost, and forced forward by `foreground.bring_to_front`: show/restore, topmost,
  borrow the foreground thread's input queue, and if Windows still refuses, a synthetic Alt tap (the standard
  unlock), then `SetForegroundWindow`; if that fails the taskbar button flashes until clicked. It retries for
  about two seconds while the window maps;
- the tray also raises a balloon notification when a prompt opens, as a second signal;
- the frozen exe starts its own dialogs as `PartylineHelper.exe dialog <request>` (it cannot run `python -m`).

**Version check.** The helper reports its version (`importlib.metadata`, carried inside the frozen build) in its
hello. `GET /api/screen/devices` returns `helper_version` and `update_available` (true when the helper is older
than the server's own version; `unknown` is never flagged), and the computers list in Partyline shows
"Helper update available" with the download link for Windows computers.

**Building.** `.github/workflows/windows-installer.yml` runs on `windows-latest`: it freezes the helper with
PyInstaller (`packaging/windows/PartylineHelper.spec`), checks the frozen exe (`selfcheck`), builds the installer
with Inno Setup (`packaging/windows/installer.iss`), installs and uninstalls it silently as a smoke test and
uploads `PartylineHelper-Setup.exe` as an artifact of every main push (and of pull requests that touch the
helper). A `v*` tag attaches it to the release; the tag-version job dispatches the workflow because a tag pushed
with `GITHUB_TOKEN` cannot start another workflow itself. Locally on Windows, with uv:
`uv run --extra helper python packaging/windows/make_icon.py build/PartylineHelper.ico`, then
`uv run --extra helper --with pyinstaller==6.14.2 pyinstaller packaging/windows/PartylineHelper.spec`, then
`iscc /DAppVersion=<version> packaging\windows\installer.iss`.

Choices: **PyInstaller, onedir, windowed** (mature hooks for tkinter, Pillow, ctypes users; a onefile build would
unpack ~60 MB to `%TEMP%` on every start including every dialog, and is flagged by antivirus more often; Nuitka
needs a C toolchain and a slower build). **Inno Setup** (free, per-user installs without elevation, tiny scripting
for the stop-before-upgrade step, preinstalled or one `choco` away on the runner; MSIX/WiX would force signing
or admin-style plumbing the prototype does not need).

**Signing (later).** Both signing steps in the workflow are already present and skipped until the repository
variable `WINDOWS_SIGNING=true`, with the `AZURE_*` secrets/variables for Azure Trusted Signing (or replace the
two steps with `signtool` and an OV certificate). The exe is signed before it is packed and the installer after.
The Azure steps have never run; expect to adjust their inputs the first time.

## One-time install with uv (Linux, macOS, or Windows with Python)

Run this once on the computer you want to share, and you never type a helper
command again:

```sh
uvx --from 'partyline[helper] @ git+https://github.com/High-AiQ/partyline.git' partyline-helper install
```

(From a checkout use `uv run --extra helper partyline-helper install`.) Afterwards the
Partyline dialog's **Pair with installed helper** button is a `partyline://pair?...`
link: your OS opens the helper, which asks "Pair this computer with <origin>?" in a
native dialog (a web page can trigger the link, so it never pairs silently), pairs, and
starts the helper in the background. The helper also starts at every login. Nothing
needs administrator rights; everything is per user.

`install` records the exact launch command (`<python> -m partyline_helper`) in
`install.json` next to the credentials. If it detects a temporary `uvx` cache (which
uv may delete), it first runs `uv tool install --force 'partyline[helper] @ git+...'`
and points everything at that stable tool environment instead, and prints that it did so.
It is idempotent: run it again to refresh after moving or upgrading. It prints each
thing it registered and where:

| OS | `partyline://` handler | Start at login | Log |
| --- | --- | --- | --- |
| Windows | `HKCU\Software\Classes\partyline` (uses `pythonw`, no console) | `HKCU\...\Run\PartylineHelper` | `helper.log` in the config dir |
| Linux | `~/.local/share/applications/partyline-helper.desktop` (`MimeType=x-scheme-handler/partyline`) + `xdg-mime default` | `~/.config/autostart/partyline-helper.desktop` | same |
| macOS | **not supported in phase 1** (receiving a URL needs a signed `.app` bundle); use the copyable commands | LaunchAgent `~/Library/LaunchAgents/io.partyline.helper.plist` | same |

`partyline-helper uninstall` removes exactly those entries and `install.json`, and
leaves pairing credentials alone (`unpair` deletes those). A tool installed by
`uv tool install` is removed with `uv tool uninstall partyline`.

Links are `partyline://pair?server=<origin>&code=<8 hex digits>[&name=<text>]` and
`partyline://run`. `partyline-helper open <url>` (what the OS calls) accepts nothing else:
the server must be an explicit `http(s)` origin (HTTP only on a private LAN, as for
`pair`), the code must be the 8-hex-digit format, unknown or repeated parameters are
rejected, and the URL is never passed through a shell. Only one helper runs per user (a
lock file and `run.pid` under the config dir): a second `run` or `partyline://run` exits cleanly, and
a new pairing replaces the credentials and restarts the running helper. Rejected links
and failed pairings show a short native message; details go to `helper.log`.

Without a terminal (login autostart, `pythonw`, or `open`), the share consent
`Share this region?` is a native tkinter Yes/No dialog (a short-lived child process, closed if the prompt is cancelled or times out) instead of the y/N prompt. The
1-second input guard and 60-second timeout still apply, and silence, closing the window
or any error declines. The terminal-only `s` stop key is unavailable then; end the helper
by revoking the device or killing its process.

## Manual commands (fallback)

From a checkout:

```sh
uv run --extra helper partyline-helper pair https://partyline.example YOUR-CODE --name "My desktop"
uv run --extra helper partyline-helper monitors
uv run --extra helper partyline-helper run
```

Without a checkout (use the same prefix for each command):

```sh
uvx --from 'partyline[helper] @ git+https://github.com/High-AiQ/partyline.git' partyline-helper pair https://partyline.example YOUR-CODE
uvx --from 'partyline[helper] @ git+https://github.com/High-AiQ/partyline.git' partyline-helper run
```

Pairing codes are 8 hexadecimal digits. Create a short-lived pairing code in Partyline's screen devices UI first. Pairing
claims that code and stores the server origin, device ID, device name and token.
The helper never prints the token. HTTPS is the default when the scheme is omitted.
Explicit HTTP is accepted only for private LAN addresses and prints an unencrypted
transport warning. Certificate verification failures print the host and verification
reason, then exit without reconnecting; fix the certificate before retrying. Use
HTTPS on any network you do not fully trust.

Credentials live at `$XDG_CONFIG_HOME/partyline/helper.json` (default
`~/.config/partyline/helper.json`) on POSIX, mode 0600; on Windows they live in
`~/AppData/Local/Partyline/helper.json` under your profile's default ACL.
`partyline-helper unpair` deletes the local credential. Also revoke the device in
Partyline to invalidate existing copies; revocation disconnects the running helper.

## Local consent and privacy

Each request prints the requester, line, and desktop rectangle last. Requester and
line text have terminal controls removed and are capped at 120 characters. Input
is ignored for the first second of each prompt. While a prompt is pending, new
share requests are declined with `prompt pending`; they cannot replace the
requester or region awaiting consent. Then answer
`Share this region? [y/N]` with `y` within 60 seconds to accept. Silence or any other
answer declines. The terminal displays SHARING ACTIVE until stopped. Type `s` and
Enter to stop a share, or Ctrl+C to stop and exit. Keep this terminal visible.
`run --yes` explicitly disables per-request share confirmation and prints a warning;
use it only when you intend every incoming share request to be accepted. It never
grants agent control (see below).

While sharing, a thin amber border appears just **outside** the selected rectangle
so you can see exactly which region is being sent. It is click-through, stays on
top, never takes focus, and is outside the captured pixels; supported Windows
versions also exclude the border windows from capture. The border disappears on
local or remote stop, disconnect, errors, and Ctrl+C. Run with `run --no-border`
to disable it. If the native overlay cannot be created, the helper prints one
warning and continues sharing without it.

Only the selected desktop region is captured after acceptance. Monitor previews
are an exception: the connected server can request low-resolution whole-monitor
stills for region picking, without a share consent prompt. Their long edge is
capped at 480 pixels, with at most one preview every three seconds per monitor,
including across reconnects. Excess requests receive a rate-limit error and do
not capture pixels. Every preview prints a notice locally. Run the helper only
while you want these previews to be available.

Frames contain compressed screen pixels, the selected rectangle, elapsed time,
and the exact global pointer position with a flag indicating whether it lies in
the region. Monitor layout, device name, OS and helper version are also sent.
No audio is collected. The helper moves the pointer or types only while you have
granted agent control (below); while control is active it watches your keyboard
for the kill switch but sends no keystrokes to Partyline.
Pixels remain in memory; no screenshots are stored locally. The server may retain
received images according to its own policy. Credentials persist until unpaired.

Frames default to at most one per second and 1280 pixels on the long edge. Small
changes are suppressed by comparison with the last sent grayscale thumbnail;
pointer movement also triggers a frame at the configured rate. A requested snap
sends a fresh frame even when nothing changed, subject to the same frame-rate
limit. Snaps arriving less than `1/max_fps` seconds after the last frame are
refused with an error containing the request ID; retry after that interval. Images
use WebP, falling back to JPEG, and each binary message is at most 4 MB. Disconnects end sharing; reconnects
require a new request and fresh consent. Backoff reaches at most 60 seconds.

### Read a Windows window's UI elements

In the helper tray, choose **Allow agents to read a window**, select one visible
window by title and executable, and explicitly allow it. No window is selected by
default. The grant is separate from screen sharing: either can be used alone.
The tray shows the selected window and **Stop reading window** revokes access.
Closing the window or disconnecting the helper ends the grant. Grants and revocations
are recorded in the helper's local audit log. Access pauses on the secure desktop and
resumes when the normal desktop returns, provided the window is still open.

`screen_elements` reads that window's UI Automation tree without bringing it to the
front or sending input. It returns one compact line per element, a snapshot ID,
the window title and executable, control types, names, safe values, states, supported
pattern names, and screen-coordinate bounds. When a current pixel share overlaps an
element it also includes frame-pixel bounds. Element IDs are stable for the same runtime identity and tree path, and only IDs from the latest
snapshot are accepted as action targets. Password values and other windows' elements
are excluded and text is capped. Element metadata may include offscreen text from
the selected window. Count, depth and time bounds limit traversal; an isolated child
process is killed if a provider hangs. Errors, denied consent, closed windows and
unsupported platforms return an unavailable reason. Settle/wait, macOS AX and Linux AT-SPI are planned.
The Windows-only helper dependency `comtypes` supplies the typed UI Automation
COM interfaces; it is not installed on other platforms.

### Act on elements in the chosen window

With both window access and agent control granted on the same computer, an agent can call
`screen_element_action` with an ID from the latest `screen_elements` snapshot. The supported
actions are `invoke`, `toggle` and `set_value`, using the corresponding UI Automation pattern.
The helper rechecks the window, element identity, containment, enabled state and supported pattern
before dispatch. Password fields and read-only values cannot be set. The response includes the
element's updated name, role, enabled and value or toggle state when available. Partyline does
not synthesize mouse or keyboard input, move the cursor, or call an activation API for these
actions. The target application can nevertheless bring itself forward in response; classic
Win32 buttons and checkboxes can do so on Invoke or Toggle, and other apps may activate or
open dialogs. The response and local audit include `foreground_changed` and `target_came_forward`
after the pattern call and the element re-read. A timeout or refusal before dispatch cannot
report those observations.

Element actions alone do not arm physical mouse or ordinary-key takeback. Press Ctrl+Alt+Esc,
stop reading the window, stop sharing or revoke agent control to stop further actions. Lock and
UAC pause actions; closing or replacing the selected window ends its grant. A pattern call already
dispatched when consent is revoked can still complete: the result says `revoked_during`, and no
further action can start from that grant. The deadline covers the operation; a timed-out call is
abandoned and never retried automatically. UIA providers execute in the target application and
may therefore have application-specific effects.

Each action is recorded in the helper's local hash-chained audit with the requesting agent,
process, role, name, action and outcome. For `set_value` the audit records the value's length,
not the submitted text.

## Platforms and troubleshooting

- **Windows:** no administrator access required. Per-monitor DPI awareness is set
  before initializing capture or pointer reading so coordinates use physical
  desktop pixels, including negative origins. On Windows 10 2004 and later the
  border uses `WDA_EXCLUDEFROMCAPTURE` in addition to lying outside the region.
  UAC and secure-desktop windows are not captured. Keep the helper on the
  interactive desktop session.
- **macOS:** System Settings → Privacy & Security → Screen Recording (called
  Screen & System Audio Recording on newer versions): enable the terminal or
  Python application running the helper, then quit and reopen it. Reading the
  pointer does not require Accessibility permission; agent control does (below). The helper checks Screen
  Recording permission and rejects black captures with instructions (a completely black desktop can also
  trigger that warning). Retina capture pixels can differ from desktop points;
  the helper multiplies desktop points and pointer positions by the uniform
  display backing scale and converts capture rectangles back to points. Mixed
  Retina display scales are refused rather than reporting ambiguous coordinates;
  use displays with the same scale. The border uses PyObjC when it is already
  installed; without PyObjC the helper prints a notice and shares without a
  border. Test monitor selection on your actual Mac before sharing sensitive
  material.
- **Linux:** use an X11 session with access to its display. A Wayland session
  (`XDG_SESSION_TYPE=wayland` or a set `WAYLAND_DISPLAY`) exits with
  `Wayland is not supported yet (needs the xdg-desktop-portal ScreenCast/RemoteDesktop route)`.
  Portal support is a later phase.

If pairing fails, check the origin, network, TLS certificate and code expiry.
If revoked, create a fresh code and pair again. If capture initialization fails,
verify desktop permissions and install the `helper` extra. The dependencies are
mss (MIT), pynput (LGPL-3.0), websockets and Pillow; pynput reads the pointer and,
only during agent control, injects input and listens for the kill switch. Automated tests use fake capture and an in-process server. The
headless development server cannot verify real desktop capture; native interactive
smoke testing is still required on each platform.

## Agent control

An agent on the line can ask to drive the mouse and keyboard **inside the shared
region only**. This is a separate consent from sharing, and it lasts for one share.

**Consent.** When an agent calls `screen_control_request`, the helper prints the
requesting agent and line, ignores input for one second, then asks
`Allow agent control? [y/N]`. Answer `y` within 60 seconds; silence or anything
else declines, and the agent is told. Without a terminal (login autostart) the
same question is a native Yes/No dialog with the same guard and timeout. To offer control with the share itself,
start the share with `"control": true` (`POST /api/screen/shares`); the same
prompt follows the share prompt and the grant covers every agent on the line.
`run --yes` does **not** grant control. Only
`run --allow-control-without-prompt` does, and it prints a loud warning at start
and on every grant; use it only on a machine you are willing to hand over.
Control ends when the share ends (`s` Enter, Ctrl+C, a stop from Partyline, or a
disconnect). A new share needs a new grant.

**Indicator.** While control is active the terminal shows
`AGENT CONTROL ACTIVE` and logs every action (`Agent agent-x: click left at
(-90, 20)`). The capture-zone border turns from amber to red while an agent has
control and back to amber when control ends (unless the helper runs with
`--no-border` or the overlay could not be drawn). The
share API (`GET /api/screen/shares`) and the line's `screen_share` events carry
`share.control` with its status, holder and action count; the event is re-sent after every
action so the count stays current.

**Kill switch.** Physical input takes control back and revokes it for the rest of the share
once mouse or keyboard control has armed the switch (the baseline is the agent's own injected
point). Element actions alone do not arm it: moving the mouse or pressing an ordinary key does
not stop them unless mouse or keyboard control has already armed the switch. Ctrl+Alt+Esc
always revokes; stopping sharing or revoking control also stops further element actions:

- moving the pointer more than 8 pixels from where the agent last put it
  (checked ten times a second and before every action);
- pressing any key, even while the agent is typing. Windows and macOS flag the
  agent's own keystrokes, so any unflagged key revokes. On X11 the agent's text is
  flagged too, but named keys it presses (Enter, Tab, Ctrl, …) also echo once
  unflagged; each such echo is accepted once, for at most half a second, and any
  other key revokes. Text is typed one character at a time and stops at the first
  key you press;
- Ctrl+Alt+Esc, which always revokes;
- `s` Enter, which stops sharing and so ends control.

The person who started the share can also revoke control from Partyline
(`DELETE /api/screen/shares/{share_id}/control`). A revocation or a stop takes
effect at once: actions already queued on the helper are discarded, and one in
progress (a drag or typing) stops at its next step. Every revocation is posted to the
line and @mentions the agent that held or last used control.

**What agents can do.** `screen_click`, `screen_move`, `screen_drag`,
`screen_scroll`, `screen_type` and `screen_key` take coordinates in pixels of the
latest `screen_frame` image ((0, 0) is its top-left corner). The server converts
them with the frame's region and scale (the inverse of `mark_pointer`), and both
the server and the helper refuse anything outside the region. Actions settle for
0.3 seconds. The optional `frame` parameter chooses `thumb`
(the default), `full` (original), or `none`. Responses contain one media URL;
use its ID and tier with `get_media`. An identical frame returns `unchanged`
with the previous reference. Coordinates always use the full frame dimensions.
Frames are stored as line media without a chat post and are visible through the
line file listing; ordinary line access checks and media retention apply. Typing
and keys are refused until the
agent has clicked inside the region, so they cannot land in the helper's own
terminal. These combos are blocked on both sides: Ctrl+Alt+Delete,
Ctrl+Alt+Backspace, Ctrl+Alt+F1–F12, Ctrl+Alt+Esc, Win+L (Windows), Super+L and
Ctrl+Alt+L (Linux), and Ctrl+Cmd+Q, Cmd+Alt+Esc and Cmd+Shift+Q (macOS), including
any of them with extra modifiers.

**Audit.** Actions are posted to the line as compact system notes, batched every
60 seconds (or every 100 actions) with repeated pointer moves folded together,
and flushed when control ends. Each action is recorded durably before it is
acknowledged; pending batches are posted after a server restart. Audit entries
are retained in a hash chain, with the final hash included in each note. Typed
text appears as its first 40 characters.
An action that stopped partway is audited as `(interrupted: …)`, and one the
computer never confirmed as `(unconfirmed)`.

**Limits.** By default at most 10 actions per second, 500 characters per
`screen_type`, and 300 actions per share; the helper also enforces a hard local
ceiling of 20 actions per second and 500 characters. Server operators set the
limits with `PARTYLINE_CONTROL_RATE`, `PARTYLINE_CONTROL_MAX_TEXT` (the helper's
500 still applies) and `PARTYLINE_CONTROL_SESSION_ACTIONS`; invalid values stop
the server at startup.

**Permissions.**

- **Windows:** none beyond running the helper on the interactive desktop. Input
  cannot reach elevated (UAC) windows or the secure desktop.
- **macOS:** System Settings → Privacy & Security → **Accessibility** (to move the
  pointer and type) and **Input Monitoring** (for the kill-switch key listener):
  enable the terminal or Python running the helper, then quit and reopen it.
  Without them the helper refuses control and says why; it never runs control
  without the kill switch.
- **Linux:** an X11 session (XTest). Wayland is refused.

**Compatibility.** The helper announces `control: 1` in its hello. Helpers that
predate agent control get no control messages; agents receive `helper too old
for control` instead.
