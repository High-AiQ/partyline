"""Nonblocking, non-raising handover rider inventory with a short freshness window."""
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .handover_jobs import live_jobs, jobs_text

TTL_SECONDS = 5
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='handover-jobs')
_lock = threading.Lock()


def state_jobs(runtime, att_id, handover_id=None, viewer=None):
    adapter = getattr(runtime, 'live', {}).get(att_id)
    if adapter is None:
        return ''
    with _lock:
        cache = getattr(runtime, 'handover_job_cache', None)
        if cache is None:
            cache = runtime.handover_job_cache = {}
        entry = cache.get(att_id)
        if entry is None or entry['adapter'] is not adapter:
            entry = cache[att_id] = {'adapter': adapter, 'at': 0, 'text': '', 'pending': False}
        stale = time.monotonic() - entry['at'] >= TTL_SECONDS
        if stale and not entry['pending']:
            entry['pending'] = True
            _executor.submit(_refresh, runtime, att_id, entry)
        text = entry['text']
        if handover_id and entry.get('jobs'):
            seen = entry.setdefault('seen', {})
            key = (handover_id, viewer)
            signature = tuple((job['host_pid'], job.get('started'), job['command'])
                              for job in entry['jobs'])
            if seen.get(key) == signature:
                text = (f"\n{len(entry['jobs'])} live jobs awaiting live_jobs decision; "
                        'see first notice.')
            else:
                seen[key] = signature
    return text + ('\nLive job inventory is refreshing.' if stale else '')


def _refresh(runtime, att_id, entry):
    try:
        jobs = live_jobs(runtime, att_id)
        text = jobs_text(jobs)
    except Exception:
        jobs = []
        text = '\nLive job inventory unavailable; completion will retry inspection.'
    with _lock:
        entry.update(text=text, jobs=jobs, at=time.monotonic(), pending=False)


async def refresh(runtime, att_id):
    """Prime offer/accept notices without inspecting processes on the loop."""
    entry = {'adapter': getattr(runtime, 'live', {}).get(att_id),
             'at': 0, 'text': '', 'pending': True}
    with _lock:
        cache = getattr(runtime, 'handover_job_cache', None)
        if cache is None:
            cache = runtime.handover_job_cache = {}
        previous = cache.get(att_id, {})
        if previous.get('adapter') is entry['adapter']:
            entry['seen'] = previous.get('seen', {})
        cache[att_id] = entry
    await asyncio.to_thread(_refresh, runtime, att_id, entry)
