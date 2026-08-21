"""Guards for the scheme partyline puts in the URLs it hands to processes.

The absolute media URLs in a message body are built from the incoming request.
Behind a TLS-terminating proxy the request arrives as plain HTTP, so unless the
proxy is trusted the URL goes out as ``http://``, the proxy answers ``301``, and
a reader that does not follow redirects saves the redirect notice under the
filename it asked for. That failure reports success and produces a file, which
is why it needs an executable guard rather than a warning in prose.
"""

import asyncio
import os
import unittest

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from partyline.adapters.briefing import BRIEFING
from partyline.bind import forwarded_allow_ips, uvicorn_config


def _scheme_seen_by_app(trusted: str, client_host: str) -> str:
    """The scheme an ASGI app sees for a proxied request, given a trust list."""
    seen = {}

    async def app(scope, receive, send):
        seen["scheme"] = scope["scheme"]

    scope = {
        "type": "http",
        "scheme": "http",
        "client": (client_host, 51234),
        "headers": [(b"x-forwarded-proto", b"https"), (b"x-forwarded-for", client_host.encode())],
    }
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=trusted)
    asyncio.run(wrapped(scope, None, None))
    return seen["scheme"]


class ForwardedAllowIpsTest(unittest.TestCase):
    def test_default_is_loopback_only(self):
        self.assertEqual(forwarded_allow_ips({}), "127.0.0.1")

    def test_blank_value_falls_back_rather_than_trusting_nothing(self):
        self.assertEqual(forwarded_allow_ips({"PARTYLINE_FORWARDED_ALLOW_IPS": "  "}), "127.0.0.1")

    def test_environment_names_the_proxy(self):
        self.assertEqual(
            forwarded_allow_ips({"PARTYLINE_FORWARDED_ALLOW_IPS": " 192.168.1.10 "}),
            "192.168.1.10",
        )

    def test_config_carries_proxy_trust_into_uvicorn(self):
        config = uvicorn_config(
            object(), "0.0.0.0", 8642, {"PARTYLINE_FORWARDED_ALLOW_IPS": "192.168.1.10"}
        )
        self.assertTrue(config.proxy_headers)
        self.assertEqual(config.forwarded_allow_ips, "192.168.1.10")
        self.assertEqual((config.host, config.port), ("0.0.0.0", 8642))

    def test_config_reads_the_real_environment_when_none_is_passed(self):
        os.environ["PARTYLINE_FORWARDED_ALLOW_IPS"] = "10.0.0.5"
        try:
            self.assertEqual(
                uvicorn_config(object(), "127.0.0.1", 8642).forwarded_allow_ips, "10.0.0.5"
            )
        finally:
            del os.environ["PARTYLINE_FORWARDED_ALLOW_IPS"]


class ForwardedSchemeTest(unittest.TestCase):
    """The regression itself: this is what decides http:// versus https://."""

    def test_untrusted_proxy_leaves_the_scheme_wrong(self):
        # The old behaviour, pinned so the fix cannot silently revert: a proxy
        # on another host is not the loopback, so its X-Forwarded-Proto is
        # ignored and every absolute URL is built as http.
        self.assertEqual(_scheme_seen_by_app(forwarded_allow_ips({}), "192.168.1.10"), "http")

    def test_named_proxy_makes_the_scheme_honest(self):
        trusted = forwarded_allow_ips({"PARTYLINE_FORWARDED_ALLOW_IPS": "192.168.1.10"})
        self.assertEqual(_scheme_seen_by_app(trusted, "192.168.1.10"), "https")


class BriefingRedirectTest(unittest.TestCase):
    def test_briefing_teaches_following_redirects_when_fetching_a_file(self):
        self.assertIn("-L", BRIEFING)
        self.assertIn("redirect", BRIEFING)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
