"""Bodies the real docker CLI sent (scripts/capture_docker_create.py) must pass the create checks."""

import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from partyline import docker_plan
from partyline.docker_body import canonical_create, network_refs
from partyline.docker_policy import Denied

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "docker_create").glob("*.json"))


async def bridge(method, path, *args, **kwargs):
    return 200, {"Driver": "bridge"}


def create_checks(body):
    fresh, problems = canonical_create(body, set(), [], 86400)
    asyncio.run(docker_plan.check_networks(network_refs(fresh["HostConfig"], fresh.get("NetworkingConfig"))))
    return problems


class CliFixtureTests(unittest.TestCase):
    def test_every_captured_create_passes(self):
        self.assertTrue(FIXTURES, "run scripts/capture_docker_create.py")
        for path in FIXTURES:
            record = json.loads(path.read_text())
            with self.subTest(case=record["case"], cli=record["cli"]), \
                    patch.object(docker_plan.docker_api, "request", bridge):
                self.assertEqual(create_checks(record["body"]), [])

    def test_endpoint_defaults_are_typed(self):
        record = json.loads(next(p for p in FIXTURES if "full-managed" in p.name).read_text())
        endpoint = next(iter(record["body"]["NetworkingConfig"]["EndpointsConfig"].values()))
        self.assertEqual((endpoint["GwPriority"], endpoint["DNSNames"]), (0, None))
        for key, value in (("GwPriority", "high"), ("GwPriority", True), ("DNSNames", "web"),
                           ("DNSNames", [1]), ("DNSNames", ["bad name;"])):
            body = json.loads(json.dumps(record["body"]))
            next(iter(body["NetworkingConfig"]["EndpointsConfig"].values()))[key] = value
            with self.subTest(key=key, value=value):
                self.assertIn("malformed-body", [p[0] for p in canonical_create(body, set(), [], 86400)[1]])
        body = json.loads(json.dumps(record["body"]))
        next(iter(body["NetworkingConfig"]["EndpointsConfig"].values()))["DNSNames"] = ["web", "web.local"]
        self.assertEqual(canonical_create(body, set(), [], 86400)[1], [])

    def test_a_non_bridge_network_is_still_refused(self):
        async def overlay(*args, **kwargs):
            return 200, {"Driver": "overlay"}

        record = next(json.loads(p.read_text()) for p in FIXTURES if "bridge-network" in p.name)
        with patch.object(docker_plan.docker_api, "request", overlay), self.assertRaises(Denied):
            create_checks(record["body"])
