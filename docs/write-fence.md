# The write fence

Every attached process runs inside a platform kernel sandbox where only
its line's declared write set is writable. The fence is the enforcement
below the text brief: whatever a line's worker is told, the kernel decides
where writes land.

| DO | DO NOT |
| --- | --- |
| Wrap at the one spawn point (`adapters.base.Adapter.start`) so no adapter can forget it | Wrap per adapter, or leave one spawn path unwrapped |
| Fail closed: backend missing or unable to run, no process — a 409 naming the reason, the platform, and the switch | Fall back to an unconfined launch, ever |
| Ship a backend for every platform partyline runs on | Fail closed on a platform with no backend without naming the switch |
| Push over HTTPS with gh credentials or `ssh -F /dev/null` from a fenced process | Expect the system ssh config to be readable inside the fence |
| Treat the fence as the line's real sandbox | Assume the CLI's own sandbox also applies under the fence |
| Grant extra scope explicitly, from a person or a captain above, recorded on the line | Let a line widen its own write set, or grant by implication |
| Keep the wrap to filesystem writes: mounts on Linux, a profile on Darwin, nothing else added | Unshare the network, pid namespace, or environment — this is a filesystem fence, not a jail |
| Bind or allow a path only if it exists | Bind or allow a path that does not exist "so it will work later" |

## Platforms

`fence.launch_argv` picks the backend by `sys.platform` and refuses to
spawn when the chosen one cannot run (`fence.backend_available()` returns
a human-readable reason; the 409 from attach and resume carries it with
the platform and `PARTYLINE_FEATURE_WRITE_FENCE=0`).

- **Linux — bubblewrap.** A mount namespace: `/` bound read-only, fresh
  `/dev` and `/proc`, a private tmpfs over `/tmp`, each write-set path
  bound writable at its real path, `--die-with-parent`. The strongest
  guarantee: sibling data is physically read-only, and `/tmp` is private.
- **Darwin — `/usr/bin/sandbox-exec`.** macOS has no bubblewrap and no
  mount namespace a process may create, so the fence generates an SBPL
  profile (Apple's documented sandbox profile language) and passes it
  with `-p`: `(allow default)`, `(deny file-write*)`, then
  `(allow file-write* (subpath …))` for every write-set path, plus
  `/private/tmp` and the process `TMPDIR` in both spellings, and the
  devices a CLI needs to write — `/dev/null`, `/dev/tty`, `/dev/console`,
  and the `/dev/ttysNNN` pty slaves. Availability is checked the same
  way as bubblewrap's: no `sandbox-exec`, no process.

Known limits of the Darwin backend, documented rather than hidden: the
profile is visible in `ps` (so is the bubblewrap argv — this is a fence
against accidents, not a jail against malice); `/tmp` stays shared with
the host (no tmpfs exists there); and `sandbox-exec` is formally
deprecated by Apple while remaining the documented interface available
on every macOS this code runs on.

## The wrap

`partyline/fence.py` builds the plan. On Linux:

```
bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp
      --bind <write-set path> <same path> ... --die-with-parent -- <command>
```

On Darwin:

```
sandbox-exec -p <generated profile> <command>
```

The environment, working directory, process group, and network are kept.
Reads are not fenced: a process can still read the host. The fence bounds
**writes**, and it is not a security boundary against a hostile binary —
it is a fence against accidents, not a jail against malice. See
`docs/security.md` for the trust model.

## The write set

| path | writable | why |
| --- | --- | --- |
| the line's cwd tree | yes | the tree the line works in; a directly attached line keeps its cwd writable because the person put it there |
| the repository's `.review/` directory | yes | disposable review checkouts may be created after spawn; only the line's recorded review checkouts get writable Git metadata |
| git shared state (child lines) | partially | see the mirror below |
| adapter home paths from the manifest `write_paths` | yes | sessions, transcripts, auth state each CLI writes (`~/.claude`, `~/.cursor`, `~/.grok`, …) |
| an adapter's computed paths | yes | a per-attachment vendor home the manifest cannot name (codex's `CODEX_HOME`) |
| granted paths (`conversation_write_grants`) | yes | requested, granted, recorded |
| `~/.cache`, `~/.config` | yes | the two home directories CLIs routinely update |
| everything else | no | read-only via the `/` bind, including the host's other checkouts and `/` itself |

For any line working in a repository, the whole canonical `<repo>/.review/`
directory is writable, including review checkout directories created after
the process starts. These checkouts are disposable: Partyline creates and
prunes them, and acceptance verifies the SHA object rather than the checkout.
This means sibling lines can write files in each other's review checkouts;
nothing under `.review/` is a source of truth.

