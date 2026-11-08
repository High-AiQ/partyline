"""Manual hosted-runner recording, through WindowAccess and ActionWorker. No pixels."""
import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from audit import complete, snapshots
from protocol import SPLITS, digest, predicate, tasks

ROOT = Path(__file__).resolve().parent


def write(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def visible():
    # The normal enumerator excludes its own descendants. A separate observer
    # can see this recorder's explicitly launched apps without changing production.
    code = 'import json; from partyline_helper.uia_window_list import windows; print(json.dumps(windows()))'
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                            check=True, timeout=10)
    return json.loads(result.stdout)


class Audit:
    def __init__(self, path):
        self.path = path

    def ensure_writable(self):
        with self.path.open('a', encoding='utf-8'):
            pass

    def append(self, *entry):
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry) + '\n')
            stream.flush()
            os.fsync(stream.fileno())


async def capture(grant, application, output):
    from partyline_helper.uia_access import WindowAccess
    from partyline_helper.uia_action_worker import ActionWorker
    from partyline_helper.uia_window_identity import mark

    grant['marker'] = mark(grant['hwnd'])
    if not grant['marker']:
        raise RuntimeError('could not mark explicitly selected fixture window')
    session = SimpleNamespace(status=SimpleNamespace(window_title=None, changed=lambda: None),
                              tools=SimpleNamespace(audit=Audit(output / (application + '-audit.jsonl'))),
                              share={'share_id': 'offline-corpus'}, accepted=True, last_uia_frame=None,
                              control=SimpleNamespace(granted=True))
    access = WindowAccess(session, picker=lambda: grant, list_windows=visible)
    session.window = access
    await access.choose()
    try:
        before = await access.snapshot()
        if not complete(before):
            return {'application': application, 'before': before, 'verification': []}
        pairs = []
        field = next((e for e in before['elements'] if 'set_value' in e.get('actions', []) and
                      e.get('enabled') and not e.get('offscreen') and
                      e.get('value') != 'uia-corpus-complete'),
                     None)
        after = before
        if field:
            expected = {'element_id': field['id'], 'equals': {'value': 'uia-corpus-complete'}}
            unchanged = await access.snapshot()
            pairs.append({'kind': 'unchanged', 'label': 'failed', 'before': before,
                          'after': unchanged, 'predicate': expected})
            worker = ActionWorker(session, timeout=8)
            bad = {'element_id': 'nonexistent-corpus-element', 'action': 'set_value',
                   'value': 'uia-corpus-complete', 'share_id': 'offline-corpus', 'agent': 'corpus'}
            failed = await worker.perform(bad)
            failed_after = await access.snapshot()
            pairs.append({'kind': 'refused', 'label': 'failed', 'before': unchanged,
                          'after': failed_after, 'predicate': expected, 'action_result': failed})
            message = {**bad, 'element_id': field['id']}
            result = await worker.perform(message)
            after = await access.snapshot()
            observed = predicate(after, expected)
            label = 'success' if observed and result.get('status') == 'completed' else 'unknown'
            pairs.append({'kind': 'set_value', 'label': label, 'before': failed_after,
                          'after': after, 'predicate': expected, 'action_result': result})
        return {'application': application, 'before': before, 'after': after, 'verification': pairs}
    finally:
        access.revoke('corpus complete')


def command(application):
    if application == 'tk':
        return [sys.executable, str(ROOT / 'fixture_tk.py')]
    if application in ('open-dialog', 'save-dialog', 'winforms'):
        mode = {'open-dialog': 'open', 'save-dialog': 'save', 'winforms': 'fixture'}[application]
        return ['powershell.exe', '-NoProfile', '-STA', '-File', str(ROOT / 'fixture.ps1'), mode]
    return [{'notepad': 'notepad.exe', 'calculator': 'calc.exe', 'charmap': 'charmap.exe'}[application]]


def record(application, output):
    from partyline_helper.uia_window_list import descendants
    child = subprocess.Popen(command(application), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    owned = {child.pid}
    try:
        deadline, selected = time.monotonic() + 20, None
        while time.monotonic() < deadline:
            owned |= descendants({child.pid}) or set()
            candidates = [w for w in visible() or [] if w['pid'] in owned]
            if candidates:
                selected = candidates[0]
                break
            time.sleep(.25)
        if selected is None:
            raise RuntimeError('no visible window owned by launched process; app may be absent or brokered')
        return asyncio.run(capture(selected, application, output))
    finally:
        # Kill only the explicitly launched process tree. Never pattern-match.
        owned |= descendants({child.pid}) or set()
        for pid in owned:
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        child.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ephemeral-runner', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--application', choices=SPLITS)
    args = parser.parse_args()
    if not (args.ephemeral_runner and sys.platform == 'win32' and
            os.environ.get('GITHUB_ACTIONS') == 'true' and
            os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'):
        parser.error('recording requires explicit opt-in on an ephemeral GitHub-hosted Windows runner')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['PARTYLINE_CORPUS_DIR'] = str(output)
    if args.application:
        try:
            result = record(args.application, output)
        except Exception as exc:
            result = {'application': args.application, 'unavailable': str(exc)}
        write(output / (args.application + '.json'), result)
        return
    manifest = {'schema': 1, 'source': 'recorded-windows-uia', 'platform': platform.platform(),
                'commit': os.environ.get('GITHUB_SHA'), 'run_id': os.environ.get('GITHUB_RUN_ID'),
                'splits': SPLITS, 'applications': [], 'choices': [], 'verification': []}
    for application in SPLITS:
        cmd = [sys.executable, str(Path(__file__).resolve()), '--ephemeral-runner',
               '--output', str(output), '--application', application]
        worker = subprocess.Popen(cmd)
        try:
            if worker.wait(timeout=120):
                raise RuntimeError('application recorder failed')
            record_data = json.loads((output / (application + '.json')).read_text(encoding='utf-8'))
        except (subprocess.SubprocessError, OSError, ValueError, RuntimeError) as exc:
            # Kill the recorder's owned tree while its parent pid still exists.
            # subprocess.run(timeout=...) would orphan the app before cleanup.
            subprocess.run(['taskkill', '/PID', str(worker.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            worker.wait(timeout=10)
            record_data = {'application': application, 'unavailable': str(exc)}
        manifest['applications'].append(record_data)
        before = record_data.get('before', {})
        if complete(before):
            manifest['choices'].extend(tasks(application, before))
            after = record_data.get('after')
            if after and digest(after.get('elements')) != digest(before['elements']):
                manifest['choices'].extend(
                    r for r in tasks(application, before, after) if r['case'] == 'stale')
        for index, pair in enumerate(record_data.get('verification', [])):
            pair.update(application=application, split=SPLITS[application],
                        id=f'{application}-verify-{index}')
            manifest['verification'].append(pair)
        write(output / 'dataset.json', manifest)
    # A failed collection still uploads diagnostics, but never looks like a full corpus.
    if any(not complete(r.get('before', {})) or any(not complete(s) for s in snapshots(r).values())
           for r in manifest['applications']):
        raise SystemExit('Incomplete corpus: unavailable, empty or truncated snapshot; inspect artifacts')


if __name__ == '__main__':
    main()
