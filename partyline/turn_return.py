"""The return path: a turn a process asked for, that answered no process, bounces back.

Inside one harness, delegated work returns to its caller by construction: a
sub-agent's result is the caller's next input. Across harnesses on a line,
the only return was the worker remembering to ``@mention`` whoever asked. It
forgot constantly — a turn ends with "committed abc, tree clean", a routine
report with ``notify:false``, or a mention aimed at a handle on another
line — and the lead, whose goal it was, was never woken. Every prose reminder
and a fifteen-minute heartbeat failed to close that gap, because the lead
still had to *notice* silence. This closes it structurally.

The server already observes both halves. A wake digest says which processes
mentioned this one (its *requesters*); the harness receipt says when the
turn ended; the process's own posts say whether it handed off to anyone.
When a turn ends and nothing it said reached a live process, each requester
is rung with a short notice carrying what was last said, on the requester's
own line. The lead is woken by the fact that matters — "your worker
finished and the ball is with nobody" — not by a clock.

What keeps this a return rather than a second source of noise:

* The notice is a system message. It never counts as a requester, so a
  turn woken *only* by a notice owes nothing when it ends — one explicit
  wake yields at most one implicit reply, and no chain can run on its own.
* Handing off clears only the requesters that speech actually reaches.
  Delegating downward leaves an upstream requester owed; a later turn that
  addresses them clears them. This turn sends no "finished" notice while
  the work is moving, and a deferred notice is superseded by the hand-off.
* A manager wrapping up to a person does not bounce back to its
  implementers. The lead's terminal turn — "@operator the PR is up" — is the
  one case where a requester's silence is correct, so a manager's turn
  returns only to requesters that are managers themselves.
* Only a harness-reported ending returns. An exit or detach is announced
  on the line already and a fleet restart would ring every lead at once.
* Humans read their own line, so a human requester is told only when it
  asked from another line — an unrouted notice where it was typed.
* A request is a message *for* this process, not one that talks about it.
  "@lead please have @worker build it" rings worker too — every mention
  rings — but only lead's turn owes anything: the leading run of mentions
  names the addressees (`mentions.addressees`). Without this, every status
  line naming a worker made its author a requester, and the room filled
  with returns about turns nobody had asked for.
* A silent turn after an addressed wake is unanswered: each requester is
  told it said nothing, and a child captain also tells the parent line's
  captain. Words said before the wake are not this turn's words. A turn
  woken only by a notice still owes nothing, and the notice names the
  finisher without a sigil, so it never rings the finisher.
* A return rings only a requester that is waiting. A captain that acks
  "@lead on it" and keeps working has not stopped for an answer; ringing
  it with the lead's "holding" interrupted real work on the live run, and
  it answered "still holding" — one wasted turn per courtesy. So a return
  owed to a requester that is mid-turn is deferred until that turn ends,
  and dropped if the requester handed off to anyone in the meantime: its
  next signal supersedes the stale one.
* The decision waits a moment after the receipt. A harness reports the end
  of a turn through one channel and its last words through another (the
  transcript tail), and on the first live trial the receipt won by a few
  hundred milliseconds: the notice quoted "on it" while the findings landed
  one message later. The last words are the notice's payload, so the return
  is settled after a short grace, and speech that arrives inside it is
  quoted — or, if it hands off, cancels the notice.
* A return waits for ten seconds without pty output, with a twenty-minute
  cap for a process whose terminal keeps changing.
"""

from __future__ import annotations

from .return_path import ReturnPath

__all__ = ["ReturnPath"]
