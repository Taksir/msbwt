"""Pure host-side tests for the frozen-reader smoke harness."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


sys.dont_write_bytecode = True

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENT_ROOT = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment"
FIXTURE_ROOT = REPOSITORY_ROOT / "compat" / "fixtures" / "synthetic"
sys.path.insert(0, str(ENVIRONMENT_ROOT))
SPEC = importlib.util.spec_from_file_location("legacy_reader_smoke", ENVIRONMENT_ROOT / "reader_smoke.py")
assert SPEC is not None and SPEC.loader is not None
reader_smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader_smoke)


class LegacyReaderSmokeTests(unittest.TestCase):
    def test_reads_plain_and_gzip_fixture_sequences_identically(self) -> None:
        plain = reader_smoke.read_fastq_sequences(str(FIXTURE_ROOT / "uniform-a.fastq"))
        compressed = reader_smoke.read_fastq_sequences(str(FIXTURE_ROOT / "uniform-a.fastq.gz"))

        self.assertEqual(compressed, plain)

    def test_fixture_queries_include_overlapping_counts_and_absent_sequence(self) -> None:
        sequences = reader_smoke.read_fastq_sequences(str(FIXTURE_ROOT / "nonuniform.fastq"))
        queries = reader_smoke.all_fixture_substrings(sequences)

        self.assertEqual(reader_smoke.overlapping_count([b"TTTTTTTT"], b"TT"), 7)
        self.assertIn(b"TT", queries)
        self.assertIn(b"A" * (max(map(len, sequences)) + 1), queries)

    def test_inventory_comparison_records_reader_side_effects(self) -> None:
        before = {"existing.npy": {"sha256": "a", "size": 1}}
        after = {
            "existing.npy": {"sha256": "b", "size": 2},
            "fmIndex.npy": {"sha256": "c", "size": 3},
        }

        self.assertEqual(
            reader_smoke.compare_inventories(before, after),
            {
                "added": [{"path": "fmIndex.npy", "sha256": "c", "size": 3}],
                "changed": [
                    {
                        "path": "existing.npy",
                        "before": {"sha256": "a", "size": 1},
                        "after": {"sha256": "b", "size": 2},
                    }
                ],
                "removed": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
