"""Find the live captain above a finishing child captain."""

from .hierarchy import lead_attachment, parent_id_of
from .mention_relay import LIVE


def parent_captain(db, finisher):
    if not finisher.get('is_lead'):
        return None
    parent = parent_id_of(db.get_conversation(finisher['conv_id']))
    if not parent:
        return None
    manager = lead_attachment(db, parent)
    if manager and manager['status'] in LIVE and manager['id'] != finisher['id']:
        return manager
    return None
