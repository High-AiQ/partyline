# Native screen helper

Run this program **on the computer whose desktop you want to share**. It makes an
outbound connection to Partyline; it needs no inbound firewall rule or browser
capture extension. Windows 11 is the primary target; macOS and Linux X11 need the
permissions described below. On Windows the installer below needs nothing else; on Linux and
macOS Python 3.11+ and uv are required.

Pair a computer once with your Partyline account; it can then be shared from any line. A screen share
belongs to the line where you start it, and only that line receives its frames and control. The sidebar
icon marks lines with active shares.

When a person starts sharing, Partyline saves the first received frame as line media and
asks the processes on that line to look now. When sharing stops, the notice includes the
last distinct frame's media id. Fetch either image with `get_media`; this remains available
after the live screen tools disappear. Walkthroughs keep their own recording and do not
create these automatic frame files.

Screen MCP tools appear while a live screen or window grant is available and disappear when access ends.
The grant notice explains how to inspect a window: start with a summary, then use find, ls, or text;
use element ids to act, page long results with offset/next_offset, and refresh after page changes.
Screen-control tools appear only after control consent.
Claude Code and OpenCode V2 refresh their tool list on MCP `list_changed`. Codex CLI does not, so its
screen tools remain listed for the session and return a clear denial when no screen is shared.

## Standing window access

After pairing, the tray item **Let agents on my lines see and use my windows** is off by default and
persists across restarts. In **Settings → Computers**, the paired person selects a **Window access**
set of lines for each computer. The filterable picker offers top-level lines with a live attached process;
selected lines stay listed when idle so they can be removed. Readability follows the rail's rules:
people can currently read every line. Each selected line and its sublines inherit
access. Use checkboxes or arrows and Enter to toggle; Space toggles when the filter is empty, so
multiword filters remain plain text. Use Backspace to remove the last chip, and
Escape to close. Removing a line immediately revokes its subtree's standing window grants on the server
and helper; disjoint selected subtrees and explicit shares keep their grants. If both an ancestor and a
subline are selected (for example through pairing), removing the ancestor also revokes outstanding
standing grants in the subline. The still-selected subline retains authorization and may attach again.
Adding a line revokes nothing.
Pairing from a line initially adds that line. Settings pairing and existing account-wide helpers start
with no authorized lines until their owner selects them. An unknown owner
never receives standing access. Turn the tray toggle on to let agents on an authorized line call
`screen_windows` and `screen_attach_window(window, reason)`. Discovery returns the HWND, process, title
and state Windows UIA provides. If Chrome approval is active, the list can also include inactive tabs
with their titles and URLs; otherwise it returns what UIA exposes. For example, a worker can select the
**Catalog Dashboard** window, choose `shop.us` or `shop.uk`, follow **Manage listing content** to the
**Listing Content Manager** page, then attach with a short reason.

The rail shows an outlined computer on authorized lines and their sublines while the computer is online
and its toggle is on. A live window grant, screen share or control shows a filled green computer. These
states update from server events. The person-only, computer-owner-only
`PUT /api/screen/devices/{id}/window-access-lines` replaces the full set with `{"conv_ids":[...]}`;
`GET` on the same path returns readable picker options. The older singular route replaces the set with
zero or one line for compatibility. Existing saved bindings migrate exactly once, without adding scope.

Attach creates the same line window grant as an explicit share. Existing per-call checks still apply, and
sublines inherit through the existing grant tree. The first attach in each helper session shows a toast
naming the line and agent. Turning the item off blocks the next call: the helper checks its saved setting
on every request, and the server's mirror also denies requests while off. Access pauses while Windows is
locked or on its secure desktop. **Pause and disconnect** revokes active window grants and cancels
in-flight calls. Local gates close before awaited cleanup; disconnect starts independently of capture,
transport and browser teardown.

Standing access covers discovery, window screenshots, UI Automation reads and actions, and scoped key
commits, and point input on a Chrome page through CDP (no cursor moves). Real mouse or keyboard input in
any other window asks the person first, once per grant (see *Point input in the chosen window*).
Pixel-control keyboard control, full-monitor capture and clipboard keep their separate consent paths. Partyline Helper, terminals and shells, password managers, UAC and OS
security windows are never listed or attachable this way; password values remain redacted. The tray shows
window access as off, on or active; the active tooltip names the line and agent. **Recent activity** shows
the helper's append-only metadata log. The server also keeps a durable, hash-chained per-line audit of call
type, app, title and result without contents. Individual calls do not post chat messages. The first standing
call on a line for each computer posts one short note pointing to **Settings → Computers → View log**; it is
not repeated unless access is revoked and re-granted (or the server restarts).

People can read the newest 50 entries under the computer's selected line with **View log**, including each
entry hash and the current chain head. The equivalent person-only API is
`GET /api/conversations/{conv_id}/window-access-audit?limit=50` (limit 1–200, default 50). It returns
`entries` newest first, each with `agent`, `call`, `app`, `title`, `result`, `time` and `entry_hash`, plus the
overall `chain_head`. Agent credentials cannot read this route. Window-access rows deliberately remain
unpublished, and restart recovery never turns them into chat messages; live-consented pixel-control audits
keep their existing chat behavior.

Each granted window has a thin blue outline just outside its visible frame. It follows the window and
hides while the window is minimized or on another virtual desktop. It is click-through, does not take
focus, and supported Windows versions exclude it from screen capture. The outline is not always-on-top: it sits
in the z-order directly above its granted window, so anything in front of that window (a game, a
dialog, another browser window) covers the outline exactly as it covers the window. The helper re-seats
the outline just above its window on foreground and z-order WinEvents (no polling, no timers), moves it
only when it is not already directly above, never moves the granted window, and never activates the
outline. It is removed as soon as the grant ends. The whole-monitor capture border is unchanged and
stays topmost.

Some UI Automation actions can bring the granted window forward. When an action does that, the helper
attempts to restore the window that was in front, provided the granted window is still in front when
the action completes. Windows can refuse this best-effort restore; `foreground_restored` reports whether
it succeeded. The helper does not synthesize global input to force activation, and skips restoration
when another window is observed in front. Actions intended to activate a window are not restored.

The Partyline Computers dialog shows these
commands with your server's address and a pairing code filled in, each with a copy
button. Run them in a terminal **on the computer you want to share, not on the
Partyline server**. After `pair` succeeds the helper prints the full `run` command
for both forms below. Keep the `run` terminal open and answer `y` to each share prompt.

## Windows installer (prototype)

