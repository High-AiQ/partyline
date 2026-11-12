# Automatic storage cleanup

Startup and lifecycle cleanup preserve readable tracked and untracked changes in
`refs/partyline/discarded/storage-*` in the owning repository before deleting a
retired or orphaned checkout. A dangling linked checkout whose registration was
pruned compares content hashes against objects reachable from surviving owner
refs, even under another filename. Reachability is enumerated once per owner per
sweep. Present but unreachable blobs (such as staged-only files or detached
commits) are anchored in a recovery tree without copying their bytes. Missing
content is saved raw in that owner, never in the outer repo. Normalized hashes
also recognize committed CRLF and LFS-style checkouts; unique bytes still get
raw, unfiltered recovery.
Independent repositories and checkouts without a surviving owner stay kept.

Ignored files outside known caches keep the worktree for a person's decision.
Settings → Storage → Clean up now lists the reason, a few ignored paths and their
individual and combined readable sizes. Each such worktree offers **Remove
anyway**, explicitly allowing its ignored files to be deleted. The override
accepts only an exact path previously offered as a kept entry with that action;
it covers that entry and its own nested worktrees, never an arbitrary ancestor. This waives only the ignored-file guard;
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
mtimes, Git HEAD/index metadata and the tree's own branch value before any Git
inspection or size walk. Loose and packed refs are compared by value: unrelated
merges, fetches and ref packing do not invalidate kept trees. Changes to the
tree's own inputs invalidate a decision; Clean up now always
retries. An edit to an existing file without directory or Git metadata changes
requires that manual retry. Partial deletion failures wait for a manual retry
even if the tree changes, so deletions from the previous cleanup cannot create
another snapshot on every start. On-demand storage listings may measure sizes.

Retirement previews do not delete files. For an empty orphan whose surviving
assigned branch is merged, retirement itself removes the empty directories and
stale Git link on the server, outside the CLI's write fence. Nonempty or unmerged
orphans are refused without directing a fenced captain to run `rm`.
