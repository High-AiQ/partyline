# Storage

Settings → **Storage** shows what Partyline keeps on disk and clears what it can recreate.
People only: processes get 403 on all storage routes. Sizes are measured when the section opens or
is refreshed, in a thread, under a 10 s budget; a category that ran out of time shows `≈`
(`approximate: true`). Automatic cleanup runs once in the background after startup and on lifecycle events; there is no timer.

| Category | Clearable when |
| --- | --- |
| CLI session homes (`~/.partyline/sessions/{codex,pi}/<id>`) | the attachment is not running, not in the saved restart plan, and has no session to resume (or its line is archived). Resumable, inactive homes keep their sessions but shed `cache/` automatically |
| Temporary files (`/var/tmp/partyline/<instance>/<id>`) | the attachment is not starting/running and not in the restart plan |
| Review checkouts (`<repo>/.review/*`) | no `in_review` task uses it, no running process works in it, no retired line preserved it. Removed with `git worktree remove --force` and `prune` |
| Scratch worktrees (`<repo>/.scratch/*`) | HEAD is merged into the repo's main branch, `git status` is clean, and no running process works inside |
| Media, database | never; shown only |

`GET /api/storage` lists categories; `POST /api/storage/<key>/clear` re-checks every candidate
at that moment (the listing is not trusted), returns `{removed, freed_bytes, skipped}` with a
reason per kept path, and posts one system notice on the root line naming the person.
The UI asks for confirmation, listing the count, size and first paths, before it calls clear.

## Automatic cleanup and Clean up now

Cleanup is on by default. Attachment stops clear recreatable Codex/pi `cache/`
directories and detached connection/MCP configuration files. Unresumable or
archived session homes are removed entirely using the same eligibility rules as
category Clear. Starting/running attachments and every attachment in the saved
restart plan keep their files, including caches and worktrees.

Retirement, purge, and startup housekeeping revisit retired worktrees and orphans
under `.partyline-worktrees`, including registered checkouts and unregistered
folders without a line row. Dirty or unmerged Git changes are saved first in the real repository's
`refs/partyline/discarded/storage-<id>/` refs: `snapshot` contains working files,
`index` the staged state, and `head`, `branch`, and `mirror` preserve available
commit tips. For example, `git show <snapshot-ref>:path/to/file` reads a recovered
file; create a branch at the snapshot ref to restore the checkout. Unregistered
plain folders get a snapshot tree containing their files. Ignored recreatable
files in registered worktrees follow the existing retirement rules and are not
backed up. Conflicts, unsupported files, failed snapshots, or changed evidence
retain the directory with a reason.

Nested linked worktrees are recovered in their surviving owning repositories and
removed through the existing registered-worktree removal path. Independent nested
clones are kept: their unique commits may exist nowhere else. A failure logs and
continues with other candidates. Walks, Git commands, and removal run in threads;
every candidate is rechecked immediately before deletion. Size walks and recovery snapshots run outside the shared runtime ownership lock.
Only each candidate's final recheck and removal take that lock, so other processes
can receive messages and start while the sweep prepares the next candidate.
Only full sweeps serialize with one another. Attachment and line cleanup bypass
that sweep lock, so detach, exit broadcasts and retirement do not wait behind a
startup or manual sweep. Per-candidate ownership checks protect concurrent removal.
Retirement and archive events clean only their own lines; startup housekeeping
runs in the background so serving requests and reattachment can begin immediately.
A resume claims its starting state before publishing connection files and staging
its initial delivery. Clean, merged checkouts need no additional recovery refs.

Fence mirrors are keyed by **line ID** (`sessions/fence/<line>/git-<repository hash>`).
For purged lines and orphans, cleanup inspects all loose and packed refs and anchors
any unpublished tips in recovery refs in the real owning repository before
removing the mirror. Missing owners or failed recovery retain it with a reason.

**Clean up now** invokes the same cleanup in one click (`POST /api/storage/cleanup`),
returns `{removed, freed_bytes, skipped}`, and shows bytes freed plus every kept
path, size and reason. `GET /api/storage/details` lists kept worktrees/orphans and
open lines with no live process and no messages for more than 14 days, including
worktree sizes. Idle lines are only flagged; cleanup never retires them. A purge with attachments
in the saved restart plan is refused until the plan is cleared, so its ownership
records continue protecting their files. Category
Clear remains available separately with its confirmation dialog.

## The database file

The server opens its SQLite database in write-ahead mode with `synchronous=NORMAL`
(`partyline/db_wal.py`). A commit appends to `<db>-wal` and does not sync; a worker thread
checkpoints the log into the main file after every few hundred writes. That leaves one sync on
the event loop per completed checkpoint (SQLite syncs the log's header when the log restarts)
instead of two or three per commit. A process crash loses nothing. A power loss leaves the database consistent but can
drop the last few commits. `<db>-wal` and `<db>-shm` belong to the database: copy all three while
the server runs. An orderly stop folds the log into the main file, which is then complete alone. The mode is recorded in the file, so an older build
opens it unchanged.

