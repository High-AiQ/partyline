# Storage

Settings → **Storage** shows what Partyline keeps on disk and clears what it can recreate.
People only: processes get 403 on both routes. Sizes are measured when the section opens or
is refreshed, in a thread, under a 10 s budget; a category that ran out of time shows `≈`
(`approximate: true`). Nothing scans in the background.

| Category | Clearable when |
| --- | --- |
| CLI session homes (`~/.partyline/sessions/{codex,pi}/<id>`) | the attachment is not running, not in the saved restart plan, and has no session to resume (or its line is archived). `fence/` is never touched |
| Temporary files (`/var/tmp/partyline/<instance>/<id>`) | the attachment is not starting/running and not in the restart plan |
| Review checkouts (`<repo>/.review/*`) | no `in_review` task uses it, no running process works in it, no retired line preserved it. Removed with `git worktree remove --force` and `prune` |
| Scratch worktrees (`<repo>/.scratch/*`) | HEAD is merged into the repo's main branch, `git status` is clean, and no running process works inside |
| Media, database | never; shown only |

`GET /api/storage` lists categories; `POST /api/storage/<key>/clear` re-checks every candidate
at that moment (the listing is not trusted), returns `{removed, freed_bytes, skipped}` with a
reason per kept path, and posts one system notice on the root line naming the person.
The UI asks for confirmation, listing the count, size and first paths, before it calls clear.

## The database file

The server opens its SQLite database in write-ahead mode with `synchronous=NORMAL`
(`partyline/db_wal.py`). A commit appends to `<db>-wal` and does not sync; a worker thread
checkpoints the log into the main file after every few hundred writes, so no sync runs on the
event loop. A process crash loses nothing. A power loss leaves the database consistent but can
drop the last few commits. `<db>-wal` and `<db>-shm` belong to the database: copy all three while
the server runs. An orderly stop folds the log into the main file, which is then complete alone. The mode is recorded in the file, so an older build
opens it unchanged.

