"""Blocking handover temp work, called only from worker threads."""
from .attachment_tmp import attachment_tmp_dir, guarded_path, reap_tmp_dir
from .handover_jobs import live_jobs
from .tmp_owners import owned, record
from .tmp_processes import in_use
from .tmp_retention import remember


def prepare(runtime, row):
    att_id = row['from_attachment_id']
    record(att_id, runtime.live.get(att_id))
    path = guarded_path(att_id)
    if path is not None:
        jobs = live_jobs(runtime, att_id)
        if jobs or in_use(path, owned(att_id)):
            remember(att_id, row['conv_id'], row['to_attachment_id'], jobs)


def reap_notice(row):
    att_id = row['from_attachment_id']
    reap_tmp_dir(att_id)
    path = guarded_path(att_id)
    if path is None:
        return None
    remember(att_id, row['conv_id'], row['to_attachment_id'])
    link = attachment_tmp_dir(row['to_attachment_id']) / 'retained' / att_id
    return (f"☏ Retained handover files for {row['id']}: {path}; "
            f"successor link: {link if link.is_symlink() else 'use the retained path above'}. "
            "Cleanup will retry once live jobs and cwd/fd holders exit.")
