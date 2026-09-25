# The write fence

Every attached process runs inside a platform kernel sandbox. All
repositories known to Partyline and Partyline's database are protected
from writes by default. A line's own worktree and git needs are reopened
on top; paths outside the protected set are writable. The fence is the
enforcement below the text brief: the kernel decides where writes land.

| DO | DO NOT |
| --- | --- |
| Wrap at the one spawn point (`adapters.base.Adapter.start`) so no adapter can forget it | Wrap per adapter, or leave one spawn path unwrapped |
| Fail closed: backend missing or unable to run, no process — a 409 naming the reason and person-side install remedy | Fall back to an unconfined launch, ever |
| Ship a backend for every supported platform | Fail closed without naming the install remedy |
| Push over HTTPS with gh credentials or `ssh -F /dev/null` from a fenced process | Expect the system ssh config to be readable inside the fence |
| Treat the fence as the line's real sandbox | Assume the CLI's own sandbox also applies under the fence |
| Protect every active managed repository and the Partyline database by default | Assume an unknown repository is protected before Partyline has recorded a line there |
| Grant extra write scope only by person or captain-above decision, recorded on the line | Let a line widen its own write scope, or widen it because a brief asked nicely |
| Keep the wrap to filesystem writes: mounts on Linux, a profile on Darwin, nothing else added | Unshare the network, pid namespace, or environment — this is a filesystem fence, not a jail |
| Bind or allow a path only if it exists | Bind or allow a path that does not exist "so it will work later" |

## Platforms

`fence.launch_argv` picks the backend by `sys.platform` and refuses to
spawn when the chosen one cannot run (`fence.backend_available()` returns
a human-readable reason; startup preflight and the attach 409 include the
same platform-specific person-side install remedy).

- **Linux — bubblewrap.** A mount namespace starts with `/` bound
  writable, `/dev` passed through with `--dev-bind`, and `/proc` mounted.
  The host's `/tmp` remains writable. Partyline then binds protected repository
  roots read-only, reopens this line's worktree and required Git paths
  writable, binds the database and its sidecars read-only, and applies
  recorded grants last. Bind order matters: the last mount at a path wins.
