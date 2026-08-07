"""Tag a version-changing main commit after its required checks pass."""

from __future__ import annotations

import argparse
import subprocess

from scripts.version_policy import revision_version


BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], check=check, capture_output=True, text=True
    )


def existing_target(tag: str) -> str | None:
    result = git("rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}", check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="previous main revision")
    parser.add_argument("--head", default="HEAD", help="green main revision")
    parser.add_argument("--remote", default="origin", help="tag destination")
    args = parser.parse_args(argv)

    before = revision_version(args.base)
    after = revision_version(args.head)
    if before == after:
        print(f"version unchanged at {after}; no tag needed")
        return 0

    tag = f"v{after}"
    head = git("rev-parse", f"{args.head}^{{commit}}").stdout.strip()
    target = existing_target(tag)
    if target is not None:
        if target == head:
            print(f"{tag} already points to {head}; nothing to do")
            return 0
        print(f"FAIL: {tag} already points to {target}, not {head}")
        return 1

    git(
        "-c",
        f"user.name={BOT_NAME}",
        "-c",
        f"user.email={BOT_EMAIL}",
        "tag",
        "-a",
        tag,
        head,
        "-m",
        f"partyline {after}",
    )
    git("push", args.remote, f"refs/tags/{tag}")
    print(f"created {tag} at {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
