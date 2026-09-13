# Configuration

## Serving on a specific IP or port

The default bind is `127.0.0.1:8642`. To choose another address or port, use command-line
options:

```bash
uv run --locked partyline --host 192.168.1.20 --port 9000
```

You can set the same values with `PARTYLINE_HOST` and `PARTYLINE_PORT`:

```bash
PARTYLINE_HOST=192.168.1.20 PARTYLINE_PORT=9000 uv run --locked partyline
```

For a persistent setting, create `partyline.toml` in the current directory, or
`~/.config/partyline/config.toml`:

```toml
[server]
host = "192.168.1.20"
port = 9000
```

Pass a different file with `--config /path/to/partyline.toml`. Settings are resolved independently
in this order: command-line option, environment variable, config file, then the defaults above.
Values loaded from the local `.env` file are part of the environment layer, so they take precedence
over the TOML config (an explicitly exported environment variable still wins over `.env`).
Binding to a non-loopback address exposes the chat and its ability to start processes to that
network; keep the server on a trusted network. Process-control endpoints such as shutdown remain
restricted to loopback callers — endpoints that *start or stop* a process, not every endpoint
about one. Forgetting an already-stopped card is authorized by capability alone, so an
operator can do it from a LAN browser. Partyline itself speaks HTTP; put TLS on a reverse proxy if you
need it.

When several Partyline servers are reachable from the same browser, give each one a visible,
deployment-neutral label with `--instance-name`, `PARTYLINE_INSTANCE_NAME`, or an `[instance]`
table in the same config file:

```toml
[instance]
name = "Development"
```

The label appears in a compact banner above the line. It does not change storage, networking, or
authentication, and an unset label leaves the existing interface unchanged.

Each running server owns one SQLite file (`PARTYLINE_DB`, default `~/.partyline.db`). Do not
point two processes at the same file: live posts only broadcast inside the process that wrote
them.

## Behind a reverse proxy

partyline builds the absolute URLs it hands to processes from the incoming request, so a proxy
that terminates TLS has to be trusted before the scheme is believed. Uvicorn honours
`X-Forwarded-Proto` only from addresses named in `PARTYLINE_FORWARDED_ALLOW_IPS`, which defaults
to the loopback alone — correct for a proxy on this host, silently wrong for one anywhere else.
Set it to the proxy's address:

```bash
PARTYLINE_FORWARDED_ALLOW_IPS=192.168.1.10 uv run --locked partyline
```

Leave it unset and every media URL goes out as `http://`, the proxy answers `301`, and any
reader that does not follow redirects saves the redirect body instead of the file. Whatever is
trusted here can also lie about the scheme and the client address, so name addresses rather
than widening it to everything.

Files live on disk, segregated by line, under a media root: `PARTYLINE_MEDIA_DIR` when set,
otherwise a `media/` directory named after the database file (`~/.partyline.db` →
`~/.partyline/media/<line>/`). Point it at a NAS mount if the files should live with the
rest of your data. Purging a line deletes its files too. Every media response is `nosniff`.
Only `image/*` (except SVG), `audio/*`, `video/*`, `application/pdf`, and `text/plain` are
served `inline`; everything else — including HTML, XHTML, SVG, and XML — is
`Content-Disposition: attachment`, so user documents are never executed from partyline's origin.

## Environment and config file

| env var | default | notes |
|---|---|---|
| `PARTYLINE_PORT` | `8642` | bind setting; see [Serving on a specific IP or port](#serving-on-a-specific-ip-or-port) |
| `PARTYLINE_HOST` | `127.0.0.1` | bind setting; see [Serving on a specific IP or port](#serving-on-a-specific-ip-or-port) and [Security](security.md) |
| `PARTYLINE_INSTANCE_NAME` | unset | optional label shown above every line; CLI/config precedence matches bind settings |
| `PARTYLINE_DB` | `~/.partyline.db` | conversations, messages, attachments, presets. One file per running server — do not share it across processes |
| `PARTYLINE_MEDIA_DIR` | `<PARTYLINE_DB stem>/media` | uploaded files, one subdirectory per line |
| `PARTYLINE_ADAPTERS_DIR` | `~/.partyline/adapters` | where imported adapter repos are checked out |
| `PARTYLINE_FORWARDED_ALLOW_IPS` | `127.0.0.1` | upstream addresses whose `X-Forwarded-*` headers are trusted; set this to your reverse proxy's address or the absolute URLs partyline hands to processes will carry the wrong scheme. See [Behind a reverse proxy](#behind-a-reverse-proxy) |

The optional server config file uses `[server] host` and `port`, plus optional `[instance] name`; see
[Serving on a specific IP or port](#serving-on-a-specific-ip-or-port) for its search paths and
precedence.

The working-directory `partyline.toml` is relative to the server's current directory. Use
`--config` or `~/.config/partyline/config.toml` for a setting that should not depend on cwd.

When partyline is served by an external ASGI runner instead of `uv run partyline`, that runner
does not call `main()` and therefore does not apply `PARTYLINE_HOST`, `PARTYLINE_PORT`, or the TOML
config automatically. Resolve the settings with `partyline.bind.resolve_bind` and pass the result
to the ASGI server yourself.

Control actions are exposed as REST (`/api/conversations`, `/api/adapters`, `/api/presets`,
`/api/attachments/<id>/compact`,
`/api/attachments/<id>/{resume,screen,keys}` plus `PATCH /api/attachments/<id>`), as are the
coordination surfaces a process needs — files (`/api/conversations/<id>/files`, the
`/images` alias, `/api/media/<id>/{original,thumb,slim}`), the goal, child lines and
reports — so creating lines, attaching processes, editing stopped commands, peeking,
resuming and posting a file are all scriptable from anything that can curl.
The live terminal is a WebSocket at `/ws/attachments/<id>/terminal`. **Chat itself is not
REST**:
sending a message and receiving live updates both happen over the WebSocket at `/ws/<conv-id>`,
so a script that needs to talk on a line has to speak that protocol.

**Stopping partyline.** `POST /api/shutdown` stops the server gracefully — attached processes are
stopped through the normal lifespan teardown, so nothing is orphaned — and `GET /api/running`
lists what would be stopped. Both are also in the UI, as **stop** next to the operator name in
the sidebar footer. Shutdown is refused unless the request comes from this machine, since the
bind address is configurable and localhost-only is not something to assume.
