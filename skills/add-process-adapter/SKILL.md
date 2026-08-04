---
name: add-process-adapter
description: Create, package, import, reload, test, or review a Partyline adapter for an interactive process. Use when adding a built-in process adapter, publishing an external adapter repository, or diagnosing adapter discovery and lifecycle behavior.
---

# Add a process adapter

Read `docs/adapters.md` before implementation. Use one package per process:

```
partyline/adapters/<adapter-id>/
  adapter.toml
  adapter.py
```

Use the same `adapters/<adapter-id>/` layout at the root of external adapter repositories. Keep
the directory id lowercase, stable, and URL-safe.

## Define the manifest

Create `adapter.toml`:

```toml
[adapter]
name = "Example Process"
version = "0.1.0"
description = "Interactive adapter for Example Process."
entrypoint = "adapter.py"
command = ["example-process"]
requires = []
capabilities = []
env_unset = []
```

Use an argv array for `command`, not a shell string. Keep secrets and machine-specific paths out
of the manifest. Use `env_unset` only for inherited variables that would interfere with a child
process.

## Implement lifecycle behavior

Export a `PartylineAdapter` class from `adapter.py`, subclassing the framework adapter base.
Implement the interactive argv and any transcript or log tailing needed by the process. Preserve
these invariants:

- Start the actual interactive executable in the supplied pty; do not substitute a headless
  mode or an SDK call.
- Send chat input through the inherited bracketed-paste-plus-Enter path.
- Drain terminal output continuously so the child cannot block.
- Prefer structured transcripts or logs for assistant replies. Do not turn a terminal screen
  into chat messages.
- Start observing output after this attachment starts, and avoid replaying prior records after
  a resume.
- Report meaningful lifecycle status and cleanly stop background tasks.

Use the attachment working directory and inherited environment. Do not edit shell profiles or
persist credentials. If a process needs credentials, document its variable name without a value.

## Test locally

Run partyline with a throwaway database and port. Test start, mention delivery, output posting,
exit, terminal peek, and stop. Exercise import and reload:

```bash
curl -X POST http://127.0.0.1:8643/api/adapters/import \
  -H 'content-type: application/json' \
  -d '{"repository":"https://github.com/example/partyline-adapters.git"}'
curl -X POST http://127.0.0.1:8643/api/adapters/reload
curl http://127.0.0.1:8643/api/adapters
```

Validate missing manifest fields, duplicate ids, an invalid entrypoint, and a process that exits
before producing output. Review imported source before executing it.
