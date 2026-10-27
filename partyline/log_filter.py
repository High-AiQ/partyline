"""Keep request query strings out of Uvicorn's access and WebSocket logs."""

import logging


class AccessQueryFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn logs WebSocket handshakes on uvicorn.error and HTTP requests
        # on uvicorn.access; both pass the request target as a separate argument.
        if not isinstance(record.args, tuple):
            return True
        if record.name == "uvicorn.error" and record.msg in (
            '%s - "WebSocket %s" [accepted]',
            '%s - "WebSocket %s" 403',
            '%s - "WebSocket %s" %d',
        ):
            index = 1
        elif record.name == "uvicorn.access" and record.msg == '%s - "%s %s HTTP/%s" %d':
            index = 2
        else:
            return True
        args = list(record.args)
        if len(args) > index and isinstance(args[index], str):
            args[index] = args[index].split("?", 1)[0]
            record.args = tuple(args)
        return True
