# OpenCode v2 transcript provenance

`idle.jsonl` and `queued.jsonl` are redacted copies of user `session_message`
rows in `~/.local/share/opencode/opencode-v2.db`, SQLite rowids 3 and 7
(sequence values 13 and 37). The fixture keeps each actual marker and the
`data.text` shape; session IDs and surrounding message text are removed.

`provider-log.log` preserves the logfmt field shapes observed read-only in the
last 1 MB of the application log on 2026-11-04: TUI `cli starting`, its `spawning
process` with `serve --stdio --port 0`, the server's separate `cli starting`, and
that server's first `spawning process` with a cwd. No pid/ppid fields appeared in
those records. Times, run ids, commands, paths, claims and causes are replaced;
two activations are deliberately interleaved at identical startup times. Error
records use the reported `Failed to drain Session` shape. The later cross-cwd
tool spawn is a negative control: it must not revise the server's initial cwd.

The `args` field is a quoted logfmt string containing an escaped JSON array,
not a bare array. `provider-log-quoted.log` keeps the reported 2026-11-04
09:09:06 parent-spawn/server-start/server-spawn/error format literally, with
redacted command/cwd/account data and valid representative git arguments.
The parser regression asserts the outer logfmt decode returns a string before
binding decodes the inner array. Test log writers use that same encoding.
