# Adapter packages

An adapter package connects partyline to one interactive process. A package can ship with
partyline or live in an importable repository. Imported repositories must put packages directly
under `adapters/`:

```
adapters/
  example-process/
    adapter.toml
    adapter.py
```

The directory name is the stable adapter identifier. Use lowercase letters, digits, and hyphens.

## Manifest

Every package needs `adapter.toml` with one `[adapter]` table:

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

`name`, `version`, `description`, `entrypoint`, and `command` describe the package. `command`
is an argv array, not a shell string. `requires` declares required local prerequisites.
`capabilities` declares optional behavior exposed by the package. `env_unset` lists inherited
environment variables that must be removed before the process starts. Never put secrets in a
manifest.

## Entrypoint

The entrypoint file must define an adapter class named `PartylineAdapter` that subclasses the
framework adapter base. Keep process-specific code inside the package. The class should build the
interactive argv, consume a structured transcript or log when available, and delegate terminal
input to the base class.

An adapter must keep the terminal drain active, avoid replaying old transcript records after a
resume, and clean up background tasks on stop. Do not use a screen scrape as chat output.

## Import and reload

Import a repository with `POST /api/adapters/import` and JSON containing `repository` plus an
optional `ref`. partyline clones it into its local adapter store and validates every discovered
manifest. Use `GET /api/adapters` to inspect enabled metadata. Use
`POST /api/adapters/reload` after changing installed adapter code or manifests.

Imported code runs locally with the user's privileges. Review it before import.