Git metadata is narrower. At spawn and resume, Partyline loads review rows
for the owning conversation only. The fence checks each row's owner, full
SHA, canonical `<repo>/.review/<sha>` path, and repository identity before
binding that checkout's own Git metadata writable through `git_fence`.
The shared `.git/worktrees/` directory stays read-only. A checkout created
after spawn has no writable metadata bind, so a Git index refresh fails
softly; read-only commands such as `diff`, `log`, and `show` still work.

Note on the private `/tmp`: bubblewrap recreates the directory chain of
each bind destination inside the tmpfs, so paths under `/tmp` that are
not bind destinations resolve to empty ghost directories, not to host
files. Keep real work out of `/tmp`.

## Git for a child line

A worktree's Git metadata lives in the parent repository's shared `.git`.
Binding it writable would let a line rewrite a sibling's branch, the repo
config, or its hooks. `partyline/git_fence.py` shares only what commits
need:

- `objects/` is shared and writable — content-addressed and immutable
  once written, and the commit a line hands its captain must exist in the
  real object store or the accept fast-forward cannot find it.
- `refs/`, `logs/`, and `packed-refs` are a **copy-on-write mirror** under
  `~/.partyline/sessions/fence/<line>/`, mounted over the real paths. The
  line reads fresh sibling refs and commits to its own branch freely;
  every write lands in the mirror and the real repository is never bound
  writable. The mirror refreshes on each launch — real refs copied in,
  the line's own branch (and any branch it created) kept.
- `worktrees/` is read-only except the line's own metadata directory.

On Darwin there are no mounts, so the mirror cannot exist and the
guarantee is weaker by construction (`git_fence.darwin_write_paths`):
the profile allows file-write on the worktree, the line's own
`.git/worktrees/<name>` directory, and the repository's `objects/`,
`refs/`, `logs/`, and `packed-refs`. **Sibling refs are writable there.**
`config`, `hooks`, and `description` are never named, so they stay
read-only under the default deny. A sibling can clobber this line's
branch view (and vice versa); the acceptance flow — hand a SHA, let the
captain fast-forward — is what keeps work trustworthy, not the
filesystem.

Consequences worth knowing (these describe the Linux mirror; on Darwin
the real refs really do move):

- The line's branch advances **in the mirror**. `git log` inside the line
  is correct; the real branch moves only when the captain accepts the
  handed-off SHA (which works, because the commit object is shared).
- Deleting a ref that lives only in `packed-refs` fails with a warning;
  the line's own branch is always loose in the mirror, so its own branch
  operations are unaffected.
- Branch views are launch-time fresh; a long-lived process does not see
  sibling merges that happen mid-turn.

## Nested sandboxes

Some CLIs bring their own filesystem sandbox. Codex's is bubblewrap on
Linux, and bubblewrap cannot nest under the fence (verified 2026-09-22:
the inner namespace creation is refused); on Darwin its sandbox-exec
profile cannot nest under ours either. When a process is fenced, an
adapter's declared `fence_args` are appended to its command — codex
declares `--dangerously-bypass-approvals-and-sandbox`, so the fence is
the only sandbox, as it already is for every other adapter. `fence_args`
apply only while the process is actually fenced; with the feature off,
the CLI's own sandbox stays.

## Scope expansion

```
POST /api/conversations/<id>/write-set   {"path": "/abs/normalized/path"}
GET  /api/conversations/<id>/write-set
```

A person, or the captain of an ancestor line, may grant. A line may ask,
never grant its own. Grants are rows in `conversation_write_grants` with
the grantor recorded, and a system notice announces them on the line.
Paths must be absolute and normalized; a path that does not exist at
spawn time binds nothing.

## Feature flag

`write_fence` (default **on**, stable). `PARTYLINE_FEATURE_WRITE_FENCE=0`
or `[features] write_fence = false` turns it off for one emergency
restart cycle. It is not a permanent configuration: an unfenced launch
is what the 409 path exists to avoid.

## Adapter notes

| adapter | manifest additions | first attach |
| --- | --- | --- |
| codex | `fence_args` (sandbox replaced by the fence) | none: repo-root trust covers worktrees |
| claude | `write_paths` | a folder-trust dialog per new worktree path, answered once in the pty |
| cursor | `write_paths` | none: the bundled command ships `--trust` |
| opencode | `write_paths` | none |
| antigravity | `write_paths` | a trust dialog per new worktree path; the pinned log root is part of the write set |
| grok | `write_paths` | none with `--permission-mode bypassPermissions` |

Probe evidence (2026-09-22/23, real CLIs under the fence): codex, claude,
cursor, opencode, and grok completed real turns and wrote only inside the
fence; antigravity validated startup, auth, transcript writes, and paste
ingestion (its model turn was quota-blocked, which is external to the
fence). Logs: the write-fence line's hand-off.
