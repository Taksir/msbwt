"""Focused no-write guard tests for the frozen Python-2 oracle probe."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


# This module loads a host-side copy of a Python-2-compatible harness directly
# from the worktree.  Do not leave bytecode in either oracle or test paths.
sys.dont_write_bytecode = True

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment" / "probe_legacy.py"
FIXTURE_ROOT = REPOSITORY_ROOT / "compat" / "fixtures" / "synthetic"

sys.path.insert(0, str(PROBE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("legacy_probe_guard", PROBE_PATH)
assert SPEC is not None and SPEC.loader is not None
legacy_probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(legacy_probe)


class LegacyProbeGuardTests(unittest.TestCase):
    def test_validates_exact_first_golden_fixture_case_and_hashes(self) -> None:
        result = legacy_probe.validate_first_golden_fixtures(str(FIXTURE_ROOT))

        self.assertEqual(result["case_id"], "uniform-multifile")
        self.assertEqual(result["fixture_manifest"], "fixture-manifest.json")
        self.assertEqual(
            result["files"],
            [
                {
                    "byte_count": 173,
                    "path": "uniform-a.fastq",
                    "sha256": "da3466b992e0ba4ef4da2d0731062661f13e66b83ec154b56471ec4286798180",
                },
                {
                    "byte_count": 162,
                    "path": "uniform-b.fastq",
                    "sha256": "04124b73a3dde82da5cd70d9d244180d6e076a952dda404e4746b1e9388e1029",
                },
            ],
        )

    def test_main_rejects_first_goldens_without_dependency_install_before_results(self) -> None:
        results = REPOSITORY_ROOT / "compat" / ".guard-results-no-install"
        self.assertFalse(results.exists())

        with self.assertRaisesRegex(SystemExit, "requires --install-dependencies"):
            legacy_probe.main(
                [
                    "--source",
                    str(REPOSITORY_ROOT),
                    "--results",
                    str(results),
                    "--run-first-goldens",
                ]
            )

        self.assertFalse(results.exists())

    def test_main_rejects_missing_fixture_root_before_results(self) -> None:
        results = REPOSITORY_ROOT / "compat" / ".guard-results-missing-fixture"
        missing_fixture_root = REPOSITORY_ROOT / "compat" / ".missing-first-golden-fixtures"
        self.assertFalse(results.exists())
        self.assertFalse(missing_fixture_root.exists())

        with self.assertRaisesRegex(SystemExit, "invalid first-golden fixtures"):
            legacy_probe.main(
                [
                    "--source",
                    str(REPOSITORY_ROOT),
                    "--results",
                    str(results),
                    "--install-dependencies",
                    "--run-first-goldens",
                    "--fixture-root",
                    str(missing_fixture_root),
                ]
            )

        self.assertFalse(results.exists())

    def test_nonzero_gate_skips_first_golden_without_recorder_execution(self) -> None:
        recorder = mock.Mock(spec=legacy_probe.Recorder)
        fixture_info = {
            "fixture_root": str(FIXTURE_ROOT),
            "files": [],
        }
        gate = {
            "base_dependency_install": 1,
            "route_dependency_install": 0,
            "build": 0,
            "build_ext_inplace": 0,
            "import_smoke": 0,
            "cli_version": 0,
        }

        with mock.patch.object(legacy_probe, "ensure_directory") as ensure_directory, mock.patch.object(
            legacy_probe, "write_json"
        ) as write_json:
            result = legacy_probe.run_first_golden_case(
                recorder=recorder,
                route="generated-c-no-cython",
                candidate_name="historical-source-claims",
                destination="nonexistent-oracle-destination",
                run_dir="nonexistent-legacy-probe-run",
                fixture_info=fixture_info,
                gate=gate,
                dependency_install_failures={"base": ["numpy"], "route": []},
            )

        self.assertEqual(result["status"], "skipped-gate-failure")
        self.assertNotEqual(result["status"], "passed")
        recorder.run.assert_not_called()
        ensure_directory.assert_called_once()
        write_json.assert_called_once()

    def test_oracle_tree_hash_is_repeatable_for_checked_in_fixture_directory(self) -> None:
        first = legacy_probe.oracle_tree_sha256(str(FIXTURE_ROOT))
        second = legacy_probe.oracle_tree_sha256(str(FIXTURE_ROOT))

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)


if __name__ == "__main__":
    unittest.main()
