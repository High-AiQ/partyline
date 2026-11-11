"""The runtime callbacks an adapter holds, timed at the one place they are stored.

Everything an adapter hands to the runtime — speech, status, session ids, and the
callbacks in its attachment dict — passes through here, so a slow dispatch is
recorded whichever transcript path produced it, and a new adapter needs no timers.
"""

from partyline import op_timing


def _timed(key):
    slot = f"_timed_{key}"

    def get(self):
        return getattr(self, slot, None)

    def put(self, fn):
        setattr(self, slot, op_timing.callback(self.att, key, fn))

    return property(get, put)


class TimedCallbacks:
    _post_to_chat = _timed("post")
    on_status = _timed("on_status")
    on_cli_session = _timed("on_cli_session")
