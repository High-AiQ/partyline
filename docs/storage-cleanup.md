# Automatic storage cleanup

Startup and lifecycle cleanup preserve readable tracked and untracked changes in
`refs/partyline/discarded/storage-*` in the owning repository before deleting a
retired or orphaned checkout. A dangling linked checkout whose registration was
pruned uses its surviving owner's object store: raw Git blob hashes recognize
content anywhere in that store, even under another filename. Only missing blobs
are snapshotted there; committed gigabytes are never copied into the outer repo.
Independent repositories and checkouts without a surviving owner stay kept.

Ignored files outside known caches keep the worktree for a person's decision.
Settings → Storage → Clean up now lists the reason, a few ignored paths and their
individual and combined readable sizes. Each such worktree offers **Remove anyway**, explicitly
allowing its ignored files to be deleted. This waives only the ignored-file guard;
open lines, live processes, independent repositories and failed recovery stay
protected. A normal Clean up now retries decisions without granting that waiver.

The single cache list is `IGNORED_CACHE_PATTERNS` in
`partyline/storage_ignored.py`, matched against path components at any depth:
`.venv`, `venv`, `virtualenv`, `env`, `__pycache__`, `node_modules`,
`.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `.hypothesis`, `.tox`, `.nox`,
`.cache`, `.next`, `.nuxt`, `.parcel-cache`, `.turbo`, `.svelte-kit`, `build`,
`dist`, and `*.egg-info`. Only Git-ignored entries matching these patterns are
eligible for cache deletion. A generic `cache/` or a browser profile is not on
this list. Readable files in a plain orphan folder are all recovered, including
ignored files; unreadable subtrees remain in place with a bounded reason.

Kept decisions persist across starts. Automatic cleanup stats recorded directory
mtimes and Git HEAD/index/ref metadata before any Git inspection or size walk.
Directory or Git metadata changes invalidate a decision; Clean up now always
retries. An edit to an existing file without directory or Git metadata changes
requires that manual retry. Partial deletion failures wait for a manual retry
even if the tree changes, so deletions from the previous cleanup cannot create
another snapshot on every start. On-demand storage listings may measure sizes.

Retirement previews do not delete files. For an empty orphan whose surviving
assigned branch is merged, retirement itself removes the empty directories and
stale Git link on the server, outside the CLI's write fence. Nonempty or unmerged
orphans are refused without directing a fenced captain to run `rm`.
