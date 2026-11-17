"""Live descendant inventory shared by handover briefing and completion."""
from .attachment_tmp import attachment_tmp_dir
from .process_memory import process_snapshot
from .tmp_processes import references
from .job_details import describe
from .top_processes import _descendants, namespace_pid
from .tmp_owners import members, owned
from .handover_processes import actionable, listing


def live_jobs(runtime, att_id):
    adapter = getattr(runtime, 'live', {}).get(att_id)
    pid = getattr(getattr(adapter, 'proc', None), 'pid', None)
    if not isinstance(pid, int):
        return []
    snapshot = process_snapshot()
    if snapshot is None:
        from fastapi import HTTPException
        raise HTTPException(409, 'Cannot inspect live jobs; retry after process inspection recovers. '
                                 'This failure is not waived by live_jobs="transfer": that acknowledgment '
                                 'applies only once the jobs have been inspected.')
    # Every process still under the attached runtime transfers by default.
    # Only owned jobs that escaped/reparented out of that tree need a decision.
    runtime_tree = _descendants(snapshot[0], pid)
    found = (members(adapter, snapshot) | owned(att_id)) - runtime_tree
    facts = listing() if found else {}
    jobs = []
    for member in sorted(found):
        fact = facts.get(member, {})
        if not actionable(fact):
            continue
        command, found_cwd, why = describe(member)
        if (not command or command.strip() in ('?', 'unknown', 'command unknown')
                or '<defunct>' in command):  # exited or unreadable at the per-PID inspection
            continue
        cwd, files, _ = references(member, attachment_tmp_dir(att_id))
        jobs.append({'pid': namespace_pid(member), 'host_pid': member, 'command': command,
                     'state': fact.get('state') or 'unavailable',
                     'started': fact.get('started') or 'unavailable',
                     'cwd': found_cwd or (cwd if cwd != '?' else None), 'files': files,
                     'unknown': why})
    return jobs


def completion_hint(ident='id'):
    return ('Both participants must independently confirm, including the receiver. '
            'While background jobs remain, each must pass live_jobs="transfer", '
            'including the receiver even after the old captain has acknowledged them. '
            'For remaining background jobs, live_jobs allows only "transfer"; omit it after '
            'finishing or stopping the jobs. The attachment process tree transfers by default. '
            'Transfer retains files; detach still stops the original process group. '
            f'Example: extras(op="complete_handover", args={{"handover_id": "{ident}", '
            '"live_jobs": "transfer"}).')


def _short(value, limit):
    text = ' '.join(str(value).split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _files_text(files):
    shown = [_short(path, 100) for path in files[:2]]
    if len(files) > len(shown):
        shown.append(f'+{len(files) - len(shown)} more files')
    return ', '.join(shown) or 'none observed'


def jobs_text(jobs, limit=1800):
    """Bound the list at whole entries; never cut the instructions or a job in half."""
    if not jobs:
        return ''
    lines = ['\nLive jobs of the old captain:']
    for index, job in enumerate(jobs):
        line = (f"pid {job['pid']} (host {job['host_pid']}): "
                f"{_short(job['command'] or 'command unknown', 200)}; "
                f"state={_short(job.get('state', 'unavailable'), 16)}; "
                f"started={_short(job.get('started', 'unavailable'), 64)}; "
                f"cwd={_short(job['cwd'] or 'unknown', 120)}; tmp files={_files_text(job['files'])}"
                + (f"; unknown because {_short(job['unknown'], 120)}" if job.get('unknown') else ''))
        if sum(len(value) + 1 for value in lines) + len(line) + 40 > limit:
            lines.append(f'+{len(jobs) - index} more')
            break
        lines.append(line)
    return '\n'.join(lines)


def inspect_completion(runtime, att_id):
    from .tmp_owners import record
    record(att_id, runtime.live.get(att_id))
    return live_jobs(runtime, att_id)