For a person who should never open a terminal: one download, one double-click, then only native dialogs.
In Partyline's **Computers** dialog, a visitor on Windows sees **Download for Windows**
(the link points at the exact helper version this server ships). Installers are listed on the
[releases page](https://github.com/High-AiQ/partyline/releases). Each is named `PartylineHelper-Setup-<helper version>.exe`
and attached to the `helper-v<helper version>` release, for example
`releases/download/helper-v1.2.0/PartylineHelper-Setup-1.2.0.exe`; there is no fixed-name or `latest` alias, and the
version also shows in the file's Properties → Details. The server builds that URL in one place
(`installer_info` in `partyline/helper_release.py`); the web UI reads it from `GET /api/screen/helper-installer` and a
connecting helper gets the same link in its update message. Linux and macOS visitors keep the `uvx`
commands described below.

1. Open `PartylineHelper-Setup-<version>.exe`. It installs for the current user only (no administrator rights, no UAC
   prompt) to `%LOCALAPPDATA%\Programs\Partyline Helper`, adds a Start-menu entry and an uninstaller
   (Settings → Apps), registers `partyline://` and start-at-login (the same `install` logic as the `uvx`
   route, pointed at the installed exe) and starts the helper.
2. **SmartScreen.** The prototype is not code-signed, so Windows may show "Windows protected your PC".
   Click **More info**, then **Run anyway**. (Edge/Chrome may also ask to keep the download; choose **Keep**.)
   This warning goes away once the installer is signed and has reputation.
3. Back in Partyline click **Pair with installed helper** and answer the dialogs. A round icon appears in the
   system tray.

**Tray icon.** Grey: not connected; green: paired; amber: sharing; red: an agent controls the mouse and keyboard
(the capture border changes colour the same way). The menu has the status, **Stop screen sharing**, **Stop all sharing** (screen share and
every window grant; enabled while anything is shared), a **Stop** submenu per shared window, and **Quit Partyline
Helper**. The tooltip is cut to Windows' 127-character limit; a tray update that pystray rejects is logged once in the helper's log. Quit ends any share cleanly (the server is told) and the helper returns at the next login.
`run --no-tray` turns the icon off; it is on by default on Windows only.

**Every prompt is a native window**, since the installed program has no console: pairing, share consent, agent
control consent and error messages (a failed pairing, a rejected link, a missing capability). Starting the program
from the Start menu while it already runs, or before pairing, explains that in a dialog.

**Upgrade.** Run the newer installer over the old one. It first runs `PartylineHelper.exe stop`, installs the new
version under `versions/<version>`, re-registers, and starts the helper again. Settings and pairing stay. The same stop also ends an older
`uvx`-installed copy, because both use the lock and pid under `%LOCALAPPDATA%\Partyline`. **Uninstall** stops the
helper and removes the registry entries and files; pairing credentials are left (use "Unpair" through
`PartylineHelper.exe`, or delete `%LOCALAPPDATA%\Partyline\helper.json`), and revoke the computer in Partyline.

**`partyline-helper stop`** (any platform) asks the running helper to exit: it drops a `run.stop` file in the
config directory, which the helper observes through native filesystem notifications and answers by ending any
share, removing the border and leaving. If the helper (for example an old version that predates this command) does not exit within about five
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

**Version check.** The helper reports its own version in its hello. The server compares it with
the helper version shipped in its checkout and sends the result to capable helpers. The tray and
Computers list show available updates; unknown versions are not flagged.

**Building.** `.github/workflows/windows-installer.yml` runs on `windows-latest`: it freezes the helper with
PyInstaller (`packaging/windows/PartylineHelper.spec`), checks the frozen exe (`selfcheck`), builds the installer
with Inno Setup (`packaging/windows/installer.iss`), installs and uninstalls it silently as a smoke test and
uploads `PartylineHelper-Setup-<version>.exe` as an artifact for helper pull requests. A `helper-v*` tag publishes
the installer and its SHA-256 sidecar to the helper release. The spec runs `packaging/windows/make_version_info.py` to write the exe's Windows
version resource from `partyline_helper.__version__`, and the workflow passes the same version to Inno Setup
(`/DAppVersion`) for the installer's file name and version resource. The tag-version job dispatches the workflow for tags created with `GITHUB_TOKEN`.
Locally on Windows, with uv:
`uv run --extra helper python packaging/windows/make_icon.py build/PartylineHelper.ico`, then
`uv run --extra helper --with pyinstaller==6.14.2 pyinstaller packaging/windows/PartylineHelper.spec` (the spec itself
writes the exe's version resource, so no build path can omit it), then
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
the region. On Windows, a successful `GetCursorInfo` query also reports
`pointer.captured: true` when the OS cursor is hidden. Helpers without that hint
cannot confirm capture. Monitor layout, device name, OS and helper version are also sent.
No audio is collected. The helper moves the pointer or types only while you have
granted agent control (below); while control is active it watches your keyboard
for the kill switch but sends no keystrokes to Partyline.
Pixels remain in memory; no screenshots are stored locally. The server may retain
received images according to its own policy. Credentials persist until unpaired.

Walkthroughs annotate a pointer as stationary when at least three consecutive frames
keep the visible pointer within a 3-pixel bounding box while image content changes.
Region or output-size changes break the run. Detection uses the buffered recording
before frame selection, so duplicates cannot erase the evidence. Stationary frames
say `(pointer at x,y, stationary)` and keep the marker at the reported position.
Scrolling, typing and video playback can all produce this pattern; stationarity alone
never means capture. `screen_frame` uses recent share frames for the same additive hint.

Only a helper-reported `pointer.captured: true` produces `(view centre; pointer captured)`
and a centre crosshair with `mark_pointer`. The centre is a view-direction reference.
Deduplication compares pixels in both cases and skips pointer-position comparison only
for confirmed captured frames. Normal and stationary visible pointers retain their
reported desktop coordinates and markers.

Frames default to at most one per second and 1280 pixels on the long edge. Small
changes are suppressed by comparison with the last sent grayscale thumbnail;
pointer movement also triggers a frame at the configured rate. A requested snap
sends a fresh frame even when nothing changed, subject to the same frame-rate
limit. Snaps arriving less than `1/max_fps` seconds after the last frame are
refused with an error containing the request ID; retry after that interval. Images
use WebP, falling back to JPEG, and each binary message is at most 4 MB. Disconnects end sharing; reconnects
require a new request and fresh consent. Backoff reaches at most 60 seconds.

### Read a Windows window's UI elements

In the helper tray, choose **Share a window…**, select a visible window by title and executable,
then choose exactly one line in **Share this window with which line?** The second picker lists every
line visible to the paired computer's owner, with a count of the processes attached to it, with
sublines indented beneath their parent. Lines with no process are listed too, so you can share first
and let a process attach later. Nothing is selected by default; cancelling either picker grants no
access. The line can be any line the computer's owner can open. Window grants need no captain, task
or subline: a plain line with a few person-attached processes is the primary case.

A grant belongs to the line, not to one process. Every live process attached to that line or any
live, non-archived subline can call `screen_elements` and `screen_element_action` on its windows,
including processes that attach later and processes started by a compaction rotation. Ancestors,
siblings and unrelated lines cannot use the grant. When the holding line is one the caller may see
(its own line, an ancestor, or a descendant for a captain) the refusal names it so the caller can
ask the person; a hidden line is never named, and an id or title held there answers like a missing
window. Inheritance works in plain line trees and captain/task trees alike. When a grant starts or
ends, the owning line sees one brief system message and every live process on that line and its live
sublines receives a private terminal notice with the window ID and usage instructions (an ending
names its reason). A process that attaches to, or is re-briefed on, a line with live grants hears
about them in its briefing, with inherited grants naming the owning line.

You can share several windows with the same line, or different windows with different lines. The
tray lists each as **window → «line» (and its sublines)**, with its own **Stop**; **Stop all
sharing** ends every grant and the screen share. An item appears when its grant starts and
disappears when it ends, including when the web or the server revokes it. The web computer list also
shows each target line and offers **Stop sharing window**. Your sidebar marks each target line with
a computer icon; its tooltip names the shared windows and their lines. A grant ends when you stop it
(tray **Stop**, **Stop all sharing**, or the web **Stop sharing window**), the window closes, the
helper disconnects, the server restarts, or the owning line is archived or deleted. Archiving or
retiring a subline keeps its parent’s grant. A process detaching, exiting, resuming or being
replaced by a compaction rotation does not end it. Ending one grant leaves other windows alone.
Consent is never restored after a restart. Grants and revocations are recorded in the helper's local
audit.

Window grants cover `screen_elements`, `screen_window_look`, `screen_element_action`, `screen_window_snapshot` and the point tools
(`screen_window_click`, `_scroll`, `_drag`, `_type`, `_key`). With one window the target is
unambiguous. With several, pass `window` as the grant ID or title; an ambiguous call lists every
choice with its owning line, and each snapshot returns its grant ID as `window`. Inherited reads
also name the owning line in `inherited_from`. Snapshots and element caches are per grant, shared by
the processes on the line and its sublines, so a second process reads the stored tree. Actions on
one window run one at a time, so processes across the subtree never interleave dispatches. These
grants are independent of line-based pixel sharing and mouse/keyboard control: `screen_frame`,
`screen_click`, `screen_type`, `screen_key`, `screen_scroll`, `screen_drag` and `screen_move` keep
their existing pixel-share permissions.

The server stores live grants in `screen_line_window_grants`, keyed by line. The earlier
per-process table and its detach, exit and activation triggers are dropped when the database
opens; rows are cleared on startup and helper disconnection, so no row is migrated and no
consent is ever restored. Archiving a line deletes its grants by trigger and the server tells the helper to
stop them. The helper reports a grant only after both native choices, and the server
revalidates the line against the lines visible to the owner. Machine credentials cannot create or
revoke grants, and a different human cannot revoke the owner's grants. Access pauses on
the secure desktop and resumes only while the same window and grant are still live.

**Compatibility.** The helper announces `windows` in its hello: 1 shares a window with a line, 2 (helper 1.2.0) also takes
window screenshots; helpers before 1.1.0 omit it.
For a helper that announces it, `list_share_targets` returns every visible line (with an empty
`processes` list where none is attached) and `window_grant` carries `line_id`. A helper that
omits it still picks a process, so it is offered only lines that have a live process, and its
`window_grant` carries `attachment_id`. The server maps that attachment to its line and
grants the line, not the process, so the whole line gets the window. The old tray shows the
chosen process's handle and the line, and the grant is not tied to that process afterward.
A `window_grant` with neither a usable `line_id` nor a mappable `attachment_id` is refused with
"update the Partyline helper". A current helper that sends only `attachment_id` is refused the same way.

`screen_elements` captures that window's whole UI Automation tree without bringing the window to the
front or sending input, and the server keeps it. No page is too big, but an agent never receives it
all at once; each answer stays near 4 KB (about 3.4 KB of lines). A call with no arguments returns a
summary: window title, element count, counts by control type, and an outline of the main regions
with child counts (a web page's `Document` is opened two levels deeper, skipping single-child wrapper
chains; runs of alike unnamed siblings fold into `+N alike`, and rows of one shape show two examples).
The summary also calls out repeated structures so the common case is summary, then act: a `pager` (a
small subtree whose links are named 1, 2, 3 or next/previous) with each link's id, and "N similar DataItem
rows in Table ..." with an example. From there the agent explores the stored tree like a filesystem, with
no new read:

| Question | Arguments |
| --- | --- |
| `ls` | `root=<id>`, `depth` 1 to 3: the children, each with its child count |
| `find` | `query` matches the **name**, `value` the value (both given: both must match), and/or `control_type`; `root` limits it to a subtree. Terms: `a|b` either; `=x` or `^x$` the whole text; `^x` starts, `x$` ends; otherwise a case-insensitive substring. Matches are grouped under an `in: Document > List Pagination` line that is repeated only when the ancestors change; unnamed `Group`/`Pane`/`Custom` wrappers are left out of the path |
| `text` | `text=true`: what a person reads, in reading order. `Text` nodes, leaf names, `Edit` values, and the accessible name of an item (`DataItem`, `ListItem`, `Button`, `Hyperlink`, ...) whose own text below does not already say it (a row named "Book in Series Title" holding only "Series"). `query` greps it (same terms) with `context` lines around each hit; `root` scopes it (default: the first `Document`) |
| `id` | `id=<id>`: one element whole, like `cat`: its full name (up to 1,000 characters) and value (600), actions, child count and `in:` path |
| `changes` | `changes=true`: what the last `refresh=true` added (the topmost new elements) with a `+added -gone` count; `offset` pages it |
| paging | a long answer ends with `more` and `next_offset`; pass `offset` to continue |
| `refresh` | `refresh=true` takes a new snapshot now; ids of unchanged elements stay valid |

Role-less popup triggers with standard ARIA `haspopup` (`listbox`, `menu`, `true`), `expanded`, or
`controls`/`owns` targeting a List/Menu are mapped to ComboBox (with a popup hint), so
`screen_elements(control_type="ComboBox")` can find them on CDP and UIA. Existing computed/native widget
roles (Button, Hyperlink, Edit, TreeItem, etc.) stay intact and can expose the popup hint. A hint adds no
input capability; use the listed actions or a look mark's guarded point fallback. UIA resolves IDREFs
through one cached List/Menu index per provider read, rather than a descendant search per trigger.

There is no regex search: a backtracking pattern over tens of thousands of names could stall the server, so `find` and `text` take the plain terms above only.

Lines read `id Type "name" ="value" [actions] flags`; `bounds=true` adds screen and frame-pixel
rectangles. A lone `scroll_into_view` action is not printed, `off` marks an off-screen element. Lines clip
a name at 240 characters and a value at 80 with `…` (the stored fields keep 1,000 and 600; read them with
`id`). The helper now sends names up to 1,000 characters and values up to 600 (it used to cut both at 160),
so **the helper must be updated to read past 160 characters**; an older helper still works, with its names cut
at 160 (automation ids stay at 160). Text is stripped to one line; password values and other windows'
elements are excluded. Element metadata may include offscreen text from the selected window. Every id
in the stored snapshot is a `screen_element_action` target, so a deep element found by `find` can be
acted on directly.

**Stable ids.** The server gives each element a short id (6 base-32 characters) hashed from its type, name,
value, automation id, its place among identical siblings and its anchor: for an element with a name or
automation id, the nearest ancestor that has one (so a new unnamed banner or a "Previous" item in front of a
pager does not renumber the links); for an unnamed element, its parent. `Window` and `Document`
names and the values of `Edit`, `ComboBox` and similar controls are left out, so a new page title or typed
text does not renumber the page. After `refresh=true` an id still names the same element while that element
is unchanged, and the server translates it to the helper's current id for actions; an id that is no longer
in the stored tree fails with `unknown element id` and is not sent to the helper. An unnamed element's id
names a position, so after an insertion it can point at its neighbour instead of failing. If two different
elements hash to the same id, the later one moves on to its next candidate, and the server remembers which
element holds each id for as long as the window grant lasts, whatever happens to its trees (expiry, eviction,
a failed refresh), so a gone element's id is never handed to another one. A window that has been given
more than 100,000 ids starts a new numbering (every id changes and gains an `-1`, `-2`... epoch suffix, so an id from before can never name an element after) rather than forget a claim. A summary's pager and repeated-row lines are clipped to 200 characters each and share a 900-byte budget. The helper's own ids
(16 or 64 hex digits) from the same snapshot are still accepted. Stable id translation is server-side, and a helper older than the whole-window capture still works
as before. Optional event-clock and inspect metadata below requires the updated helper.

How the capture works. The helper walks the tree depth-first in tree order, in parts of at most 2,000
elements, 10,000 visited nodes or 3 s, whichever comes first. A part that stops early returns a
`next_cursor`; the server follows cursors until the window is done, for up to 20 s per call and 60,000
nodes. A larger window comes back marked `partial` and `more=true` continues it from the same cursor, so
no cap is a dead end (there is no depth limit, since the walk is iterative). The helper keeps each
part's ids and paths, merged, until the next plain snapshot; a cursor from an earlier snapshot is
refused as expired. The server keeps at most 16 trees. New helpers permit reuse only after a live subscription/event-counter barrier; without confirmed events every read recaptures. Older helpers retain the 3-second expiry and pushed-event fallback. UI Automation property and structure events invalidate a grant's tree, retaining it only as a delta baseline. A cursor remembers, for each unread section, which element it hangs under and how many children that element had; if the page changed when a part resumes, those sections are dropped rather than read from shifted positions, and every answer carries a `changed` note telling the agent to `refresh`. Each answer reports `snapshot_age_seconds` and `change_event_since_snapshot`. Stored trees total at most 300,000 nodes (120,000 in one), go when their grant ends or a refresh starts, and answers are measured in UTF-8 bytes (4,096 at most, title and hint included), so CJK pages fit. An older helper sends a flat list: summary and `ls` work on it, with a note to update the helper. The first part's whole-tree prefetch runs under the start limit, not the part's 3 s budget. Every part runs in the
isolated child process (killed about 12 s after its budget); the unread frontier travels to the child in
a file, because it can be far longer than a command line. Unnamed, patternless
`Pane`/`Group`/`Custom` wrappers are walked but not listed.

Speed. The Windows provider asks UI Automation for a cache request (control view; the properties and
pattern-availability flags, plus Value, Toggle, SelectionItem and ExpandCollapse state) so a node costs no further cross-process
calls. The first part prefetches the whole tree with one TreeScope_Subtree request; later parts, and the
action recheck, fetch a node and its children (TreeScope_Element | Children) once per parent. If the
one-call prefetch ever outruns its budget, the helper switches to per-parent reads for later snapshots.
The cached-children path and these timings were written without a Windows machine to run them on, so
they are unmeasured: the fake-provider tests pin the behaviour (a 5,000-node page is reached through
cursors, every node once) but not real Chrome timings. Measure `screen_elements` on a large page
once a Windows box is available and tune `MAX_ELEMENTS`, `BUDGET` and `KILL_SLACK` in
`partyline_helper/uia_snapshot.py` and `uia_process.py` if needed.

Errors, denied consent, closed windows and unsupported platforms return an unavailable reason.
macOS AX and Linux AT-SPI are planned. The Windows-only helper dependency `comtypes`
supplies the typed UI Automation COM interfaces; it is not installed on other platforms.

### Look at a window

Use `screen_window_look(window=W, detail="thumb", query?)` when the text read does not explain
what is on screen; otherwise prefer `screen_elements` and text deltas after actions. It is listed
wherever window grants are available, and callable through `extras` for clients that do not re-list.
Helper 1.7.0 (`windows: 5`) takes a fresh element read and the window image back to back under
one window operation lock, for both CDP transports and UIA. They carry one shared `generation`.
Events during capture add a `changing` note: element state may lag the image. A busy page
still returns a bounded look, and boxes and list always use the same captured nodes.

The MCP answer contains one image with a light coordinate grid and numbered boxes, plus one
compact state line per box, for example `[7] Button "Save" invoke,press focused`. Lines also show
checked, selected, disabled and value state when available. Visible elements with bounds get
boxes even without actions (`no actions`). Actionable elements come first, then smaller areas;
at most 80 boxes are drawn, with a truncation note. `query` uses the same name matching as
`screen_elements`, before the cap; every drawn box has exactly one matching list entry. Elements
clipped outside the image or too small to draw have no box and no list entry. Partial tree reads
also report truncation. The answer includes `snapshot`, `generation`, a coordinates note and
`image_tokens`. Box geometry uses the same screen/CSS-to-image mapping as snapshot marks.

`thumb` fits within 1000 pixels on the longest edge and 700,000 total pixels (about 930 image
tokens). `slim` fits within 1600 pixels; `full` preserves the window's own size. The helper resizes
before drawing so labels stay readable and point coordinates name the delivered image's pixels.

Act with `screen_element_action(window=W, mark=7, action="invoke")`, giving exactly one of
`mark` or `element_id`. A supported named action uses the normal CDP/UIA element route and its
guards. Otherwise `invoke` or `click` uses the box centre through `screen_window_click`'s existing
route: snapshot freshness, geometry, hard floor, consent, deadlines, hit and cover checks all
apply. It uses CDP page input or the consented real cursor, never script clicks. `force` cannot
bypass point guards. Other unsupported actions are refused. Marks have increasing numbers and
belong to the latest look by that caller; another look invalidates the older generation.
Unrelated events and ordinary reads or actions do not discard marks. Named actions still perform
the existing source-scoped freshness checks, and point actions retain snapshot and geometry guards.
A stale mark says `take a fresh screen_window_look`. Successful actions keep text deltas; use `then={}`
to read them.

### Screenshot of the chosen window

`screen_window_snapshot` (listed with `screen_elements`; on clients that never re-list, `extras(op="screen_window_snapshot")`)
returns one image of a window shared with the caller's line, and of nothing else. It is not the default way to
work in a window: read `screen_elements` first, and the deltas after each `screen_element_action`; take a
screenshot only when layout or visuals matter, or when elements do not explain what is on screen. The grant
notice an agent receives says the same. It needs no pixel share and no monitor region, so an agent with only a
window grant never has to ask for the whole screen.

- **Capture.** The helper takes that window's own content with Windows Graphics Capture for one window handle,
  falling back to `PrintWindow(PW_RENDERFULLCONTENT)`. A covered or partly off-screen window comes out whole;
  desktop pixels, which would include other windows, are never grabbed. A minimised window is refused with a
  plain error and is never restored. Protected (DRM) content is drawn black by Windows; an all-black result
  carries a `note` saying so.
- **Access.** The same as `screen_elements`: only processes on the grant's line, machine credentials need read
  access to that line, other lines get the same refusal, and a grant that has ended is a clear error. The route is
  `POST /api/conversations/{conv_id}/screen-window-snapshot?window=&device=`, and the window is resolved only
  through `resolve_window`, as for elements.
- **No limits on the picture.** It is the window at its own resolution, with no size cap and no rate limit; the
  person's visibility is the audit below. The helper sends it as a lossless PNG, in as many 4 MB binary
  messages as it takes. Only if that exceeds what the media store itself accepts (20 MB) does it use the highest
  WebP quality that fits (never fewer pixels).
- **Thumb tier (the default with marks).** A snapshot with `marks: true` is shrunk by the helper to at most
  1000 px on its longest side and 700,000 pixels (a 1920 x 1080 window becomes 1000 x 562, about 750 image
  tokens; no shape costs more than about 930), before the boxes are drawn, so the labels stay legible and the
  recorded geometry is the small picture's. The answer carries `budget` (`tier`, `max_edge`, `max_pixels`,
  `image_tokens`) and no `full` variant. `tier=full` keeps the window's own size. A plain snapshot (no marks)
  is the window's own size, as before.
- **Variants.** The media store keeps the capture as the original and derives `slim` (at most 1600 px) and `thumb`
  (at most 512 px) as it does for every image. The result lists `full`, `slim` and `thumb`, each with its `url`
  (`/api/media/<id>/original|slim|thumb`, which `get_media` also fetches), `width`, `height` and `image_tokens`
  (width x height / 750 after a model's own resize). `slim` is the usual choice; `full` is the window's own pixels.
- **Result.** Also `file` (the same reference as `screen_frame`, whose `urls` an agent can post to the line),
  `window`, `title`, and `unchanged`: true when the bytes match this agent's previous capture of the window, in which
  case the stored file is reused. An unchanged window answers compactly with `unchanged: true`, the previous
  `file` id, the size and the new `snapshot` id (and `marks_unchanged: true` instead of repeating marks the
  agent already has); use the earlier picture with that snapshot id.
- **Marks.** `marks: true` overlays a light coordinate grid (a line every 100 image pixels, labelled at the
  edges) and numbered boxes for the visible, actionable elements of the latest `screen_elements` read of that
  grant (at most 60; elements that can do no more than scroll into view or press are left out), and lists each
  in the compact form `{n, id, role, name, box}` (`name` at most 40 characters). Every coordinate is a pixel of the returned
  image, (0, 0) at its top left. With no earlier read the grid still appears and `marks_note` says so; a read
  and a click discard the stored tree, so read again before asking for boxes. Every snapshot returns a
  `snapshot` id and its `coordinates` note; the helper records the picture's window rectangle, per-axis
  scale, DPI, client areas and grant generation under that id, for `screen_window_click`.
- **Audit.** Each capture is recorded in the screen control audit (who asked, the grant, the size) and noted in the
  line; the helper's local audit records it too. The tray's window label reads "last screenshot HH:MM by @handle"
  and the web window-grant list carries `last_screenshot` for the grant.
- **Protocol.** The server sends `snapshot_window` (`request_id`, `grant_id`, `agent`); the helper
  answers `window_snapshot` with the same `request_id`, `ok`, and either `error` or `mime`, `width`, `height` and
  `media: true` and `chunks: n`, followed by n binary messages that join into the image.
  The helper checks consent once more under its writer lock immediately before the first byte leaves, and the
  server checks once more after it has stored and announced the capture, immediately before it answers; if the
  grant ended in between, nothing is sent or returned, the new media is deleted, and the audit gains a "withheld" entry. Only a helper whose hello says `windows: 2` is asked; an older
  one is told "update the Partyline helper to use window screenshots" at once, never left to time out.

### Act on elements in the chosen window

This is the first way to act: read with `screen_elements`, act with `screen_element_action`. It names a control,
so it is precise, fast and cheap, and survives layout changes. Pictures and point input are the fallback, never
a step of their own, and a script click on a page is never the answer.

**When an action fails.** A failure a picture can explain (the element is covered or outside the viewport, was
not found, is stale, or the page never settled) carries a `screenshot` with it: a thumb-tier picture of the
granted window alone, a `snapshot` id and the numbered `marks`, taken right then from a fresh tree read (bounded
to 20 s, and only for a caller who may read the window). Take the point from that picture and call a point tool
(see *Point input in the chosen window*) without another look. A revoked grant, a refused consent, a floor
program or a vanished window carry no picture. An element-action success carries no image; pass
`then: {"snapshot": true}` to get one after the action. The default `then` answers with what changed only (`diff` with added, removed and
updated ids, and its notes), not a full re-read; any other `then` option reads as before.

With a window granted to its line, any process on that line can call
`screen_element_action` with an ID from the current `screen_elements` snapshot (any part, or one remembered
from an earlier snapshot whose element is unchanged), using the matching
UI Automation pattern. Each snapshot element lists its `patterns` and the `actions` it supports; the
helper reads pattern state (range, scroll axes, window abilities) only for the action's target.

| Action | Pattern | Parameters |
| --- | --- | --- |
| `invoke`, `toggle` | Invoke, Toggle | none |
| `set_value` | Value | `value` (text) |
| `press` | UIA focus, then window messages | `key`: `enter`, `tab`, or `escape` only |
| `select` | SelectionItem; ComboBox expands then selects an option | `value` (option name) on ComboBox; none on an option |
| `add_to_selection`, `remove_from_selection` | SelectionItem | none |
| `expand`, `collapse` | ExpandCollapse | none |
| `scroll` | Scroll | `direction` (`up`, `down`, `left`, `right`), `amount` (`small`, `large`) |
| `set_scroll_percent` | Scroll | `horizontal_percent` and/or `vertical_percent`, 0 to 100 |
| `scroll_into_view` | ScrollItem | none |
| `set_range_value` | RangeValue | `number`, within the element's minimum and maximum |
| `window_close`, `window_minimize`, `window_maximize`, `window_restore` | Window | none |
| `window_move`, `window_resize` | Transform | `x`, `y` (screen pixels) / `width`, `height` |

**Commit a field.** After `set_value`, use `press` with `key="enter"` to request navigation or
submission. Prefer `invoke` on a submit/default button when the UIA tree exposes one: UIA has no
general Enter/submit pattern. For Enter, the helper first checks the field's immediate container
for enabled Invoke buttons named Submit, Search or Go (case insensitive). A match returns
`status:"no_effect"`, a `native_submit` selector and a `hint` to find and invoke that button; it
does not guess a button or post a key. Other names, localized buttons and deeper form structures
can still be found with `screen_elements` and invoked explicitly.

Otherwise `press` calls UIA `SetFocus` on the target and posts only
`WM_KEYDOWN`, `WM_CHAR`, `WM_KEYUP` to its own HWND. Chrome page content uses a
`Chrome_RenderWidgetHostHWND` in the target's ancestry, or the unique renderer child containing
the element's center; ambiguous/missing renderers are refused. Chrome's omnibox uses its top-level
window. Other controls use their nearest native ancestor within the granted window. There is no
global keyboard injection, modifier support, mouse movement, thread-input attachment or activation
call. If the app changes foreground during UIA focus, or UIA cannot confirm the target's focus,
no key is posted; the result reports it.
The grant checks, per-window lock, revocation barrier and audit are the same as other actions.

Queueing messages is not success: `posted` counts messages accepted by Windows, while `status`
is `completed` only if the immediate read observes a value, focus, title or address-bar change.
`observation` contains `before`, `after`, and `changed`; the baseline is taken after focus preparation,
so SetFocus alone never counts as a key effect. Observation text is bounded in bytes (with
`truncated:true` when shortened); comparisons use the full values. Password values are excluded. The URL observation
is available only when the action target itself is a recognized address control (English names or
omnibox/addressEditBox automation IDs), using its Value, never a page field. Helper 1.3.0 no longer
walks browser chrome to find a separate address bar for a page-field target; use `then` to read the page
after a key, and do not treat a missing URL observation as proof that navigation did not happen.
Unsupported providers, missing HWNDs, focus/delivery failures,
or unchanged state return `status:"no_effect"` plus `hint`. A stale element after navigation can also
prevent immediate confirmation. Use `then` or a fresh read for delayed effects; `no_effect` describes
the immediate observation, and `after` independently reports the later tree. Never retry automatically.

**Chrome evidence and limits.** Chromium's
[renderer keyboard handler](https://github.com/chromium/chromium/blob/main/content/browser/renderer_host/legacy_render_widget_host_win.cc)
forwards keyboard messages to its window event target. This supports the HWND route, but does not
establish that Chrome will accept background Enter on every version, focus state or page. Microsoft's
[PostMessage contract](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-postmessagew)
confirms asynchronous delivery and integrity-level restrictions; it promises no application effect.
No native Windows/Chrome test was available for this change. The exact live procedure is in
[screen-press-live-check.md](screen-press-live-check.md); record observations there when run.

**Compatibility.** Helper 1.2.0 announces `press: 1` in hello. A helper without that capability is
refused before any capture or action exchange with “update the Partyline helper to use press”.
Existing UIA actions continue to work with older helpers.

**Click then read.** `then` takes the `screen_elements` read fields (`query`, `value`, `control_type`,
`root`, `id`, `text`, `context`, `depth`). After a completed action the server takes a
new snapshot at an event-counter boundary and returns the answer as `after` (also for `no_effect`), within the same 4 KB for the action result and the answer
together. The next separate `screen_elements` read recaptures again, so a delayed app update is not hidden by the immediate post-action snapshot. The client waits up to 160 s for a call with `then` (100 s without), allowing time for a multi-part pre-action snapshot and action. An empty `then` returns what is new: the topmost elements the new snapshot has that the old one
did not (ids are stable, so a page change lists the new rows and not the unchanged chrome) and a `diff`
count `+added -gone`, plus `~updated` for changed state on stable ids. The read needs read access to the line as well as write. If the share ends meanwhile,
`after` says so and the action result is kept.

The helper rechecks the window, element identity, containment, enabled state and supported pattern
before dispatch, and refuses an element that lacks the pattern with an error naming the actions
it does support. Password fields and read-only values or ranges cannot be set, a range value outside
the element's minimum and maximum is refused, scrolling needs a scrollable axis and expand/collapse
a node that can expand. Window actions apply only to the element that is the shared window itself
(the first snapshot element), never to a child or another window, and honour its minimize, maximize,
move and resize capabilities. Dragging stays on the pixel path (`screen_drag`).
`window_close` asks the window to close. If the window is gone when the call returns the result
says `window_closed` and the grant ends; if the app keeps it open (an unsaved-changes prompt) the
result says `close_requested`, the grant stays, and it ends as soon as the window disappears. The
response includes the element's updated name, role, enabled and value, toggle, selection, expand,
range, scroll or window state when available (and the new bounds after a move or resize). Partyline does
not synthesize global mouse or keyboard input, move the cursor, or call an activation API for these
actions; `press` uses only the scoped messages described above. The target application can nevertheless
bring itself forward in response; classic
Win32 buttons and checkboxes can do so on Invoke or Toggle, restoring a minimized window usually
activates it, and other apps may activate or open dialogs. The response and local audit include
`foreground_changed` and `target_came_forward` after the pattern call and the element re-read. A
timeout or refusal before dispatch cannot report those observations.

Window actions do not arm physical mouse or ordinary-key takeback. Stop that window grant
in the tray or web computer list, or choose Stop all sharing, to stop further actions.
Lock and UAC pause actions; closing or replacing the selected window ends its grant. A pattern call already
dispatched when consent is revoked can still complete: the result says `revoked_during`, and no
further action can start from that grant. The deadline covers the operation; a timed-out call is
abandoned and never retried automatically. UIA providers execute in the target application and
may therefore have application-specific effects.

Each action is recorded in the helper's local hash-chained audit with the requesting agent,
process, role, name, action and outcome. For `set_value` the audit records the value's length,
not the submitted text; numeric and enumerated parameters (direction, amount, percentages, number,
coordinates, size) are recorded as given. Every action uses its window grant,
dispatch gate, rate limit, local audit and revocation, independently of pointer control.

### Point input in the chosen window

Prefer `screen_elements` and `screen_element_action`. When the tree cannot act on something (a canvas, a
custom-drawn widget, an element a hit-test misses) or an action failed, take the `screenshot` the failure
carried (or `screen_window_snapshot` with `marks: true`), look for the point, and use a point tool. Never click
or type with page scripts. All five are listed beside `screen_element_action` wherever a window grant is, take
`window` and `capture=none|thumb`, and answer with the route taken, a `settle` state and, with `capture: thumb`,
a thumbnail taken afterwards:

- `screen_window_click(snapshot, x, y, button=left|right, clicks=1|2)`
- `screen_window_scroll(snapshot, x, y, dx, dy)`: wheel steps at the point; `dy` > 0 scrolls up, `dx` > 0
  right, at most 50 steps either way. CDP sends one `mouseWheel` of 100 CSS pixels per step; the real route
  sends 120-unit wheel notches.
- `screen_window_drag(snapshot, from, to)`: press at `from`, move through a short checked path, release at
  `to`. It is plain mouse input, so it moves sliders, selections and canvases, but a page that uses HTML5
  drag-and-drop may not react.
- `screen_window_type(text)`: at most 500 characters (printable text, new lines and tabs) into the field the
  last click focused.
- `screen_window_key(keys)`: one combo such as `enter`, `ctrl+a` or `shift+tab`.

`type` and `key` name no point. They need a successful `screen_window_click` earlier in the same window grant
(a re-grant forgets it) and go to where that click put the focus; otherwise they are refused before anything is
asked. They are refused when the focused field is a password field or cannot be inspected: on a Chrome page the
helper walks the focused element through shadow roots and same-origin frames (a cross-origin frame, no focus, or
a masked text field counts as unknown), and on the real route UI Automation's `IsPassword` must say false. Keys
that only move or edit (tab, arrows, backspace, ctrl+a) are not typing and may go to a password field. On the
real route a Tab or Enter inside `text` moves the focus, so the field is inspected again before any character
that follows one and the typing stops there (the answer says how many characters went in). Each run is also
guarded again, after that inspection and just before it is sent: the deadline, revocation, consent and the window
in front are re-checked, so no input follows a condition that failed. A key combo that
holds modifiers is lifted again if its send is cut short. A character key takes the Shift the keyboard layout
needs; on a Chrome page `shift` plus a digit or punctuation key is refused (what it types depends on the
layout), so use `screen_window_type` for symbols. Never
sent on either route: the lock, log-out and session combos pixel control already blocks, clipboard combos
(ctrl+c, x, v, insert, shift+insert, shift+delete: the clipboard stays guarded) and alt+f4 (use the
`window_close` action). The real keyboard also refuses the Windows key, alt+tab, alt+esc and ctrl+esc, which
leave the granted window.

- **Coordinates.** `x` and `y` are pixels of the named snapshot's image. The server converts them with the
  geometry the helper reported for that snapshot (`rect`, per-axis `scale`, `dpi` and the client areas) and
  refuses a point outside the image or outside the window's client area (frame, title bar and shadows are not
  clickable; controls there go through `window_*` element actions). The helper converts again with its own
  record, never with the server's numbers, and the two must agree.
- **Landing evidence.** Every point-operation reply has `landing`, with `snapshot` and `points` (both
  endpoints for a drag; empty for typing and keys). Each point reports `snapshot_point`, `screen_point`
  (physical screen pixels), the raw `hwnd` and `class` returned by `WindowFromPoint`, `granted_window`
  (the handle is the grant itself), and `page_area_child` (a child belongs to the grant).
  Read each point's `landed_in` verdict: `granted_page` means a child whose `GA_ROOT` is the granted HWND,
  `granted_window` means the grant's own chrome/frame, and `other_window` means another root, with the hit
  class and a warning. This ownership check works for every app; renderer class names are not authority.
  `dpi` and `dpi_scale` (DPI / 96) describe the named snapshot; `image_scale` is image pixels per physical
  screen pixel on each axis. DPI is never multiplied into the physical mapping a second time.
  `foreground_before` and `foreground_after` say whether the grant or its owned dialog was foreground,
  before activation and immediately after input, before restoring the person's foreground. `input_sent`
  distinguishes observed input from a refused attempt. Unknown observations are `null`, including old
  helpers and transport timeouts; these fields contain no page text. On CDP, `screen_point` is the mapped
  physical equivalent: input goes to the page in CSS pixels and the hit window is observational only.
- **What changed.** After a click, read `changes` before deciding it failed. Every point operation,
  including a look mark falling back to a point, compares read-only element observations before and after
  input, on CDP and UIA. `changes` lists appeared/disappeared elements and state transitions (for example,
  `expand_state collapsed→expanded`), with ordinary actionable element IDs. New Lists/Menus include option
  IDs and names. The reply caps the delta at 20 lines plus a `more` note; read `screen_elements` for the rest.
  The helper computes this delta locally, sending only changed rows and option samples under a 128 KiB
  wire cap; whole before/after trees are never combined into a reply. Partial observations are labelled and
  never claim missing elements disappeared. Read failures are explicit; the text delta needs read permission.
  The pre-input read has its own 500 ms cap and is skipped with at most one second of input budget left,
  so a diagnostic read cannot consume the approved input's whole start budget.
- **Settling.** Quiet barriers reset on real change events; they never poll. Waiting stays within the
  existing two-second CDP / 200 ms UIA settle limits, plus at most 500 ms for a final read, and never exceeds
  the action's existing deadline. The final read has reserved time even when quiet waiting expires; a busy
  page does not hold the window lock for the full consent/input budget. Events during a read can restart
  the barrier within this short bound. If the window keeps changing, `settle: changing` and
  `still changing after N ms` accompany that final observation's delta (or an explicit read failure).
- **Reading a miss.** Unchanged outcomes (`settle: unchanged`, `status: no_effect`, or an unchanged requested
  `after` image) with no clear element change, and windows still changing at the deadline, attach
  `landing_thumb`: a crop of at most 240 × 240 pixels of the granted window around the last
  landing point, with a red crosshair edged in white. It needs read permission, captures no desktop pixels,
  and supplies no new coordinate snapshot. Compare the crosshair with the intended control. An unexpected
  physical point suggests image scale or offset; an unexpected handle/class suggests a covering window or
  layer. A false foreground-before followed by true foreground-after records activation: the helper
  activates first, confirms foreground, and then sends a separate page click. A correct crosshair and
  target with unchanged pixels suggests the component ignored input; it does not prove that no state changed.
  Do not repeat input automatically. If the window moved away from the landing point, the crop reports that
  failure instead. At most one crosshair crop is attached; a clear settled delta needs no image.
- **Stale pictures.** The click is refused, with "take a fresh `screen_window_snapshot`", when the snapshot
  is unknown or older than the last eight for that grant, or when the window moved, resized, closed, or was
  re-granted, or when the secure desktop is up. The check compares the live rectangle and client areas with the
  recorded ones and the grant generation, so a picture can never misdirect a click.
- **Hard floor.** Terminals, password managers, OS security windows and Partyline's own windows are never
  clickable, by grant or by what is under the point.
- **Route 1, Chrome with a CDP connection.** The click goes through `Input.dispatchMouseEvent` on the page's
  own session (hover, then press and release, `clickCount` 2 for a double-click). The helper maps the point to
  CSS pixels from the page area's rectangle and the viewport width, so browser zoom and DPI are exact; a
  point on the browser's own controls, a pinch-zoomed page, or a grant on a tab that is not the one
  shown in the window is refused.
  **Finding the page area.** The helper takes the visible `Chrome_RenderWidgetHostHWND` child windows of the
  granted window. One is the page. Of several (side panel, split view, embedded surface) the page is the one
  whose size is the viewport's (`innerWidth` and `innerHeight` times `devicePixelRatio`, within 2%) and that
  holds the clicked point; a point on none of them is on the browser's own controls, and the click is
  refused as ambiguous only when two of the same size both hold it. Recent Chrome builds can drop the
  renderer child window altogether; the helper then uses, in order, the UI Automation `Document` element of
  the active tab inside the granted window (its `BoundingRectangle`; empty rectangles are ignored, and it must
  be the viewport's size within the same 2%, chosen the same way if there are several). With neither, the
  click is refused: the window's CDP bounds give the page's size but not its place (a toolbar above the page
  cannot be told from a panel below it), so they are never used to guess where the page is. Every source goes through the same pinch-zoom and
  resize check, and `screen_window_snapshot` marks use the same resolver, so a snapshot and a click agree.
  When nothing is
  found the error says what was seen, for example "found 0 renderer windows and no page document" or
  "found 3 renderer windows, none matching the viewport". No cursor moves, no window comes
  forward and no consent prompt is shown: it is allowed under standing access and under any window grant, as
  CDP element actions are. It works over iframes, since the events enter at the top-level page.
- **Route 2, any other window (or Chrome without CDP).** A real-cursor click with `SendInput`, confined to the
  window. The helper brings the window forward the way UIA actions do (best effort, never restoring a
  minimised window), moves the cursor to the point, and checks that the window under the point is the granted
  window or a dialog it owns, is not a hard-floor program, and that the foreground has not changed. Any miss
  refuses with nothing sent. The slow checks run first; then, with the window in front, the helper re-checks
  revocation, the person's consent and the window's place against the snapshot, and the point's target, with
  nothing slow before the input. One `SendInput` call moves to that checked point and does every press and
  release, so a cursor moved meanwhile cannot redirect it and no button stays down. The deadline and the person's consent are judged
  last, after every blocking call. A CDP click is also bounded: no press starts after the budget or after 20 s
  of input, and a press whose answer failed is followed by a release attempt, reported only as
  released when it was confirmed. Real-cursor clicks run one
  at a time across all grants. It
  then puts the cursor and the previous foreground back where it can; `cursor_restored`,
  `foreground_restored` and `target_came_forward` report what happened.
- **Consent.** The first real-cursor operation (any of the five) on a grant shows a prompt on that computer,
  "Allow `<line>/<agent>` to use the mouse and keyboard in `<window title>`?", with **Allow for this window**
  and **Deny**; one answer covers every kind of input in that grant. Allow lasts as long as that grant: it ends when the grant is stopped or its window closes, when
  access is paused, when the helper disconnects, and when standing access is switched off (an answer that arrives after that is discarded). A Deny refuses
  that click and any further asks for two minutes. While a click is running the tray shows
  "using your mouse".
- **Audit.** Each operation writes the grant, line, process, operation (`screen_window_click`, `_scroll`,
  `_drag`, `_type`, `_key`), route (`cdp` or `cursor`), the point (image and screen pixels; both ends of a
  drag) and the result to the helper's tool audit before any input is sent (a log that cannot be written
  refuses it), and again with the outcome; the server's screen control audit and the line notice carry the
  same, and the helper's recent-activity log lists `point_<op>`. Typed text is never recorded, only its
  length, and no pixels are.
- **Deadline.** The server tells the helper how long it may take to *start* the click (`budget`, 40 s from
  arrival) and waits 70 s for the answer, so a click never goes through after the server has reported it
  `unconfirmed`. A consent answer that arrives after the budget is discarded and nothing is sent.
- **Same rules for every operation.** Scroll and drag convert their points with the snapshot's geometry
  exactly as a click does (a drag converts and checks both ends, and on the real route every point of its
  path), and every operation goes through the same checks: the same stale, client-area, floor, window-under-
  the-point, foreground, consent and revocation refusals, the same server deadline judged after the last
  blocking call, and one real-input operation at a time. A refusal sends nothing; one about the point (an unknown
  or evicted snapshot, a point outside the client area) is answered as a failure (`status:"failed"`, `reason`
  `stale` or `outside`) with the same marked thumb as any other failure.
- **Protocol.** The server sends `window_click` for a click (`request_id`, `grant_id`, `snapshot`, `x`, `y`,
  `screen`, `button`, `clicks`) and `window_point` with an `op` for the others (`dx`, `dy`; `x2`, `y2` and
  `screen2` for a drag; `text`; `keys`), so a helper that predates an operation cannot read it as a click. The
  helper answers `window_element_result`; a refusal a picture can explain carries `reason` (`covered`, `stale`
  or `outside`), and the server then attaches the failure `screenshot`. A snapshot reply carries
  `snapshot_id`, `geometry` and `marks`. A helper whose hello says `windows: 3` is asked to click only; one
  that says `windows: 4` does all five; an older one is told to update at once.

## Accessibility lab

Open **`/lab/a11y`** in the normal Chrome window and share that window. This standalone page makes no API calls,
stores nothing, and follows the browser's light or dark theme. Each card keeps its control names stable except for
the intentional **Count** rename. The DOM state and UIA state should be compared, not assumed to agree.

| Card | What it tests | Expected UIA reading |
| --- | --- | --- |
| 1. Sync enable | A real `disabled` attribute removed synchronously by `change` | `Sync target` starts `disabled`; selecting A removes that flag. |
| 2. Delayed enable | Real `disabled` attributes removed at 300 ms and 2500 ms | An immediate `then` reads at its event-counter boundary; it may precede either deadline. Once both targets visibly enable, a fresh read shows neither as `disabled`. |
| 3. Looks enabled, accessibility says disabled | Only the link's CSS class changes | **`Class-only link` remains `disabled` in UIA after selection**, even though it looks enabled. This deliberately models the listing dashboard’s accessibility divergence. |
| 4. aria-disabled link done right | Selection removes `aria-disabled` | `ARIA link` starts `disabled`; selecting A removes that flag. |
| 5. Disabled ancestor | A button inherits disabled state from `<fieldset disabled>` | `Fieldset target` is `disabled` while `Fieldset disabled` is on, and enabled after toggle off. |
| 6. Name change | The button increments its own accessible name | Invoking `Count 0` produces `Count 1`, then `Count 2`. |
| 7. Structure change | A simulated fetch inserts three list items after 1 s | An immediate `then` can precede insertion. Once the list visibly appears, a fresh read shows `Item 1`, `Item 2`, and `Item 3`. |
| 8. Text field | UIA Value `set_value`, with independent DOM event indicators | `Text field` has value `hello`; the visible `input fired:` and `change fired:` lines report exactly which events Chrome emitted. |
| 9. Event log | The last 20 `change`, `input`, `click`, and `keydown` events | `Event log` is a live list with millisecond timestamps and control names; key events include `key=<key>`. |
| 10. Reset | Initial state restoration and pending-timer cancellation | All targets return to their initial states and the event log says `No events yet.` |

### Ordered live-retest script

For each ID below, first call `screen_elements(query="^visible name$")` and take the matching element under the
named card whenever that ID is not already in hand; the expected lookup line is the control line shown in the table.
For the repeated **A** options, query `^A$` and use the `ListItem` under the named card in the `in:` path. An expected
line shown without `disabled` means that flag must be absent.

1. `screen_elements(query="^Sync target$")` → `<id> Button "Sync target" [invoke] disabled`.
   Then `screen_elements(query="^A$")` → `<sync-a> ListItem "A" [select]` under **1. Sync enable**.
2. `screen_element_action(element_id=<sync-a>, action="select", then={"query":"^Sync target$"})` →
   `after: <id> Button "Sync target" [invoke]`.
3. Select **A** under **2. Delayed enable** with
   `screen_element_action(element_id=<delayed-a>, action="select", then={"query":"Delayed target"})` →
   record both targets' current flags. The immediate capture may precede either deadline; once each target
   visibly enables, its next read must omit `disabled`.
4. Select **A** under **3. Looks enabled, accessibility says disabled** with
   `screen_element_action(element_id=<class-a>, action="select", then={"query":"^Class-only link$"})` →
   `after: <id> Hyperlink "Class-only link" [invoke] disabled`. The green visual state does not change this expected result.
5. Select **A** under **4. aria-disabled link done right** with
   `screen_element_action(element_id=<aria-a>, action="select", then={"query":"^ARIA link$"})` →
   `after: <id> Hyperlink "ARIA link" [invoke]`.
6. `screen_element_action(element_id=<fieldset-checkbox>, action="toggle", then={"query":"^Fieldset target$"})` →
   `after: <id> Button "Fieldset target" [invoke]`. Toggle it again with the same `then` → the line ends in `disabled`.
7. `screen_element_action(element_id=<count-0>, action="invoke", then={"query":"^Count 1$"})` →
   `after: <id> Button "Count 1" [invoke]`.
8. `screen_element_action(element_id=<load-list>, action="invoke", then={"query":"^Item 1$"})` → record the current match;
   `then` captures immediately, so insertion may not have happened yet.
9. `screen_element_action(element_id=<text-field>, action="set_value", value="hello", then={"query":"^Text field$"})` →
   `after: <id> Edit "Text field" ="hello"`. Then `screen_elements(text=true, query="fired:")` → the two status lines;
   record their yes/no values rather than treating value mutation as proof of either event.
10. Once the page visibly enables both delayed targets and displays the loaded list, call
    `screen_elements(query="^Delayed target 2500 ms$", refresh=true)` → the line has no `disabled`, then
    `screen_elements(query="^Item 1$", refresh=true)` → `<id> ListItem "Item 1"`.
11. `screen_elements(query="^Event log$")` → `<id> List "Event log"`; its latest entries include the selection,
    value input, and invocation events with elapsed milliseconds. At most 20 entries are present.
12. `screen_element_action(element_id=<reset-lab>, action="invoke", then={"query":"^Sync target$"})` →
    `after: <id> Button "Sync target" [invoke] disabled`. Follow with
    `screen_elements(query="^Count 0$", refresh=true)` → `<id> Button "Count 0" [invoke]`, and
    `screen_elements(query="^Item 1$", refresh=true)` → no match. The text value, both event indicators, selects,
    links, checkbox, delayed targets, and event log are back to their initial readings too.

## Platforms and troubleshooting

- **Windows:** no administrator access required. Per-monitor DPI awareness is set
  before initializing capture or pointer reading so coordinates use physical
  desktop pixels, including negative origins. On Windows 10 2004 and later the
  border uses `WDA_EXCLUDEFROMCAPTURE` in addition to lying outside the region.
  UAC and secure-desktop windows are not captured. Keep the helper on the
  interactive desktop session.
- **macOS:** capture is unsupported pending a ScreenCaptureKit stream backend.
  Pointer reading does not require Accessibility permission; agent control does
  (below). The helper border can still be shown when PyObjC is installed.
- **Linux X11:** capture is unsupported pending an event-driven desktop stream
  backend. Wayland also needs the XDG desktop-portal ScreenCast route; it is
  rejected during helper startup today.

**Capture backend.** Windows uses the `windows-capture` binding to Windows
Graphics Capture. The helper resolves the consented region to the top-level
window under its centre, captures that HWND through a `GraphicsCaptureItem`,
and crops each `FrameArrived` image to the requested rectangle. Windows
Graphics Capture disables its capture border for this session. Updates arrive
only when the window content changes; the helper drops event frames above the
upload rate cap and never samples the window on a timer. Closing the window or
revoking the share stops capture. The native binding is included in the
Windows-only helper extra and explicitly collected by the frozen PyInstaller
build.

The helper's capture path is supported on Windows only. macOS and Linux capture
are currently unsupported. macOS needs a
ScreenCaptureKit stream backend; Linux needs an XDG desktop-portal ScreenCast
stream backend (Wayland and X11 are both unsupported by this helper build).
The helper reports no shareable monitors on those platforms and rejects a
capture request instead of falling back to periodic screenshots.

If pairing fails, check the origin, network, TLS certificate and code expiry.
If revoked, create a fresh code and pair again. If capture initialization fails,
verify desktop permissions and install the `helper` extra. The dependencies are
windows-capture (MIT; Windows only), pynput (LGPL-3.0), websockets and Pillow; pynput reads the pointer and,
only during agent control, injects input and listens for the kill switch. Automated tests use fake capture and an in-process server. The
headless development server cannot verify real desktop capture; native interactive
smoke testing is still required on each platform.

Window reading and actions are generic. The helper follows DOM, shadow-DOM, accessibility-tree and UI Automation rules that hold on every site and app; it carries no selectors, names or special cases for a particular website. When a site misbehaves, fix the general rule and test it with a neutral fixture.

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
point). Window element actions have separate grants and Stop controls. Ctrl+Alt+Esc
always revokes pixel control:

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


## Helper versions and updates

The helper has its own version in `partyline_helper/__init__.py`, independent of the
server. Changes to helper code, Windows packaging, or shared helper imports require a
helper version bump. Server changes require a server bump; a change touching both
requires both. Features bump minor, fixes patch, and breaking changes major.

On a green merge, CI tags changed helper versions `helper-v<version>` and builds
the Windows installer. Its release contains `PartylineHelper-Setup-<version>.exe`
and `PartylineHelper-Setup-<version>.exe.sha256`. The extension manifest version must
match the helper version; CI checks that before freezing. Pull requests also build
smoke-test artifacts. Server `v<version>` tags do not create helper releases.

At connection or reconnection the server compares the reported helper version with
its checkout. The tray and Computers list show available updates. Clicking the tray
item opens the exact versioned Windows installer; other platforms use the helper
install command. Legacy helpers reporting a Partyline 2.x version are flagged for
manual installation. Automatic installation never downgrades or guesses an unknown version.

**Install updates automatically** is available from helper 1.6.0 and is off by default.
Install that first supporting version once using the existing tray installer link. If an older
unpacked extension was already loaded, reload it once at `chrome://extensions` to load
the new updater code; subsequent opted-in updates reload and reconnect automatically. Enable it in the Windows tray
or Settings → Computers. The helper persists the choice beside its existing pairing
configuration. Computers can queue a change while offline; the paired person's
pending choice is sent on reconnect. Processes cannot change it. Changes are recorded
in the server's helper update audit and the helper's local `screen-access-audit.jsonl`.

After the new version is running, the tray shows a one-off **Partyline Helper updated to <version>**
notice, for automatic updates and for manual installs that replaced an older version. The helper
records the last announced version in `announced-version.json` beside its pairing configuration, so
it fires once per version, even across restarts. It never shows on a first install or on a restart at
the same version. A helper that predates this notice has no record, so its first run only records the
version: the first announcement comes with the next update.

With the setting enabled, a connection's update announcement makes one attempt.
If the installer or checksum is missing (404), nothing happens: the release has not
been published yet. Other transient download failures can be tried on the next connection or
published-release event, without a timer. There is no polling, sleep loop, retry timer, or added background
watcher. After both release assets exist, the captain makes one authenticated
`POST /api/screen/helper-release-published` with `{"version":"<helper-version>"}`.
Only a person or the root captain can announce the server's helper version. This
push reaches computers connected before the installer finished building. CI can
make the same call when `PARTYLINE_RELEASE_API` and `PARTYLINE_RELEASE_TOKEN` are
configured as a repository variable and secret; keep the credential out of logs.

**Pause, install, recover.** The helper announces the target version and waits for
an acknowledgment that the server paused its grants. Reads, actions, evaluations,
snapshots and clicks return `status:"paused", reason:"helper updating"` with a retry
hint, including while the helper is disconnected. Outstanding exchanges are released
with the same response. An earlier action may already have completed: inspect fresh
state before requesting another action; Partyline never repeats the action itself.

The helper saves window lifetime markers, the selected lines, standing access,
existing mouse consent, Chrome transport preference and unanswered native prompts.
Credentials stay in their existing private store. It invalidates action dispatch
barriers and cancels pending work with one bounded event wait; an open prompt does
not block installation. It then launches an independent supervisor and exits before
the installer copies files. A single three-second exit deadline also ends any abandoned
executor thread after the normal shutdown request. The per-user installer uses `/VERYSILENT
/SUPPRESSMSGBOXES /NORESTART /START=1 /AUTOUPDATE=1`: no elevation, UAC or close-applications
dialog. Each version has its own binary folder so the previous helper and native
host remain available without holding the new files open.

On restart, the server supplies only grants it still authorizes. The helper checks
the live HWND, process identity, lifetime marker, desktop/integrity and protected-window
floor before restoring each grant. A mismatch drops that grant and records a local
note. Trees and snapshot coordinates are discarded; read again. Pending mouse-consent prompts are
shown again without assuming an answer; the new answer applies to the restored window.
Other interrupted requests are shown as information notices containing the original
question and explaining that the request was cancelled. They have no discarded Yes/No answer.
An interrupted operation needs a fresh request.
After restoration the server lifts the pause and posts “helper updated to <version>;
window access resumed” on affected lines. Tray notifications and the local audit
record both the start and outcome.

The supervisor waits on process completion and a Windows event, with bounded installer
and reconnect deadlines. A failed installer or missing successful reconnect stops the
new instance, restores the previous executable's registration and extension files,
and starts it again. Registration also repairs the Start-menu shortcut and uninstall
icon to point at the restored executable. The old helper reports the failure and restores still-valid
grants. The server deadline includes the supervisor’s full install and rollback budgets plus
a final reconnect allowance. An abandoned pause revokes offline or unconfirmed grants and
reports that access ended. A late helper gets an empty recovery response without starting
a second pause or posting another failure notice. Failed
versions are remembered locally and are not automatically retried; the tray's manual
installer link remains available. A failure before exit removes its recovery intent and downloaded installer and restores
the access gates it invalidated. Completed attempts remove their downloaded installers.
After success, cleanup retains the current and previous binaries, any identified live native
host version, and newer installation folders; older unused versions are removed. If a live
host cannot be identified, pruning waits for a later update event. Uninstall removes all versions.

**Trust model.** Opting in grants the same release publisher the ability to run an
installer as clicking the tray's installer link. The helper constructs and checks the
exact `installer_info` URL, requires HTTPS with normal certificate and hostname
verification (including redirects), downloads into its own data directory, and
requires the matching release's SHA-256 sidecar. The checksum detects corrupt or
mismatched assets; it does not protect against a compromised release publisher who
can replace both files. Signed releases declare `# authenticode=required` in the checksum sidecar,
which requires Windows Authenticode verification even from an earlier unsigned build.
Builds made with `WINDOWS_SIGNING=true` also pin that requirement for future updates
through Windows Authenticode verification through `WinVerifyTrust`, with no signature UI
and certificate revocation checks. A missing or invalid signature fails closed. The
prototype remains unsigned until signing is configured; enabling automatic updates
does not supply an independent signing identity or bypass the Windows trust store.

### Helper 1.5.0

Point input beyond clicks: `screen_window_scroll`, `_drag`, `_type` and `_key` (hello `windows: 4`), the
failure `screenshot` and `then.snapshot`, and a thumb-tier marked snapshot (at most 1000 px and 700,000 pixels,
about 930 image tokens or fewer) with compact marks (`{n, id, role, name, box}`, at most 60). The consent
prompt now reads "use the mouse and keyboard". See *Point input in the chosen window*.

### Helper 1.4.0

Marked window snapshots and `screen_window_click`: a worker on a window grant can look at the picture and
click a point the element tree cannot reach, through CDP on a Chrome page or with a consented real-cursor
click in any other window. See *Point input in the chosen window*. The hello reports `windows: 3`.

### Helper 1.3.0

This release combines scoped owned dialogs, UIA action latency instrumentation and filtered
reads with retained action IDs, and approved Chrome CDP reads and actions. These changes
share one helper version.

#### Dropdown options and reported-disabled controls

A window snapshot includes its visible owned popups, labelled `popup: …` under the
shared window. Win32's owner chain must reach the granted HWND. Same-process popups
remain in scope; a popup in another process must be a top-level `#32770` dialog,
and every foreign process on its owner chain must have the same executable image path
as the granted process. Image lookup failures deny access. Popup UIA ProcessId and
NativeWindowHandle are checked too. An unrelated window, even from the same browser
image, cannot join without that owner chain. Content hosted by another process inside
the granted HWND remains readable and actionable through that granted subtree. Popup
controls are action targets under the same grant; actions identify their popup in the
local audit. Screenshots compose pixels captured from the granted window and its scoped
popups, with blank space between them. Hidden or closed popups add nothing to subsequent
reads. UIA events are scoped to the granted element and each discovered popup root. WinEvent
show/hide/destroy notifications invalidate reads and post messages to reconcile popup
subscriptions outside the callbacks. Persistent UIA handlers do not inspect sender
properties or walk desktop ancestry. Desktop scope is used only during the short Expand
deadline. No timed popup discovery runs.

Use `select` for dropdowns and `set_value` for text fields. On a ComboBox,
`select(value="shop.uk")` expands it if needed, searches its children, then nearby
Lists and owned popups (newly appeared lists first), uses SelectionItem.Select on the
exact option name, and requests collapse. Chrome can expose a dropdown's List as a
sibling under the Document rather than under the ComboBox. Ambiguous names require
reading and selecting the option's own id. The response includes `selected_option`
and `value_changed` (null if the provider cannot expose the value). If cleanup fails
after selection, `collapse_failed=true` preserves the selection result; cleanup also
never replaces an earlier selection error. Selecting an option
directly also uses SelectionItem.Select. This is the pattern Chrome uses for a genuine
selection and its page `change` event; setting Value is not a substitute.

Expand, collapse, toggle, select and set_value return `status="completed"` with
`effect="changed"`, `"none"` or `"unknown"`, comparing the exposed pattern state before
and after. An unchanged value reports `none`. A provider that cannot expose state
reports `unknown`, rather than claiming a change. Native Expand allows one structure-event deadline (up to 250 ms) before reading its
result; there is no repeated state check. Expand also reports `options_found`,
a bounded preview in `option_names`, and whether an option container appeared. Chrome
may continue reporting Collapsed while its sibling List is open: in that case the
response labels the raw state `reported_expand_state` and points to the options.
`effect="none"` refers to the reported pattern state, which may disagree with these
option observations. `then={root: id}` includes the root itself even when it has no
children or the query finds none. Ordinary `screen_elements(root=id)` lists children.

Disabled lines include `IsEnabled=false`, raw UIA `AriaProperties` when available,
and a nearby disabled ancestor's id, or `self` when none was found in the captured
ancestry. Disabled unnamed containers are retained as evidence. `ancestor=…` means
that ancestor also reports disabled: UIA does not distinguish inheritance from an
independently disabled child, so this is evidence of a possible cause, not proof.
These annotations use the captured tree and do not require a second ancestor walk.

If the person confirms a reported-disabled control works, `force=true` permits invoke,
toggle, select or expand under the same grant and revocation checks. The helper tries
the pattern; on failure for a link or button supporting LegacyIAccessible, it tries
DoDefaultAction. It never synthesizes input. It reports `reported_disabled=true`, the
method used, observed focus/value changes and the window title before/after (including
whether it changed). A target removed by navigation may have no readable final state.
An ordinary disabled refusal explains when to use force. Force does not bypass password,
read-only, ownership, window identity, consent or action parameter checks.

**Response sizes.** The deterministic Chrome-shaped fake has a window, one ComboBox,
and a separate popup List with two options. These are compact JSON response bytes
(UTF-8, excluding MCP envelope), with the requested estimate of bytes / 4 tokens;
real page content and names change the sizes. `tests/test_uia_dropdown.py` measures
the actual server read/action path with a fake clock and no elapsed-time waits.

| Call | Bytes | Estimated tokens |
| --- | ---: | ---: |
| `screen_elements()` with the popup closed | 515 | 128.75 |
| `screen_elements(query="marketplace")` | 279 | 69.75 |
| Unchanged `set_value` action, without `then` | 300 | 75 |
| `expand` action with `then={root:C, depth:2}` | 517 | 129.25 |
| Read open popup options with `control_type="ListItem"` | 364 | 91 |
| `screen_elements()` with popup options included | 589 | 147.25 |

After collapse the same summary returns to 515 bytes: popup support adds no bytes to
closed-popup reads. Summary and query output retain the existing 4 KB budget; expand
previews at most eight option names rather than returning every option in the action.

**Native Chrome check.** Run against a granted Catalog Dashboard Chrome window with the marketplace
select and Manage listing content link; another Chrome window can remain open to check
exclusion. These are MCP calls, in order. Bind `W` to the existing window grant id,
`C` to the ComboBox id in step 1, `O` to the shop.uk ListItem id in step 3,
and `L` to the link id in step 8. Use the returned ids, not old examples.

1. `screen_elements(window=W, refresh=true, control_type="ComboBox", query="=Choose a marketplace…")`
2. `screen_element_action(window=W, element_id=C, action="expand", then={root:C, depth:2})`
   — root is listed; inspect effect and any option observations, including a stale reported state.
3. `screen_elements(window=W, control_type="ListItem", query="=shop.uk")`
   — find the sibling or popup option; no controls from the other Chrome window should appear.
4. `screen_element_action(window=W, element_id=O, action="select", then={query:"=Manage listing content"})`
   — verify the link href switches to the UK domain (the page's `change` handler ran).
5. `screen_element_action(window=W, element_id=C, action="select", value="shop.us", then={root:C})`
   — selected_option is shop.us; value_changed is true; select requests collapse.
6. `screen_element_action(window=W, element_id=C, action="set_value", value="shop.us", then={root:C})`
   — effect is none; the root still appears.
7. `screen_element_action(window=W, element_id=C, action="select", value="shop.us", then={root:C})`
   — value_changed is false and effect is none for an already-selected option.
8. `screen_elements(window=W, refresh=true, query="=Manage listing content")`
   — inspect disabled evidence and the restored shop.us href.
9. `screen_element_action(window=W, element_id=L, action="invoke")`
   — when reported disabled, refusal explains the force override.
10. After the person confirms the link works:
    `screen_element_action(window=W, element_id=L, action="invoke", force=true, then={})`
    — inspect reported_disabled, action_method, focus/value changes and window title/navigation.
11. `screen_elements(window=W, refresh=true)`
    — inspect the destination and confirm a dismissed popup no longer appears.


#### UIA latency, scoped reads and live state diagnostics

Reads, actions and window snapshots include local monotonic phase timings. Name/type queries
use scoped UIA capture; prior IDs stay in a bounded action-only map and require live identity
validation before dispatch. Press observes the target and window title without a broad browser
scan. See [the latency audit](screen-action-latency.md) for phases, retained-ID limits and the
remaining costs to measure. CDP reads may return a full tree for the same query scope; the
server then clears the scoped marker and applies its normal full-tree filtering.

`screen_elements(inspect="<element id>")` compares the retained snapshot with a new **uncached**
UIA read of that same identity. It deliberately bypasses refresh/TTL/invalidation: refreshing first
would destroy the evidence of a stale snapshot. It does not click or focus the window. Live data
includes IsEnabled, Name, Value (redacted for passwords), Toggle, SelectionItem, ExpandCollapse,
BoundingRectangle, AriaRole/AriaProperties, LegacyIAccessible State and its
`STATE_SYSTEM_UNAVAILABLE` bit, ClassName, FrameworkId and ProviderDescription. Unsupported live
properties are null. Missing cached properties are null, rather than inferred values. The raw-view
ancestor walk reports each ancestor's live name/IsEnabled through the grant root, plus whether that
root was reached; it never walks above the grant root. The element's live/snapshot mismatch wins
the verdict in either direction. A disabled ancestor names the source only when the element itself
is live-disabled and there is no enabled-state mismatch.
`events_supported`, `subscription_live`, `event_counter`, `last_event_time` (Unix time),
`snapshot_event_counter`, `event_counter_advanced_since_snapshot`, `server_change_version` and
`snapshot_change_version` expose the grant's subscription and both sides of invalidation. Inspect requires only the existing window read grant,
including on a plain line with person-attached processes and no captain.

The helper's thread-safe event counter advances **inside the UIA callback**, before scheduling the
100 ms push debounce. A stored tree carries the counter sampled before its capture. Before serving
that tree the server makes one cheap status request and requires matching counters and a confirmed
live subscription. A failed/unconfirmed subscription never authorizes cache reuse. A status request
never walks UIA or waits behind a capture. Helpers without counter metadata retain their previous
expiry/push behavior. This barrier establishes truth as of its status response; it cannot predict a
future JavaScript change or a UIA event Chrome has not delivered yet.

Post-action reads capture immediately, then recapture only when an observed event crossed that capture.
Churn is bounded by the capture deadline and eight attempts; exhaustion says `tree inconsistent`.
The answer includes `snapshot_event_counter` and checks the helper clock again after rendering, so
an event during that final interval sets `change_event_since_snapshot`. Observed capture races also
set that flag on the capturing reply, even if a recapture reaches a consistent boundary; later cache hits
report their current barrier result without repeating an already-reported capture race. The next
ordinary read after an action recaptures, and comparisons include enabled/value/toggle/selection/expand state on stable ids,
so late changes appear in the delta as `~updated`. Bounds, focus, offscreen status and pattern-list
changes do not count as semantic updates, preventing layout or scrolling from burying the changed link.
The comparison runs off the server event loop. A later event cannot retroactively alter an already
returned reply; the next read's barrier detects it even if its debounced push is still in flight.
A `more` across a counter change restarts from the root, or explicitly reports an inconsistent tree;
it never silently combines epochs. A restarted continuation returns `continuation_restarted`.

**Busy subtrees (helper 1.4.4).** A window whose one subtree raises events without end (a view that keeps
enumerating) must still read and act. UIA handlers register with a cache request for the sender's runtime id
(the element scope; UIA forbids a parent scope), so each event names its sender without a COM call; `EventState` keeps the distinct sources (a source
that fires continuously is one entry, bounded at 512) and the helper maps runtime ids to element ids, with a
wrapper standing for its nearest listed ancestor. `event_status` with `events_since=<counter>` adds
`event_sources` (`ids`: each source with its listed ancestors from the read's child-index paths, nearest first;
`unsure`: sources whose ancestry may be stale because an ancestor raised an event after they were listed;
`unplaced`; `overflow`); status carries `event_sources_supported`. The server judges
a capture by where events came from, not by whether any came:

| Situation | Outcome |
| --- | --- |
| Events only from elements outside what the read answers (a `root`, an `id`, a query's matches) | The read is clean; `change_event_since_snapshot` is false |
| Events from placed elements the read covers | One recapture, then the tree is returned with `busy`, naming the outermost busy subtrees and `root=<id>` of stable parts to read instead |
| Events the helper cannot place (never listed, overflow, none named) | The old rule: up to eight attempts, then `partial` says to read the whole window once, then scope by `root` or `query` |
| An action whose target, ancestors and descendants had no events | The action proceeds without a recapture, even while another subtree is busy; descendants count even when a query's tree kept no node for them |
| An event at the target, above it or below it, or a source with stale ancestry (an ancestor event, or an event with no sender or an unlisted one, after it was listed) that the tree does not hold | The tree is read again; every action target is proved against the live event counter, fresh tree or not, retained ids included; the action is refused if the target is still changing |

Continuation parts send `tolerate_events`, so the helper no longer refuses them for an unrelated event;
the final judgement covers the whole capture. No polling or sleeps are added: each judgement is one
status exchange after a capture.

`uia_events.PROPERTIES` includes IsEnabled (30010), Value (30045), Toggle (30086), SelectionItem
(30079), ExpandCollapse (30070), Name (30005), AriaRole (30101), AriaProperties (30102) and
LegacyIAccessible State (30096). Persistent property and structure registration uses
`TreeScope_Subtree` (7) at the granted window and visible owned-popup roots. There is no sender
walk/filter in these callbacks, so an aria change on an ancestor or descendant reaches the counter.
Whether the real Chrome provider emits the expected event remains part of the live retest.

| Timing in the elements path | Replacement or purpose |
| --- | --- |
| `SETTLE_SECONDS=0.5`, `settle()`, post-action sleep | Removed. Capture immediately and recapture on observed counter changes; report races. |
| `SNAPSHOT_TTL=3` | Retained as expiry/memory policy and old-helper fallback. New helpers additionally require a live counter barrier; TTL never proves freshness. |
| `queue_change` 100 ms debounce | Push coalescing only. Callback increments the counter first; a status request sees in-flight changes. |
| `uia_access.watch(sleep)` | Unused sleep parameter removed. Watch blocks on native window events/local grant changes. |
| Expand's 250 ms structure-event wait | One event wait after Expand, bounded for providers emitting no structure event. It never proves expanded state; selection rechecks the live options/value/state and reports unknown on timeout. |
| `CAPTURE_SECONDS=20`, eight capture attempts, `MAX_NODES`/`more` | Bound work/churn, never establish freshness. Epoch mismatch restarts or marks inconsistency. |
| Snapshot part `BUDGET=3`, child startup `START_LIMIT=25`, `KILL_SLACK=4` | Bound a walk or hung COM provider. Child signals READY through a pipe; no readiness sleep. |
| `WindowTask.READ_TIMEOUT=33`, server exchange 35 s, MCP read 60 s/action 100 s/then 160 s | Bound failed exchanges/operations. No elapsed interval is used to infer page state. |
| UIA subscription ready wait / thread join, each 3 s | Bound native registration/shutdown. Cache requires a confirmed living subscription thread, not successful waiting. |
| ActionWorker 32 s shared deadline for audit readiness and native action | Bounds failure; timeout revokes the dispatch gate and reports uncertainty. No sleep proves action success. |
| Socket hello/binary 45 s and heartbeat receive 15 s | Bound failed helper transport; protocol liveness, never tree freshness. |
| Picker 65 s / consent exchange 70 s | Bound independent human consent, outside snapshot correctness. |

##### Exact manual retest

Deploy the state-truth server **and helper** first; use helper 1.3.0 or newer for the latency timings
and filtered captures. Share Chrome with the testing line using the tray, and attach an ordinary
person-owned process to that line. No captain is required. Run from the repository with that process's existing connection JSON (or omit
`--connection` when `PARTYLINE_MCP_CONNECTION` is set):

```bash
uv run --locked python scripts/uia-state-retest.py --connection "$PARTYLINE_MCP_CONNECTION"
```

The script sends these actual MCP `tools/call` requests over stdio, retaining the returned window
and element id in variables rather than requiring an id to be transcribed:

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"screen_elements","arguments":{"query":"=Manage listing content","control_type":"Hyperlink","refresh":true}}}
```

At the prompt, choose the marketplace **by hand** in the real Catalog Dashboard window, observe the visible link,
then press Enter. The next request is exactly `screen_elements({"window": before["window"],
"inspect": link_id})`. It never refreshes between the manual change and inspect. Save the before
and inspect JSON and the final one-line verdict. Repeat the run if the snapshot was evicted or the
identity disappeared; do not substitute a different node silently.

Also run against `/lab/a11y` once that sibling change is deployed. Use `--query '=LINK NAME'` for
the unique hyperlink in each card (copy its exact accessible name from the lab page/docs), and
`--window 'WINDOW GRANT OR TITLE'` if needed. At the manual prompt, trigger the matching card:

1. Sync enable; delayed enable at 300 ms; delayed enable at 2.5 s. Press Enter immediately after the
   trigger, then run inspect again on the same id after the page's DOM event log reports the change.
   No sleep or guessed delay is required. Record both DOM-log and UIA-clock observations.
2. Class-only enable retaining aria-disabled, correct aria-disabled enable, and disabled-fieldset
   ancestor. Record live/snapshot/ancestor evidence; visual styling alone is not proof of enabled UIA.
3. Name change, structure change and input/change checks: record clock advancement, use a fresh
   `screen_elements(changes=true)` for the state/structure delta, and note if a renamed identity is gone.
4. Finish with the default script on the Catalog Dashboard’s Manage listing content link after
   choosing a marketplace by hand. Agree-disabled identifies Chrome's exposed state; live-enabled/snapshot-disabled identifies
   stale Partyline state; ancestor-disabled names the source. ProviderDescription/FrameworkId distinguish
   native Chrome UIA from an MSAA proxy.

The script performs no artificial waits. A live result must include the actual JSON/verdict; fake
provider tests establish invariants but cannot decide which side of Greg's real page reports disabled.
Tool result sizes and image estimates can be compared in the line's Usage section;
see [tool telemetry](telemetry.md) for estimators, privacy and retention.

#### Chrome page state with Partyline Chrome (recommended)

The Windows installer ships **Partyline Chrome** and registers its native-messaging host
for the current user only. After installing/updating the helper, load it once:

1. Open `chrome://extensions` and turn on **Developer mode**.
2. Choose **Load unpacked** and select `%LOCALAPPDATA%\Partyline\chrome-extension`.
3. Leave the extension enabled. It stays installed across Chrome restarts. Its toolbar
   button offers manual reconnect. With **Install updates automatically** enabled, upgrades
   keep the native port alive from its previous version folder. When the updated helper connects,
   the host's hello reads the installed folder's manifest version and the persisted opt-in. If
   those files are newer than `chrome.runtime.getManifest().version`, the extension calls
   `chrome.runtime.reload()`. Its worker reconnects the native host on startup, without a toolbar
   click. Chrome local extension storage records the attempted version before reloading.
   The same or an older target cannot trigger another automatic reload, even if the
   unpacked extension was loaded from a different folder and its running version did not change.
   A newer installed version can make one new attempt. Equal, older, invalid or unknown versions
   never trigger reload; the opt-in must be true.
   Manual installations and uninstalls can suspend the host before replacing its registration.

