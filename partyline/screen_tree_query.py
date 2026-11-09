"""Query terms: `a|b` means either; `=x` or `^x$` match the whole text; `^x` and `x$` match an end."""


def terms(query):
    found = []
    for part in (query or "").split("|"):
        part = part.strip().lower()
        whole = part.startswith("=")
        start, end = part.startswith("^"), part.endswith("$") and len(part) > 1
        part = part[1:] if whole or start else part
        part = part[:-1] if end and not whole else part
        if part.strip() or whole:
            found.append((part.strip() if whole else part, whole or (start and end), start, end))
    return found


def matcher(query):
    """A function saying whether a text matches any term, or None when the query has no terms."""
    wanted = terms(query)
    if not wanted:
        return None

    def matches(text):
        text = text.lower()
        for word, whole, start, end in wanted:
            if (text == word if whole else text.startswith(word) if start else text.endswith(word)
                    if end else word in text):
                return True
        return False
    return matches
