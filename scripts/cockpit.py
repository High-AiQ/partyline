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
    uv run python -m scripts.cockpit arm --pid NNNNN
    uv run python -m scripts.cockpit plan LINE --manual-offer --debrief "what to continue"

The first three commands do not restart anything. ``arm`` is the deliberate,
announced trigger after every participant is clear; human input is not required.
"""

from __future__ import annotations

import os
import re
import shlex
import sqlite3
import subprocess
import sys
import time
from argparse import ArgumentParser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.client import HTTPResponse
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from pydantic import TypeAdapter

from partyline.contracts import (
    ConversationResponse,
    RestartPlanMode,
    RestartPlanRequest,
    RestartPlanResponse,
)
from scripts.restart_server import process_generation

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COCKPIT = Path(os.environ.get("PARTYLINE_COCKPIT", Path.home() / "partyline-cockpit"))

# A change anywhere but here needs a restart to take effect. Adapter packages
# are re-executed in place by POST /api/adapters/reload.
RELOADABLE = ("partyline/adapters/",)

# Where imported adapter repositories are installed. These are *executed* by the
# running server, so they are as load-bearing as anything in this repository —
# and until this check existed, nothing verified them at all.
ADAPTER_STORE = Path(os.environ.get("PARTYLINE_ADAPTERS_DIR", "~/.partyline/adapters")).expanduser()
# Where the *authoritative* checkouts of those adapters live, by convention
# `<root>/<same directory name>`. The installed copy is a deployment artefact;
# this is the thing anyone actually reviews and pushes.
ADAPTER_SOURCE_ROOT = Path(os.environ.get("PARTYLINE_ADAPTER_SOURCES", "~/code")).expanduser()
RESTART_SCRIPT = REPO_ROOT / "scripts" / "restart_server.py"


class ResponseOpener(Protocol):
    def __call__(self, request: Request) -> HTTPResponse: ...


@dataclass(frozen=True)
class Finding:
    """One thing that is wrong, and what to do about it."""

    problem: str
    fix: str


@dataclass(frozen=True)
class PendingPlanInspection:
    plan: Mapping[str, object] | None
    findings: list[Finding]


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


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


def adapter_checkouts(store: Path = ADAPTER_STORE) -> list[Path]:
    """Every imported adapter repository the server would execute."""
    if not store.is_dir():
        return []
    return sorted(path for path in store.iterdir() if (path / ".git").is_dir())


def adapter_source(checkout: Path, root: Path = ADAPTER_SOURCE_ROOT) -> Path | None:
    """The authoritative checkout for an installed adapter, if it is on this box."""
    candidate = root / checkout.name
    return candidate if (candidate / ".git").is_dir() else None


def check_adapter_store(
    store: Path = ADAPTER_STORE, source_root: Path = ADAPTER_SOURCE_ROOT
) -> list[Finding]:
    """The code the server actually runs must exist somewhere reproducible.

    Adapters are imported into a local store and executed as us. Nothing about
    them is covered by this repository's cleanliness, which is how a restart
    once ran an adapter that existed *only* as an uncommitted local edit: the
    behaviour under test was in no repository, no preflight mentioned it, and
    re-importing would have silently reverted the fix.

    This is the same failure as a cockpit sitting three commits behind — the
    code being run was not the code anyone had reasoned about — so it gets the
    same treatment: a dirty or unpushed adapter checkout blocks a restart.
    """
    findings = []
    for checkout in adapter_checkouts(store):
        label = f"adapter repository {checkout.name}"
        findings += check_tree_clean(checkout, label, untracked=True)
        # Ask whether the running commit exists on a remote, not whether this
        # checkout tracks a branch. An installed store is a deployment target:
        # it is legitimately a detached clone pinned to one commit, exactly like
        # the cockpit. Demanding a tracking branch here confuses "reproducible"
        # with "someone's working copy" — the same category error that made an
        # earlier version of this file refuse a perfectly good deployment.
        try:
            remote_refs = git("branch", "-r", "--contains", "HEAD", cwd=checkout)
        except RuntimeError as exc:
            findings.append(Finding(f"{label} cannot be inspected: {exc}",
                                    f"check that {checkout} is a usable git checkout"))
            continue
        if not remote_refs.strip():
            findings.append(Finding(
                f"{label} runs a commit no remote has",
                "push it from its source repository — nobody else can obtain "
                "the code the server is executing"))

        # The two roles have different obligations. The installed copy must be
        # clean and identical; the source must additionally be somewhere a
        # reviewer can reach. Checking only one of them is how a fix lived in
        # the runtime copy alone for hours while every test passed against a
        # source that had never seen it.
        source = adapter_source(checkout, source_root)
        if source is None:
            continue
        findings += check_tree_clean(source, f"{label} source", untracked=True)
        findings += check_adapter_drift(checkout, source)
        findings += check_adapter_tests(source)
    return findings


def check_adapter_drift(installed: Path, source: Path) -> list[Finding]:
    """Is the adapter the server executes the same commit as its source?

    The installed store and the authoritative checkout are two copies of the
    same repository, and nothing keeps them in step. During this incident the
    installed copy carried a fix that the source repository had never seen, so
    the running behaviour was correct, unreviewable, and one re-import away
    from silently reverting.
    """
    try:
        installed_head = git("rev-parse", "HEAD", cwd=installed)
        source_head = git("rev-parse", "HEAD", cwd=source)
    except RuntimeError as exc:
        return [Finding(f"cannot compare {installed.name} with its source: {exc}",
                        f"check that {source} is a git checkout of the same repository")]
    if installed_head != source_head:
        return [Finding(
            f"the installed {installed.name} is at {installed_head[:9]}, "
            f"its source at {source_head[:9]}",
            "re-import the adapter so the server runs the reviewed commit")]
    return []


def check_adapter_tests(source: Path) -> list[Finding]:
    """Run the adapter repository's own enforce-all-packages test command."""
    runner = source / "run_tests.py"
    if not runner.is_file():
        return [Finding(
            f"adapter source {source.name} has no run_tests.py",
            "add a runner that fails when any adapter lacks its own vendor-free tests",
        )]
    done = subprocess.run(
        [sys.executable, str(runner)],
        cwd=source,
        capture_output=True,
        text=True,
    )
    if done.returncode:
        detail = (done.stderr or done.stdout).strip()[-500:]
        return [Finding(
            f"adapter source {source.name} tests fail: {detail}",
            f"run `{runner}` and fix every adapter suite before restarting",
        )]
    return []


