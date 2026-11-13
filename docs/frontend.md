# Frontend: contracts and conventions


| DO | DO NOT |
| --- | --- |
| Run `npm run verify` before every frontend commit, and commit the rebuilt `partyline/static/` bundle with the source | Ship UI source whose bundle matches nothing, or a bundle without its source |
| Keep rules in `src/lib/` (pure, unit-tested), state in runes stores, looks in components | Bury business logic inside components where no test can reach it |
| Prefer Tailwind utility classes on markup for layout, spacing, color, typography, and simple states | Add new hand-written rules in `<style>` for anything a utility already expresses |
| Keep design tokens in `src/app.css` `@theme` and use the generated utilities (`bg-ink`, `text-copper`, …) | Invent parallel color or spacing constants inside component CSS |
| Leave custom CSS for keyframes, complex selectors, pseudo-elements, and shared `@layer components` vocabulary (`.led`, dialog forms) when utilities would obscure the contract | Grow per-component scoped styles for ordinary layout and chrome Tailwind already covers |
| Treat `static/build.json` as frontend-bundle identity only; release semver lives in `partyline/__init__.py` | Use either file as the other's source of truth |
| Let Prettier own formatting; hand-wrap Python by the repository convention | Enforce an autoformatter on hand-wrapped Python or argue style through ESLint |

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
  `board/`, `dialogs/`). Looks are Tailwind utilities on the markup first;
  a component `<style>` block is the exception, not the default.
- `src/app.css` — Tailwind v4 entry (`@import "tailwindcss"`), `@theme` design
  tokens, base resets, and shared `@layer components` vocabulary reused across
  regions. Token names become utilities (`--color-ink` → `bg-ink` / `text-ink`).

**Styling.** Tailwind is the default for component looks. Convert layout,
spacing, color, and typography to utilities before reaching for a scoped rule.
Custom CSS stays legitimate for animations/keyframes, pseudo-elements (the film
grain), selectors Tailwind expresses poorly, and the shared vocabulary in
`@layer components` that several regions must share by construction (`.led`,
dialog form chrome). When you add a token, put it in `@theme` so both utilities
and any remaining hand-written rules read one source of truth. Responsive
rules still have to agree with `NARROW_MAX_WIDTH` in `state/layout.svelte.ts`
(today: `899px`) — a utility breakpoint that drifts from that constant is the
same bug the dual-source note below is about.

