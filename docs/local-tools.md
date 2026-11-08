# Local tools

An agent on a line can ask to use a **local tool** on the person's own computer: a program there that
Partyline's helper can reach through a small add-on. The wire format, consent and audit are generic; the first
tool is exposed to agents as the `blender_*` MCP tools (`partyline/mcp/tools_blender.py`) and the helper's
adapter registry (`partyline_helper/tools_addon.py`). Design and decisions: `docs/design/blender-python-relay.md`.
The add-on lives in the `partyline-addons` repository.

## Path of a call

`MCP tool` → server REST (`partyline/local_tools_routes.py`) → `LocalTools` hub (`partyline/local_tools.py`) →
helper websocket → helper (`partyline_helper/tools.py`) → add-on on `127.0.0.1:<ephemeral port>` with a bearer
secret. The server never sees the secret or the port: only the helper reads the add-on's discovery file next
to `helper.json`.

Wire messages (helper hello advertises `tools: 1`):

| Direction | Message |
| --- | --- |
| server → helper | `tools_request{session_id, tool, requested_by, line_name, checker, scope_only}`, `tool_call{session_id, call_id, op, args, timeout}`, `tool_cancel`, `tools_revoked{session_id, reason}` |
| helper → server | `tools_granted{session_id, checker, info}`, `tools_revoked{session_id, reason}`, `tool_result{call_id, ok, result \| error, media?, mime?}` |

`tool_result.ok` is transport success; the script's own outcome is `result.ok`. A result with `media: true` is
followed by exactly one binary message (the image), as frames are; the hub reads it in the same step, so the
stream stays aligned even for a call nobody awaits any more.

## Images: render and screenshot

`blender_render` and `blender_screenshot` run under the same session grant, limits and audit as `exec`.

1. The add-on clamps and reports (`adjusted`): sides 16..2048 px, samples 1..64, frame inside the scene's
   range (the scene's own sample count is clamped too), viewport screenshots at most 1600 px on the long edge. Only the two fast engines named in
   `blender_render` are offered, never the slow one. It writes a PNG to a private temp directory under a random **artifact id** and answers with the id and
   the settings used.
2. The helper fetches the artifact (`POST /artifact`, single use, session-bound), **decodes and re-encodes** it
   (WebP, JPEG without WebP support; size unchanged, metadata dropped) and sends it as the binary message above.
3. The server checks it decodes, stores it with `screen_frame_store.store_frame` (line-scoped media, no chat
   post) and returns the `screen_frame` reference shape: `file` (use `get_media`), plus `settings`, `adjusted`
   and `media{mime, bytes, width, height}`.

**4 MiB ceiling.** The WebSocket rejects messages above 4 MiB (`MAX_FRAME_BYTES`) and closes the connection, so
the helper never sends one: after re-encoding at quality 85, 70 and 50 an image still above 4 MiB is refused with
"the image is N MiB at WxH even after compression, over the 4 MiB limit; ask for a smaller size". The size is
never reduced silently. The add-on refuses to hand over a file above 32 MiB. A session may store 256 MiB of
images (`local_tools_media.SESSION_BYTES`); then it needs a fresh grant.

**Audit.** The call rows now carry the request (`render {"camera":"Side","width":640}`), the result rows the
outcome (`ok (image/webp, 12345 bytes, 640x360)` in the helper copy, `ok, media <file id>` on the server), so
both copies show what was rendered and what came back.

## Open risks of the image tools (phase b)

- **GPU offscreen on Greg's machine.** `blender_screenshot` draws the viewport into an off-screen GPU buffer,
  and `blender_render` with `engine="eevee"` needs a working GPU context. CI fakes the application's Python API,
  but the add-on was also driven in the real application, version 5.2.2, under a virtual display with software
  GL: the `eevee` engine identifier, drawing the viewport from a timer callback, saving a generated image, the
  clamps, restoring the scene's settings and an overrun render all behaved as described here. **A real GPU on
  Windows is still open**; the checklist rows below are that test. A failure comes back as an error naming the
  exception, never as an empty image.
- **Render cancel.** A render is one native call on the application's main thread and cannot be interrupted
  from Python. The server cancels at `timeout + 5 s`, the kill switches end the session at once and the helper
  stops waiting, but the application stays busy until the frame finishes; the add-on then discards the image and
  the next call is refused as busy until it does. The clamps (2048 px, 64 samples, fast engines only) bound how
  long that can be.
- **4 MiB ceiling.** See above. Noisy or very large renders can exceed it; the answer is a smaller size, not a
  silent downscale. A larger limit would mean raising `MAX_FRAME_BYTES` for every socket.

## Consent and the kill switch

- **Every session asks again**, on the person's computer: a native Yes/No dialog with a one-second guard and a
  60 s timeout. Silence declines. There is no flag that grants without a prompt; the helper refuses any
  `tool_call` unless it holds a live local grant, so a compromised server cannot forge one.
- The dialog has a checkbox for render checks, **unticked by default**. Phase (a) only records the choice in the
  grant (`tools_granted.checker`); nothing uses it yet. Adding it to a live session needs a fresh dialog.
- Grants live in memory only. A server restart, a helper restart, a lost connection or the add-on's restart
  ends them. The session is not tied to a screen share.
- The grant is bound to the requesting agent and one session.
- Ends without the server: tray "End agent session" and Quit, **Ctrl+Alt+Esc** (the control kill switch), the
  add-on's End button, and the add-on lease (the helper renews every 5 s; 15 s of silence ends the session, so
  a dead helper fails closed). Also from Partyline: `DELETE /api/local-tools/sessions/{id}` by the computer's
  owner, and the agent's own `blender_end`.
