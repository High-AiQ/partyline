"""Create, list, or prune a line's managed review worktrees without the API.

The server-side facility (``POST /api/conversations/<id>/review-worktrees``)
is the normal door; this CLI is the form for a reviewer with shell access but
no credential for that line. It operates on the instance database directly,
like ``python -m scripts.line_management``:

    uv run --locked python -m scripts.review_worktree \
        --database /absolute/path/instance.db create \
        --conversation <line-id> --sha <full-or-short-sha>

    ... list   --conversation <line-id>
    ... prune  --conversation <line-id>

Create checks the exact SHA out at ``<repo>/.review/<sha>`` (detached) and
records it on the line, so accept, retire, purge, and the startup sweep prune
it. Prune drops every review worktree of the line; the SHAs stay in the repo.
"""

from __future__ import annotations

import argparse

from partyline.db import Db
from partyline.review_worktrees import (
    create_review_worktree,
    list_review_worktrees,
    prune_review_worktrees,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", required=True, help="path to the instance database")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "list", "prune"):
        command = sub.add_parser(name)
        command.add_argument("--conversation", required=True, help="the line's id")
        if name == "create":
            command.add_argument("--sha", required=True, help="the commit to review")
    args = parser.parse_args(argv)

    db = Db(args.database)
    try:
        if args.command == "create":
            done = create_review_worktree(db, args.conversation, args.sha)
            print(f"{done['path']} detached at {done['sha']}")
        elif args.command == "list":
            rows = list_review_worktrees(db, args.conversation)
            for row in rows:
                print(f"{row['sha']} {row['path']}")
            if not rows:
                print("no review worktrees recorded for this line")
        else:
            done = prune_review_worktrees(db, args.conversation)
            print(f"removed {done['removed']} review worktrees, kept {done['kept']}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
