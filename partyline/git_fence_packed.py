"""Merge packed refs without replacing a shared mirror's protected branches."""

import os


def _object_id(value: str) -> bool:
    return len(value) in (40, 64) and all(char in "0123456789abcdefABCDEF" for char in value)


def _entries(root: str) -> tuple[list[str], dict[str, str]] | None:
    path = os.path.join(root, "packed-refs")
    if not os.path.isfile(path) or os.path.islink(path):
        return None
    headers, entries = [], {}
    previous = None
    with open(path, encoding="utf-8") as file:
        for raw in file:
            line = raw.strip()
            if line.startswith("#"):
                headers.append(line + "\n")
                previous = None
            elif line.startswith("^"):
                if previous is not None and _object_id(line[1:]):
                    entries[previous] += line + "\n"
            else:
                previous = None
                fields = line.split()
                if (len(fields) == 2 and _object_id(fields[0])
                        and fields[1].startswith("refs/")):
                    previous = fields[1]
                    entries[previous] = f"{fields[0]} {previous}\n"
    return headers, entries


def merged_packed_refs(common: str, mirror: str, protected: set[str]) -> str | None:
    """Keep mirror protected entries, refresh the rest, retaining peeled records."""
    real, private = _entries(common), _entries(mirror)
    if real is None:
        return None if private is None else ''.join(private[0] + list(private[1].values()))
    headers, entries = real
    private_entries = private[1] if private else {}
    for ref in protected:
        entries.pop(ref, None)
        if ref in private_entries:
            entries[ref] = private_entries[ref]
    for ref, entry in private_entries.items():
        if ref.startswith("refs/partyline/shared/"):
            entries[ref] = entry
    return ''.join(headers + [entries[ref] for ref in sorted(entries)])
