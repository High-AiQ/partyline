"""Recognize repository-wide test invocations before applying the task-mode guard."""

import argparse
import os
from pathlib import Path


def task_suite_refusal() -> str | None:
    """Read the immutable launch mode, or query an older attachment once."""
    mode = os.environ.get('PARTYLINE_TASK_MODE')
    if mode is None and os.environ.get('PARTYLINE_CONV_ID'):
        import json
        from urllib.error import HTTPError, URLError
        from urllib.request import Request, urlopen
        api, token = os.environ.get('PARTYLINE_API'), os.environ.get('PARTYLINE_TOKEN')
        if not api or not token:
            return 'cannot determine task mode; use the scoped gates: python -m partyline.task_gates'
        request = Request(f"{api}/api/conversations/{os.environ['PARTYLINE_CONV_ID']}/task",
                          headers={'Authorization': f'Bearer {token}'})
        try:
            with urlopen(request, timeout=10) as response:
                mode = json.load(response)['mode']
        except HTTPError as exc:
            if exc.code == 404:
                return None  # an ordinary line, not a task
            return 'cannot determine task mode; use the scoped gates: python -m partyline.task_gates'
        except (URLError, OSError, ValueError, KeyError):
            return 'cannot determine task mode; use the scoped gates: python -m partyline.task_gates'
    if mode in ('full', 'light', 'express'):
        return 'full suites are forbidden in task lines; use the scoped gates: python -m partyline.task_gates'
    return None


def whole_suite(command: list[str]) -> bool:
    """Unittest discovery and omitted test names are whole-suite entry points.

    A task must name its test modules explicitly. Discovery is deliberately
    reserved for suite lines, including when extra discovery options are supplied.
    """
    if not command:
        return True
    arguments = None
    for index, value in enumerate(command):
        if value == '-m' and command[index + 1:index + 2] == ['scripts.parallel_test']:
            return True
        if Path(value).as_posix().endswith('scripts/parallel_test.py'):
            return True
        if value == '-m' and command[index + 1:index + 2] == ['unittest']:
            arguments = command[index + 2:]
            break
        if Path(value).name in ('unittest', 'unittest.exe'):
            arguments = command[index + 1:]
            break
    if arguments is None:
        return False
    options = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    options.add_argument('-k', action='append')
    _, remaining = options.parse_known_args(arguments)
    names = [value for value in remaining if not value.startswith('-')]
    return (not names or 'discover' in names
            or any(name in ('.', 'tests', 'tests/', './tests') for name in names))