**Toolbar badge.** The extension's toolbar button shows whether the helper is reachable; hover it
for the reason in plain words. It uses `chrome.action` only, which needs no extra permission.

| Badge | Colour | Meaning |
| --- | --- | --- |
| `…` | grey | Connecting to the native host; **reconnecting** after the host went away (the title names why, for example *the helper bridge stopped*); or the extension is **ready and the helper is away** (not started yet, quit, restarting or updating). Nothing to do: the extension reconnects by itself and the helper attaches by itself when it starts. Start the helper if it stays grey. |
| `✓` | green | Connected: the helper greeted the extension (`Partyline: connected to helper <version>`). The tray's **Chrome** row reads *extension connected*. |
| `!` | red | Not connected; the title says why. *Native host not found*: Chrome has no registration for the helper's host, so reinstall or restart the helper. *Access forbidden*: the extension id does not match; load the extension from the helper's own folder. *Native host has exited* (shown only after every automatic retry below failed): the native host process kept ending, so make sure the helper is running and click the button. *Paused for a helper update*: a manual install or uninstall asked the host to release its files; click the button to reconnect. |

Click the button to retry; the badge turns grey straight away and then green or red. A click while
no helper is attached, or on a port that never greeted, replaces the native port instead of doing
nothing; a click while connected just repaints the badge. The service worker console
(`chrome://extensions` → **Inspect views: service worker**) shows concise `[Partyline]` lines for each
connect attempt, hello, disconnect with Chrome's error text, and reload decision. Page content and
CDP payloads are never logged.

