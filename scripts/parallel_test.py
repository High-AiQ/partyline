"""Run unittest discovery in balanced process shards and combine coverage."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.test_time_allowlist import SLOW_TEST_ALLOWLIST

RAN = re.compile(r"^Ran (\d+) tests? in ([0-9.]+)s$", re.MULTILINE)
SKIPPED = re.compile(r"\bskipped=(\d+)")


def default_workers() -> int:
    """Useful parallelism without oversubscribing a small developer machine."""
    return min(8, max(1, (os.cpu_count() or 2) // 2))


def flatten(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def make_shards(workers: int) -> list[tuple[list[str], int]]:
    """Balance modules loaded exactly as their workers will load them.

    Discovery runs an imported TestCase again in the importing module, while its
    test id still names the defining module. Loading each module independently
    preserves that context; pairing discovery suites with file paths by position
    would not. Class-name shards silently lose those imported executions.
    """
    if workers < 1:
        raise ValueError("workers must be positive")
    groups = {}
    for path in sorted(Path("tests").glob("test_*.py")):
        name = f"tests.{path.stem}"
        suite = unittest.defaultTestLoader.loadTestsFromName(name)
        count = sum(1 for _ in flatten(suite))
        if count:
            groups[name] = count
    names = [[] for _ in range(workers)]
    counts = [0] * workers
    loads = [0] * workers
    for name, count in sorted(groups.items(), key=lambda item: (-item[1], item[0])):
        index = min(range(workers), key=lambda i: (loads[i], i))
        names[index].append(name)
        counts[index] += count
        loads[index] += count
    return [(sorted(shard), count) for shard, count in zip(names, counts, strict=True) if shard]


def worker_environment(base: dict[str, str], directory: Path, coverage: Path) -> dict[str, str]:
    """Give every process independent state before it imports the test package."""
    directory.mkdir()
    env = base.copy()
    env.update({
        "PARTYLINE_DB": str(directory / "partyline.db"),
        "PARTYLINE_TMP_BASE": str(directory / "tmp"),
        "TMPDIR": str(directory),
        "COVERAGE_FILE": str(coverage),
    })
    return env


def report_worker(index: int, result: subprocess.CompletedProcess, expected: int) -> tuple[int, int, bool]:
    output = result.stdout
    matches = list(RAN.finditer(output))
    ran = int(matches[-1].group(1)) if matches else -1
    seconds = matches[-1].group(2) if matches else "?"
    skipped = sum(int(value) for value in SKIPPED.findall(output))
    okay = result.returncode == 0 and ran == expected
    print(
        f"parallel-test: worker {index}: {ran} tests in {seconds}s, "
        f"skipped={skipped}, exit={result.returncode}", flush=True,
    )
    if not okay:
        print(f"parallel-test: worker {index} output (expected {expected} tests):\n{output}", flush=True)
    return ran, skipped, okay


def summarize_workers(results) -> tuple[int, int, bool]:
    """Require every shard and the aggregate to match their discovered counts."""
    total = skipped = 0
    okay = True
    for index, (result, expected) in enumerate(results):
        ran, worker_skipped, worker_okay = report_worker(index, result, expected)
        total += max(0, ran)
        skipped += worker_skipped
        okay = okay and worker_okay
    expected_total = sum(expected for _, expected in results)
    if total != expected_total:
        print(f"parallel-test: expected {expected_total} tests, got {total}", file=sys.stderr)
        okay = False
    return total, skipped, okay


def first_pass_violations(timings) -> dict[str, float]:
    """One candidate per unallowlisted test, retaining its slowest first pass."""
    violations = {}
    for row in timings:
        if row["seconds"] > 1.0 and row["id"] not in SLOW_TEST_ALLOWLIST:
            violations[row["id"]] = max(row["seconds"], violations.get(row["id"], 0))
    return violations


def confirm_violations(violations: dict[str, float], rerun) -> bool:
    """Resolve scheduler outliers with one isolated rerun per candidate."""
    okay = True
    for index, (ident, first) in enumerate(sorted(violations.items())):
        second, rerun_okay = rerun(ident, index)
        second_text = f"{second:.3f}s" if second is not None else "missing"
        print(
            f"parallel-test: isolated timing for {ident}: "
            f"first={first:.3f}s, rerun={second_text}", flush=True,
        )
        if not rerun_okay or second is None or second > 1.0:
            print(f"parallel-test: isolated rerun did not clear {ident}", file=sys.stderr)
            okay = False
    return okay


def isolated_rerun(ident: str, root: Path, index: int) -> tuple[float | None, bool]:
    """Run one test in a fresh warm worker and return its duration and health."""
    coverage = root / f".coverage.rerun-{index}"
    timing_path = root / f"timings-rerun-{index}.json"
    env = worker_environment(os.environ.copy(), root / f"rerun-{index}", coverage)
    env["PARTYLINE_TEST_TIMINGS"] = str(timing_path)
    result = subprocess.run(
        [sys.executable, "-m", "coverage", "run", "--parallel-mode",
         "-m", "scripts.test_worker", ident],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    matches = list(RAN.finditer(result.stdout))
    ran = int(matches[-1].group(1)) if matches else -1
    okay = result.returncode == 0 and ran == 1
    seconds = None
    try:
        with open(timing_path, encoding="utf-8") as stream:
            rows = json.load(stream)
        if len(rows) == 1 and rows[0]["id"] == ident:
            seconds = float(rows[0]["seconds"])
        else:
            okay = False
    except (OSError, ValueError, KeyError, TypeError):
        okay = False
    if not okay:
        print(f"parallel-test: isolated worker output for {ident}:\n{result.stdout}", flush=True)
    return seconds, okay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=default_workers())
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be positive")

    shards = make_shards(args.workers)
    expected_total = sum(count for _, count in shards)
    print(
        f"parallel-test: discovered {expected_total} tests; starting {len(shards)} workers",
        flush=True,
    )
    coverage_output = Path(os.environ.get("COVERAGE_FILE", ".coverage")).absolute()
    coverage_output.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="partyline-parallel-test-") as temporary:
        root = Path(temporary)
        processes = []
        for index, (names, _) in enumerate(shards):
            coverage = root / f".coverage.worker-{index}"
            command = [
                sys.executable, "-m", "coverage", "run", "--parallel-mode",
                "-m", "scripts.test_worker", *names,
            ]
            env = worker_environment(os.environ.copy(), root / f"worker-{index}", coverage)
            env["PARTYLINE_TEST_TIMINGS"] = str(root / f"timings-{index}.json")
            processes.append(subprocess.Popen(
                command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            ))
        results = []
        for process, (_, expected) in zip(processes, shards, strict=True):
            output, _ = process.communicate()
            results.append((subprocess.CompletedProcess(process.args, process.returncode, output), expected))
        total, skipped, okay = summarize_workers(results)
        timings = []
        for index in range(len(shards)):
            try:
                with open(root / f"timings-{index}.json", encoding="utf-8") as stream:
                    timings.extend(json.load(stream))
            except (OSError, ValueError) as exc:
                print(f"parallel-test: missing worker {index} timings: {exc}", file=sys.stderr)
                okay = False
        print("parallel-test: slowest 10 tests", flush=True)
        for row in sorted(timings, key=lambda row: row["seconds"], reverse=True)[:10]:
            print(f"parallel-test: {row['seconds']:.3f}s {row['id']}", flush=True)
        violations = first_pass_violations(timings)
        for ident, seconds in sorted(violations.items()):
            print(
                f"parallel-test: over 1s without an allowlist reason: "
                f"{seconds:.3f}s {ident}", file=sys.stderr,
            )
        rerun_okay = confirm_violations(
            violations,
            lambda ident, index: isolated_rerun(ident, root, index),
        )
        # A shared developer host can deschedule even a no-op test. CI fails
        # only when a fresh isolated worker confirms the slow duration.
        if os.environ.get("CI"):
            okay = okay and rerun_okay
        env = {**os.environ, "COVERAGE_FILE": str(coverage_output)}
        combined = subprocess.run(
            [sys.executable, "-m", "coverage", "combine", root], env=env,
        )
    print(
        f"parallel-test: Ran {total} tests across {len(shards)} workers; skipped={skipped}",
        flush=True,
    )
    if combined.returncode:
        print("parallel-test: coverage combine failed", file=sys.stderr)
        okay = False
    return 0 if okay else 1


if __name__ == "__main__":
    raise SystemExit(main())