- After a **local** kill (tray, hotkey, End button) the agent may not re-ask for 10 minutes. 15 minutes
  without a call ends the session. Both are enforced by the helper.
- The tray icon turns violet (`tools`) while a session is live, only if the helper was otherwise idle.

## Audit

Every script is recorded in two places, so neither side can edit the other's copy.

1. **Helper:** `tools-audit.jsonl` in the helper's config directory (`%LOCALAPPDATA%\Partyline` on Windows),
   hash-chained, appended *before* the script is sent. If the log cannot be written the call is refused.
2. **Server:** table `local_tool_audit` (hash-chained, full code up to 64 KB). A system note "Local tools
   audit — … [audit sha256: …]" is posted to the line in batches (every 25 rows or 60 s, at once on revoke);
   notes wake no process. Pending batches are published again after a restart.

## Limits

Code 64 KB; images 4 MiB each and 256 MiB a session; one call in flight; 60 calls a minute and 500 a session (`PARTYLINE_TOOLS_RATE`,
`PARTYLINE_TOOLS_SESSION_CALLS`); `exec` default 20 s, `blender_render` default 60 s, both at most 120 s; output cut to 16 KB (head 12 KB, tail
4 KB, `truncated`); tracebacks 4 KB. The server waits `timeout + 5 s`, then sends `tool_cancel`.
Cancel is cooperative: a Python loop stops within about a second; a call stuck inside native code cannot be
stopped, so the session stays busy until the add-on is free again. A script that catches every exception in a
loop can also outlive its deadline; closing the application is then the remedy.

## Tests

`tests/test_local_tools_server.py` (hub, routes, MCP tools, helper over a pipe), `test_local_tools_helper.py`
(consent, kill switches, lease, idle, cool-down, audit, fail-closed), `test_local_tools_addon.py` (the
loopback client against a real local HTTP server, the dialog checkbox) and `test_local_tools_media.py` (images
stored and returned as media, the 4 MiB refusal, no grant, cancel, kill switch, both audit copies). The add-on's own tests, including the
wrong-secret, browser-origin and runaway-loop cases, run against a fake `bpy` in `partyline-addons`.

## Windows live acceptance (Greg runs this)

- [ ] Install the add-on's extension zip, enable it, run the helper. `blender_request` shows the dialog **in
  front of other windows**; the checkbox is unticked.
- [ ] Decline: the agent is told; no banner appears in the application. Silence for 60 s does the same.
- [ ] Accept: banner shows the agent's name, a backup copy of the open file is written next to it, and
  `blender_exec` runs `print(1)`; Ctrl+Z in the application steps back over a script that changed the scene.
- [ ] Each of these ends the session and the **next** call is refused: Ctrl+Alt+Esc, tray "End agent session",
  tray Quit, the add-on's End button, killing the helper process (lease lapses within about 15 s), unplugging
  the network (the helper disconnects).
- [ ] After a local kill, a new request is refused for 10 minutes with that reason; afterwards the dialog
  appears again with the checkbox unticked.
- [ ] A browser `fetch` to the add-on's port is refused (origin), and a request with a wrong secret gets 401.
- [ ] `while True: pass` with `timeout_s=3` returns a deadline error and the application stays usable.
- [ ] `tools-audit.jsonl` and the line's audit note show the same scripts and hashes.
- [ ] Phase (b), reinstall the 0.2.0 zip: `blender_render` with defaults (Workbench) returns a `file` reference;
  `get_media` shows the scene from the active camera; the scene's camera, resolution and engine are unchanged
  afterwards. A second camera by name works; a wrong name lists the cameras.
- [ ] `blender_render` with `width=5000, samples=500, engine="eevee"` reports the clamps in `adjusted`
  (record whether `eevee` works on this GPU).
- [ ] `blender_screenshot` returns the 3D viewport as the person sees it (not a black or empty image). Record the
  GPU and driver if it fails.
- [ ] A render that takes a few seconds with `timeout_s=1`: the agent gets the timeout, the application finishes the
  frame, no image arrives and the next call works once it is free. Pressing Ctrl+Alt+Esc during a render ends the
  session at once, and no image is delivered.
- [ ] Both audit copies show the render request and its outcome.
