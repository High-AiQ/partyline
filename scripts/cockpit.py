"""Get the cockpit onto the latest build, and prove it before anyone restarts.

partyline is developed through a running copy of itself. The *workbench* is the
checkout being edited; the *cockpit* is the separate clone hosting the
conversation. A restart is only worth its cost if the cockpit is actually
running the code that was just written — and the failure mode is quiet, because
a cockpit at an old commit starts perfectly happily and serves the old UI.

That is not hypothetical. It is exactly what happened the first time the Svelte
frontend landed: the workbench was three commits ahead, the cockpit was
restarted, and the old 1532-line page came back looking like nothing had
changed.

    uv run python -m scripts.cockpit check     # is the workbench fit to deploy?
    uv run python -m scripts.cockpit deploy    # check, advance the cockpit, verify

Neither command restarts anything. Stopping the server drops every participant,
including whoever runs it, so it stays a deliberate act by a person who has
announced it — see AGENTS.md.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COCKPIT = Path(os.environ.get("PARTYLINE_COCKPIT", Path.home() / "partyline-cockpit"))

# A change anywhere but here needs a restart to take effect. Adapter packages
# are re-executed in place by POST /api/adapters/reload.
RELOADABLE = ("partyline/adapters/",)


@dataclass(frozen=True)
class Finding:
    """One thing that is wrong, and what to do about it."""

    problem: str
    fix: str


def git(*args: str, cwd: Path = REPO_ROOT) -> str:
    """Run git and return its stdout, or raise with git's own complaint."""
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout.strip()


# -- checks ----------------------------------------------------------------
# Each returns a list of Findings and touches nothing. The caller decides what
# a finding means, which is what makes them testable without a repository.


def check_tree_clean(repo: Path, label: str) -> list[Finding]:
    if git("status", "--porcelain", cwd=repo):
        return [Finding(f"the {label} has uncommitted changes",
                        f"commit or stash them in {repo}")]
    return []


def check_pushed(repo: Path) -> list[Finding]:
    """The cockpit pulls from the remote, so unpushed work cannot reach it."""
    head = git("rev-parse", "HEAD", cwd=repo)
    try:
        remote = git("rev-parse", "origin/main", cwd=repo)
    except RuntimeError:
        return [Finding("no origin/main to compare against",
                        "git fetch origin, or push this branch first")]
    if head != remote:
        ahead = git("rev-list", "--count", "origin/main..HEAD", cwd=repo)
        if ahead != "0":
            return [Finding(f"the workbench is {ahead} commit(s) ahead of origin/main",
                            "git push origin main")]
        return [Finding("the workbench is behind origin/main",
                        "git pull --ff-only")]
    return []


def referenced_assets(static_dir: Path) -> list[str]:
    """The asset filenames index.html actually asks the browser to load."""
    index = static_dir / "index.html"
    if not index.is_file():
        return []
    return re.findall(r'/assets/([A-Za-z0-9._-]+)', index.read_text())


def check_bundle_present(repo: Path, label: str) -> list[Finding]:
    """The committed bundle must exist and be self-consistent.

    A missing file here is the difference between a working app and a blank
    page, and nothing else in the stack notices: the server starts, the HTML
    is served, and the browser quietly fails to fetch a script.
    """
    static_dir = repo / "partyline" / "static"
    wanted = referenced_assets(static_dir)
    if not wanted:
        return [Finding(f"the {label} has no built frontend",
                        "run `npm install && npm run build` in frontend/ and commit the result")]
    missing = [name for name in wanted if not (static_dir / "assets" / name).is_file()]
    if missing:
        return [Finding(f"the {label}'s index.html references missing assets: {', '.join(missing)}",
                        "rebuild the frontend and commit partyline/static/ in full")]
    return []


def check_bundle_current(repo: Path) -> list[Finding]:
    """Rebuild and see whether the committed bundle changes.

    This is the check that prose cannot replace. Editing `frontend/src/` and
    forgetting to build leaves the source and the shipped app disagreeing, and
    every symptom of that looks like "my change did not work".

    Skipped where npm is unavailable — a machine without Node can still deploy
    a bundle somebody else built.
    """
    frontend = repo / "frontend"
    if not (frontend / "node_modules").is_dir():
        return []
    done = subprocess.run(["npm", "run", "build", "--silent"], cwd=frontend,
                          capture_output=True, text=True)
    if done.returncode:
        return [Finding("the frontend does not build",
                        f"fix it: {done.stderr.strip()[:300]}")]
    if git("status", "--porcelain", "--", "partyline/static", cwd=repo):
        return [Finding("the committed bundle is stale — rebuilding changed it",
                        "commit partyline/static/ along with the source that changed it")]
    return []


def check_in_sync(cockpit: Path, expected: str) -> list[Finding]:
    at = git("rev-parse", "HEAD", cwd=cockpit)
    if at != expected:
        return [Finding(f"the cockpit is at {at[:9]}, not {expected[:9]}",
                        "run `scripts.cockpit deploy`, or fast-forward it by hand")]
    return []


def restart_needed(repo: Path, old: str, new: str) -> bool:
    """Does going from `old` to `new` require a restart, or just an adapter reload?"""
    if old == new:
        return False
    changed = git("diff", "--name-only", f"{old}..{new}", cwd=repo).splitlines()
    return any(not path.startswith(RELOADABLE) for path in changed)


# -- commands --------------------------------------------------------------


def report(findings: list[Finding]) -> int:
    for finding in findings:
        print(f"  ✗ {finding.problem}\n    → {finding.fix}")
    if findings:
        print(f"\n{len(findings)} thing(s) to fix before restarting.")
        return 1
    print("  ✓ ready")
    return 0


def check(repo: Path = REPO_ROOT) -> int:
    print(f"workbench {repo}")
    findings = [
        *check_tree_clean(repo, "workbench"),
        *check_bundle_present(repo, "workbench"),
        *check_bundle_current(repo),
        *check_pushed(repo),
    ]
    return report(findings)


def deploy(cockpit: Path, repo: Path = REPO_ROOT) -> int:
    if (failed := check(repo)):
        return failed

    if not (cockpit / ".git").is_dir():
        return report([Finding(f"no cockpit clone at {cockpit}",
                               "clone it, or set PARTYLINE_COCKPIT")])

    print(f"\ncockpit {cockpit}")
    if dirty := check_tree_clean(cockpit, "cockpit"):
        return report(dirty)

    before = git("rev-parse", "HEAD", cwd=cockpit)
    git("fetch", "origin", cwd=cockpit)
    git("merge", "--ff-only", "origin/main", cwd=cockpit)
    after = git("rev-parse", "HEAD", cwd=cockpit)

    findings = [*check_in_sync(cockpit, git("rev-parse", "HEAD", cwd=repo)),
                *check_bundle_present(cockpit, "cockpit")]
    if findings:
        return report(findings)

    if before == after:
        print(f"  ✓ already at {after[:9]}; nothing to restart for")
        return 0

    print(f"  ✓ {before[:9]} → {after[:9]}")
    if restart_needed(cockpit, before, after):
        print("\nThis needs a restart to take effect.\n"
              "Announce it, let everyone commit and post status, then restart —\n"
              "and make sure nobody is mid-turn, including you.")
    else:
        print("\nAdapters only: POST /api/adapters/reload is enough, no restart needed.")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "check"
    if command == "check":
        return check()
    if command == "deploy":
        return deploy(Path(argv[1]).expanduser() if len(argv) > 1 else DEFAULT_COCKPIT)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
