"""Element identities bind the provider runtime identity to its control-view path."""
import hashlib
import json


def element_id(provider, node, path):
    payload = json.dumps([list(provider.runtime_id(node)), path], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
