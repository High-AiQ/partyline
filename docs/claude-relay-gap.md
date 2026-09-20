# Claude relay gap

Status: evidence and design note only (2026-09-20). No fallback is implemented by
this note.

## What the transcript evidence says

The Claude adapter tails JSONL in file order. It does not follow or validate
`parentUuid` or `logicalParentUuid`, so a post-compaction parent-chain rewrite cannot,
by itself, make the adapter skip later records. The compaction filter excludes the
one compaction-boundary system record; it does not exclude the records that follow it.

In the observed session, the boundary was JSONL line 4796
(`2026-09-19T21:37:33.164Z`). Its `logicalParentUuid` points before the boundary and
its `parentUuid` is null. The later transcript contains ordinary, non-sidechain
assistant text at lines 4834, 4882, 4913, 4993, and 5041, and the current handler
would relay each of those records.

The two missing prefixes, `Not at all, Greg` and `Luna's pruning is correct`, occur
only inside later Bash `tool_use.input.command` diagnostic commands. They do not occur
in an assistant `text` block or another structured speech-bearing record. A search of
the Claude project transcripts found no second session or sidechain containing either
phrase. The missing rendered model text therefore points strongly to Claude Code
2.1.276 not persisting those segments, rather than Partyline filtering persisted
records. The surrounding records are ordinary non-sidechain `thinking`, `tool_use`,
and `tool_result` entries; even the literal UI sentence about a user sending a
message while work was in progress is absent except in a later diagnostic command.
Message `27864` does appear inside the tool-result content at line 4915, but the
assistant reply to it is not present in any later assistant `text` record.

This evidence does not prove that every missing reply has the same cause. It proves
that a warning inferred from a tool-use record would be unsafe, and that PTY screen
scraping cannot fill the gap: structured transcripts are the speech source.

## The Stop-hook lead

The captured Claude Stop fixture, `tests/fixtures/hooks/claude_stop.json`, contains a
`last_assistant_message` field. The current `HookPayload` deliberately permits vendor
extras but does not model that field, and `handle_hook` currently uses the hook for
turn presence and attention only. No Stop-hook speech fallback exists yet.

If this lead is pursued, the hook must be treated as corroborating structured input,
not as proof that it can recover a complete transcript. Claude may provide only the
final assistant message at Stop, so it cannot recover every intermediate commentary
segment. It also cannot recover a message that Claude did not put in the hook payload.

Two payload semantics remain unresolved and require raw-payload fixtures and probes:

- When visible assistant speech precedes a tool call, does
  `last_assistant_message` contain all visible speech for that turn, only the final
  segment, or no message until the turn ends?
- When a user message is injected mid-turn, does the field contain the assistant
  speech before the injection, the final assistant speech after the turn resumes, or
  an empty/other value?

Those answers must be observed alongside the JSONL records. They cannot be inferred
from the field name, and a fallback must not assume either ordering or payload shape.

## Required race and dedup design before implementation

The Stop hook and JSONL tail are concurrent observations of one turn. A safe fallback
needs a short transcript grace window at the turn boundary and deduplication scoped to
that turn:

1. If JSONL speech arrives first, record its stable transcript identity and do not
   later repost the same final message when Stop supplies `last_assistant_message`.
2. If Stop arrives first, retain its candidate only through the short grace window;
   let a transcript record win if it appears, otherwise emit the candidate once after
   the window. The candidate must be tied to the current attachment/session and turn,
   not matched globally by body alone.
3. If the final message was already relayed before Stop, the Stop payload is a no-op.

The exact turn identity and the stable comparison between a hook candidate and a
transcript record still need to be specified and tested. A content-only global
deduplication set would suppress legitimate repeated replies, while immediate hook
delivery would race the tail and duplicate speech. The grace interval must be bounded
and must not block ordinary transcript delivery indefinitely.

## Proposed regression fixtures

These are fixtures to write before any fallback is treated as proven:

1. A sanitized post-compaction JSONL fixture containing the real boundary and
   attachment-chain shapes. Assert that later ordinary assistant text is relayed even
   though the parent chain changes.
2. A sanitized missing-turn fixture containing `thinking`, `tool_use`, and
   `tool_result`, with no assistant `text`. This is a negative control: the parser
   must not invent speech from tool inputs or emit a generic gap warning.
3. An extended Claude Stop-hook contract fixture covering both payload semantics and
   all three orderings: capture what `last_assistant_message` contains when visible
   assistant speech precedes a tool call; capture what it contains when a user message
   is injected mid-turn; then prove that the transcript arriving first does not
   duplicate, the hook arriving first emits one delayed fallback only when the
   transcript does not arrive during the grace window, and a Stop payload whose final
   message was already relayed produces no duplicate. The existing fixture supplies
   the field shape, but these payload and race cases are not yet implemented or
   proven.

Until those fixtures and the race behavior pass, the accurate product statement is
that the Stop hook is a promising lead for the final assistant message, not a Claude
reply-loss fix.
