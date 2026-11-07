# Development

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and `git`. `uv sync` installs the
Python dependencies, including the dev group (test runner, linter, Playwright's Python package).
Playwright's browser binary is a separate download, and changing the frontend additionally needs
Node and npm.

```bash
uv sync --locked                         # pinned runtime + dev dependencies
uv run --locked playwright install chromium       # once, for the UI tests and screenshots
```

**Node is needed only to change the frontend**, not to run partyline. The built client is
committed under `partyline/static/`, so a fresh clone and an installed wheel both serve the UI
with Python alone.

### The frontend

The client is strict TypeScript with [Svelte 5](https://svelte.dev),
[Tailwind](https://tailwindcss.com), and Zod runtime validation at its REST and WebSocket
boundaries. Vite builds it into `partyline/static/`:

```bash
cd frontend
npm install
npm run dev      # hot reload, proxying /api and /ws to a partyline on $PARTYLINE_PORT
npm run verify   # format + lint + svelte-check + tests; the gate CI runs
npm run build    # → partyline/static/ — rebuild before committing a UI change
npm run format   # apply Prettier
```

`src/lib/` holds framework-free functions — markdown rendering, mention candidates, jack
selection, routing — and is where most of the pure unit tests live. `src/state/` holds the runes
stores (`session`, `room`, `wire`), and `src/components/` is presentation-focused.

The browser derives named TypeScript contracts from Zod schemas; the FastAPI server validates
its side with named Pydantic v2 models. `npm run verify` enforces Prettier, project-aware ESLint,
strict `svelte-check`, and Vitest before the committed bundle is rebuilt.

#### Release identity and browser build

`partyline.__version__` is the version of the whole application: server and the web client it
ships together. It changes for every feature or fix. The frontend `build` value in
`partyline/static/build.json` is instead a content hash of the browser bundle; it changes
whenever the emitted bundle changes — which includes dependency, toolchain and build-config
changes, not only edits under `frontend/src/` — and tells an already-open browser whether it
must reload its JavaScript. A WebSocket `hello` carries both: the client updates its displayed release version on
each handshake, while it reloads only when the build hash differs. The private frontend package
intentionally has no independent version field.

### Running the tests

```bash
./scripts/capped-test                    # parallel suite + combined coverage, under a 4 GB cap
./scripts/capped-test --workers 4        # override the default min(8, cores/2) workers
uv run --locked coverage report          # fails under 90% line+branch coverage
uv run --locked ruff check .             # lint; must be clean before every commit
```

The default runner discovers test modules, balances them across process shards, and combines
every worker's branch coverage afterward. Each worker must complete exactly the number of tests
discovered in its shard, and their sum must equal the full discovered total; skips are reported
without pinning a historical count. Each worker gets its own database, media, and temporary
directory. The 4 GB cap covers the complete cgroup or Windows job; the verified
`RLIMIT_AS` fallback is inherited by every process but limits each process individually. CI uses
the same capped parallel command with two workers.

Every worker records per-test durations. The run prints the ten slowest tests. Any unallowlisted
test over one second is rerun once, alone in a fresh warm worker, with both durations printed; CI
fails only if that rerun fails or remains over one second. Genuine workloads can instead carry an
explicit reason in `scripts/test_time_allowlist.py`. Tests must inject clocks, patch timeout
constants in the calling module, or resolve events rather than wait out real sleeps, polling,
startup delays, or stop timeouts. The allowlist is for real work such as concurrency or Git
integration, never for a delay.

To run a focused test under the same memory guard, pass a command explicitly:

```bash
./scripts/capped-test -- uv run --locked python -m unittest tests.test_db
```

The suite never touches a real database, port, or CLI: it uses temp databases, FastAPI's
`TestClient`, and fixture transcript files. Adapter tests never invoke the vendor tool they
adapt.

### UI tests and screenshots

Browser tests live under `tests/ui/` and are deliberately **not** picked up by `discover`, so a
missing browser can't break the normal suite. Run them explicitly:

```bash
uv run --locked python -m unittest tests/ui/test_line_menu.py -v
```

`scripts/uishot.py` drives the real UI in headless Chromium. It starts a throwaway server on an
OS-assigned port with a temp database, signs in through the handle gate, and hands back a
Playwright page — so a frontend change can be looked at instead of guessed at:

```bash
uv run --locked python -m scripts.uishot --out /tmp/partyline-ui   # capture the standard state set
```

```python
from scripts.uishot import ui_session

with ui_session(["alpha line", "beta line"]) as ui:
    ui.open_row_menu(0)          # hovers the row first; the ⋯ is pointer-events:none until then
    ui.shot("menu-open")
```
