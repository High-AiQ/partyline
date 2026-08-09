---
name: verify-visual-change
description: See a partyline UI change with real screenshots, or prove a change is visually invisible. Use before claiming any frontend change is verified, when a refactor or formatter run must not move pixels, or when writing or debugging a browser test under tests/ui/.
---

# Verify a visual change

A UI change is not verified until it has been *looked at*. Static reading has repeatedly missed
what a screenshot caught immediately — icon glyphs rendering as tofu, a menu clipped by its
scroll container. Do not describe a visual change as verified when you have only checked that it
parses.

## Look at what you changed

```bash
uv run --locked playwright install chromium                        # once per machine
uv run --locked python -m scripts.uishot --out /tmp/partyline-ui   # the standard state set
```

`scripts/uishot.py` starts a throwaway server and drives the real page in headless Chromium.
Capture the state you changed, then open the image with whatever image-viewing capability your
harness has and actually look at it.

## Prove an invisible change is invisible

A refactor, a conversion, a formatter — anything claiming not to touch the UI — should be
bracketed by:

```bash
uv run --locked python -m scripts.uidiff baseline   # before the change
uv run --locked python -m scripts.uidiff check      # after; non-zero if anything moved
```

It renders the standard state set — 17 states covering the rail, the menus, the dialogs, the
populated feed in both message modes, the board, the mention popover, and the narrow layout
including a shortened keyboard-up viewport — and compares PNG bytes.

Three details are load-bearing, each established by measurement after the obvious assumption
turned out to be wrong:

- **Every command captures twice.** Headless Chromium is *nearly* deterministic — about one run
  in three had a single state off by a hair, and not the same state each time. A state is only
  compared if two consecutive captures agree; one that disagrees with itself is named and
  excluded. This separates a timing flake (differs sometimes) from a regression (differs every
  time) without a fuzz threshold that would hide small changes worth catching.
- **Animations are finished before each shot, not suppressed.** Forcing
  `animation-duration: 0s` looks like the obvious freeze and is wrong: `.msg` arrives with
  `fill-mode: both`, so a zero-duration animation pins it to its *opening* frame and the whole
  feed captures faded. Finite animations and transitions are run to their end state; only
  infinite ones (the LED pulse, a ringing jack) are paused at a fixed frame.
- **Fixtures carry a fixed timestamp.** Messages render `HH:MM`, so a baseline recorded at
  09:15 and checked at 09:20 would otherwise differ every time.

A state that races an async load will wobble rather than fail loudly — wait for the *response*,
not for a rendered proxy. The empty feed looks identical before and after a line loads, which is
how a seeding race first showed up as an empty mention popover rather than as an error.

A reported difference is not automatically a bug — an intended visual change shows up here too.
It has to be looked at, then accepted by re-running `baseline`.

## Browser tests

```bash
uv run --locked python -m unittest tests/ui/test_line_menu.py -v
```

Reach for a plain unit test first: browser tests earn their place only when the thing under test
genuinely needs one — layout, hit-testing, a two-sided client/server protocol. They live in
`tests/ui/` and are excluded from `unittest discover` on purpose: a missing browser must never
break the ordinary suite, and they are not counted toward the coverage floor.

**Beware a browser test that passes for the wrong reason.** A page reload closes its WebSocket
cleanly, timers fire on their own, elements are often visible for reasons unrelated to the
change. When a browser test protects something subtle, write the control that should fail and
confirm that it does — a reconnect test here passed until its control proved the reconnect path
was never being reached.
