"""Every bundled adapter must declare and pin its delivery-proof contract."""

from __future__ import annotations

import asyncio
import importlib
import json
import tomllib
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from partyline.adapters.bundled.grok.transcript import user_input
from partyline.adapters.bundled.grok.wake_receipts import WakeReceipts
from partyline.adapters.bundled.opencode.wakes import WakeSettlement
from partyline.adapters.jsonl_receipts import JsonlPasteReceipts, _user_text

ROOT = Path(__file__).parents[1]
BUNDLED = ROOT / "partyline/adapters/bundled"
PROOF_SHAPES = {"transcript-user-record", "receipt-boundary", "none-with-reason"}
TRANSCRIPT_FIXTURE_ADAPTERS = {
    "antigravity", "claude", "codex", "grok", "opencode", "opencode-v2"
}
NO_LOCAL_FIXTURE_ADAPTERS = {"cursor", "deepseek", "pi"}


class DeliveryProofConformanceTest(unittest.TestCase):
    def test_each_bundled_adapter_declares_a_tested_delivery_proof(self):
        manifests = sorted(BUNDLED.glob("*/adapter.toml"))
        self.assertTrue(manifests)
        for manifest_path in manifests:
            with self.subTest(adapter=manifest_path.parent.name):
                with manifest_path.open("rb") as stream:
                    manifest = tomllib.load(stream)["adapter"]
                proof = manifest.get("delivery_proof")
                self.assertIn(proof, PROOF_SHAPES)
                test_ref = manifest.get("delivery_proof_test", "")
                test_path, separator, test_name = test_ref.partition("::")
                self.assertTrue(separator and test_name)
                source_path = ROOT / test_path
                self.assertTrue(source_path.is_file())
                module_name = test_path[:-3].replace("/", ".")
                module = importlib.import_module(module_name)
                cases = [
                    case for case in vars(module).values()
                    if isinstance(case, type) and issubclass(case, unittest.TestCase)
                    and hasattr(case, test_name)
                ]
                suite = unittest.TestSuite(
                    unittest.defaultTestLoader.loadTestsFromName(
                        f"{module_name}.{case.__name__}.{test_name}"
                    ) for case in cases
                )
                self.assertGreater(suite.countTestCases(), 0, "test ref must resolve")
                result = unittest.TestResult()
                suite.run(result)
                self.assertEqual(result.errors, [], "declared proof test errored")
                self.assertEqual(result.failures, [], "declared proof test failed")
                if proof == "none-with-reason":
                    self.assertTrue(manifest.get("delivery_proof_reason", "").strip())
                    continue

                capabilities = manifest.get("capabilities", {})
                if proof == "transcript-user-record":
                    self.assertTrue(capabilities.get("transcript"))
                    fixture_dir = ROOT / "tests/fixtures/transcripts" / manifest_path.parent.name
                    fixture_paths = sorted(fixture_dir.glob("*.jsonl"))
                    if manifest.get("delivery_proof_fixture") == "none-local":
                        self.assertIn(manifest_path.parent.name, NO_LOCAL_FIXTURE_ADAPTERS)
                        self.assertFalse(fixture_paths)
                        continue
                    self.assertTrue(fixture_paths, "transcript proof needs captured fixture records")
                    if manifest_path.parent.name in TRANSCRIPT_FIXTURE_ADAPTERS:
                        provenance = fixture_dir / "README.md"
                        self.assertTrue(provenance.is_file(), "real fixtures need provenance")
                        self.assertRegex(
                            provenance.read_text(encoding="utf-8"),
                            r"(?:line \d+|rowids? \d+)",
                        )
                    for case in ("idle", "queued"):
                        if manifest_path.parent.name in TRANSCRIPT_FIXTURE_ADAPTERS:
                            fixture = fixture_dir / f"{case}.jsonl"
                            self.assertTrue(fixture.is_file(), f"missing {case} fixture")
                    for fixture in fixture_paths:
                        text = fixture.read_text(encoding="utf-8")
                        if manifest_path.parent.name == "grok":
                            self.assertNotRegex(text, r"\[partyline-paste:")
                            continue
                        self.assertRegex(
                            text,
                            re.compile(r"\[partyline-paste: [0-9a-f-]+\]"),
                            f"{fixture.relative_to(ROOT)} must retain a paste marker",
                        )

    def test_transcript_fixtures_are_credited_by_their_receipt_reader(self):
        async def check_jsonl(adapter_name: str, record: dict, marker: str) -> None:
            credited = []

            async def confirm(ids):
                credited.extend(ids)
                return True

            reader = object.__new__(JsonlPasteReceipts)
            reader._jsonl_receipts = [{
                "digest": marker, "marker": marker, "ids": [701], "proven": False,
            }]
            reader._jsonl_confirmed_ids = set()
            reader._jsonl_receipt_event = asyncio.Event()
            reader.att = {"confirm_delivery_ids": confirm}
            await reader._observe_jsonl_paste(record)
            self.assertEqual(credited, [701], adapter_name)

        async def check_grok(record: dict, marker: str) -> None:
            parsed = user_input(record)
            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertIn(marker, parsed[1])
            credited = []

            async def confirm(ids):
                credited.extend(ids)
                return True

            adapter = SimpleNamespace(
                att={"confirm_delivery_ids": confirm},
                _silent_until_wake=True,
                format_digest=lambda _messages: parsed[1],
            )

            async def send_keys(_text):
                return None

            adapter.send_keys = send_keys
            receipts = WakeReceipts()
            receipts.seed(parsed[0] - 1)
            await receipts.deliver(adapter, [{"id": 703}])
            await receipts.observe(adapter, record)
            self.assertEqual(credited, [703], "grok")

        async def check_opencode(record: dict, marker: str) -> None:
            credited = []

            async def confirm(ids):
                credited.extend(ids)
                return True

            reader = object.__new__(WakeSettlement)
            reader._wake_receipts = [{"marker": marker, "ids": [702], "proven": False}]
            reader._confirmed_delivery_ids = set()
            reader._delivery_confirmed = asyncio.Event()
            reader._seen_user_parts = set()
            reader.att = {"confirm_delivery_ids": confirm}
            part = record.get("part") or {}
            text = (
                (part.get("data") if isinstance(part.get("data"), dict) else part)
                or record.get("data")
                or {}
            ).get("text", "")
            await reader._observe_user_part(json.dumps({"text": text}), "fixture")
            self.assertEqual(credited, [702], "opencode")

        loop = asyncio.new_event_loop()
        try:
            for adapter_name in sorted(TRANSCRIPT_FIXTURE_ADAPTERS - {"grok"}):
                fixture_dir = ROOT / "tests/fixtures/transcripts" / adapter_name
                for fixture in sorted(fixture_dir.glob("*.jsonl")):
                    record = json.loads(fixture.read_text(encoding="utf-8").splitlines()[0])
                    marker_match = re.search(
                        r"\[partyline-paste: [0-9a-f-]+\]", fixture.read_text(encoding="utf-8")
                    )
                    assert marker_match is not None
                    marker = marker_match.group()
                    if adapter_name == "grok":
                        loop.run_until_complete(check_grok(record, marker))
                    elif adapter_name in {"opencode", "opencode-v2"}:
                        loop.run_until_complete(check_opencode(record, marker))
                    else:
                        text = _user_text(record)
                        self.assertIsNotNone(text, adapter_name)
                        self.assertIn(marker, text, adapter_name)
                        loop.run_until_complete(check_jsonl(adapter_name, record, marker))
        finally:
            loop.close()
