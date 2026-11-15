"""Element identities bind the provider runtime identity to its control-view path."""
import hashlib
import json

ID_LENGTH = 16  # hex digits: short enough to print per element, ample for one window's nodes


def element_id(provider, node, path, runtime=None):
    runtime = provider.runtime_id(node) if runtime is None else runtime
    payload = json.dumps([list(runtime), path], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:ID_LENGTH]
