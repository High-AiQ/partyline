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
    uv run python -m scripts.cockpit plan LINE --debrief "what to continue"
    uv run python -m scripts.cockpit plan LINE --manual-offer --debrief "what to continue"

Neither command restarts anything. Stopping the server drops every participant,
including whoever runs it, so it stays a deliberate act by an initiator who has
announced it — human input is not required; see AGENTS.md.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from http.client import HTTPResponse
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from pydantic import TypeAdapter

from partyline.contracts import (
    ConversationResponse,
    RestartPlanMode,
    RestartPlanRequest,
    RestartPlanResponse,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COCKPIT = Path(os.environ.get("PARTYLINE_COCKPIT", Path.home() / "partyline-cockpit"))

# A change anywhere but here needs a restart to take effect. Adapter packages
# are re-executed in place by POST /api/adapters/reload.
RELOADABLE = ("partyline/adapters/",)


class ResponseOpener(Protocol):
    def __call__(self, request: Request) -> HTTPResponse: ...


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


def check_tree_clean(repo: Path, label: str, *, untracked: bool) -> list[Finding]:
    """Is this checkout in a state we can reason about?

    `untracked` differs by role, and the difference is the point. In the
    workbench an untracked file is usually a new source file nobody has
    committed — work that cannot reach the cockpit, which is exactly what this
    script exists to catch. The cockpit is a deployment target: it accumulates
    logs and databases that are none of our business, and refusing to deploy
    over a stray `cockpit.log` would be the kind of false alarm that teaches
    people to skip the preflight.
    """
    flags = ["--porcelain"] + ([] if untracked else ["--untracked-files=no"])
    if git("status", *flags, cwd=repo):
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


def resolve_line(
    conversations: list[ConversationResponse], selector: str
) -> ConversationResponse:
    """Resolve an exact id or unique case-insensitive name without guessing."""
    if found := next((line for line in conversations if line.id == selector), None):
        return found
    matches = [line for line in conversations if line.name.casefold() == selector.casefold()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValueError(f"line name {selector!r} is ambiguous; use its id")
    raise ValueError(f"no live line matches {selector!r}")


def schedule_restart_plan(
    selector: str,
    debrief: str,
    base_url: str,
    open_url: ResponseOpener = urlopen,
    *,
    mode: RestartPlanMode = "automatic",
) -> RestartPlanResponse:
    """Persist a same-line plan in the running cockpit, without restarting it."""
    conversations_request = Request(urljoin(base_url, "/api/conversations"))
    with open_url(conversations_request) as response:
        conversations = TypeAdapter(list[ConversationResponse]).validate_json(response.read())
    conversation = resolve_line(conversations, selector)
    body = RestartPlanRequest(
        conversation_id=conversation.id,
        debrief=debrief,
        mode=mode,
    )
    request = Request(
        urljoin(base_url, "/api/restart-plan"),
        data=body.model_dump_json().encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with open_url(request) as response:
        return RestartPlanResponse.model_validate_json(response.read())


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
        *check_tree_clean(repo, "workbench", untracked=True),
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
    if dirty := check_tree_clean(cockpit, "cockpit", untracked=False):
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


def plan(
    selector: str,
    debrief: str,
    base_url: str,
    *,
    mode: RestartPlanMode = "automatic",
) -> int:
    try:
        scheduled = schedule_restart_plan(selector, debrief, base_url, mode=mode)
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        print(f"could not schedule reattachment: HTTP {exc.code} {detail}")
        return 1
    except (URLError, ValueError) as exc:
        print(f"could not schedule reattachment: {exc}")
        return 1
    names = ", ".join(candidate.name for candidate in scheduled.attachments)
    print(f"  ✓ {scheduled.conversation_id}: {names}")
    if mode == "automatic":
        print("After restart, that line's plan will be consumed automatically; no browser is required.")
    else:
        print("After restart, only that line will receive the accept/cancel offer.")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "check"
    if command == "check":
        return check()
    if command == "deploy":
        return deploy(Path(argv[1]).expanduser() if len(argv) > 1 else DEFAULT_COCKPIT)
    if command == "plan":
        parser = ArgumentParser(prog="python -m scripts.cockpit plan")
        parser.add_argument("line", help="exact line id or unique name")
        parser.add_argument("--debrief", required=True, help="continuation instructions")
        parser.add_argument(
            "--manual-offer",
            action="store_true",
            help="show the human accept/cancel offer instead of auto-accepting after restart",
        )
        parser.add_argument(
            "--url",
            default=f"http://127.0.0.1:{os.environ.get('PARTYLINE_PORT', '8642')}",
            help="running cockpit base URL",
        )
        args = parser.parse_args(argv[1:])
        mode: RestartPlanMode = "offer" if args.manual_offer else "automatic"
        return plan(args.line, args.debrief, args.url, mode=mode)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
