# Message pins

Pins belong to one line and refer to messages by their database ID. People can
create and remove pins and set an optional alias of up to 120 characters.
Machines can read pins on lines their credentials can read, but pin writes are
people-only. A pin remains visible as unavailable if its source message is
missing; removing the pin still works. Purging a line removes its pins.

The sidebar loads pins from `GET /api/conversations/{id}/pins`. The
`pins_changed` WebSocket event carries the updated list to tabs open on that
line. `GET /api/conversations/{id}/messages/around?message_id=…&limit=…`
returns the target and a bounded window on either side; `limit` is clamped to
1–50 messages on each side. The browser merges that window by message ID,
preserving the live tail and the normal older-history cursor.
