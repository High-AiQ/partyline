---
name: verify-visual-change
description: See a partyline UI change with real screenshots, or prove a change is visually invisible. Use before claiming any frontend change is verified, when a refactor or formatter run must not move pixels, or when writing or debugging a browser test under tests/ui/.
---

# Verify a visual change

A UI change is not verified until it has been *looked at*. Static reading has repeatedly
missed what a screenshot caught immediately — icon glyphs rendering as tofu, a menu clipped
by its scroll container.

## Look at what you changed

```bash
uv run --locked playwright install chromium                        # once per machine
uv run --locked python -m scripts.uishot --out /tmp/partyline-ui   # the standard state set
```

`scripts/uishot.py` starts a throwaway server and drives the real page in headless Chromium.

| DO | DO NOT |
| --- | --- |
| Capture the state you changed and open the image with whatever image-viewing capability your harness has | Describe a visual change as verified when you have only checked that it parses |

## Prove an invisible change is invisible

Bracket any change claiming not to touch the UI — a refactor, a conversion, a formatter run.
The tooling renders the 17-state standard set (rail, menus, dialogs, populated feed in both
message modes, board, mention popover, narrow layouts) and compares PNG bytes.

```bash
uv run --locked python -m scripts.uidiff baseline   # before the change
uv run --locked python -m scripts.uidiff check      # after; non-zero if anything moved
```

Three details of the capture tooling are load-bearing, each established by measurement after
the obvious assumption turned out to be wrong. Preserve them when touching `scripts/uishot.py`
or `scripts/uidiff.py`.

| DO | DO NOT |
| --- | --- |
| Capture every state twice and compare only when consecutive captures agree — that separates a timing flake from a regression | Add a fuzz threshold that would hide small changes worth catching |
| Run finite animations and transitions to their end state; pause only infinite ones (the LED pulse, a ringing jack) at a fixed frame | Suppress animations with `animation-duration: 0s` — `fill-mode: both` pins a zero-duration animation to its *opening* frame and the whole feed captures faded |
| Give fixtures a fixed timestamp — messages render `HH:MM` | — |
| Wait for the *response* when a state loads async — a race wobbles instead of failing loudly | Wait on a rendered proxy (the empty feed looks identical before and after a line loads) |
| Look at every reported difference, then accept intended ones by re-running `baseline` | Treat a reported difference as automatically a bug |

## Browser tests

```bash
uv run --locked python -m unittest tests/ui/test_line_menu.py -v
```

Browser tests live in `tests/ui/`, are excluded from `unittest discover` on purpose (a
missing browser must never break the ordinary suite), and are not counted toward the
coverage floor.

| DO | DO NOT |
| --- | --- |
| Reach for a plain unit test first | Write a browser test except for layout, hit-testing, or a two-sided client/server protocol |
| Write the control that should fail and confirm it does when a test protects something subtle | Trust a passing browser test blindly — reloads close WebSockets cleanly, timers fire on their own, and elements are often visible for unrelated reasons |
