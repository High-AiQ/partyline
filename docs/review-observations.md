# Structured review observations

Partyline stores a review decision as a first-class immutable object. It is not
a chat message, reaction, reply, or prose convention. The API serves an
external evidence producer, so this page is a closed wire contract.

## Write

`POST /api/conversations/{conv_id}/review-decisions` accepts exactly:

```json
{"presentation_message_id":10650,"decision":"approve"}
```

Only an authenticated human may write. The message must already belong to the
named, unarchived conversation. Partyline derives the reviewer from the
credential, creates the source UUID and timestamp itself, and permits exactly
one immutable decision per human and presentation. A second write returns 409.

## Read

`GET /api/conversations/{conv_id}/review-observations?presentation_message_id=10650`
requires ordinary Partyline authentication, including a machine credential.
It has no trailing-slash route. A real binding with no decisions returns 200
with an empty list; a missing conversation or presentation binding returns 404.

The response has exactly this shape, with no pagination or display fields:

```json
{"observations":[{
  "conversation_id":"line-id",
  "presentation_message_id":"10650",
  "evidence_kind":"decision",
  "evidence_ref":"decision:source-uuid",
  "sender_id":"partyline-user-42",
  "decision":"approve",
  "observed_at":"2026-09-02T22:15:00+00:00"
}]}
```

`sender_id` uses the immutable account primary key, not a handle. The source
locator names the decision row, not the presentation. `observed_at` is the
stored server timestamp rendered with a UTC offset. Archive preserves
decisions; permanent purge is the explicit authority-destruction boundary and
removes them with the line.
