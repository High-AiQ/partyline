"""Prove that a refactor did not change what the app looks like.

A conversion — JavaScript to TypeScript, a formatter, a component split — is
supposed to be invisible. "Supposed to be" is the problem: the only honest
check is to render the app before and after and compare the pixels, and doing
that by eye across a dozen states and four parallel workstreams is exactly the
kind of task people quietly stop doing.

    uv run python -m scripts.uidiff baseline   # before: record how it looks now
    uv run python -m scripts.uidiff check      # after: report anything that moved

`check` exits non-zero if any state changed, so it can gate a merge. A reported
difference is not automatically a bug — an intentional visual change shows up
here too — but it does have to be *looked at*, which is the point. Re-run
`baseline` to accept a change deliberately.

The comparison is on the encoded PNG bytes, and **every command captures the
state set twice**. That is not belt and braces; it is the whole design.

Headless Chromium is *nearly* deterministic, not deterministic. Measured here:
two captures of an unchanged build usually match exactly, but roughly one run
in three has a single state off by a hair — and not the same state each time.
A check that reports a phantom change one run in three is a check people learn
to ignore, at which point it hides every real regression too.

The fix is not a fuzz threshold, which would hide the small changes most worth
catching. It is to use the property that actually separates the two cases: a
timing flake differs *sometimes*, a real change differs *every time*. So each
command captures twice and only trusts states where the two agree. A state that
disagrees with itself is reported as unstable and excluded from the comparison
rather than being quietly counted as either same or different.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = REPO_ROOT / ".ui-baseline"
CURRENT_DIRNAME = ".ui-current"
# Which states the baseline run could actually pin down. Without this, a state
# the baseline found unstable would look merely *absent* on the next run, and
# get reported as newly added every time.
STABLE_LIST = "stable-states.txt"


def read_stable_list(baseline_dir: Path) -> set[str] | None:
    path = baseline_dir / STABLE_LIST
    if not path.is_file():
        return None
    return {line for line in path.read_text(encoding="utf-8").split("\n") if line}


class Change(StrEnum):
    """What happened to one captured state between two runs."""

    CHANGED = "changed"
    ADDED = "added"
    REMOVED = "removed"


@dataclass(frozen=True)
class Difference:
    """One state that does not match the baseline."""

    name: str
    change: Change

    def describe(self) -> str:
        return {
            Change.CHANGED: f"{self.name} looks different",
            Change.ADDED: f"{self.name} is new — no baseline to compare against",
            Change.REMOVED: f"{self.name} is gone — the baseline has it, this run does not",
        }[self.change]


# -- comparison ------------------------------------------------------------
# Pure functions over {name: digest} maps, so the interesting logic is testable
# without a browser, a server, or a screenshot.


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digests(directory: Path) -> dict[str, str]:
    """Every PNG in a directory, by name, as a content digest."""
    if not directory.is_dir():
        return {}
    return {path.stem: digest(path.read_bytes()) for path in sorted(directory.glob("*.png"))}


def compare(baseline: dict[str, str], current: dict[str, str]) -> list[Difference]:
    """Everything that differs, in a stable order.

    A state present in only one side is reported rather than skipped: a
    capture that silently stopped producing a shot would otherwise read as a
    clean run, which is the failure mode this whole script exists to avoid.
    """
    differences = [
        Difference(name, Change.CHANGED)
        for name in sorted(baseline.keys() & current.keys())
        if baseline[name] != current[name]
    ]
    differences += [Difference(name, Change.ADDED) for name in sorted(current.keys() - baseline.keys())]
    differences += [Difference(name, Change.REMOVED) for name in sorted(baseline.keys() - current.keys())]
    return differences


def same_shots(baseline: dict[str, str], current: dict[str, str]) -> bool:
    """Did nothing move at all?"""
    return not compare(baseline, current)


@dataclass(frozen=True)
class Capture:
    """What two runs of the state set agreed on, and what they did not.

    `stable` is the part worth comparing. `unstable` is named rather than
    dropped: a state that cannot reproduce itself is a fact about the capture
    that someone should eventually fix, and silently excluding it would leave
    that part of the UI unwatched with nobody aware of it.
    """

    stable: dict[str, str]
    unstable: tuple[str, ...]


def reconcile(first: dict[str, str], second: dict[str, str]) -> Capture:
    """Keep only the states two consecutive captures agreed on.

    A real change moves a state in *both* runs, so it survives into `stable`
    and is still detected. A timing flake moves it in one, and is quarantined.
    """
    shared = first.keys() & second.keys()
    stable = {name: first[name] for name in sorted(shared) if first[name] == second[name]}
    unstable = tuple(sorted(name for name in shared if first[name] != second[name]))
    # A state only one run produced is not stable by any reading of the word.
    unstable += tuple(sorted(first.keys() ^ second.keys()))
    return Capture(stable=stable, unstable=unstable)


# -- commands --------------------------------------------------------------


def capture(out_dir: Path) -> list[Path]:
    """Render the standard state set into `out_dir`, as still frames."""
    from scripts.uishot import capture_all

    out_dir.mkdir(parents=True, exist_ok=True)
    # Frozen animations remove the largest source of frame-to-frame variation.
    # They do not remove all of it, which is why callers capture twice.
    return capture_all(out_dir=str(out_dir), freeze_animations=True)


def capture_twice(keep_dir: Path) -> Capture:
    """Run the state set twice and report only what reproduced.

    The first run's images are kept — they are what a person compares by eye
    when something is reported — and the second exists solely to decide which
    of them can be trusted.
    """
    if keep_dir.exists():
        shutil.rmtree(keep_dir)
    capture(keep_dir)
    with tempfile.TemporaryDirectory(prefix="partyline-uidiff-") as second:
        confirm_dir = Path(second)
        capture(confirm_dir)
        return reconcile(digests(keep_dir), digests(confirm_dir))


def report_unstable(capture_result: Capture) -> None:
    for name in capture_result.unstable:
        print(f"  ~ {name} did not reproduce itself; excluded from comparison")


def record_baseline(out_dir: Path = BASELINE_DIR) -> int:
    result = capture_twice(out_dir)
    report_unstable(result)
    (out_dir / STABLE_LIST).write_text("\n".join(sorted(result.stable)) + "\n", encoding="utf-8")
    print(f"recorded {len(result.stable)} comparable states in {out_dir}")
    return 0


def check(baseline_dir: Path = BASELINE_DIR) -> int:
    baseline = digests(baseline_dir)
    trusted = read_stable_list(baseline_dir)
    if not baseline or trusted is None:
        print(f"no baseline at {baseline_dir}\n  → run `scripts.uidiff baseline` before the change")
        return 2
    baseline = {name: value for name, value in baseline.items() if name in trusted}

    current_dir = baseline_dir.parent / CURRENT_DIRNAME
    result = capture_twice(current_dir)
    report_unstable(result)

    # Only judge states both sides consider trustworthy. One the baseline could
    # not pin down is not evidence of anything.
    comparable = {name: value for name, value in result.stable.items() if name in baseline}
    differences = compare(baseline, comparable)

    if not differences:
        print(f"  ✓ all {len(comparable)} comparable states look exactly as they did")
        return 0

    for difference in differences:
        print(f"  ✗ {difference.describe()}")
    print(f"\n{len(differences)} state(s) changed. Compare {baseline_dir} against {current_dir}.")
    print("If the change was intended, re-run `scripts.uidiff baseline` to accept it.")
    return 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "check"
    if command == "baseline":
        return record_baseline()
    if command == "check":
        return check()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
