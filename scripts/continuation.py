"""Did every resumed process actually receive its continuation?

A restart is only recovery if the processes come back *and are told what to
continue*. Those are separate claims, and on the night this was written the
second one was false for every codex process while every automated signal said
otherwise.

Three oracles were tried first and all three lied:

  - **the database cursor** said delivered — it records the intent to deliver,
    which is the bug itself;
  - **the terminal screen** said lost for every process including one that
    demonstrably received its debrief, because the text had scrolled;
  - **a plain transcript grep** said two of three received it — both hits were
    the investigation's own tool traffic, one of them the very command that
    *created* the plan.

Only a person peeking into four terminals got it right. That is the thing this
script exists to replace.

So the oracle here is deliberately narrow: a phrase counts as received only
when it appears in a record the process's own CLI classifies as *input*, never
in tool calls or their output. When the investigation and the thing under
investigation share a transcript, the oracle has to be one the investigation
cannot forge.

    uv run python -m scripts.continuation --nonce a1b2c3d4

A `--nonce` is strongly preferred: a random token cannot reach a transcript by
any route except delivery, whereas ordinary debrief prose can be quoted,
dumped, or passed on a command line by an agent looking into the problem.

That claim needed narrowing after Restart #7, in two directions:

*Nonce alone is not unforgeable.* The initiator announces the nonce in the room
before arming, so by the time the restart happens every participant's
transcript already contains it as a genuine, user-role chat message. A receipt
therefore requires the coordinator's own `Continuation debrief:` marker in the
same record — not merely the number. On live data this cut the counts from 7-8
to 2 per process; the surplus was everyone discussing the plan.

*Role alone does not mean "said to".* Claude addresses tool results to `user`
as well, so an agent grepping its own transcript for the nonce produces a
`type=user` record containing marker and nonce both. The content must be text
rather than a `tool_result` block, or the act of looking for a receipt creates
one.

**Remaining assumption**, stated rather than hidden: this is a *structural*
test, not a temporal one. It cannot distinguish the current restart's debrief
from an identically-marked debrief carrying the same nonce in an earlier
generation of the same transcript. A fresh nonce per restart is what closes
that gap, and it is the caller's responsibility. An `--after` cutoff would be
strictly stronger; it is not implemented because a timestamp key common to
every supported CLI has not been verified, and a cutoff that silently fails to
parse one format would re-create exactly the blind spot this file exists to
report.
"""

from __future__ import annotations

import json
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path

# Record types a CLI uses for "this was said to the model". A partyline wake
# arrives as one of these; verified against 139 known-good deliveries.
DELIVERED_TYPES = {"user_message", "message"}
# The coordinator's own wording, from `ReattachCoordinator` in reattach.py. A
# nonce is only unforgeable while nobody says it out loud — and the initiator
# announces it in the room before arming, so by the time the restart happens
# every participant's transcript already contains it as ordinary chat. Counting
# those would let a restart that delivered nothing still report a receipt.
# Requiring the marker in the same record asks the narrower question that was
# always meant: was this process handed the debrief, not did it hear the number.
DEBRIEF_MARKER = "Continuation debrief:"
# Record types that carry the investigation's own traffic. A hit here proves
# somebody looked at the problem, not that anybody was told anything.
ARTEFACT_TYPES = {
    "custom_tool_call", "custom_tool_call_output",
    "function_call", "function_call_output",
}


@dataclass(frozen=True)
class Receipt:
    """What one process's own transcript says it was actually told."""

    name: str
    delivered: int
    artefacts: int

    @property
    def received(self) -> bool:
        return self.delivered > 0

    def describe(self) -> str:
        mark = "✓" if self.received else "✗"
        detail = f"delivered={self.delivered}"
        if self.artefacts:
            # Worth showing: this is exactly the count a naive grep would have
            # reported as success.
            detail += f"  (ignored {self.artefacts} investigation artefact(s))"
        return f"  {mark} {self.name:8} {detail}"


