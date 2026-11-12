#!/usr/bin/env python3
"""Measure the context Partyline itself puts into an attached process.

    uv run --locked python -m scripts.context_budget [--tools] [--json]

Prints characters and approximate tokens (characters / 4) for: (a) the MCP tool
catalog per role and adapter, (b) the startup briefing and captain pack, (c) the
paste on resume, (d) the suffix lines on every delivered message, (e) the system
notices a process is pasted over a real-looking hour. Temp database only; it never
reads the live database, a CLI store or the running server.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

# A measurement must never fall through to a real database.
os.environ["PARTYLINE_DB"] = os.path.join(tempfile.mkdtemp(prefix="measure-"), "x.db")
for name in [key for key in os.environ if key.startswith("PARTYLINE_") and key != "PARTYLINE_DB"]:
    del os.environ[name]

from scripts.context_fixtures import World  # noqa: E402
from scripts import context_sections as sections  # noqa: E402

ADAPTERS = ("opencode-v2", "claude", "codex")


def tokens(chars: int) -> int:
    return round(chars / 4)


def row(label: str, chars: int, note: str = "") -> str:
    return f"{label:<58}{chars:>9,}{tokens(chars):>9,}  {note}".rstrip()


def collect(per_tool: bool) -> dict:
    result: dict = {}
    for adapter in ADAPTERS:
        world = World()  # fresh rows per adapter: resume and notices add messages
        result[adapter] = {
            "tools": sections.catalog(world, adapter, per_tool),
            "startup": sections.startup(world, adapter),
            "resume": sections.resume(world, adapter),
            "suffix": sections.suffix(world, adapter),
        }
        world.close()
    world = World()
    result["notices"] = sections.notices(world)
    result["listings"] = sections.listings(world)
    world.close()
    return result


def show(result: dict, per_tool: bool) -> None:
    print(f"{'what':<58}{'chars':>9}{'~tokens':>9}")
    for adapter in ADAPTERS:
        print(f"\n=== {adapter} ===")
        data = result[adapter]
        for role, info in data["tools"].items():
            print(row(f"(a) catalog: {role}", info["chars"], f"{info['count']} tools"))
            if per_tool:
                for name, chars in sorted(info["per_tool"].items(), key=lambda kv: -kv[1]):
                    print(row(f"      {name}", chars))
        for group in ("startup", "resume", "suffix"):
            letter = {"startup": "b", "resume": "c", "suffix": "d"}[group]
            for label, chars in data[group].items():
                print(row(f"({letter}) {group}: {label}", chars))
    print("\n=== all adapters ===")
    for label, chars in result["notices"].items():
        print(row(f"(e) notices: {label}", chars))
    for label, chars in result["listings"].items():
        print(row(f"(f) listing: {label}", chars))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", action="store_true", help="list every tool's size")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    result = collect(args.tools)
    print(json.dumps(result, indent=1)) if args.json else show(result, args.tools)
    return 0


if __name__ == "__main__":
    sys.exit(main())
