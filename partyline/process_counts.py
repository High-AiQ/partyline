"""Shared policy for process counts and admission reservations."""


def counts(row: dict) -> bool:
    return row["adapter"] != "raw" or bool(row.get("counts_toward_total"))
