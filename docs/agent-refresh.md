# Refresh an agent on the same line

A conversation retains its history independently of a process session. **Resume** reopens
that session; **Start fresh** creates a new attachment and CLI session under the same handle.
**Remove from roster** forgets a stopped attachment and its credentials, without deleting chat
or vendor-owned transcript files. Removal also removes that attachment from a saved restart plan.

| Action | Result |
| --- | --- |
| Detach | Stop the process; keep its card and resumable session. |
| Resume | Continue the saved session with its existing context. |
| Start fresh | Replace a stopped card with a new identity, token, and session. Earlier chat is excluded by default. |
| Remove from roster | Forget the stopped card and its session pointer after confirmation. |

## Continue work with fresh context

1. Finish and record outstanding provider calls. Do not refresh while their outcome is unknown.
2. Write a compact checkpoint in the working repository at
   `docs/agent-checkpoints/<book-or-project-id>/<task-id>.md`. Include the task, authoritative
   artifact/version links, acceptance state, pending work, the next action, and the last message
   id incorporated. Link to the actual ledger rather than trusting a copied spend total.
3. Detach. Choose **Start fresh**, supply the checkpoint pointer and its last incorporated message
   id. Partyline creates a new identity and keeps later messages pending through the normal wake
   delivery mechanism. Do not manually fetch the same messages again.
4. The replacement reads the checkpoint, verifies the referenced state, and announces readiness.
   Mention it to deliver retained messages; it then records its new attachment id in its task
   claim/receipt before continuing. A completed worker assignment is
   delivery evidence, not product acceptance.

A checkpoint without a message id provides continuation instructions but starts chat delivery at
fresh-start time. With neither field, **Start fresh** is a blank session receiving the normal
briefing and topic. It does not copy its predecessor's transcript or delivered-message history.
Messages arriving during startup remain after the new cursor. No conversation rotation is needed.

Use the attachment's delivery cursor as a candidate checkpoint boundary only after incorporating
all delivered messages. Do not substitute the conversation's newest message id: it can include
instructions the outgoing agent has never received.

The task board currently identifies assignees by handle; record the replacement attachment id in
its checkpoint/claim receipt rather than assuming that reusing a handle proves process identity.

## HTTP contract

All requests require the usual Authorization bearer header. Fresh/remove are local process-control
endpoints, like command editing, and refuse live processes. Neither implicitly kills a running job.

- `POST /api/attachments/<id>/fresh` accepts an optional JSON body:
  `{"checkpoint":"docs/agent-checkpoints/project/task.md","after_message_id":123}`.
  The boundary must identify a positive message id on this line and requires a checkpoint.
  Retained history is limited to 100 messages and 32,000 characters at refresh time. A stale
  checkpoint is refused before spawning; no instructions are silently dropped.
  Returns the new attachment. If startup fails, the old stopped session remains available. A possibly live replacement
  whose cleanup failed remains tracked for an explicit detach; its row is never silently erased.
- `DELETE /api/attachments/<id>/record` removes a stopped card and revokes its token.
- Removal broadcasts `attachment_removed` with `attachment_id` and `conversation_id`;
  fresh also broadcasts the new `attachment` state.

The cursor records delivery, not proof that an agent understood every instruction. Existing
transcript adapters retain their receipt checks; retrying uncertain provider work still requires
checking the provider and ledger. A restart during refresh may leave both stopped cards visible;
inspect them before choosing which session to keep.

## Verification

`tests/test_attachment_lifecycle.py` checks a twenty-message history followed by instructions during
the detach gap and startup: only messages after the checkpoint boundary reach the replacement,
and a second delivery does not repeat them. It also checks new credentials, no resumed session,
spawn failure recovery, concurrent resume exclusion, stopped-only removal, and preserved chat.
Tests use a temporary database and fake adapters, never a live coding CLI or the cockpit database.
