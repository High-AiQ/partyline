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

## Machine API scope

Machine credentials are confined to their own line. A designated manager also
receives explicit capabilities on descendant lines; unrelated lines remain
inaccessible. Roles are read from current database records on every request.
Parent linking is human-only. Managers can appoint managers inside their own
subtree, and cannot grant access to an unrelated project.

Participants may inspect their own line, including its terminal screens, and
write messages, tasks, files, and their own claims. Sending terminal keys,
attaching or stopping processes, and overriding another participant's claim
require manager authority. Preset and adapter configuration changes are human-only. The shutdown API is human-only and loopback-only, as is starting a fresh session; removing a
stopped attachment record is not, since it controls no process.
Fleet restart planning never silently narrows the requested instance scope:
a machine must manage every selected line, or planning is refused.

This is an API boundary, not OS isolation: attached processes still run under
the same local user. See [manager operations](hierarchy.md) and
[credential handling](credentials.md).
