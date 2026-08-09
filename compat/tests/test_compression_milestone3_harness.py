"""Host-side guards for the manifest-driven non-resumable interruption oracle.

Milestone 3 is failure characterization only.  These tests prove the external
failpoint adapter supports the m3c1/m3c2/m3c4 worker cases with the exact
failpoint semantics, that the driver records the exact CLI/refusal contract,
that the manifest pins the verified profile and evidence constants, and that
the partial-state classification helpers behave deterministically.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENT_ROOT = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment"
MANIFEST_PATH = ENVIRONMENT_ROOT / "compression-milestone3-cases.json"
RUNNER_PATH = ENVIRONMENT_ROOT / "compression_milestone3.py"
ADAPTER_PATH = ENVIRONMENT_ROOT / "failpoint_adapter.py"
PROBE_PATH = ENVIRONMENT_ROOT / "probe_legacy.py"
WSL_DRIVER = ENVIRONMENT_ROOT / "wsl" / "run-wsl-probe.sh"
GOLDEN_ROOT = REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0"
FIXTURE_ROOT = REPOSITORY_ROOT / "compat" / "fixtures" / "synthetic"

sys.path.insert(0, str(ENVIRONMENT_ROOT))
SPEC = importlib.util.spec_from_file_location("compression_milestone3", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
compression_milestone3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compression_milestone3)

ADAPTER_SPEC = importlib.util.spec_from_file_location("failpoint_adapter", ADAPTER_PATH)
assert ADAPTER_SPEC is not None and ADAPTER_SPEC.loader is not None
failpoint_adapter = importlib.util.module_from_spec(ADAPTER_SPEC)
ADAPTER_SPEC.loader.exec_module(failpoint_adapter)


@contextmanager
def writable_temporary_directory():
    path = REPOSITORY_ROOT / (".milestone3-harness-test-" + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


class CompressionMilestone3HarnessTests(unittest.TestCase):
    def test_manifest_pins_profile_route_evidence_and_cases(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            manifest["format"], "msbwt-legacy-compression-milestone3-cases-v1"
        )
        self.assertEqual(manifest["profile_id"], "py27-late-05a7d6d83862")
        self.assertEqual(manifest["route"], "pyx-historical-cython")
        self.assertEqual(manifest["failpoint_exit_code"], 86)
        self.assertEqual(manifest["natural_failure_exit_code"], 87)
        self.assertEqual(manifest["canonical_runs"], ["run-a", "run-b"])
        self.assertEqual(manifest["fixture_cases"]["uniform"], "uniform-multifile")
        self.assertEqual(
            manifest["uniform_preprocess"]["tree_sha256"],
            "4f666f2f8841b2326160ca0d8c2fb975cac3e8e58d006e90ee1265fd238ecf05",
        )
        self.assertEqual(
            manifest["uniform_byte_golden"]["primary_sha256"],
            "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f",
        )
        self.assertEqual(manifest["evidence"]["repeat_count"], 22000)
        self.assertEqual(manifest["evidence"]["expected_total_symbols"], 1056000)
        self.assertEqual(manifest["evidence"]["expected_tuples"], 2)

        m3c1 = manifest["cases"]["m3c1"]
        self.assertEqual(
            m3c1["adapter_function"], "MUS.MSBWTGen.compressBWTPoolProcess"
        )
        self.assertEqual(m3c1["expected_exit_codes"], [86])
        self.assertEqual(m3c1["temp_prefix"], "comp_msbwt.npy.temp.")

        m3c2 = manifest["cases"]["m3c2"]
        self.assertEqual(
            m3c2["adapter_function"], "MUS.MSBWTGen.decompressBWTPoolProcess"
        )
        self.assertEqual(m3c2["expected_exit_codes"], [86, 87])
        self.assertEqual(m3c2["source_side_effects"],
                         ["comp_fmIndex.npy", "comp_refIndex.npy", "totalCounts.p"])

        m3c4 = manifest["cases"]["m3c4"]
        self.assertEqual(
            m3c4["adapter_function"], "MUSCython.MSBWTGenCython.createMsbwtFromSeqs"
        )
        self.assertEqual(m3c4["failpoint_prefix"], "Finished iteration 2 in")
        self.assertEqual(m3c4["restart_mode"], "restart-from-scratch")
        self.assertEqual(m3c4["partial_minimum_state_files"], 6)

        self.assertEqual(manifest["parser_refusals"]["m3c1"]["cli"],
                         ["compress", "-p", "1", "SOURCE", "DESTINATION"])
        self.assertEqual(manifest["parser_refusals"]["m3c2"]["cli"],
                         ["decompress", "-p", "1", "SOURCE", "DESTINATION"])

    def test_runner_records_the_exact_milestone_three_contract(self) -> None:
        source = RUNNER_PATH.read_text(encoding="utf-8")

        for required in (
            "FORMAT = \"msbwt-legacy-compression-milestone3-raw-v1\"",
            "FAILPOINT_EXIT_CODE = 86",
            "NATURAL_FAILURE_EXIT_CODE = 87",
            "PARSER_REFUSAL_EXIT_CODE = 2",
            "RESUME_MARKERS = (\"Resuming previous run\", \"Backup located\", \"resuming...\")",
            "FROM_SCRATCH_MARKERS = (\"Generating level 1 insertions\", \"Beginning iterations\")",
            "def m3c1_case(",
            "def m3c2_case(",
            "def m3c4_case(",
            "def parser_refusal(",
            "def assert_determinism(",
            'cli_argv("compress", "-p", "1", evidence_root, rle_root)',
            'cli_argv("cfpp", "-p", "1", "-u", restart)',
            "case_config[\"restart_mode\"]",
            "\"Non-empty directory already exists\" not in sanitized",
            "returncode != PARSER_REFUSAL_EXIT_CODE",
            "partial_key = {\"m3c1\": \"destination\", \"m3c2\": \"destination\", \"m3c4\": \"partial\"}",
        ):
            self.assertIn(required, source)

    def test_failpoint_adapter_supports_milestone_three_cases_externally(self) -> None:
        source = ADAPTER_PATH.read_text(encoding="utf-8")

        self.assertIn("FAILPOINT_EXIT_CODE = 86", source)
        self.assertIn("NATURAL_FAILURE_EXIT_CODE = 87", source)
        self.assertIn('choices=("r1", "r2", "m3c1", "m3c2", "m3c4")', source)
        self.assertIn("def run_compression_worker_case(", source)
        self.assertIn("def run_decompression_worker_case(", source)
        self.assertIn("def run_byte_builder_case(", source)
        self.assertIn("MSBWTGen.compressBWTPoolProcess(tup)", source)
        self.assertIn("MSBWTGen.decompressBWTPoolProcess(tups[0])", source)
        self.assertIn("MSBWTGenCython.createMsbwtFromSeqs(args.dataset, args.processes, logger)", source)
        self.assertIn("os._exit(FAILPOINT_EXIT_CODE)", source)
        self.assertIn("os._exit(NATURAL_FAILURE_EXIT_CODE)", source)
        self.assertNotIn("state.", source)
        self.assertNotIn("setattr", source)

    def test_failpoint_logger_byte_builder_prefix_exits_86(self) -> None:
        with writable_temporary_directory() as temporary:
            log_path = str(temporary / "adapter-log.txt")
            record_path = str(temporary / "failpoint-record.json")
            original_exit = failpoint_adapter.os._exit
            exits = []

            def fake_exit(code):
                exits.append(code)

            failpoint_adapter.os._exit = fake_exit
            logger = failpoint_adapter.FailpointLogger(
                log_path, "Finished iteration 2 in", record_path, "m3c4", "/scratch/m3c4-partial"
            )
            try:
                logger.info("Preparing to merge 8 sequences...")
                self.assertEqual(exits, [])
                logger.info("Finished iteration 2 in 0.125 seconds(0.130 clock)...")
                self.assertEqual(exits, [86])
                record = json.loads(Path(record_path).read_text(encoding="utf-8"))
                self.assertEqual(record["case"], "m3c4")
                self.assertEqual(record["exit_code"], 86)
                self.assertTrue(record["triggering_message"].startswith("Finished iteration 2 in"))
            finally:
                failpoint_adapter.os._exit = original_exit
                logger.close()

    def test_nonzero_region_fingerprint_distinguishes_completed_and_unwritten(self) -> None:
        boundary = 4
        completed = bytearray([1, 2, 3, 4, 0, 0, 0, 0])
        unwritten = bytearray([0, 0, 0, 0, 0, 0, 0, 0])
        completed_fp = compression_milestone3.nonzero_region_fingerprint(completed, boundary)
        unwritten_fp = compression_milestone3.nonzero_region_fingerprint(unwritten, boundary)
        self.assertTrue(completed_fp["prefix_region_any_nonzero"])
        self.assertFalse(completed_fp["tail_region_any_nonzero"])
        self.assertFalse(unwritten_fp["prefix_region_any_nonzero"])
        self.assertFalse(unwritten_fp["tail_region_any_nonzero"])

    def test_validate_config_accepts_the_committed_goldens(self) -> None:
        config, fixtures, uniform_build = compression_milestone3.validate_config(
            str(MANIFEST_PATH), str(GOLDEN_ROOT), str(FIXTURE_ROOT)
        )
        self.assertEqual(config["profile_id"], "py27-late-05a7d6d83862")
        self.assertIn("uniform", fixtures)
        self.assertTrue(os.path.isdir(uniform_build))
        self.assertTrue(os.path.isfile(os.path.join(uniform_build, "msbwt.npy")))

    def test_probe_requires_milestone3_inputs_and_historical_pyx_route(self) -> None:
        source = PROBE_PATH.read_text(encoding="utf-8")

        self.assertIn('args.compression_milestone3', source)
        self.assertIn("compression3_options", source)
        self.assertIn("import compression_milestone3", source)
        self.assertIn("--compression-milestone3 requires --route pyx-historical-cython", source)
        self.assertIn("--compression-milestone3 requires --fixture-root and --golden-root", source)
        self.assertIn("DEFAULT_COMPRESSION3_CASES", source)

    def test_wsl_driver_passes_milestone3_through(self) -> None:
        source = WSL_DRIVER.read_text(encoding="utf-8")

        self.assertIn("COMPRESSION_MILESTONE3", source)
        self.assertIn("--compression-milestone3", source)
        self.assertIn("--compression-milestone3 requires an existing --golden-root.", source)


if __name__ == "__main__":
    unittest.main()
