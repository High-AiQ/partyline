"""The root captain's mention of another task's worker, said in a task line,
is held back — one consolidated notice per spoken message."""

from .orchestrator_store import task


def split_cross_task(db, conv_id, speaker, withheld):
    """Withheld targets living on a different task line, and the rest.

    Only the root captain of the task it is speaking in is guarded: names that
    differ by a suffix are easy to confuse, and a mention landing on another
    task's worker is worse than one that reaches nobody.
    """
    mine = task(db, conv_id)
    if not (mine and speaker and speaker.get('is_lead') and speaker['conv_id'] == mine['root_id']):
        return [], withheld
    other = [t for t in withheld if t['conv_id'] != conv_id and task(db, t['conv_id'])]
    return other, [t for t in withheld if t not in other]


def cross_task_text(db, conv_id, targets):
    """The held-back sentence: every handle with its task, and the exact call that reaches it."""
    from .task_remedy import message_task_call, task_role
    mine = task(db, conv_id)
    here = ', '.join(f"{label} {mine[key]}" for label, key in
                     (('implementer', 'implementer_handle'), ('reviewer', 'reviewer_handle'))
                     if mine[key]) or 'no live process'
    listed = []
    for target in targets:
        line = (db.get_conversation(target['conv_id']) or {}).get('name', '?')
        found = task_role(db, target['id'])
        how = f"; reach it with {message_task_call(*found)}" if found else ''
        listed.append(f"{target['name']} belongs to another task («{line}», "
                      f"conv_id {target['conv_id']}){how}")
    return (f"held back: {'; '.join(listed)}. This line is "
            f"«{(db.get_conversation(conv_id) or {}).get('name', '?')}» ({here}).")


async def notify_cross_task(runtime, conv_id, speaker, targets, unreached=None):
    """Tell the captain, privately and once per spoken message, whose handles belong elsewhere.

    One notice lists every held-back handle with its line, however many the
    message named: one reply that mentioned three workers used to ring the
    captain six times, a notice per line-and-handle pair, each calling a
    delivery a hold-back. With ``unreached`` the sentence joins the speaker's
    single notice for the message instead.
    """
    if not (targets and speaker):
        return
    text = cross_task_text(runtime.db, conv_id, targets)
    if unreached is not None:
        return unreached.note(text)
    from .orchestrator_notices import tell
    await tell(runtime, speaker['id'], text)