The helper accepts the native host whenever it connects: after install, after the extension is
loaded or reloaded, after Chrome restarts, and after an installer pause (`suspend-chrome`) ends. A
running helper watches the host's endpoint file with an operating-system file event (no timer), and
the host lets the newest authenticated helper replace a stale one. The host also exits once
Chrome closes its port, even while a helper is still attached, so the next host can start.

**Helper restarts need no click.** Chrome starts the native host only when the extension connects, so the
host usually outlives the helper. When the helper quits or restarts, the host keeps Chrome's port and tells
the extension the helper is away (grey badge; the extension drops its debugger attachments). The next
helper finds the host through its endpoint file, authenticates, and the host greets the extension again:
the badge goes green with no click.

**Automatic updates and a host that goes away.** An automatic update stops the helper and replaces files
without asking the host to release them, so the host process (started from the old install) can still exit
or be killed, and Chrome then closes the extension's native port ("Native host has exited"). The extension
reconnects by itself, event-driven and bounded: at once when the port closes, then one `chrome.alarms`
alarm per failure after 1 s, 5 s, 30 s, 2 min and 5 min, and a try on browser start, on a toolbar click, and
on tab activation (at most every 30 s, never while an alarm is waiting). The step is kept in
`chrome.storage.session`, so a worker woken by an alarm, or started while the helper is still restarting,
continues the schedule instead of starting over; a greeting from the host ends it. This is not polling: an
attempt follows a transport failure, one alarm exists at a time, success or a click stops the schedule, and
after the last step nothing runs until a click, a browser start or a tab activation. The badge stays grey
while attempts remain and turns red only when they are spent; *host not found* and *access forbidden* are red
at once (the schedule still runs quietly in case an installer is replacing the registration). The
alarms are why the extension needs the `alarms` permission. Chrome's 30 s minimum alarm delay applies
only to a packed extension; the extension is loaded unpacked, so the short steps run as listed. Only an
installer that must replace the host's files (a manual install or uninstall) sends `Partyline.suspend`
with `release`, which makes the extension close the port; that one case shows red *paused* and needs a
click (or Chrome restart).

