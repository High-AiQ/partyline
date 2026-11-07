"""The helper's own version: installed metadata (uvx, checkout, or the frozen exe's bundled copy)."""
from importlib.metadata import PackageNotFoundError, version

UNKNOWN = "unknown"


def helper_version(lookup=None):
    """Read distribution metadata without importing server modules; the server ignores `unknown`."""
    try:
        return (lookup or version)("partyline")
    except PackageNotFoundError:
        return UNKNOWN
