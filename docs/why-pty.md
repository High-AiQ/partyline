# Why a real terminal?

Because the interactive app is the real thing. Headless and one-shot modes are a different
program with different behaviour, different context discovery, and different auth. partyline
spawns the **actual interactive executable in a pty** — same startup, same project files, same
per-project config and trust settings as running it yourself. It inherits partyline's own
environment and the working directory you choose, not a fresh login shell, so credentials reach
it the way they reach the server (see [Credentials](credentials.md)). The
trick that keeps it clean: **the screen is never scraped.**

| direction | mechanism |
|---|---|
| chat → process | keystrokes written to the pty — the app sees a typed message. Transcript adapters use bracketed paste; `raw` sends line input |
| process → chat | tail the app's own structured transcript; its replies become chat messages |

For a process with no transcript of its own, the `raw` adapter falls back to the ANSI-stripped
pty stream, flushed on quiescence. Every adapter prefers a transcript when one exists, because
that is what keeps replies free of spinners, redraws and box-drawing characters.