def is_input_record(record: dict, phrase: str) -> bool:
    """Was `phrase` said *to* this process, rather than logged around it?

    `role` is checked as well as `type` because a CLI may mirror one delivery
    into two shapes; either is evidence, and neither can be produced by a tool
    call, which is the only confound that matters here.
    """
    payload = record.get("payload", record)
    if not isinstance(payload, dict):
        return False
    kind = payload.get("type")
    if kind in ARTEFACT_TYPES:
        return False
    if kind not in DELIVERED_TYPES and not is_spoken_input(payload):
        return False
    body = json.dumps(payload)
    return phrase in body and DEBRIEF_MARKER in body


SPOKEN_BLOCKS = {"text", "input_text"}


def is_spoken_input(payload: dict) -> bool:
    """Was this text *said to* the model, or handed back to it by a tool?

    Claude types a tool result `user` as well, because that is who the result
    is addressed to — so role alone cannot separate "the coordinator woke this
    process" from "this process ran `grep` for the nonce and got a hit". The
    investigation into whether a receipt exists would otherwise manufacture the
    receipt, which is precisely the confound the nonce was introduced to kill.

    Speech is a string, or blocks of text. A `tool_result` block is not speech.
    """
    if speaker(payload) != "user":
        return False
    content = (payload.get("message") or payload).get("content")
    if isinstance(content, str):
        return True
    if not isinstance(content, list):
        return False
    return any(isinstance(block, dict) and block.get("type") in SPOKEN_BLOCKS
               for block in content)


def speaker(payload: dict) -> str | None:
    """Who said this, whatever shape the CLI records it in.

    Codex puts `role` at the top level; Claude nests it under `message` and
    types the record `user`. Reading only the top level made every Claude
    receipt invisible, so the oracle reported CONTINUATION LOST for a process
    whose transcript plainly contained the debrief — condemning a restart that
    had in fact worked. An oracle that cannot see one participant's transcript
    is not a stricter oracle; it is a broken one.
    """
    role = payload.get("role")
    if isinstance(role, str):
        return role
    message = payload.get("message")
    return message.get("role") if isinstance(message, dict) else None


def read_receipt(name: str, transcript: Path, phrase: str) -> Receipt:
    delivered = artefacts = 0
    with transcript.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if phrase not in line:
                continue  # cheap pre-filter; the real test is the record shape
            try:
                record = json.loads(line)
            except ValueError:
                continue
            payload = record.get("payload", record)
            if isinstance(payload, dict) and payload.get("type") in ARTEFACT_TYPES:
                artefacts += 1
            elif is_input_record(record, phrase):
                delivered += 1
    return Receipt(name=name, delivered=delivered, artefacts=artefacts)


def find_transcript(session_id: str, roots: list[Path]) -> Path | None:
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob(f"*{session_id}*.jsonl"):
            return path
    return None


def report(receipts: list[Receipt]) -> int:
    for receipt in receipts:
        print(receipt.describe())
    missing = [receipt.name for receipt in receipts if not receipt.received]
    print()
    if not receipts:
        print("no resumed processes with transcripts to check")
        return 2
    if missing:
        print(f"CONTINUATION LOST for {', '.join(missing)}")
        return 1
    print(f"CONTINUATION DELIVERED to all {len(receipts)} process(es)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--nonce", help="the unique token planted in this restart's debrief")
    parser.add_argument("--phrase", help="literal text to look for, if no nonce was planted")
    parser.add_argument("--sessions", nargs="+", metavar="NAME=SESSION_ID", required=True)
    parser.add_argument("--root", action="append", default=[],
                        help="where transcripts live (repeatable)")
    args = parser.parse_args(argv)

    phrase = args.nonce or args.phrase
    if not phrase:
        parser.error("give --nonce (preferred) or --phrase")
    if not args.nonce:
        print("! no --nonce: ordinary prose can reach a transcript by being quoted,\n"
              "  so a positive result here is weaker than it looks.\n")

    roots = [Path(root).expanduser() for root in args.root] or [
        Path.home() / ".codex" / "sessions",
        Path.home() / ".claude" / "projects",
    ]

    receipts = []
    for pair in args.sessions:
        name, _, session_id = pair.partition("=")
        transcript = find_transcript(session_id, roots)
        if transcript is None:
            print(f"  ? {name:8} no transcript found for {session_id}")
            continue
        receipts.append(read_receipt(name, transcript, phrase))
    return report(receipts)


if __name__ == "__main__":
    raise SystemExit(main())
