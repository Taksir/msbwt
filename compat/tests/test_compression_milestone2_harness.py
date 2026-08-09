"""Host-side guards for the manifest-driven builder recovery oracle milestone.

The recovery milestone must never patch frozen source.  These tests prove the
external failpoint adapter recognizes only the exact completed-checkpoint
messages, that the driver records the exact CLI/resume contract, and that the
partial-state classification helpers enforce the plan's minimum checkpoint
requirements.
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
MANIFEST_PATH = ENVIRONMENT_ROOT / "compression-milestone2-cases.json"
RUNNER_PATH = ENVIRONMENT_ROOT / "compression_milestone2.py"
ADAPTER_PATH = ENVIRONMENT_ROOT / "failpoint_adapter.py"
PROBE_PATH = ENVIRONMENT_ROOT / "probe_legacy.py"
WSL_DRIVER = ENVIRONMENT_ROOT / "wsl" / "run-wsl-probe.sh"

sys.path.insert(0, str(ENVIRONMENT_ROOT))
SPEC = importlib.util.spec_from_file_location("compression_milestone2", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
compression_milestone2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compression_milestone2)

ADAPTER_SPEC = importlib.util.spec_from_file_location("failpoint_adapter", ADAPTER_PATH)
assert ADAPTER_SPEC is not None and ADAPTER_SPEC.loader is not None
failpoint_adapter = importlib.util.module_from_spec(ADAPTER_SPEC)
ADAPTER_SPEC.loader.exec_module(failpoint_adapter)


@contextmanager
def writable_temporary_directory():
    path = REPOSITORY_ROOT / (".recovery-harness-test-" + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


class CompressionMilestone2HarnessTests(unittest.TestCase):
    def test_manifest_pins_profile_route_fixtures_and_failpoints(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            manifest["format"], "msbwt-legacy-compression-milestone2-cases-v1"
        )
        self.assertEqual(manifest["profile_id"], "py27-late-05a7d6d83862")
        self.assertEqual(manifest["route"], "pyx-historical-cython")
        self.assertEqual(manifest["failpoint_exit_code"], 86)
        self.assertEqual(manifest["canonical_runs"], ["run-a", "run-b"])
        self.assertEqual(manifest["fixture_cases"]["uniform"], "uniform-multifile")
        self.assertEqual(
            manifest["fixture_cases"]["nonuniform_recovery"], "recovery-nonuniform-259"
        )
        self.assertEqual(
            manifest["uniform_preprocess"]["tree_sha256"],
            "4f666f2f8841b2326160ca0d8c2fb975cac3e8e58d006e90ee1265fd238ecf05",
        )

        r1 = manifest["cases"]["r1"]
        self.assertEqual(
            r1["adapter_function"],
            "MUSCython.MSBWTCompGenCython.createMsbwtFromSeqs",
        )
        self.assertEqual(r1["adapter_processes"], 1)
        self.assertEqual(r1["failpoint_prefix"], "Finished iteration 2 in")
        self.assertEqual(r1["partial_checkpoint_column"], 2)
        self.assertEqual(r1["partial_minimum_files"], ["fmDeltas.2.npy", "fmStarts.2.npy"])
        self.assertEqual(r1["partial_minimum_state_files"], 6)
        self.assertEqual(r1["resume_argv"], ["cfpp", "-p", "1", "-u", "-c", "DESTINATION"])
        self.assertEqual(r1["resume_log_marker"], "Resuming previous run from 2")

        r2 = manifest["cases"]["r2"]
        self.assertEqual(
            r2["adapter_function"], "MUSCython.MultimergeCython.interleaveLevelMerge"
        )
        self.assertFalse(r2["adapter_uniform"])
        self.assertEqual(r2["failpoint_prefix"], "Backup creation finished.")
        self.assertEqual(r2["partial_backup"], "backup.256.npy")
        self.assertEqual(r2["resume_argv"], ["cfpp", "-p", "1", "DESTINATION"])
        self.assertEqual(r2["resume_log_marker"], "Backup located, resuming...")
        self.assertEqual(r2["clean_retained_backup"], "backup.256.npy")
        self.assertEqual(
            r2["clean_retained_files"],
            ["backup.256.npy", "msbwt.npy", "offsets.npy", "seqs.npy"],
        )
        self.assertEqual(
            r2["recovered_retained_files"],
            ["msbwt.npy", "offsets.npy", "seqs.npy"],
        )

    def test_runner_records_the_exact_cli_and_failpoint_contract(self) -> None:
        source = RUNNER_PATH.read_text(encoding="utf-8")

        for required in (
            'cli_argv("pp", "-u", partial, *fixture_paths)',
            'cli_argv("cfpp", "-p", "1", "-u", "-c", resume)',
            'cli_argv("cfpp", "-p", "1", resume)',
            'cli_argv("pp", partial, *fixture_paths)',
            "preexec_fn=os.setsid",
            "os.killpg(process.pid, signal.SIGKILL)",
            "returncode != FAILPOINT_EXIT_CODE",
            "FAILPOINT_EXIT_CODE = 86",
            'case_config["resume_log_marker"] not in resume_stdout.decode("utf-8")',
            "def r1_case(",
            "def r2_case(",
            "def assert_r2_relationship(",
            'config["uniform_preprocess"]["tree_sha256"]',
            'raise RuntimeError("clean R2 build did not retain backup {0}".format(backup))',
            'raise RuntimeError("recovered R2 build unexpectedly retained backup {0}".format(backup))',
            '"clean_retains_backup": True',
            '"recovered_removes_backup": True',
            '"no_other_divergence": True',
        ):
            self.assertIn(required, source)

    def test_failpoint_adapter_is_external_and_exits_86_on_exact_message(self) -> None:
        source = ADAPTER_PATH.read_text(encoding="utf-8")

        self.assertIn("os._exit(FAILPOINT_EXIT_CODE)", source)
        self.assertIn("FAILPOINT_EXIT_CODE = 86", source)
        self.assertIn("text.startswith(self._failpoint_prefix)", source)
        self.assertIn("MSBWTCompGenCython.createMsbwtFromSeqs(args.dataset, args.processes, logger)", source)
        self.assertIn("MultimergeCython.interleaveLevelMerge(args.dataset, args.processes, False, logger)", source)
        self.assertNotIn("state.", source)

    def test_failpoint_logger_flushes_record_and_exits_86_only_on_prefix(self) -> None:
        with writable_temporary_directory() as temporary:
            log_path = str(temporary / "adapter-log.txt")
            record_path = str(temporary / "failpoint-record.json")
            original_exit = failpoint_adapter.os._exit
            exits = []

            def fake_exit(code):
                exits.append(code)

            failpoint_adapter.os._exit = fake_exit
            logger = failpoint_adapter.FailpointLogger(
                log_path, "Finished iteration 2 in", record_path, "r1", "/scratch/r1-partial"
            )
            try:
                logger.info("Preparing to merge 8 sequences...")
                self.assertEqual(exits, [])
                self.assertFalse(os.path.exists(record_path))
                logger.info("Finished iteration 2 in 0.125 seconds(0.130 clock)...")
                self.assertEqual(exits, [86])
                self.assertTrue(os.path.isfile(record_path))
                self.assertTrue(os.path.isfile(log_path))
                record = json.loads(Path(record_path).read_text(encoding="utf-8"))
                self.assertEqual(record["case"], "r1")
                self.assertEqual(record["exit_code"], 86)
                self.assertEqual(record["failpoint_prefix"], "Finished iteration 2 in")
                self.assertEqual(
                    record["triggering_message"],
                    "Finished iteration 2 in 0.125 seconds(0.130 clock)...",
                )
                self.assertEqual(record["level"], "INFO")
                log = Path(log_path).read_text(encoding="utf-8")
                self.assertIn("Preparing to merge 8 sequences...", log)
                self.assertIn("Finished iteration 2 in 0.125 seconds", log)
            finally:
                failpoint_adapter.os._exit = original_exit
                logger.close()

    def test_failpoint_logger_writes_record_for_backup_message(self) -> None:
        with writable_temporary_directory() as temporary:
            log_path = str(temporary / "adapter-log.txt")
            record_path = str(temporary / "failpoint-record.json")
            original_exit = failpoint_adapter.os._exit
            exits = []

            def fake_exit(code):
                exits.append(code)

            failpoint_adapter.os._exit = fake_exit
            logger = failpoint_adapter.FailpointLogger(
                log_path, "Backup creation finished.", record_path, "r2", "/scratch/r2-partial"
            )
            try:
                logger.info("Beginning MSBWT construction...")
                logger.info("Backup creation finished.")
                self.assertEqual(exits, [86])
                record = json.loads(Path(record_path).read_text(encoding="utf-8"))
                self.assertEqual(record["case"], "r2")
                self.assertEqual(record["triggering_message"], "Backup creation finished.")
            finally:
                failpoint_adapter.os._exit = original_exit
                logger.close()

    def test_partial_checkpoint_classification_enforces_minimum_files(self) -> None:
        with writable_temporary_directory() as temporary:
            root = temporary / "partial"
            root.mkdir()
            for name in (
                "about.npy", "offsets.npy",
                "seqs.npy.0.npy", "seqs.npy.1.npy", "seqs.npy.2.npy",
                "seqs.npy.3.npy", "seqs.npy.4.npy", "seqs.npy.5.npy",
            ):
                (root / name).write_bytes(b"x")
            case_config = {
                "partial_checkpoint_column": 2,
                "partial_minimum_files": ["fmDeltas.2.npy", "fmStarts.2.npy"],
                "partial_minimum_state_files": 6,
            }
            with self.assertRaises(RuntimeError):
                compression_milestone2.assert_minimum_checkpoint(str(root), case_config)
            for symbol in range(6):
                (root / "state.{0}.2.dat".format(symbol)).write_bytes(b"state")
            with self.assertRaises(RuntimeError):
                compression_milestone2.assert_minimum_checkpoint(str(root), case_config)
            (root / "fmStarts.2.npy").write_bytes(b"starts")
            (root / "fmDeltas.2.npy").write_bytes(b"deltas")
            (root / "inserts.01.2.npy").write_bytes(b"inserts")
            checkpoint = compression_milestone2.assert_minimum_checkpoint(str(root), case_config)
            self.assertEqual(checkpoint["checkpoint_column"], 2)
            self.assertEqual(len(checkpoint["state_files"]), 6)
            self.assertIn("inserts.01.2.npy", checkpoint["insert_files"])
            self.assertIn("state.0.2.dat", checkpoint["file_set"])

    def test_partial_backup_classification_requires_complete_backup(self) -> None:
        with writable_temporary_directory() as temporary:
            root = temporary / "partial"
            root.mkdir()
            case_config = {"partial_backup": "backup.256.npy"}
            with self.assertRaises(RuntimeError):
                compression_milestone2.assert_partial_backup(str(root), case_config)
            (root / "msbwt.npy").write_bytes(b"msbwt")
            with self.assertRaises(RuntimeError):
                compression_milestone2.assert_partial_backup(str(root), case_config)
            (root / "backup.256.npy").write_bytes(b"backup")
            backup = compression_milestone2.assert_partial_backup(str(root), case_config)
            self.assertEqual(backup["backup"], "backup.256.npy")
            self.assertIn("msbwt.npy", backup["file_set"])

    def test_r2_relationship_requires_clean_backup_and_removed_recovered_backup(self) -> None:
        case_config = {
            "partial_backup": "backup.256.npy",
            "clean_retained_backup": "backup.256.npy",
        }
        with writable_temporary_directory() as temporary:
            clean = temporary / "clean"
            resumed = temporary / "resumed"
            clean.mkdir()
            resumed.mkdir()
            for name in ("msbwt.npy", "offsets.npy", "seqs.npy"):
                (clean / name).write_bytes(name.encode("ascii"))
                (resumed / name).write_bytes(name.encode("ascii"))
            clean_tree = compression_milestone2.inventory(str(clean))
            resumed_tree = compression_milestone2.inventory(str(resumed))
            with self.assertRaises(RuntimeError):
                compression_milestone2.assert_r2_relationship(
                    resumed_tree, clean_tree, case_config
                )
            (clean / "backup.256.npy").write_bytes(b"backup")
            clean_tree = compression_milestone2.inventory(str(clean))
            relationship = compression_milestone2.assert_r2_relationship(
                resumed_tree, clean_tree, case_config
            )
            self.assertTrue(relationship["clean_retains_backup"])
            self.assertTrue(relationship["recovered_removes_backup"])
            self.assertTrue(relationship["no_other_divergence"])
            self.assertTrue(relationship["common_files_equal"])
            self.assertEqual(relationship["clean_file_set"], [
                "backup.256.npy", "msbwt.npy", "offsets.npy", "seqs.npy"
            ])
            self.assertEqual(relationship["recovered_file_set"], [
                "msbwt.npy", "offsets.npy", "seqs.npy"
            ])

            # recovered build must not retain the backup
            (resumed / "backup.256.npy").write_bytes(b"backup")
            resumed_tree = compression_milestone2.inventory(str(resumed))
            with self.assertRaises(RuntimeError):
                compression_milestone2.assert_r2_relationship(
                    resumed_tree, clean_tree, case_config
                )
            (resumed / "backup.256.npy").unlink()

            # clean build must not lose the backup
            clean_no_backup = compression_milestone2.inventory(str(clean))
            del clean_no_backup["files"][:]
            clean_no_backup["files"] = [
                item for item in compression_milestone2.inventory(str(clean))["files"]
                if item["path"] != "backup.256.npy"
            ]
            with self.assertRaises(RuntimeError):
                compression_milestone2.assert_r2_relationship(
                    resumed_tree, clean_no_backup, case_config
                )

            # unexplained extra file must be rejected
            (resumed / "surprise.txt").write_bytes(b"x")
            resumed_tree = compression_milestone2.inventory(str(resumed))
            with self.assertRaises(RuntimeError):
                compression_milestone2.assert_r2_relationship(
                    resumed_tree, clean_tree, case_config
                )
            (resumed / "surprise.txt").unlink()

            # common file byte difference must be rejected
            (resumed / "msbwt.npy").write_bytes(b"different")
            resumed_tree = compression_milestone2.inventory(str(resumed))
            with self.assertRaises(RuntimeError):
                compression_milestone2.assert_r2_relationship(
                    resumed_tree, clean_tree, case_config
            )

    def test_tree_compare_reports_added_removed_and_changed(self) -> None:
        with writable_temporary_directory() as temporary:
            left = temporary / "left"
            right = temporary / "right"
            left.mkdir()
            right.mkdir()
            (left / "same").write_bytes(b"s")
            (left / "only-left").write_bytes(b"l")
            (left / "changed").write_bytes(b"a")
            (right / "same").write_bytes(b"s")
            (right / "only-right").write_bytes(b"r")
            (right / "changed").write_bytes(b"b")
            comparison = compression_milestone2.tree_compare(
                compression_milestone2.inventory(str(left)),
                compression_milestone2.inventory(str(right)),
            )
            self.assertFalse(comparison["matches"])
            self.assertEqual(comparison["added"], ["only-right"])
            self.assertEqual(comparison["removed"], ["only-left"])
            self.assertEqual(comparison["changed"], ["changed"])

    def test_assert_no_checkpoint_temps_rejects_leftovers(self) -> None:
        with writable_temporary_directory() as temporary:
            root = temporary / "clean"
            root.mkdir()
            (root / "comp_msbwt.npy").write_bytes(b"c")
            compression_milestone2.assert_no_checkpoint_temps(
                str(root), ("state.", "fmStarts.", "fmDeltas.", "inserts.")
            )
            (root / "state.5.2.dat").write_bytes(b"s")
            with self.assertRaises(RuntimeError):
                compression_milestone2.assert_no_checkpoint_temps(
                    str(root), ("state.", "fmStarts.", "fmDeltas.", "inserts.")
                )

    def test_probe_requires_milestone2_inputs_and_historical_pyx_route(self) -> None:
        source = PROBE_PATH.read_text(encoding="utf-8")

        self.assertIn('args.compression_milestone2', source)
        self.assertIn("compression2_options", source)
        self.assertIn("import compression_milestone2", source)
        self.assertIn("--compression-milestone2 requires --route pyx-historical-cython", source)
        self.assertIn("--compression-milestone2 requires --fixture-root and --golden-root", source)

    def test_wsl_driver_passes_milestone2_through(self) -> None:
        source = WSL_DRIVER.read_text(encoding="utf-8")

        self.assertIn("COMPRESSION_MILESTONE2", source)
        self.assertIn("--compression-milestone2", source)
        self.assertIn("--compression-milestone2 requires an existing --golden-root.", source)

    def test_runner_uses_committed_uniform_preprocess_contract(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        runner = RUNNER_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'preprocess["tree_sha256"] != config["uniform_preprocess"]["tree_sha256"]',
            runner,
        )
        self.assertEqual(
            manifest["uniform_preprocess"]["manifest_content_sha256"],
            "a8bdda27f2729745f4afb7b00dad41150e361b949a8807489b13be02b704fad1",
        )


if __name__ == "__main__":
    unittest.main()
