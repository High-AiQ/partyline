# Frontend: contracts and conventions

The client is a Svelte 5 app built by Vite into `partyline/static/`, which the server serves:
`/` is `index.html` and `/assets/*` is mounted `StaticFiles`. AGENTS.md carries the musts
(`npm run verify`, rebuild before committing UI changes); this file is the depth behind them.

```bash
cd frontend
npm install
npm run verify    # format:check + lint + svelte-check + tests — the gate
npm run build     # → partyline/static/  (do this before committing UI changes)
npm run dev       # hot reload against a partyline on $PARTYLINE_PORT (default 8642)
npm run format    # apply Prettier; `lint:fix` for the auto-fixable lint
```

**`npm run verify` must pass before every frontend commit**, and it is what CI
runs — the same command, so the two can never disagree. It is four gates:
Prettier formatting, ESLint, `svelte-check` at zero errors *and zero warnings*,
and the unit tests.

Formatting is Prettier's alone; `eslint-config-prettier` is last in the flat
config so ESLint has no stylistic opinions left to argue with. Note this is the
opposite of the Python rule below, where the autoformatter is deliberately not
enforced — that exception is about hand-wrapped Python, and does not extend to
the frontend.

Two ESLint settings are load-bearing rather than taste:

- **Core `prefer-const` is off inside Svelte files**, replaced by
  `svelte/prefer-const`. Props are declared `let { … } = $props()` and are
  reassigned by the framework rather than by us, so the core rule "fixes" them
  into `const` and silently breaks reactivity. It wanted to do that to 45
  declarations.
- **`svelte/no-useless-mustaches` allows string escapes**, because
  `placeholder={"a\nb"}` is the only way to get a newline into an attribute.

**`partyline/static/` is committed on purpose.** partyline installs and runs as
a Python package; requiring Node to build a wheel, or to start a fresh clone,
would break that. The cost is that a UI change is two things in one commit — the
source under `frontend/src/` and the rebuilt bundle. Rebuild before you commit,
or you will ship a stale UI that matches none of the source.

**Release and frontend build identity are different facts.**
`partyline/__init__.py` is the single source of truth for Partyline's semver
release as a whole: server, bundled client, database/protocol behavior, and
fixes. `partyline/static/build.json` identifies only the frontend bundle and
decides whether an open document must reload. A reconnect must still refresh
the release version even when the build ID is unchanged. Adapter repositories
have independent versions; `frontend/package.json` is not a Partyline release
source.

Layout, and where things belong:

- `src/lib/` — **pure functions, no framework.** Markdown rendering, mention
  candidates, jack selection, routing, the REST client. Anything with a rule in
  it belongs here, because this is the layer that gets unit tests.
- `src/state/*.svelte.ts` — runes stores: `session`, `room`, `wire`, `draft`,
  `dialogs`. One owner per concern; components read them and call methods.
- `src/components/` — presentation, grouped by region (`rail/`, `chat/`,
  `board/`, `dialogs/`).

**Responsive layout.** Three columns need about 900px. Below that the rails
become drawers over the line and exactly one can be open — before this, the
centre column computed to `0px` on a phone and the conversation itself was
invisible while the lines list and attach form took the whole screen.

The breakpoint lives in two places that have to agree, because CSS cannot read
a TypeScript constant: `NARROW_MAX_WIDTH` in `state/layout.svelte.ts`, and the
`@media (max-width: 899px)` blocks in the components. If you move one, move the
other. Everything responsive is inside those blocks on purpose — the desktop
layout is the app's identity, and keeping it out of the cascade is what lets
the parity harness prove it has not moved.

Two rules that are load-bearing rather than stylistic:

- **The wire's generation guard.** `wire.connect()` bumps a counter and every
  handler checks it. A socket closed while switching lines keeps firing, and
  without the guard the old line's traffic lands in the new line's feed.
- **Escape first, then parse.** `renderMessage` escapes the body before
  `marked` sees it, and DOMPurify runs after. Escaping is not redundant with
  the sanitiser: it is what keeps a message that *says* `<b>` looking like the
  text somebody typed, and stops a hand-written `<span class="mention">` from
  drawing a fake mention.

`window.partyline` exposes `{room, session, wire}` as a deliberate test surface
for `tests/ui/`, which needs to drop a socket and deliver fabricated events.
Treat it as API: if you rename a store, fix those tests.

TypeScript is strict from the compiler through ESLint: `strict`,
`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, and project-aware
typescript-eslint rules are all gates. Do not introduce `any`, double casts, or
blanket suppressions to get through them; narrow `unknown` or fix the contract.

Zod owns external browser boundaries: REST responses, WebSocket frames, and
persisted browser values are parsed before they enter application state. Name a
schema `PascalCaseSchema` and derive its TypeScript type with `z.infer` so the
runtime validator and compile-time contract cannot drift. The server mirrors
this with named Pydantic v2 request, response, and event models.

Object-shaped values that cross a function, component, store, REST, or wire
boundary need a named interface, type, or schema. Local object literals are
normal implementation code; anonymous object *contracts* are what is banned.