# How long a plan may sit unclaimed before it is evidence of a failed trigger
# rather than a restart still in flight. Arming waits 90 seconds; a claim
# follows within moments of the new server starting.
STALE_PLAN_SECONDS = 300.0


def check_pending_plan(now: float, plan: Mapping[str, object] | None) -> list[Finding]:
    """Has a restart been planned and then never happened?

    Two dogfood restarts failed at the trigger — a supervisor reaped before it
    fired, then a systemd unit whose inline quoting broke its own generation
    check. Both left this exact state: a plan persisted, `attempt_count` still
    0, nothing claimed, old server still serving. Both went unnoticed for hours
    because the only symptom was a version badge nobody was looking at, and the
    second one was discovered by a person asking why the number had not moved.

    An armed restart consumes its plan within a couple of minutes. One that has
    not is not waiting; it is not coming.
    """
    if plan is None:
        return []
    if plan.get("attempt_count"):
        return []  # claimed at least once: the trigger fired, whatever followed
    age = now - float(plan.get("created_at") or now)
    if age < STALE_PLAN_SECONDS:
        return []
    return [Finding(
        f"a restart plan has been pending unclaimed for {int(age // 60)} minutes",
        "the trigger never fired — check `journalctl --user -u partyline-restart*` "
        "and re-arm, or clear the plan if it is obsolete")]


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


