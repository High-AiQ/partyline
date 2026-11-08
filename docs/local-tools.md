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
| helper → server | `tools_granted{session_id, checker, info}`, `tools_revoked{session_id, reason}`, `tool_result{call_id, ok, result \| error}` |

`tool_result.ok` is transport success; the script's own outcome is `result.ok`.

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

Code 64 KB; one call in flight; 60 calls a minute and 500 a session (`PARTYLINE_TOOLS_RATE`,
`PARTYLINE_TOOLS_SESSION_CALLS`); `exec` default 20 s, at most 120 s; output cut to 16 KB (head 12 KB, tail
4 KB, `truncated`); tracebacks 4 KB. The server waits `timeout + 5 s`, then sends `tool_cancel`.
Cancel is cooperative: a Python loop stops within about a second; a call stuck inside native code cannot be
stopped, so the session stays busy until the add-on is free again. A script that catches every exception in a
loop can also outlive its deadline; closing the application is then the remedy.

## Tests

`tests/test_local_tools_server.py` (hub, routes, MCP tools, helper over a pipe), `test_local_tools_helper.py`
(consent, kill switches, lease, idle, cool-down, audit, fail-closed) and `test_local_tools_addon.py` (the
loopback client against a real local HTTP server, the dialog checkbox). The add-on's own tests, including the
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
