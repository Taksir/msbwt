"""Regression tests for deterministic, host-side synthetic fixture generation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from unittest import mock
from pathlib import Path

# The compatibility harness runs fixtures directly from the worktree.  Avoid
# leaving generated caches there when this module loads the generator below.
sys.dont_write_bytecode = True


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPOSITORY_ROOT / "compat" / "fixtures" / "synthetic" / "generate_fixtures.py"


SPEC = importlib.util.spec_from_file_location("synthetic_fixture_generator", GENERATOR)
assert SPEC is not None and SPEC.loader is not None
fixture_generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture_generator)


class SyntheticFixtureGeneratorTests(unittest.TestCase):
    def run_generator(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(GENERATOR), *arguments],
            check=False,
            text=True,
            capture_output=True,
        )

    def test_checked_in_fixtures_match_generator(self) -> None:
        result = self.run_generator("--check")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_repeated_generation_is_byte_identical(self) -> None:
        first = fixture_generator.expected_artifacts()
        second = fixture_generator.expected_artifacts()
        self.assertEqual(first, second)
        self.assertEqual(
            {name: hashlib.sha256(raw).hexdigest() for name, raw in first},
            {name: hashlib.sha256(raw).hexdigest() for name, raw in second},
        )

    def test_manifest_hashes_and_gzip_payloads_are_coherent(self) -> None:
        artifacts = dict(fixture_generator.expected_artifacts())
        manifest = json.loads(artifacts[fixture_generator.MANIFEST_NAME].decode("utf-8"))
        for item in manifest["files"]:
            self.assertEqual(item["byte_count"], len(artifacts[item["path"]]))
            self.assertEqual(item["sha256"], hashlib.sha256(artifacts[item["path"]]).hexdigest())
        self.assertEqual(
            fixture_generator.gzip.decompress(artifacts["uniform-a.fastq.gz"]),
            artifacts["uniform-a.fastq"],
        )
        self.assertEqual(
            fixture_generator.gzip.decompress(artifacts["nonuniform.fastq.gz"]),
            artifacts["nonuniform.fastq"],
        )

    def test_recovery_nonuniform_259_fixture_is_nonuniform_repeated_37_times(self) -> None:
        """Pin the documented recovery fixture rule and byte contract.

        The plan requires the exact recovery fixture for the nonuniform
        multimerge backup milestone:
        ``recovery-nonuniform-259.fastq`` = ``nonuniform.fastq`` repeated 37
        times, 9102 bytes, SHA-256
        ``8606e2b580afeafee17600ce6c33db67d14f2cc22235edfa51100811ad6d65b9``.
        """
        artifacts = dict(fixture_generator.expected_artifacts())
        nonuniform = artifacts["nonuniform.fastq"]
        recovery = artifacts["recovery-nonuniform-259.fastq"]

        self.assertEqual(recovery, nonuniform * 37)
        self.assertEqual(len(recovery), 9102)
        self.assertEqual(
            hashlib.sha256(recovery).hexdigest(),
            "8606e2b580afeafee17600ce6c33db67d14f2cc22235edfa51100811ad6d65b9",
        )
        record_count = recovery.count(b"\n") // 4
        self.assertEqual(record_count, 259)
        self.assertEqual(record_count, 7 * 37)

        manifest = json.loads(artifacts[fixture_generator.MANIFEST_NAME].decode("utf-8"))
        case_ids = {case["id"] for case in manifest["cases"]}
        self.assertIn("recovery-nonuniform-259", case_ids)
        recovery_entry = next(
            item
            for item in manifest["files"]
            if item["path"] == "recovery-nonuniform-259.fastq"
        )
        self.assertEqual(recovery_entry["byte_count"], 9102)
        self.assertEqual(
            recovery_entry["sha256"],
            "8606e2b580afeafee17600ce6c33db67d14f2cc22235edfa51100811ad6d65b9",
        )

    def test_recovery_fixture_repeats_ignored_headers_without_changing_sequences(self) -> None:
        """The 259 reads must be the seven nonuniform sequences repeated exactly."""
        artifacts = dict(fixture_generator.expected_artifacts())
        nonuniform_lines = artifacts["nonuniform.fastq"].splitlines()
        recovery_lines = artifacts["recovery-nonuniform-259.fastq"].splitlines()

        expected = (nonuniform_lines * 37)
        self.assertEqual(recovery_lines, expected)
        recovery_sequences = [recovery_lines[index] for index in range(1, len(recovery_lines), 4)]
        nonuniform_sequences = [
            nonuniform_lines[index] for index in range(1, len(nonuniform_lines), 4)
        ]
        self.assertEqual(recovery_sequences, nonuniform_sequences * 37)

    def test_check_reports_drift(self) -> None:
        expected = dict(fixture_generator.expected_artifacts())

        def changed_uniform_a(path: Path) -> bytes:
            if path.name == "uniform-a.fastq":
                return b"changed\n"
            return expected[path.name]

        with mock.patch.object(Path, "read_bytes", autospec=True, side_effect=changed_uniform_a):
            mismatches = fixture_generator.check_artifacts(Path("synthetic-fixtures"))
        self.assertEqual(len(mismatches), 1)
        self.assertIn("drifted:", mismatches[0])
        self.assertTrue(mismatches[0].endswith("uniform-a.fastq"))


if __name__ == "__main__":
    unittest.main()
