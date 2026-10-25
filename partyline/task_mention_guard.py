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


async def notify_cross_task(runtime, conv_id, speaker, targets):
    """Tell the captain, privately and once per spoken message, whose handles belong elsewhere.

    One notice lists every held-back handle with its line, however many the
    message named: one reply that mentioned three workers used to ring the
    captain six times, a notice per line-and-handle pair, each calling a
    delivery a hold-back.
    """
    if not (targets and speaker):
        return
    from .orchestrator_notices import tell
    db = runtime.db
    mine = task(db, conv_id)
    here = ', '.join(f"{label} {mine[key]}" for label, key in
                     (('implementer', 'implementer_handle'), ('reviewer', 'reviewer_handle'))
                     if mine[key]) or 'no live process'
    listed = '; '.join(
        f"{target['name']} belongs to another task "
        f"(«{(db.get_conversation(target['conv_id']) or {}).get('name', '?')}»)"
        for target in targets)
    await tell(runtime, speaker['id'],
               f"held back: {listed}. This line is "
               f"«{(db.get_conversation(conv_id) or {}).get('name', '?')}» ({here}). "
               'Use message_task(conv_id, text, to) to reach a task\'s workers.')
