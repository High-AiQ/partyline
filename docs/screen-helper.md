# Native screen helper

Run this program **on the computer whose desktop you want to share**. It makes an
outbound connection to Partyline; it needs no inbound firewall rule or browser
capture extension. Windows 11 is the primary target; macOS and Linux X11 need the
permissions described below. Python 3.11+ and uv are required.

The Partyline dialog ("Computers / Share screen" → "Pair a computer") shows these
commands with your server's address and a pairing code filled in, each with a copy
button. Run them in a terminal **on the computer you want to share, not on the
Partyline server**. After `pair` succeeds the helper prints the full `run` command
for both forms below. Keep the `run` terminal open and answer `y` to each share prompt.

## One-time install (recommended)

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
`run --yes` explicitly disables per-request confirmation and prints a warning;
use it only when you intend every incoming request to be accepted.

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
No audio or input events are collected. The helper never moves the pointer or types.
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

## Platforms and troubleshooting

- **Windows:** no administrator access required. Per-monitor DPI awareness is set
  before initializing capture or pointer reading so coordinates use physical
  desktop pixels, including negative origins. UAC and secure-desktop windows are
  not captured. Keep the helper on the interactive desktop session.
- **macOS:** System Settings → Privacy & Security → Screen Recording (called
  Screen & System Audio Recording on newer versions): enable the terminal or
  Python application running the helper, then quit and reopen it. Reading the
  pointer does not require Accessibility permission. The helper checks Screen
  Recording permission and rejects black captures with instructions (a completely black desktop can also
  trigger that warning). Retina capture pixels can differ from desktop points;
  the helper multiplies desktop points and pointer positions by the uniform
  display backing scale and converts capture rectangles back to points. Mixed
  Retina display scales are refused rather than reporting ambiguous coordinates;
  use displays with the same scale. Test monitor selection on your actual Mac
  before sharing sensitive material.
- **Linux:** use an X11 session with access to its display. A Wayland session
  (`XDG_SESSION_TYPE=wayland` or a set `WAYLAND_DISPLAY`) exits with
  `Wayland is not supported yet (needs the xdg-desktop-portal ScreenCast/RemoteDesktop route)`.
  Portal support is a later phase.

If pairing fails, check the origin, network, TLS certificate and code expiry.
If revoked, create a fresh code and pair again. If capture initialization fails,
verify desktop permissions and install the `helper` extra. The dependencies are
mss (MIT), pynput (LGPL-3.0), websockets and Pillow; pynput is used only for reading
the pointer. Automated tests use fake capture and an in-process server. The
headless development server cannot verify real desktop capture; native interactive
smoke testing is still required on each platform.