**Authentication.** `src/lib/http.ts` owns the credential lifecycle. Access and refresh tokens
live in `localStorage` (shared, so a second tab is already signed in); the socket `client_id`
lives in `sessionStorage` (per tab, so two tabs are two distinct connections rather than one
tab's reconnect killing the other). REST calls send `Authorization: Bearer`; WebSocket URLs
take `?token=`, because a browser cannot set headers on an upgrade — the structural cost is
that tokens land in the server's access logs, which is why the deployment story stays
loopback/LAN. Concurrent 401s share one in-flight refresh and retry once. A socket closed with
code 4401 is not assumed expired — a handle change closes healthy sockets with 4401 too — so
the stored access token gets one retry before any refresh, and only a genuine auth failure
(401, or no stored refresh token) clears the session; network and 5xx answers keep the tokens
and fall back to the reconnect timer. Auth payloads are Zod-parsed like every other boundary.

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

`window.partyline` exposes `{room, session, wire, presence}` as a deliberate test surface
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

## Screen sharing

Pair the native screen helper from a line's Computers panel. The helper reports
monitors in OS virtual-desktop coordinates; the browser uses its monitor preview
to select a crop and asks the helper to start. The helper requests local consent
before capture. Frames arrive as bounded still images at about one frame per
second and stay in server memory until attached to a message or requested by
`screen_frame`. The line composer can attach up to three recent distinct frames.

The composer’s **Screen** menu puts **Share screen + record voice** first, with a
**Frames + transcript on stop** explanation and a **Show me** tooltip alias. **Share screen only**
is explicitly a **Live view · no voice**. Recording is available when a paired
computer is online and uses the same computer, monitor, crop, and local consent flow; a subsequent
take reuses the last selected region on that line while its computer is online.
After consent, the browser opens the microphone and the line shows a recording
indicator. Stop transcribes the take and sends one message with timestamped
speech and selected frames. Notes typed in the composer accompany it; the
optional pointer marks default off. Cancel or Escape releases the microphone,
ends the share and discards the take. A disconnected helper ends capture and
the frames already received can still be sent. A failed recognizer leaves a
note in the message alongside those frames.

On a narrow screen (`layout.narrow`, the same breakpoint as the drawers) the **Screen** menu is not offered: a phone cannot run the helper or
share its own screen. A share another device started still shows as status with its **Stop**,
and a walkthrough already under way keeps its Cancel. While an agent holds control
(`share.control.status === "active"`) `ControlBadge` draws a pink pulsing dot and a monitor
icon, with a "Controlling <computer> (N actions)" tooltip, beside the share status and on the
holder's process card and mention row. `lib/screen-control.ts` decides when it shows: pending
or revoked control, another agent's grant, or no share at all draws nothing, and a line-wide
grant (no named holder) badges the share status only. The pulse stops under
`prefers-reduced-motion`; the colour is the `--color-pink` token, tuned for both themes.

Orchestrator controls live in `CaptainStyleSection` (root-line management only)
and `TaskHistorySetting` (beside the resource budget). Line responses carry derived
task status, round and participant names, shared by `TaskStatusChip` and
`TaskLineHeader`. The header reads the refreshed rail entry so a task verdict
updates it through `conversations_changed`, including after reconnect; it needs
no per-task polling. Captain-style and retention writes use named Zod contracts
in `orchestrator-api.ts`; failed retention writes restore the previous toggle.

Inside an attached process, bound Vitest's worker pools to stay within the
attachment memory budget: `VITEST_MAX_FORKS=2 VITEST_MIN_FORKS=1
VITEST_MAX_THREADS=2 VITEST_MIN_THREADS=1 npm run verify` (one shell command).
Run it serially with backend gates and browser captures; host CPU count does
not describe the attachment's available memory.

Task rows also show `blocked` when the implementer reports a blocker. Task lines
hide the manual process attachment panel because their staffing is server-owned.

The conversation rail puts a person's starred lines in a `Starred` group above
the regular hierarchy, preserving normal order inside each group. Stars are
stored per account; `conversations_changed` refreshes the list across tabs. A
starred child is shown with its ancestors expanded in the rail without changing
the saved expansion choices.

Jack cards use the adapter's `listens` capability (default true). Live listeners
show peek; stopped listeners keep resume, start fresh and edit command. Non-listeners
hide peek and offer restart alongside edit command when stopped. Restart reruns
the stored command through `POST /api/attachments/<id>/resume` (the server reruns a
non-listener fresh, and the route is not loopback-gated) with no checkpoint dialog. A
failed resume or restart shows as a toast and as inline text on the card.

Settings is one modal with tabs (`components/dialogs/SettingsDialog.svelte`), routed by
`#/settings/<tab>`: the tab links are real links, so a deep link opens the modal on that tab and
Back/Forward move between tabs. `state/settings-nav.svelte.ts` reads the hash and
`components/settings/SettingsRoute.svelte` opens or closes the modal to match; App skips
`room.onRouteChange()` for settings routes so the line underneath stays put. Every tab and row is
listed once in `lib/settings-registry.ts`, which drives the nav, the search box and the focus
target for a search hit. Tabs are built from `SettingsSection` + `SettingRow`; one-control
settings save on change, multi-field forms (global prose, resource budget, a recognizer) have an
explicit save, and both report through `SaveIndicator` ("saving…", a brief "saved ✓", or the
error). Every tab opened since the modal opened stays mounted (hidden when not shown), so a
search or a tab switch never discards an unsaved draft. A hidden tab must stop anything live:
`components/settings/section-shown.ts` tells a tab whether it is on screen, and a hidden Voice tab
closes its test panels, which cancels a test take. The Voice tab refetches its listing on
`voicePresets.revision` (a live event, a reconnect, or recovery after a failed load), retries its
own failed listing with backoff, and retries at once when shown again. A tab that grows — Computers, when screen pairing lands — replaces only its own
component in `components/settings/sections/`. Settings shows only settings that exist and do
something on this server.