- **Darwin — `/usr/bin/sandbox-exec`.** macOS has no bubblewrap and no
  mount namespace a process may create, so the fence generates an SBPL
  profile (Apple's documented sandbox profile language) and passes it
  with `-p`: `(allow default)`, scoped denies under protected roots and
  the database, then allows this line's own worktree, Git paths, and
  grants back in. A child worktree also allows writes under the common
  `.git` root so Git's transient root files work; later, more-specific
  denies keep `config`, `hooks`, `description`, `HEAD`, `info`, `branches`,
  and sibling worktree metadata protected, with only this line's metadata
  reopened. It also allows `/private/tmp`
  and the process `TMPDIR` in both spellings, and the
  devices a CLI needs to write — `/dev/null`, `/dev/tty`, `/dev/console`,
  and the `/dev/ttysNNN` pty slaves. Availability is checked the same
  way as bubblewrap's: no `sandbox-exec`, no process.

Known limits of the Darwin backend, documented rather than hidden: the
profile is visible in `ps` (so is the bubblewrap argv — this is a fence
against accidents, not a jail against malice); `/tmp` remains shared with
the host and writable; and `sandbox-exec` is formally
deprecated by Apple while remaining the documented interface available
on every macOS this code runs on.

## The wrap

`partyline/fence.py` builds the plan and explicitly creates the user namespace. On Linux:

```
bwrap --bind / / --dev-bind /dev /dev --proc /proc --unshare-user
      --ro-bind <protected repository> <same path> ...
      --bind <line worktree> <same path> ...
      --ro-bind <database or sidecar> <same path> ...
      --bind <granted path> <same path> ... --die-with-parent -- <command>
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

## The protected set and carve-outs

At spawn and resume, Partyline reads every non-archived conversation and
the cwd of each attachment on those lines. Each cwd inside a Git
repository contributes its canonical repository root to the protected
set; duplicate roots collapse. The database, runtime lock, and SQLite
sidecar paths are protected separately. A root captain whose cwd is the
repository root is exempt from that root's deny and keeps the person's
checkout writable. A child line's cwd is a worktree below the root, so
only that worktree is reopened. A repository that Partyline has not yet
recorded in an active line is writable until it is known to Partyline.
This follows from deriving the protected set from the database.

| path | writable | why |
| --- | --- | --- |
| a managed repository root | no | all active lines' Git roots are protected, except a root captain's own checkout |
| this line's cwd tree | yes | the line's own worktree is reopened above its protected repository root |
| the repository's `.review/` directory | yes | disposable review checkouts may be created after spawn; only the line's recorded review checkouts get writable Git metadata |
| git shared state (child lines) | partially | see the mirror below |
| Partyline's database, lock, and sidecars | no | attachment processes cannot alter Partyline state directly |
| granted paths (`conversation_write_grants`) | yes | requested, granted, recorded, and bound last |
| paths outside the protected set | yes | the protect list is intentionally derived from active Partyline lines |

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

The host's `/tmp` remains writable inside the Linux mount namespace.
Temporary files created there use the host directory and are visible to
the host; use a repository worktree for files that need repository
protection.

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

The whole common `.git` root is also covered by a per-line private overlay.
It is seeded and refreshed from root-level files while leaving `config`,
`hooks`, and the separately managed `objects/`, `worktrees/`, `refs/`,
`logs/`, and `packed-refs` out. The real objects, config, hooks, and
worktrees are then mounted with their required scopes, and this line's
metadata plus the refs mirror are mounted after them. Git can therefore
create root-level transient files such as `ORIG_HEAD`, `FETCH_HEAD`, and
`packed-refs.lock` without writing into the repository's real `.git` root.

On Darwin there are no mounts, so the private overlays cannot exist and
the guarantee is weaker by construction (`git_fence.darwin_write_paths`):
the profile allows file-write under the common `.git` root for transient
root files and shared `objects/`, `refs/`, `logs/`, and `packed-refs`.
More-specific denies keep `config`, `hooks`, `description`, `HEAD`, `info`,
`branches`, and sibling `.git/worktrees/` metadata protected; this line's
own metadata is allowed back. **Sibling refs and common transient Git
files are writable there.**
A sibling can clobber this line's branch view (and vice versa); the
acceptance flow — hand a SHA, let the captain fast-forward — is what keeps
work trustworthy, not the filesystem.

Consequences worth knowing (these describe the Linux mirror; on Darwin
the real refs really do move):

- The line's branch advances **in the mirror**. `git log` inside the line
  is correct; the real branch moves only when the captain accepts the
  handed-off SHA (which works, because the commit object is shared):
  accept reads the mirror ref (`git_fence.mirror_branch_ref`) to tell the
  line's own work from a stray, then fast-forwards the real ref.
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
GET  /api/conversations/<id>/write-set/request
POST /api/conversations/<id>/write-set/request/<id>/approve   (person only)
DELETE /api/conversations/<id>/write-set/request/<id>         (person only)
```

A **person** POST grants directly and the grant is recorded immediately. A
**machine** on the line, or the captain of an ancestor line, POST files a
pending request instead — at most one per line; a second filing is **409**.
Every open tab on that line shows the banner; a person approves or declines.
Approval inserts the grant row, posts a system notice, privately rings the
requester on its home line (by attachment id, never by name), and detaches
and resumes every live process on the line so the widened bind applies.
Decline clears the request and rings the requester the same way. Grants are
rows in `conversation_write_grants` with the grantor recorded. Paths must be
absolute and normalized; a path that does not exist at spawn time binds nothing.

## Feature flag

`write_fence` (default **on**, stable). At boot, Partyline runs the selected
backend once against a harmless command. A failed check is logged and shown
at `/api/fence/status`; attach and resume remain refused with the same
person-side install remedy. `partyline doctor` runs the probe and checks the
CLI requirements declared by installed adapter manifests. The emergency
`PARTYLINE_FEATURE_WRITE_FENCE=0` switch remains for one restart cycle only.

## Adapter notes

| adapter | manifest additions | first attach |
| --- | --- | --- |
| codex | `fence_args` (sandbox replaced by the fence) | none |
| claude | none | a folder-trust dialog per new worktree path, answered once in the pty |
| cursor | none | none: the bundled command ships `--trust` |
| opencode | none | none |
| antigravity | none | a trust dialog per new worktree path; the pinned log root is writable outside protected repositories |
| grok | none | none with `--permission-mode bypassPermissions` |
| deepseek | none | `~/.dsh` is writable unless it is within a protected repository |
| hermes | none | `~/.hermes` is writable unless it is within a protected repository |
| muse | none | `~/.local/share/muse` is writable unless it is within a protected repository |
| pi | none | `~/.pi` and pinned sessions are writable unless within a protected repository |

Probe evidence (2026-09-22/23, real CLIs under the fence): codex, claude,
cursor, opencode, and grok completed real turns and wrote only inside the
fence; antigravity validated startup, auth, transcript writes, and paste
ingestion (its model turn was quota-blocked, which is external to the
fence). Logs: the write-fence line's hand-off. deepseek, hermes, muse, and
pi never got that probe — which is how qwen (deepseek) shipped: it exited 1
at its first write to `~/.dsh` under the old fence (found 2026-09-23).
Those home writes are now writable by default unless they fall under an
active protected repository; a real fenced spawn of those four remains
to be re-probed on a host that can create namespaces.
