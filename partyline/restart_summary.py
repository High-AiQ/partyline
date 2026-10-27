"""Human-readable outcomes of sequential recovery."""

from collections import Counter


def format_summary(ready, failed, slow, unconfirmed, skipped, failure_details):
    summary = f"{len(ready)} ready"
    summary += f", {len(slow)} still settling" if slow else ""
    summary += f", {len(failed)} failed"
    if failure_details:
        summary += f" ({'; '.join(failure_details)})"
    if skipped:
        reasons = ", ".join(f"{count} {reason}" for reason, count in Counter(skipped).items())
        summary += f", {len(skipped)} skipped ({reasons})"
    if unconfirmed:
        summary += f", {len(unconfirmed)} continuation unconfirmed"
    return summary
