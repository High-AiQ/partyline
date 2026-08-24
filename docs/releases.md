# Releases


| DO | DO NOT |
| --- | --- |
| Let CI create tags on push to main — the tag list is the complete release record | Hand-create GitHub Releases, or let release prose drift from the code |
| Own the version transition in exactly one commit whose type matches the change set (feat → minor, fix → patch, breaking → major) | Split a bump across commits, bump in a commit type that does not imply it, or skip the bump a change set implies |

**Tags are the release record. There are no GitHub Releases.**

`scripts/tag_version` runs from CI on every push to `main` and creates an
immutable `vMAJOR.MINOR.PATCH` tag whenever `partyline/__init__.py` changes,
so the tag list is complete by construction — nobody has to remember. The
version itself is enforced separately: `scripts/version_policy` requires the
bump implied by the change set's Conventional Commit subjects, owned by
exactly one commit.

GitHub Releases were kept by hand for a while and lapsed after `v0.34.2`,
while tagging carried on to `v0.42.x`. The result was a repository front page
advertising a "latest release" eight versions behind the code — the only
dishonest thing about the release story, and the reason the Releases were
deleted rather than backfilled.

Nothing was lost by deleting them. Partyline publishes no artifacts: no
wheel, no sdist, no PyPI entry. It installs from source with `uv`, so a
Release carried prose and nothing else, and the prose duplicated a commit
history that CI already constrains to one-line conventional subjects. The
three hand-written bodies are archived below so the judgement in them
survives the page that hosted them.

## When to revisit

Publish Releases again when there is something to attach — a wheel, an
installer, a signed artifact. At that point automate it from the tag rather
than by hand: `gh release create "$TAG" --generate-notes` in the existing
`tag-version` job is about five lines, and automation is what stops the drift
from coming back. Hand-written Releases are a habit that decays; the lapse
above is the evidence.

Do not autogenerate Releases *without* artifacts. Machine-written notes over
one-line conventional subjects would restate the tag list, which is worse
than what was deleted.

## Archive of the hand-written releases

Preserved verbatim from the three GitHub Releases that existed before this
policy. Their tags remain and are still the authoritative pointers.

### v0.34.2 — 2026-08-18

> Grok resume replay fixed at the root: the first transcript replacement after
> a resume is a restore, never a compaction — the watermark ordinal carries
> across it, set by observed lifecycle state (a successful pre-spawn count),
> not assumption. Three controls: empty replacement, partial refill, inverse
> compaction. Includes media variant bytes honesty fix (unknown ≠ 0).

### v0.34.0 — 2026-08-17

> Three-tier media everywhere: every upload derives `{id}_thumb.webp`
> (≤512 q80) and `{id}_slim.webp` (≤1600); originals untouched, never
> upscaled. Grids render thumbs, viewer uses slim, agents get all three URLs
> plus per-variant byte sizes in metadata. Composer drop-zone and clipboard-
> image paste. Docs + briefing tier discipline. Includes v0.32.1 (cockpit venv
> sync + boot probe) and v0.32.2 (grok resume watermark fix).

### v0.32.1 — 2026-08-17

> Cockpit restart safety: sync the cockpit venv on deploy, and refuse
> check/arm unless the cockpit interpreter boots this tree's
> `partyline.server` (identity probe: file under cockpit + version matches
> HEAD).