**Extension refusal codes.** A refused extension command returns one fixed code, never Chrome's own
text (it can name a URL). The helper reports it as `Chrome extension refused <CDP method>:
<code>`, for example in a read's `source_reason`.

| Code | Meaning and fix |
| --- | --- |
| `tab_outside_grant` | The tab or window is not in the live grant (closed, moved, or not shared). Share the window again. |
| `tab_owned_by_other_grant` | An entry from an older grant still holds the tab. The helper releases that tab's stale entries and retries once on its own; if it still appears, reload the extension at `chrome://extensions`. |
| `previous_detach_incomplete` | Chrome did not finish detaching the debugger from an earlier grant. Handled like the code above; otherwise close the debugger bar or reload the extension. |
| `domain_refused` | The command is outside the allowed page domains. Not a fault; use a supported action. |
| `child_outside_grant` | A frame session outside the shared tab was named. Read again. |
| `child_detached` | The frame went away. Read again. |
| `revoked` | The grant ended or the user cancelled debugging in Chrome. Share the window again. |
| `restricted_navigation` | The page is not an HTTP(S) page (internal, extension, DevTools or `file:`). Navigate to a web page. |
| `other_extension_frame` | Chrome will not let an extension debug a page that hosts another extension's frame. The helper moves only this grant to Chrome's remote debugging (see below); if that is off, the read's `source_reason` says to enable it at `chrome://inspect/#remote-debugging` or disable the extension that injects the frame. |
| `debugger_already_attached` | DevTools or another debugging extension holds the tab. Same fallback as above; or close that debugger. |
| `restricted_page` | Chrome never lets extensions debug this page (a `chrome://` page, the extensions gallery, another extension's page). Use a normal web page. |
| `tab_gone` | The tab closed between the mapping and the command. Read again. |
| `debugger_attach_failed` | Chrome refused to attach for a reason the extension does not recognise. Read again. |
| `debugger_command_failed` | Chrome rejected a command on the attached tab for an unrecognised reason. Read again; if it repeats, reload the page. |
| `unknown` | A failure that was not a recognised refusal at all. Open the extension's service worker console. |
| `debugger_detached` | Chrome detached the debugger (the tab closed or navigated away). Reload the page and read again. |

**Remote-debugging fallback, per grant.** Only a grant whose tab Chrome refuses with `other_extension_frame`
or `debugger_already_attached` changes transport; every other grant keeps the extension. A disconnected or
reconnecting extension is never a reason (see below). The helper
tells the extension to drop that grant, and, when Chrome's remote debugging is enabled
(`DevToolsActivePort` exists), reads continue over remote debugging after Chrome's normal Allow prompt
(UIA answers meanwhile; the read reports `transport: remote_debugging`). The tray's Chrome row keeps
describing the extension. A grant for one picked tab is bound once, when it first maps over remote
debugging, to the one remote target in its window with the same URL and title; from then on only that
target is the grant's tab (navigating it keeps the grant). If no tab or several match, or the bound tab
closes, the grant selects nothing and says *pick a tab again*; it never re-matches by content. When remote debugging is off the grant stays on UIA with the actionable
`source_reason`. Read replies carry `transport` and, off the extension, a short `fallback_reason` (the
refusal code, or `extension_not_installed`). A refused grant tries the extension again on the next read after
its remote tab navigates or reloads, keeping the remote connection open until the extension serves the page;
a repeated refusal moves it back with no second Allow prompt. When no grant needs remote debugging any more
(the grant ended, or the extension served it again) the helper closes the remote connection, so Chrome's
automation infobar goes away. The extension's own service worker
console logs each refused command's method and Chrome's raw error text for the person at that machine;
that text is never sent to the helper.

A new `Partyline.hello` (after an update, a lock, or any reconnect) drops every attachment and
orphan the extension held from before it, and a failed detach is retried by the next attach, so a
new grant on the same tab does not collide with an old one. The helper's `Partyline.release`
frees only a tab no live grant of the helper owns. `reload` takes the same recovery path as a read.

For a source or `uv tool` install, run `partyline-helper install`; its output names the
extension folder and native host. The host launcher must be installed alongside that
helper. The Windows installer includes a dedicated console-subsystem native executable;
its stdout carries binary protocol frames, never log messages. The host allows only
`chrome-extension://plbehhebbdldlggkkpafpepcobmkojeb/`, fixed by the extension's public
manifest key. There are no content scripts or host permissions: the only permissions are
`debugger`, `tabs`, `nativeMessaging`, `alarms` (the bounded reconnect schedule above), and `storage` (the
local reload-attempt marker and the reconnect step). A Web Store listing is a possible later step;
loading the installed folder works without one.

The extension is preferred when connected. The tray has a dedicated **Chrome: extension
connected / extension disconnected / not installed / remote debugging** status row, and provider state includes
`transport: extension|remote_debugging`. Read results also name their transport. Remote
debugging is the default only when the extension was never installed: no native host has ever run for this
user (the host's `chrome-native.lock` in the helper's config folder does not exist and no host is up), which
is the behaviour before the extension existed, with the approved remote-debugging flow below. Once a host
has run, a helper that starts, or an extension that is disconnected or reconnecting (an update, a restart, a
reload), never chooses remote debugging: the first read of the outage waits up to 3 s for the host (woken by
its endpoint file, not a timer), later reads in the same outage do not wait, and a read that cannot use the
extension answers through UIA with the `source_reason` *Partyline Chrome is reconnecting*. Remote debugging
then appears only through the per-grant refusal fallback above. `partyline-helper uninstall` forgets that a
host ever ran. A failed page command is never automatically replayed through the fallback.

Only tabs named by a live HWND grant may be attached. Mapping checks the Chrome process
that launched the native host, the granted process/HWND identity, window bounds and active
tab title. The native HWND list must also have exactly one compatible window for that
process, caption and bounds; ambiguity fails closed to UIA even when Chrome hides another
profile or incognito window from the extension. A selected-tab grant names only that tab. Chrome
internal, extension, DevTools and local `file:` pages are refused, including pending
navigation to them and child iframe targets. Only HTTP(S) pages are eligible.
The first loaded Chrome profile owns the per-user native bridge; other profiles cannot
replace it. Profiles and incognito windows can share a browser process, so process identity
alone is insufficient: colliding native windows use UIA. Share from the extension profile
or use the fallback when the extension is absent.

Attachment lasts for the whole read/action plus **300 ms** of idle linger. A burst reuses
one attachment. Chrome's normal debugging notification appears while attached; it is never
hidden. Revoking a grant immediately gates further commands, writes the revoke signal to
the native port, and initiates Chrome detach; the extension acknowledges after detach
finishes. Clicking **Cancel** on Chrome's debugging bar also cancels that window grant's
CDP access: subsequent calls stay on UIA until the person shares the window again. A helper
restart or transport change does not undo that cancellation. A late attach completion is also detached. The OS/Chrome API completion is
asynchronous; an input already delivered before revoke cannot be recalled. On idle resume,
the helper reinitializes CDP domains and checks the document loader before reusing element
IDs. A changed document requires a fresh read. UIA supplies background change events while
CDP is idle; CDP does not claim a live subscription during that time.

Native frames use a 32-bit native-endian length prefix and a 1 MiB cap in both directions.
Large AX results are split into sequential chunks and reassembled with a 16 MiB total cap.
The Chrome-started native port survives helper reconnects, avoiding a remote-debugging
approval prompt on helper restarts. A random per-user secret authenticates the local IPC
connection; it is stored beside the helper's private pairing configuration. Discovery requires
the endpoint and PID files to name the same live native-host process. It never takes the
host's startup lock, so discovery cannot reject a concurrently starting Chrome host, and a
crashed host's stale file cannot reopen remote-debugging approval on every operation. Authentication accepts one unchunked
frame of at most 1 KiB. Automatic native-port reconnect follows the bounded schedule above; a failed decode and an
explicit installer suspension clean up locally and wait for a click.
An automatic extension reload starts a fresh worker and reconnects without a gesture.
The toolbar can also connect again without restarting Chrome.

File-input commands (`DOM.setFileInputFiles`) are relayed to Chrome without broader
permissions, but that path has not been verified against real Chrome's debugger-extension
file-access restrictions. If Chrome refuses it, use the Open dialog path. Loading local
`file:` pages is deliberately refused; no file-URL permission toggle is required.

`Partyline.metrics` reports attach/detach samples in milliseconds from the extension's
monotonic clock. The fake clock models **7 ms attach / 3 ms detach** and asserts both values;
those are injected timings, not real Chrome measurements. A separate Node test reports
measured relay overhead for 100 fake attach/detach cycles. Expect roughly **10–100 ms attach
and 1–30 ms detach** on a warm desktop Chrome as an engineering estimate, not a measured
promise; busy renderers and security software can take longer. Run against real Windows
Chrome before making a latency claim.

#### Chrome remote debugging (fallback)

In an already running **Chrome 144 or newer**, open `chrome://inspect/#remote-debugging`
and enable remote debugging once. Share the Chrome window from the helper tray. Chrome asks whether to allow the debugging connection as soon as the window is shared;
choose **Allow**. Reads use UIA with an awaiting-approval reason while that prompt is open,
so slow approval does not block a read or require sharing again.
The helper keeps one browser connection until it disconnects or exits. It never starts
Chrome, changes its command line, or copies a profile. Denying or
closing the prompt leaves UIA available. Share again to retry a refused connection.

The tray and server device snapshot report `not_enabled` (with the setting instruction),
`awaiting_approval`, `connected`, `disconnected`, or `refused`. `screen_elements` includes `source: cdp|uia`
and an explanation when Chrome mapping falls back to UIA. Chrome discovery follows
[Chrome's approved-session flow](https://developer.chrome.com/blog/chrome-devtools-mcp-debug-your-browser-session)
and the `DevToolsActivePort` reader in
[Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/BrowserManager.ts).
This attaches to the ordinary signed-in session; the old command-line debugging restriction
on default profiles is a different mechanism.

The grant covers **all tabs of the selected HWND**, following its active tab. Mapping checks
the browser process, CDP window bounds against the DWM frame (with DPI conversion), the
active tab's title against the current HWND title; visibility only breaks duplicate-title
ties. A uniquely matched tab stays on CDP when its HWND is covered and Chrome reports all
tabs hidden. Missing or
ambiguous evidence uses UIA; another Chrome window needs its own grant. Page actions are
on by default. Ignored AX nodes without an interactive DOM target are omitted before
chunking; exposed descendants attach to the nearest exposed ancestor. Chrome hit testing descends open shadow roots and follows composed-tree
ancestry, including assigned slots; an element covered by a separate subtree is still refused. Reads use Chrome AX plus live DOM native disabled, ARIA disabled, readonly,
inert, value, checked and selected state. With `bounds=true`, CDP adds `viewport@` rectangles
in CSS pixels; it does not infer screen/frame coordinates from browser decorations. A class-only link can look enabled while reporting
`disabled(aria_disabled)`; that provenance is retained. Password values are omitted.

Helper **1.4.5** also discovers keyboard-focusable DOM elements without an ARIA role,
including triggers inside shadow roots and custom hosts. Their names use the accessible
name, `aria-label`, `title`, then at most 240 characters of visible text from a bounded
32-node walk. Reads never hit-test or read whole-container text. These elements offer
`scroll_into_view`, `press` and `invoke`; invocation uses the same covering-element HIT
check and trusted mouse input as a button. Visible `option`, `menuitemradio`,
`menuitemcheckbox`, `switch`, `treeitem`, and actionable `gridcell` widgets offer
`invoke` and `select`. Open a custom popup with `invoke`, then read again to discover
its newly visible options and select an option by its element ID. Hidden options are
omitted. `tests/test_cdp_focusable.py` covers a role-less focusable shadow trigger and
custom option elements.

`screen_element_action` sends page-scoped mouse/keyboard input, focuses the actual DOM node,
and edits through `Input.insertText`. `select value=<label or value>` reads the native options,
then uses trusted `Input.dispatchKeyEvent` navigation from the **current** option. For a
native dropdown it opens the picker with Alt+Down, moves with arrow keys, and commits with
Enter. `selection_mode: keyboard_popup` should commit only the requested option once. If the
native picker ignores CDP keys, it cancels the picker and falls back to current-option arrow
steps plus Tab (`keyboard_steps`). It never resets through Home/End. The fallback can emit
one native change per step; results include `trusted_input_events` and `trusted_change_events`
so its behavior is explicit. It verifies the selected option, never sets the value or
constructs DOM input/change events, and reports `none (already selected)` for the current
sole option. Document navigation stops further input and returns an unconfirmed outcome.
The picker-open probe uses Chrome's
[`:open` support](https://developer.chrome.com/release-notes/133), and keys use the
[CDP Input protocol](https://chromedevtools.github.io/devtools-protocol/tot/Input/).
Unsupported CDP actions report an error; they never also run a UIA action.

Helper **1.4.2** observes renderer crashes (`Inspector.targetCrashed`,
`Target.targetCrashed`), target information changes, and session detachment. AX/evaluate
failures after a crash event retain that state. Reads may fall back: `screen_elements` returns Chrome's UIA window controls with `source: uia`,
`page_state: crashed` (or `detached`), and `recovery_hint`. `screen_window_snapshot`
includes the same metadata alongside the captured window pixels. UIA IDs from this
read can invoke Chrome's Reload button, select another tab, or edit its address bar.
Still-crashed reads go directly to UIA: renderer commands can hang until their deadline,
so probes wait for Chrome's recovery event. Old page IDs cannot dispatch through UIA;
page actions are refused with a reload hint.

Use `screen_element_action(element_id="page", action="reload", window=<grant>)`
to reload the mapped active tab without a page element ID or a working AX tree.
It requires helper Chrome capability 4 (older helpers are refused before dispatch) and
has the same write authorization, grant spending and audit as other element actions;
`then={}` can read the recovered page. A live page uses `Page.reload`; a crashed or
detached page uses `Page.navigate` to its last known URL. Recovery never repeats an
interrupted write automatically. After the event quiet deadline, the helper attaches a
fresh session to the same target and installs its isolated world, binding, observer and
lifecycle subscription again. The next read returns to `source: cdp`. If the person
reloads by hand, `Inspector.targetReloadedAfterCrash` permits the next requested read
to probe the recovered renderer once and restore its session without a new grant or Chrome approval, provided the tab and browser connection remain
the same. Ending the grant gates recovery commands and late attach responses too.

Helper **1.4.2** distinguishes a dropped approved socket (`disconnected`) from a denied
or failed approval (`refused`). A dropped socket reconnects on the next CDP need. A new
local window share, a standing `screen_attach_window` grant, or an explicit `reload`
permits retrying a refusal. All paths share one helper-wide limit: at most one connection
attempt, and therefore one possible Chrome Allow prompt, per 60 seconds. The limit
uses a monotonic clock and is checked only on requests; there is no retry timer.
While waiting, reads remain on UIA and `source_reason` reports the state, the possible
Allow prompt, and the seconds until another attempt is allowed. Approval remains
Chrome's decision. A reload that starts or finds a pending approval returns `failed`
immediately with an awaiting-approval reason; reads and UIA actions remain available.
Call reload again after Chrome allows the connection. Approval never schedules a
page reload automatically. An already dispatched page action is never replayed on reconnect.

`screen_eval(expression=<JavaScript>, window=<grant>)` reads page state or navigates with
`location.assign` in the active page and returns bounded JSON (a truncated preview for large results).
Never use it to click or change the page with JavaScript. Interact through
`screen_element_action`, which sends trusted input. It has the same
window grant and write authorization as page actions. It can access the page's signed-in
session. Calls are audited with grant, calling line/process, operation and input length;
code and typed text are not placed in this audit. The helper keeps its local chained audit,
and the server records calls including cached reads. Ending the grant synchronously gates
page commands and stops subscriptions; disconnect and helper exit close the browser socket.
An already dispatched action cannot be undone; an interrupted command is unconfirmed and
must not be retried automatically.

DOM/AX/lifecycle events and an isolated-world MutationObserver advance the same monotonic
counter used by the UIA state-truth barrier. CDP action settling uses an event-reset 100 ms
quiet deadline and an absolute 2 s failure deadline, without periodic page checks. Results
say `settle: quiet|changing|deadline`. A renderer round trip and counter comparison detect
events during capture. Quiet describes the observed boundary; later application work can
still change the page and invalidates the cache through events. Only the selected tab
advances the CDP grant counter; switching tabs detaches the previous page, so background
mutations cannot break continuations or settling.
Iframe navigation/removal advances the counter without resetting page-wide element IDs or
interrupting input. Main-frame navigation and `DOM.documentUpdated` invalidate those IDs.
When a link invoke reaches mouse release and main-frame navigation is observed, the result
is `completed` with `navigated: true` and `settle: changing`, without reading the old element.
This confirms the click/navigation boundary; it does not assert the destination finished loading.
Navigation before mouse release, document replacement without observed navigation, and
revocation remain interrupted outcomes.

##### Windows live comparison checklist

This implementation is tested against a fake CDP websocket and fake HWND lists on Linux.
**Live Windows connection, DPI/window matching and website behavior remain to be run.**
Record Chrome/helper versions, each card's CDP line and UIA line, DOM state, page event log,
and any difference. Upload sanitized evidence to the line; keep host/account details out.

0. **Extension badge and late connect:** start the helper first, with the extension not yet
   loaded. Load it unpacked: the badge goes grey, then green (`Partyline: connected to helper
   <version>`) and the tray row reads *extension connected* without restarting the helper. Quit
   the helper: the badge stays grey (*helper away*). Start it again with no
   click: green again. Restart the helper, and let it auto-update: green again each time with no
   click. Reload the extension and restart Chrome: both reconnect.
   **Auto-update with Chrome open:** run an automatic update from the previous version while Chrome and
   a shared Chrome window are open: the badge goes grey (*reconnecting*) and returns to green by itself,
   no click and no Allow prompt, and a read taken meanwhile reports `source: uia` with *Partyline Chrome is
   reconnecting*, never `transport: remote_debugging`. A grant whose page Chrome refused returns to the
   extension after that tab navigates, and Chrome's automation infobar disappears once nothing needs remote
   debugging. Run the manual installer over a
   running helper (it asks the host to release its files): the badge shows *paused for a helper
   update* and the button reconnects. On a page that hosts another extension's frame, expect
   `other_extension_frame` and, with remote debugging on, a read over `remote_debugging`. Open the service worker console and
   confirm `[Partyline]` lines for each step and no page content. Rename the native host
   registration to see *native host not found*, and load the extension from another folder to see
   *access forbidden*.
1. Open `/lab/a11y` in the existing signed-in Chrome window. Disable remote debugging and
   share it. Run `screen_elements(refresh=true)`; expect `source: uia` and the Chrome setting
   instruction. Enable the setting, read again, approve Chrome's prompt, and expect `source: cdp`.
   With helper 1.4.2, crash a disposable tab using Chrome's crash test page. Read with
   `refresh=true`; expect `source: uia`, `page_state: crashed`, the reload hint and
   Chrome's toolbar/tab controls. Invoke a UIA Reload control, then confirm the next
   read returns to CDP without granting again. Repeat with
   `screen_element_action(element_id="page", action="reload", then={})`, and with a
   manual Reload. Confirm an old page ID is refused while crashed, another tab can
   be selected through UIA, live reload works, and revoke during recovery prevents
   subsequent session commands. Record helper version and returned metadata.
   Drop the approved browser connection, then request another read: expect
   `disconnected` and a retry countdown in `source_reason`, UIA while waiting, and
   at most one new Allow prompt after 60 seconds. Deny once, then create a new
   standing window grant or use `reload`; verify the same cooldown and recovery.
   Repeated reads or attaches during that minute must not open more prompts.
   Verify tray/device states through not enabled, awaiting approval and connected. On a separate
   session deny once, confirm refused/UIA, then share again and approve.
2. **Sync enable:** find the select and Sync target. Select B with `then={}`. Check the page
   logged trusted input/change and the target's native disabled flag cleared. Verify
   `isTrusted` in the lab's existing event log via `screen_elements`; do not install a listener
   through `screen_eval`. Count
   trusted change events: moving from a middle option to an adjacent and a distant option
   should produce one commit in `keyboard_popup` mode, with no intermediate values. Record
   `selection_mode` and `trusted_change_events`. If the popup does not accept keys, verify
   fallback starts at the current option; an adjacent move must commit only its target,
   while a multi-step fallback may emit one change per step. Compare with UIA after
   disconnecting debugging; restore CDP and refresh before the next card.
3. **Delayed enable:** select B, record `settle`, read each delayed target before and after its
   page-side change. Expect a new event counter and fresh enabled state after each transition;
   a quiet result before delayed work is allowed. Compare UIA card by card.
4. **Class-only link:** select B, then find Class-only link. Its style looks enabled, but CDP
   must show `disabled(aria_disabled)` with DOM `aria_disabled=true`; record UIA's disabled
   provenance too. **ARIA done right:** its parallel link becomes enabled after ARIA removal.
5. **Disabled ancestor:** toggle the fieldset checkbox. Compare native disabled state on its
   child before/after. **Name change:** invoke Count 0; record stable identity and the new label.
   **Structure change:** invoke Load list; read again after the page inserts its three items.
6. **Text field:** set a value, then press Tab or Enter. Compare its value and input/change/key
   events with UIA set_value. **Reset/event log:** reset the lab and verify event/counter changes.
7. Evaluate `({title:document.title, cards:document.querySelectorAll('select').length})` with
   `screen_eval`; check bounded JSON. Return a very long Unicode string and confirm truncation.
   Inspect audits for calling grant/line/process/operation/length and absence of supplied text.
8. Open another Chrome window, including an identical-title/overlapping-window case. Confirm
   it is excluded, or mapping explicitly refuses with UIA fallback. Fully cover the shared
   window: a unique title must remain on CDP even if every tab reports hidden; duplicate
   titles with no visible tiebreaker must refuse. Switch tabs in the granted
   window; the next read follows that tab and old page IDs fail. Leave the old tab changing
   in the background: the selected tab's counter, `more` cursor and quiet settle must remain stable. Move a tab to the other window;
   verify it is no longer read through this grant. Repeat at Windows display scaling 100%/150%.
9. On Catalog Dashboard, find **Manage listing content** and record its CDP AX disabled state, DOM native/ARIA/
   readonly/inert state (use `screen_elements(inspect=<id>)`), and the matching UIA inspect.
   Count native `change` events and log selected marketplace values during the operation;
   record popup/fallback mode and verify that no unintended marketplace was committed.
   Change the marketplace, repeat all readings, then invoke only the intended link. Confirm the
   Listing Content Manager page opens. Record actual navigation and discrepancies between style, AX/UIA and DOM. Do not infer success
   from an input dispatch acknowledgement. While an iframe navigates or is removed, verify
   that main-page IDs remain usable and clicks/selects finish. A link navigating the main page
   should report `completed`, `navigated: true`, invalidate old IDs and require a fresh read.
10. Record capture and event-status latency on the lab and Catalog Dashboard pages. DOM observation now
    uses two calls per exposed DOM node plus one object-group release per capture chunk;
    event-status checks still remap the HWND. Revoke while a read/eval/action or tab attach is in flight; expect no subsequent page command/result
    disclosure, stale IDs refused, and another separately shared window unaffected. Disconnect
    the helper and quit Chrome; verify the browser socket closes and UIA fallback is explicit.


##### Windows foundations source audit

Read alongside the helper changes: `tests/test_windows_uia.py::test_background_tk_window`,
`tests/windows_uia_window.py` (native controls and separate foreground window), and
`tests/windows_uia_patterns.py` (selection, expand/collapse, range, scroll and window actions).
The foreground assertions check both a transient activation followed by restoration and a native
restore refusal, using the reported observations; the cursor must remain unchanged. Background reads
still require the foreground fixture to remain active. The shared assertion helper has a Linux
regression in `tests/test_cdp_active_select.py`; `tests/test_uia_worker.py` fakes native Win32 restore
refusals through the SetValue dispatch path.
Also read `tests/test_windows_capture_events.py` including its native Tk capture smoke test,
`tests/test_windows_packaging.py`, `tests/test_windows_startup.py`, and
`tests/test_windows_platform.py`. Their capture, packaging and startup contracts remain
applicable. This is a source audit; native Windows execution is still required by CI, and
these UIA fixtures do not establish Chrome popup/event-trust behavior for the checklist above.

### Upload files to a Chrome file input

For a shared Chrome window whose `screen_elements` result has `source: cdp`, call
`screen_element_action` with `action: "set_files"`, the `window`, `element_id`, and
one or both of `files` (readable Partyline media IDs) and `paths` (absolute file
paths on the paired computer). Supply 1–10 files total. Media files appear first,
followed by local paths, in the order supplied in each list. The input must be a
file input and must allow multiple files when more than one file is supplied.
Request `then` for the names and count read back from Chrome and the usual settle
state. If CDP is unavailable, use the Open dialog path.

CDP reads also discover file inputs missing from Chrome's accessibility tree,
including hidden inputs, open shadow roots and embedded documents in the same
DOM session. Discovery uses one pierced DOM snapshot per new read and visits at
most 10,000 nodes, exposing up to 100 additional inputs as `FileInput` controls
with `set_files`. Inputs without rendered bounds or with hidden visibility report
`hidden`; inspect reads their current file names and count. Names use bounded
label/button text or input attributes, with `aria-label` taking priority over label
text. These additional inputs follow the document root, before the remaining AX
nodes, so they stay within the server's tree cap. Existing visible input actions
stay the same.

Piercing the DOM also lets Chrome send native DOM mutation events from shadow
trees that the document's MutationObserver cannot see. These events advance the
same state counter and quiet deadline. Continuously changing shadow content may
keep action settling active until its absolute two-second deadline; this has not
been measured on a live Chrome session. The helper retains these events so reads
are invalidated when shadow content changes.

When Chrome owns a native dialog, CDP reads include a `source_reason` pointer
with its HWND. Call `screen_windows` first to register current window identities,
then `screen_attach_window(window="<hwnd>")` with the dialog's returned window id
(or share the dialog from the helper). Then read its UIA controls, for example
`screen_elements(query='File name')`. The pointer includes
only visible, safely enumerable native dialogs within the existing HWND ownership
boundary; terminal, password-manager and security windows remain excluded.

The person authorizes use through window access; the captain or agent decides
what to upload. Local paths must resolve to readable regular files. Symlinks are
followed, and files inside the helper's own data and config directory are refused,
including paths that reach it through a symlink; this protects pairing credentials
and audit files. This is the only path restriction. The helper opens paths as the
signed-in user, so network share paths work wherever that user can open them. When a
path cannot be opened, the error gives the operating system's reason, such as a
network path that was not found, but never the path itself. Local files are passed directly
to Chrome without copying. Media IDs must be readable through `get_media` and are
downloaded into a fresh helper data directory with sanitized names. Staged media
files are deleted after ten minutes, or on a later call if the helper was restarted.
The existing general media per-file cap applies to every file, with a 200 MiB total
per call. The helper and server audit media IDs, resolved local paths and their sizes,
the grant, caller, file count and total size, without recording file contents.

### Window interaction benchmark

The `/lab/window-bench/` fixtures measure live Chrome window behavior using Partyline's MCP tools. The pages cover
open, nested, slotted and closed shadow roots; a covering overlay; same-origin and cross-origin frames; native and
custom selection; text entry; file controls; scrolling; settling; dialogs, toast and navigation; and a canvas that
requires visual point grounding. Each fixture exposes an AX-readable event log with `isTrusted`, event type and
target. The cross-origin page accepts a second-origin URL with `--cross-origin-url`; serve the built `partyline/static`
directory from a second port or hostname reachable by the paired computer.

After a person grants a Chrome window, run the bench from the attached Partyline process environment with its MCP
connection available. The command prompts you to open each fixture in the granted window. It never chooses a window
or grants access itself. Reads and actions use the same `screen_elements` and `screen_element_action` MCP tools as an
agent, so the UIA transport does not require Chrome debugging. `--transport` records which sibling path is being
measured; `--helper-version` records the helper build when it is not returned by discovery.

```bash
PARTYLINE_MCP_CONNECTION=/path/to/connection.json uv run --locked python scripts/window_bench.py \
  --i-have-a-granted-window --base-url https://<partyline-host> --window '<granted-window-id>' \
  --transport uia --helper-version '<helper-version>' \
  --cross-origin-url https://<second-origin> --output window-bench-results.json
```

The run writes JSON plus a Markdown summary next to the chosen output. A step is verified only from the fixture's
trusted event log and observed page state; an action response saying `completed` is not proof. Refusal cases count
as successful when the page confirms the cover or closed root and records no trusted target event. File chooser,
file selection and canvas point-click rows prompt for the person to perform that local action; their trusted event
logs are still verified. Those manual steps do not contribute to action latency. Compare verified and failed counts first, then p50/p95 action time,
response bytes, and estimated tokens. Text cost is response bytes divided by four; a screenshot row uses the
recorded `thumb`, `slim` or `original` tier estimate. Compare runs with the same fixtures and helper/transport labels.
Each scenario carries a tool and argument map, so point, scroll, type and drag MCP tools can be added as rows without
changing the runner; the row keeps the selected transport alongside each result.

Historical UIA medians remain: press **8.1 s**, select **4.9 s**, invoke **3.4 s** p50. They predate this bench and
are context, not a matched run.
