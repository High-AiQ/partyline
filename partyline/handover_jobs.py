"""Live descendant inventory shared by handover briefing and completion."""
import os
import sys
from pathlib import Path

from .attachment_tmp import attachment_tmp_dir
from .process_memory import process_snapshot
from .tmp_processes import references
from .top_processes import argv, namespace_pid, render
from .tmp_owners import members
from .handover_mcp import commands, matches


def live_jobs(runtime, att_id):
    adapter = getattr(runtime, 'live', {}).get(att_id)
    pid = getattr(getattr(adapter, 'proc', None), 'pid', None)
    if not isinstance(pid, int):
        return []
    snapshot = process_snapshot()
    if snapshot is None:
        from fastapi import HTTPException
        raise HTTPException(409, 'Cannot inspect live jobs; retry after process inspection recovers')
    excluded = _cli_processes(snapshot[0], pid, adapter)
    found = members(adapter, snapshot) - excluded
    configured = commands(adapter)
    jobs = []
    for member in sorted(found):
        if sys.platform.startswith('linux'):
            try:
                stat = Path(f'/proc/{member}/stat').read_text()
                if stat.rsplit(')', 1)[1].split()[0] == 'Z':
                    continue
            except FileNotFoundError:
                continue
            except OSError:
                pass
        if matches(argv(member), configured):
            continue
        cwd, files, _ = references(member, attachment_tmp_dir(att_id))
        jobs.append({'pid': namespace_pid(member), 'host_pid': member,
                     'command': render(argv(member)), 'cwd': cwd, 'files': files})
    return jobs


def jobs_text(jobs):
    return ('\nLive jobs of the old captain:\n' + '\n'.join(
        f"pid {job['pid']} (host {job['host_pid']}): {job['command']}; cwd={job['cwd']}; "
        f"tmp files={', '.join(job['files']) or 'none observed'}" for job in jobs)) if jobs else ''


def _cli_processes(parents, pid, adapter):
    """Exclude the scope/fence launch chain and its CLI, never the CLI's jobs."""
    excluded = {pid}
    command = getattr(adapter, 'att', {}).get('command', [])
    cli = os.path.basename(command[0]) if command else ''
    current = pid
    while True:
        parts = argv(current)
        name = os.path.basename(parts[0]) if parts else ''
        launcher = name in ('bwrap', 'systemd-run') or '--verify-exec' in parts
        children = [child for child, parent in parents.items() if parent == current]
        if len(children) != 1:
            break
        child = children[0]
        child_parts = argv(child)
        child_name = os.path.basename(child_parts[0]) if child_parts else ''
        # Some installed CLI entrypoints wrap a native binary of the same name.
        cli_wrapper = cli and child_name == cli and any(
            os.path.basename(part) == cli + '.js' for part in parts[1:])
        if not launcher and not cli_wrapper:
            break
        excluded.add(child)
        current = child
    return excluded


def inspect_completion(runtime, att_id):
    from .tmp_owners import record
    record(att_id, runtime.live.get(att_id))
    return live_jobs(runtime, att_id)
