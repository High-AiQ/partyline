"""What complete_handover tells its caller: the real state of the handover, in words."""



def old_captain_gone(runtime, row):
    """The old captain no longer holds a live process, so nothing remains for it to confirm."""
    ident = row['from_attachment_id']
    att = runtime.db.get_attachment(ident)
    return att is None or (att['status'] not in ('running', 'starting')
                           and ident not in getattr(runtime, 'live', {}))


def summary(runtime, current):
    """Fields that say whether the handover is finished and what the old captain is doing."""
    db = runtime.db
    old = db.get_attachment(current['from_attachment_id'])
    new = db.get_attachment(current['to_attachment_id'])
    old_name = old['name'] if old else 'the old captain'
    new_name = new['name'] if new else 'the new captain'
    done = current['state'] == 'completed'
    if done and (current['detach_finished_at'] is not None or old is None):
        old_state = 'detached'
    elif done:
        old_state = 'detaching'
    else:
        old_state = 'attached' if old and old['status'] in ('running', 'starting') else 'gone'
    waiting = [name for name, flag in ((old_name, current['from_done']), (new_name, current['to_done']))
               if not flag]
    if done:
        message = (f'Handover completed: {new_name} is the captain and {old_name} '
                   + ('is detached.' if old_state == 'detached' else 'is being detached.'))
    else:
        message = (f"Handover {current['state']}: waiting for {' and '.join(waiting)} to call "
                   'complete_handover.')
    return {'completed': done, 'old_captain': old_state, 'awaiting': [] if done else waiting,
            'message': message}