def inspect_pending_plan(database: Path | None = None) -> PendingPlanInspection:
    """Read the persisted plan without migrating or writing the live database.

    Deliberately not over HTTP: the case this exists to catch is a server that
    never restarted, and asking that server would be asking the wrong process
    about its own replacement.  ``mode=ro`` is load-bearing: constructing
    :class:`partyline.db.Db` would apply migrations and commit from a command
    advertised as a read-only preflight.
    """
    database = database or Path(
        os.environ.get("PARTYLINE_DB", os.path.expanduser("~/.partyline.db"))
    )
    if not database.is_file():
        return PendingPlanInspection(None, [])
    try:
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='restart_plan'"
            ).fetchone()
            if table is None:
                return PendingPlanInspection(None, [])
            row = connection.execute(
                "SELECT conversation_id, token, mode, attempt_count, created_at "
                "FROM restart_plan WHERE singleton=1"
            ).fetchone()
            return PendingPlanInspection(dict(row) if row else None, [])
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return PendingPlanInspection(None, [Finding(
            f"the live restart plan cannot be inspected read-only: {exc}",
            f"inspect {database} with sqlite3 before trusting restart state",
        )])


def run_command(args: list[str]) -> CommandResult:
    done = subprocess.run(args, capture_output=True, text=True)
    return CommandResult(done.returncode, done.stdout, done.stderr)


def failed_restart_units(
    run: Callable[[list[str]], CommandResult] = run_command,
) -> list[Finding]:
    """Keep a failed trigger visible after its timer has disappeared."""
    result = run([
        "systemctl", "--user", "list-units", "--all", "--state=failed",
        "--plain", "--no-legend", "partyline-restart-*.service",
    ])
    if result.returncode:
        return []  # systems without a user manager can still develop Partyline
    units = [line.split()[0] for line in result.stdout.splitlines() if line.strip()]
    return [Finding(
        f"restart unit {unit} failed",
        f"run `journalctl --user -u {unit}` and resolve it before re-arming",
    ) for unit in units]


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
    plan = inspect_pending_plan()
    findings = [
        *check_tree_clean(repo, "workbench", untracked=True),
        *check_bundle_present(repo, "workbench"),
        *check_bundle_current(repo),
        *check_pushed(repo),
        *check_adapter_store(),
        *plan.findings,
        *check_pending_plan(time.time(), plan.plan),
        *failed_restart_units(),
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


def _websocket_url(base_url: str, conversation_id: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, f"/ws/{conversation_id}", "", "", ""))


def parse_systemd_exec_start(value: str) -> list[str] | None:
    """Extract the ordered argv from ``systemctl show -p ExecStart``."""
    marker = "argv[]="
    if marker not in value:
        return None
    encoded = value.partition(marker)[2].partition(" ; ignore_errors=")[0]
    try:
        return shlex.split(encoded)
    except ValueError:
        return None


