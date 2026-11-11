"""Reject timer-based state checks in production code.

All browser timers require a reviewed category, including indirect callbacks
such as setTimeout(reload). Existing unresolved OS/provider gaps are pinned to
specific calls below; they are not permission to add another poll.
"""

import ast
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CATEGORY = re.compile(r'no-poll\s+\(([bcde])\):\s*\S')
TIMERS = re.compile(r'\b(setInterval|setTimeout)\s*\(')
# Phase 1 exceptions awaiting Greg's decision; docs/polling-audit.md explains each.
UNRESOLVED = {
    ('partyline/memory_sampler.py', 'asyncio.sleep(INTERVAL)'): 1,
    ('partyline/event_loop_lag.py', 'asyncio.sleep(0.1)'): 1,
    ('partyline/event_loop_lag.py', 'asyncio.sleep(interval)'): 1,
    ('partyline_helper/capture_loop.py', "sleep(1 / request['max_fps'])"): 1,
}


def allowed(lines, line):
    return any(CATEGORY.search(text) for text in lines[max(0, line - 2):line])


def python_calls(source):
    hits = []

    class Scan(ast.NodeVisitor):
        loops = 0

        def visit_FunctionDef(self, node):
            previous, self.loops = self.loops, 0
            self.generic_visit(node)
            self.loops = previous

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_While(self, node):
            self.loops += 1
            self.generic_visit(node)
            self.loops -= 1

        visit_For = visit_While
        visit_AsyncFor = visit_While

        def visit_Call(self, node):
            function = node.func
            name = function.attr if isinstance(function, ast.Attribute) else getattr(function, 'id', '')
            if self.loops and name == 'sleep':
                hits.append((node.lineno, ast.unparse(node)))
            self.generic_visit(node)

    Scan().visit(ast.parse(source))
    return hits


def violations(path, source):
    lines = source.splitlines()
    if path.endswith('.py'):
        calls = python_calls(source)
    else:
        calls = [(source.count('\n', 0, match.start()) + 1, match[1]) for match in TIMERS.finditer(source)]
    budget = {call: count for (name, call), count in UNRESOLVED.items() if name == path}
    errors = []
    for line, call in calls:
        if allowed(lines, line):
            continue
        if budget.get(call, 0):
            budget[call] -= 1
            continue
        errors.append(f'{path}:{line}: {call}: react to an event, or document no-poll (b)/(c)/(d)/(e)')
    return errors


def main():
    errors = []
    for root in ('partyline', 'partyline_helper', 'frontend/src', 'scripts'):
        for path in (ROOT / root).rglob('*'):
            if 'static' in path.parts or path.suffix not in ('.py', '.js', '.jsx', '.ts', '.tsx', '.svelte'):
                continue
            if path == ROOT / 'scripts/uishot.py':
                continue  # Development-only screenshot server readiness; never production.
            if '.test.' in path.name:
                continue
            errors.extend(violations(str(path.relative_to(ROOT)), path.read_text()))
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('No unclassified polling timers in production source.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
