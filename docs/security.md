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
