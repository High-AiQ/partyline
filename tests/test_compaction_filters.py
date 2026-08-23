"""Compaction summaries stay in vendor transcripts and out of partyline speech."""

import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from partyline.adapters.bundled.cursor.parse import fingerprint, resync_fingerprints
from partyline.adapters.bundled.grok.transcript import assistant_text as grok_text
from partyline.adapters.bundled.hermes.adapter import PartylineAdapter as HermesAdapter
from partyline.adapters.bundled.muse.adapter import PartylineAdapter as MuseAdapter
from partyline.adapters.compaction import is_compaction_record


FIXTURES = Path(__file__).parent / "fixtures" / "compaction"


def fixture(adapter: str) -> dict:
    return json.loads((FIXTURES / f"{adapter}.json").read_text(encoding="utf-8"))


class CompactionFilterTest(unittest.TestCase):
    def test_bundled_compact_pastes_match_live_probes(self):
        root = Path(__file__).parent.parent / "partyline" / "adapters" / "bundled"
        expected = {
            "claude": "/compact",
            "codex": "/compact",
            "cursor": "/summarize\n",
            "grok": "/compact",
            "hermes": "/compress",
            "muse": "/compact",
            "pi": "/compact",
        }
        for adapter, paste in expected.items():
            with (root / adapter / "adapter.toml").open("rb") as file:
                self.assertEqual(tomllib.load(file)["adapter"]["compact_paste"], paste)
        for adapter in ("antigravity", "opencode", "raw"):
            with (root / adapter / "adapter.toml").open("rb") as file:
                self.assertNotIn("compact_paste", tomllib.load(file)["adapter"])

    def test_replacement_records_are_explicitly_filtered_per_adapter(self):
        for adapter in ("claude", "codex", "grok", "muse", "pi"):
            with self.subTest(adapter=adapter):
                self.assertTrue(is_compaction_record(adapter, fixture(adapter)))

        self.assertIsNone(grok_text(fixture("grok")))
        self.assertIsNone(MuseAdapter._assistant_message(fixture("muse")))

    def test_hermes_compacted_assistant_snapshot_is_not_speech(self):
        self.assertIsNone(HermesAdapter._assistant_text(fixture("hermes")))

    def test_cursor_rewrite_reanchors_without_replaying_old_speech(self):
        records = fixture("cursor")
        seen = [fingerprint(record) for record in records["before"]]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cursor.jsonl"
            path.write_text(
                "".join(json.dumps(record) + "\n" for record in records["after"]),
                encoding="utf-8",
            )
            anchored = resync_fingerprints(path, seen)

        self.assertEqual(anchored[-3:], seen)


if __name__ == "__main__":
    unittest.main()
