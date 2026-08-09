"""Host-side guards for the manifest-driven clean RLE oracle milestone."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENT_ROOT = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment"
MANIFEST_PATH = ENVIRONMENT_ROOT / "compression-milestone1-cases.json"
RUNNER_PATH = ENVIRONMENT_ROOT / "compression_milestone1.py"
PROBE_PATH = ENVIRONMENT_ROOT / "probe_legacy.py"
READER_PATH = ENVIRONMENT_ROOT / "reader_smoke.py"

sys.path.insert(0, str(ENVIRONMENT_ROOT))
SPEC = importlib.util.spec_from_file_location("compression_milestone1", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
compression_milestone1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compression_milestone1)


class CompressionMilestone1HarnessTests(unittest.TestCase):
    def test_manifest_pins_profile_route_sources_and_execution_order(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            manifest["format"], "msbwt-legacy-compression-milestone1-cases-v1"
        )
        self.assertEqual(manifest["profile_id"], "py27-late-05a7d6d83862")
        self.assertEqual(manifest["route"], "pyx-historical-cython")
        self.assertEqual(manifest["canonical_runs"], ["run-a", "run-b"])
        self.assertEqual(manifest["canonical_processes"], 1)
        self.assertEqual(manifest["comparison_processes"], 2)
        self.assertEqual(
            manifest["successful_case_order"],
            [
                "uniform-posthoc",
                "nonuniform-posthoc",
                "uniform-roundtrip",
                "nonuniform-roundtrip",
                "uniform-direct-split",
                "uniform-direct-wrapper",
            ],
        )
        self.assertEqual(
            manifest["starting_artifacts"]["uniform_build"]["tree_sha256"],
            "842bfc80080ca553ee23f07eb3da7616df96822cee7d774d163c1c2058d0132e",
        )
        self.assertEqual(
            manifest["starting_artifacts"]["nonuniform_build"]["tree_sha256"],
            "ad4aa043feb549e0af861ffde0deca11f8ac0b030c5305183f61f04f5f4d8c0a",
        )

    def test_runner_records_the_exact_cli_contract(self) -> None:
        source = RUNNER_PATH.read_text(encoding="utf-8")

        for required in (
            'cli_argv("compress", "-p", str(processes), source, destination)',
            'cli_argv("decompress", "-p", str(processes), source, destination)',
            'cli_argv("pp", "-u", destination, *fixture_paths)',
            'cli_argv("cfpp", "-p", str(processes), "-u", "-c", destination)',
            'cli_argv("cffq", "-p", str(processes), "-u", "-c", destination, *fixture_paths)',
            'cli_argv("cfpp", "-p", "1", "-c", cfpp_dataset)',
            'cli_argv("cffq", "-p", "1", "-c", cffq_dataset, *fixture_paths)',
        ):
            self.assertIn(required, source)
        self.assertNotIn("failpoint", source.lower())
        self.assertNotIn("recovery-nonuniform-259", source)

    def test_probe_requires_all_milestone_inputs_and_historical_pyx_route(self) -> None:
        source = PROBE_PATH.read_text(encoding="utf-8")

        self.assertIn('args.route != "pyx-historical-cython"', source)
        self.assertIn('not args.fixture_root or not args.golden_root', source)
        self.assertIn('not args.install_dependencies', source)
        self.assertIn('platform.python_implementation() != "CPython"', source)

    def test_reader_probe_records_dollar_ids_and_coexistence_preference(self) -> None:
        source = READER_PATH.read_text(encoding="utf-8")

        self.assertIn('"recovered_by_dollar_id"', source)
        self.assertIn('result["reader_class"] != "ByteBWT"', source)
        self.assertIn('rle_reader.__class__.__name__ != "RLE_BWT"', source)
        self.assertIn('os.remove(os.path.join(args.copy, "msbwt.npy"))', source)


if __name__ == "__main__":
    unittest.main()
