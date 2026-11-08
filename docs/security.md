# Security & caveats

- **Accounts are a gate, not a sandbox.** Anyone with an account can spawn processes as you.
  Keep the bind on localhost or a LAN you trust; if you expose it further, tunnel (SSH/
  tailscale) or put TLS on a reverse proxy. WebSocket and media tokens travel as `?token=`
  query parameters, so they appear in the server's access logs.
- Processes run with your user, your CLI logins, and the cwd you chose. The chat is a shared
  terminal, not a sandbox.
- Imported adapters are executed code. Review before importing.
- Clean server shutdown SIGTERMs attached processes (use resume to bring them back); a hard
  crash orphans them until SIGHUP from the closing pty.
- Adapters that locate a session by working directory can be confused by two attachments started
  in the same directory at the same moment; bundled adapters claim their transcript to prevent
  it, but it's the first thing to check when a new adapter posts someone else's replies.

## Local tools

Agents can ask to use a program on the person's computer through the helper (`docs/local-tools.md`). Every
session needs a fresh local Yes on that computer; grants live in memory only; the helper, not the server,
enforces consent, the lease, idle expiry and the kill switches (tray, Ctrl+Alt+Esc, the add-on's own End
button). The add-on listens on loopback with a per-install secret and refuses any request carrying a browser
`Origin`. Every script is audited twice, in the helper's own hash-chained file and on the server. Images a tool
makes (renders, viewport screenshots) never travel as the add-on wrote them: the helper fetches each one by id
(single use, same secret), decodes and re-encodes it under 4 MiB, and the server stores it as line-scoped
media, capped at 256 MiB per session.

**Render checks send images off the host.** The decision model is a hosted service, so a render goes there
only when the person ticked the separate render-check box (or answered the later dialog that asks for only
that) and has not withdrawn it (tray "Stop render checks"). The server sends only that session's own renders,
never screenshots, uploads or an earlier session's images, and re-checks the permission before every request.
The key (`PARTYLINE_DECISIONS_KEY`, else `OPENAI_API_KEY`) stays in the server's environment: it is in no
answer, no audit row and nothing the helper receives. Each check is audited with the images it sent.

## Machine API scope

### Screen helper pairing

Screen capture is performed by a native helper on the person's computer. Pairing
codes are single-use and expire after five minutes. Issuance is limited per account;
claims are limited per client address and globally, with repeated failed codes locked
for the five-minute window. Limits reset on server restart. A claimed computer receives a
random device token; Partyline stores only its SHA-256 hash and the owner can revoke
the device. The helper asks for local consent for every share. Capture is limited to
the selected OS-coordinate region and frames are size-capped. The WebSocket transport
rejects messages above 4 MiB for all sockets; the server keeps only
the latest 20 frames per active share in memory. A frame is written to media storage
only when attached to a message or fetched through `screen_frame`, where normal media
records provide the audit trail. Revocation or socket loss ends the share and drops
its buffered frames.

Windows window element access is a separate local, default-off grant, independent
of pixel sharing. From the helper tray a person selects one visible window by title
and process name and explicitly allows agents to read it. The helper records grants
and revocations in its local audit log, and the tray can revoke access. Access ends
when the window closes or the helper disconnects. UI Automation can expose text and
values from that window, including content not currently visible; password values
are excluded. Access pauses while a secure desktop is active and resumes when the
normal desktop returns. No input or window activation is performed by the reader.

Walkthroughs use the same per-share local consent. While recording, a line-wide
indicator identifies the person recording. Candidate frames and microphone
audio stay in memory: only the final message and selected image uploads are
saved. Ordinary frame attachment and `screen_frame` are unavailable during a
walkthrough. Cancel discards the take; a disconnected helper stops capture while the
owner can still send or discard the frames already received. Abandoned takes
expire automatically. Per-take limits are configurable with
`PARTYLINE_WALKTHROUGH_SECONDS` (default 600), `PARTYLINE_WALKTHROUGH_FRAMES`
(default 600), `PARTYLINE_WALKTHROUGH_BYTES` (default 134217728 per take),
and `PARTYLINE_WALKTHROUGH_TOTAL_BYTES` (default 536870912 across takes). The
duration limit also stops the share. Microphone audio is sent to the selected
speech recognizer and follows that recognizer's privacy policy.

Machine credentials are confined to their own line. A designated manager also
receives explicit capabilities on descendant lines; unrelated lines remain
inaccessible. Roles are read from current database records on every request.
Parent linking is human-only. Managers can appoint managers inside their own
subtree, and cannot grant access to an unrelated project.

Participants may inspect their own line, including its terminal screens, and
write messages and files. Sending terminal keys,
attaching or stopping processes, and overriding another participant's claim
require manager authority. Preset and adapter configuration changes are human-only, and so is every instance setting (global prose, resource budget, task-history cleanup, storage clearing and speech recognizers): a process token gets `403`. Speech-recognizer API keys live only in the server environment; settings names the variable and shows set or unset, and no endpoint accepts, returns or logs a key. The shutdown API is human-only and loopback-only; starting a fresh session, resuming,
editing a stopped command and removing a stopped record are gated by the `attach`/`close`
capability, not by where the caller is.
Fleet restart planning never silently narrows the requested instance scope:
a machine must manage every selected line, or planning is refused.

This is an API boundary, not OS isolation: attached processes still run under
the same local user. See [manager operations](hierarchy.md) and
[credential handling](credentials.md).
