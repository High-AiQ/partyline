"""Handover tools are available to captains and offered participants."""
from urllib.parse import quote

from .validation import validate_arguments


def tool_list(state):
    if state.get('kind') != 'machine':
        return []
    ref = {'type': 'string', 'minLength': 1, 'maxLength': 80}
    result = []
    for name, tail, description in (
        ('offer_handover', 'offer', 'Offer captainship to a live attachment on your line, attached for '
         '60 seconds. A pending restart request must be resolved or cancelled first. Reference files, '
         'directories, notes, worktrees and report IDs in the required debrief (maximum 4000 characters).'),
        ('cancel_handover', 'cancel', 'Cancel your pending handover offer.'),
        ('accept_handover', 'accept', 'Accept an offer addressed to your attachment. A pending restart '
         'request from the old captain must be resolved or cancelled first.'),
        ('complete_handover', 'complete', 'Confirm the accepted handover. Both old and new captains must '
         'confirm before the old captain is detached. A person may resolve a timed-out handover.')):
        properties = ({'attachment_id': ref, 'debrief': {'type': 'string', 'minLength': 1, 'maxLength': 4000}}
                      if tail == 'offer' else {'handover_id': ref})
        result.append({'name': name, 'description': description, 'inputSchema': {
            'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}})
    return result


def call(client, name, args, state):
    tool = next(item for item in tool_list(state) if item['name'] == name)
    if name == 'offer_handover' and (not args.get('debrief') or not str(args['debrief']).strip()):
        raise ValueError('A debrief is required. Reference files and directories '
                         'instead of explaining inline.')
    if name == 'offer_handover' and isinstance(args.get('debrief'), str) and len(args['debrief']) > 4000:
        raise ValueError(f"Debrief is {len(args['debrief'])} characters; maximum 4000. "
                         "Reference files and directories instead of explaining everything inline.")
    validate_arguments(tool['inputSchema'], args)
    tail = name.removesuffix('_handover')
    return client.request('POST', f"/api/conversations/{quote(client.home, safe='')}/handover/{tail}", args)