def arm_restart(
    cockpit: Path,
    pid: int,
    delay_seconds: int,
    base_url: str,
    *,
    unit: str | None = None,
    run: Callable[[list[str]], CommandResult] = run_command,
    inspection: PendingPlanInspection | None = None,
    generation: Callable[[int], str | None] = process_generation,
) -> int:
    """Schedule the reviewed restart executable and read the timer back.

    ``systemd-run`` receives an argv, never shell source.  A successful return
    only proves scheduling, so the timer state, trigger listing, and service
    command are independently read back before this function says "armed".
    """
    inspection = inspection or inspect_pending_plan()
    if inspection.findings:
        return report(inspection.findings)
    plan = inspection.plan
    if plan is None:
        return report([Finding(
            "there is no persisted restart plan",
            "run `scripts.cockpit plan LINE --debrief ...` before arming",
        )])
    if plan.get("mode") != "automatic":
        return report([Finding(
            "the persisted restart plan is a manual offer",
            "replace it with an automatic plan before an unattended restart",
        )])
    expected_start = generation(pid)
    if expected_start is None:
        return report([Finding(
            f"pid {pid} has no readable process generation",
            "resolve the current listener pid again; never guess or reuse an old pid",
        )])
    if delay_seconds < 10:
        return report([Finding(
            f"the requested {delay_seconds}s delay is too short to end the arming turn",
            "use at least 10 seconds, normally 90",
        )])

    script = cockpit / RESTART_SCRIPT.relative_to(REPO_ROOT)
    python = cockpit / ".venv" / "bin" / "python3"
    server = cockpit / ".venv" / "bin" / "partyline"
    logfile = cockpit / "cockpit.log"
    for path, label in ((script, "restart script"), (python, "cockpit Python"), (server, "server")):
        if not path.is_file():
            return report([Finding(f"the deployed {label} is missing at {path}",
                                   "run `scripts.cockpit deploy` again")])

    unit = unit or f"partyline-restart-{pid}-{int(time.time())}"
    failure_ws = _websocket_url(base_url, str(plan["conversation_id"]))
    service_argv = [
        str(python),
        str(script),
        str(pid),
        expected_start,
        str(server),
        str(logfile),
        str(cockpit),
        "--failure-ws",
        failure_ws,
    ]
    command = [
        "systemd-run",
        "--user",
        f"--unit={unit}",
        f"--on-active={delay_seconds}s",
        f"--working-directory={cockpit}",
        "--property=Type=exec",
        "--property=SuccessExitStatus=SIGTERM",
        *service_argv,
    ]
    scheduled = run(command)
    if scheduled.returncode:
        return report([Finding(
            f"systemd refused restart unit {unit}: {scheduled.stderr.strip()}",
            "resolve the user service error; no process was signalled",
        )])

    timer = f"{unit}.timer"
    service = f"{unit}.service"
    timer_state = run([
        "systemctl", "--user", "show", timer,
        "-p", "LoadState", "-p", "ActiveState", "-p", "SubState", "-p", "Triggers",
    ])
    timer_listing = run([
        "systemctl", "--user", "list-timers", timer, "--no-pager", "--no-legend",
    ])
    service_state = run([
        "systemctl", "--user", "show", service, "-p", "ExecStart",
    ])
    timer_ok = (
        timer_state.returncode == 0
        and "LoadState=loaded" in timer_state.stdout
        and "ActiveState=active" in timer_state.stdout
        and "SubState=waiting" in timer_state.stdout
        and f"Triggers={service}" in timer_state.stdout
        and timer_listing.returncode == 0
        and timer in timer_listing.stdout
    )
    command_ok = (
        service_state.returncode == 0
        and parse_systemd_exec_start(service_state.stdout) == service_argv
    )
    if not timer_ok or not command_ok:
        run(["systemctl", "--user", "stop", timer])
        return report([Finding(
            f"restart unit {unit} could not be verified after scheduling",
            "inspect the unit, then re-arm; an unverified timer is not armed",
        )])

    trigger = timer_listing.stdout.strip()
    print(f"  ✓ armed {service}\n  ✓ {trigger}\n  ✓ exact generation {pid}/{expected_start}")
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
    if command == "arm":
        parser = ArgumentParser(prog="python -m scripts.cockpit arm")
        parser.add_argument("--pid", required=True, type=int, help="exact current server pid")
        parser.add_argument("--delay", type=int, default=90, help="seconds before signalling")
        parser.add_argument("--unit", help="stable systemd unit name for tests or diagnosis")
        parser.add_argument(
            "--url",
            default=f"http://127.0.0.1:{os.environ.get('PARTYLINE_PORT', '8642')}",
            help="running cockpit base URL",
        )
        parser.add_argument(
            "--cockpit",
            type=Path,
            default=DEFAULT_COCKPIT,
            help="deployed cockpit checkout",
        )
        args = parser.parse_args(argv[1:])
        if (failed := check()):
            return failed
        expected = git("rev-parse", "HEAD")
        if findings := check_in_sync(args.cockpit, expected):
            return report(findings)
        return arm_restart(
            args.cockpit,
            args.pid,
            args.delay,
            args.url,
            unit=args.unit,
        )
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
