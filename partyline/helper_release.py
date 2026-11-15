"""Server comparison, including helpers which used the legacy server version numbering."""
from partyline_helper import __version__
from partyline_helper.update_release import installer_info, parse, RELEASES_URL  # noqa: F401


def update_available(helper_version, server_version=None) -> bool:
    helper, server = parse(helper_version), parse(server_version or __version__)
    return helper is not None and server is not None and (helper[0] >= 2 or helper < server)
