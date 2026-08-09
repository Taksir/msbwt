"""Strict integrity checks for Compression/Recovery Milestone 2 goldens.

These tests protect the resolved builder-recovery legacy contract:

  R1  resumed and clean final trees are byte-identical, and the recovered
      comp_msbwt.npy equals the committed uniform-direct-split golden.
  R2  resumed msbwt.npy is byte-identical to the clean primary, the clean
      control deterministically retains backup.256.npy as an auxiliary legacy
      checkpoint artifact, the recovered build deterministically removes it,
      reader behavior is identical, and no other unexplained file difference
      exists.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = REPOSITORY_ROOT / "compat" / "tools" / "artifact_manifest.py"
SPEC = importlib.util.spec_from_file_location("compression_artifact_manifest", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
artifact_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifact_manifest)

PROFILE_ID = "py27-late-05a7d6d83862"
ROUTE = "pyx-historical-cython"
SOURCE_COMMIT = "7503346ec072ddb89520db86fef85569a9ba093a"
GOLDEN_ROOT = REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0"
M2 = GOLDEN_ROOT / "compression-milestone2"

R1_PRIMARY_SHA256 = "0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372"
R1_DECODED_BWT_SHA256 = "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e"
R1_DECODED_BWT = "ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$"
R2_PRIMARY_SHA256 = "04c9d88aa1c3f9a93c72b240f63635aa301db9874b71d1b042b70d69d86e2ad5"
R2_BACKUP_SHA256 = "ab03a690620fd6d3ce5d9bffb2fd25ec0ddd9050a0ec0e9d064e2bcceebbd1dc"
R1_RECOVERED_FILES = [
    "about.npy", "comp_msbwt.npy", "offsets.npy",
    "seqs.npy.0.npy", "seqs.npy.1.npy", "seqs.npy.2.npy",
    "seqs.npy.3.npy", "seqs.npy.4.npy", "seqs.npy.5.npy",
]
R2_RECOVERED_FILES = ["msbwt.npy", "offsets.npy", "seqs.npy"]
R2_CLEAN_FILES = ["backup.256.npy", "msbwt.npy", "offsets.npy", "seqs.npy"]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def assert_sanitized(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "/home/" not in text, path
    assert "/mnt/" not in text, path
    assert "Google Drive" not in text, path
    assert "msbwt-oracle" not in text, path
    assert "~/.local" not in text, path
    assert "C:\\" not in text, path


class CompressionMilestone2GoldenTests(unittest.TestCase):
    def test_profile_provenance_pins_profile_route_and_recovered_primaries(self) -> None:
        prov = load_json(M2 / "profile-provenance.json")

        self.assertEqual(prov["format"], "msbwt-legacy-compression-milestone2-profile-provenance-v1")
        self.assertEqual(prov["profile_id"], PROFILE_ID)
        self.assertEqual(prov["route"], ROUTE)
        self.assertEqual(prov["source_commit"], SOURCE_COMMIT)
        self.assertEqual(prov["canonical_runs"], ["run-a", "run-b"])
        self.assertEqual(prov["failpoint_exit_code"], 86)
        self.assertEqual(prov["r1"]["recovered_primary_sha256"], R1_PRIMARY_SHA256)
        self.assertEqual(prov["r1"]["decoded_bwt_sha256"], R1_DECODED_BWT_SHA256)
        self.assertEqual(prov["r1"]["decoded_bwt"], R1_DECODED_BWT)
        self.assertEqual(prov["r2"]["recovered_primary_sha256"], R2_PRIMARY_SHA256)
        self.assertEqual(prov["r2"]["shape"], [1110])
        self.assertEqual(prov["r2_clean_retained_backup"]["file"], "backup.256.npy")
        self.assertEqual(prov["r2_clean_retained_backup"]["sha256"], R2_BACKUP_SHA256)
        assert_sanitized(M2 / "profile-provenance.json")

    def test_r1_relationship_requires_tree_equality_and_primary(self) -> None:
        rel = load_json(M2 / "relationship-r1.json")

        self.assertEqual(rel["format"], "msbwt-legacy-compression-recovery-relationship-v1")
        self.assertEqual(rel["case"], "r1")
        self.assertEqual(rel["status"], "passed")
        self.assertTrue(rel["tree_equal"])
        self.assertTrue(rel["primary_equal"])
        self.assertEqual(rel["resume_log_marker"], "Resuming previous run from 2")
        self.assertEqual(rel["checkpoint_column"], 2)
        self.assertEqual(len(rel["state_files"]), 6)
        self.assertEqual(
            rel["insert_files"],
            ["inserts.11.2.npy", "inserts.22.2.npy", "inserts.33.2.npy",
             "inserts.35.2.npy", "inserts.54.2.npy", "inserts.55.2.npy"],
        )
        self.assertEqual(rel["resumed_primary"]["sha256"], R1_PRIMARY_SHA256)
        self.assertEqual(rel["resumed_primary"]["shape_literal"], "(22L,)")
        self.assertEqual(rel["resumed_primary"]["decoded_sha256"], R1_DECODED_BWT_SHA256)
        self.assertEqual(rel["resumed_primary"]["decoded_bwt"], R1_DECODED_BWT)
        self.assertEqual(rel["clean_primary"]["sha256"], R1_PRIMARY_SHA256)
        assert_sanitized(M2 / "relationship-r1.json")

    def test_r2_relationship_encodes_the_resolved_legacy_contract(self) -> None:
        rel = load_json(M2 / "relationship-r2.json")

        self.assertEqual(rel["format"], "msbwt-legacy-compression-recovery-relationship-v1")
        self.assertEqual(rel["case"], "r2")
        self.assertEqual(rel["status"], "passed")
        self.assertTrue(rel["clean_retains_backup"])
        self.assertTrue(rel["recovered_removes_backup"])
        self.assertTrue(rel["no_other_divergence"])
        self.assertTrue(rel["primary_equal"])
        self.assertEqual(rel["retained_backup"], "backup.256.npy")
        self.assertEqual(rel["backup_sha256"], R2_BACKUP_SHA256)
        self.assertEqual(rel["clean_file_set"], R2_CLEAN_FILES)
        self.assertEqual(rel["recovered_file_set"], R2_RECOVERED_FILES)
        self.assertEqual(rel["common_files"], ["msbwt.npy", "offsets.npy", "seqs.npy"])
        self.assertTrue(rel["common_files_equal"])
        self.assertEqual(rel["resume_log_marker"], "Backup located, resuming...")
        self.assertEqual(rel["resumed_primary"]["sha256"], R2_PRIMARY_SHA256)
        self.assertEqual(rel["resumed_primary"]["dtype"], "|u1")
        self.assertEqual(rel["resumed_primary"]["shape"], [1110])
        self.assertEqual(rel["clean_primary"]["sha256"], R2_PRIMARY_SHA256)
        assert_sanitized(M2 / "relationship-r2.json")

    def test_r1_recovered_and_clean_manifests_are_identical_and_match_committed_golden(self) -> None:
        recovered = artifact_manifest.load_json(M2 / "r1-recovered" / "manifest.json")
        clean = artifact_manifest.load_json(M2 / "r1-clean" / "manifest.json")

        self.assertEqual(recovered["content_sha256"], clean["content_sha256"])
        self.assertEqual(
            sorted(item["path"] for item in recovered["artifacts"]),
            R1_RECOVERED_FILES,
        )
        comp = next(item for item in recovered["artifacts"] if item["path"] == "comp_msbwt.npy")
        self.assertEqual(comp["sha256"], R1_PRIMARY_SHA256)
        self.assertEqual(comp["npy"]["dtype_descriptor"], "|u1")
        self.assertEqual(comp["npy"]["shape"], [22])

        # the recovered primary must be byte-identical to the committed
        # uniform-direct-split golden, proving recovery reproduces the clean route
        split_golden = artifact_manifest.load_json(
            GOLDEN_ROOT / "uniform-direct-split" / PROFILE_ID / ROUTE / "manifest.json")
        split_comp = next(
            item for item in split_golden["artifacts"] if item["path"] == "comp_msbwt.npy")
        self.assertEqual(comp["sha256"], split_comp["sha256"])

        recovered_bytes = (M2 / "r1-recovered" / "artifacts" / "comp_msbwt.npy").read_bytes()
        self.assertEqual(hashlib.sha256(recovered_bytes).hexdigest(), R1_PRIMARY_SHA256)
        decoded = artifact_manifest.decode_npy_rle_primary(
            M2 / "r1-recovered" / "artifacts" / "comp_msbwt.npy")
        self.assertEqual(decoded["decoded_sha256"], R1_DECODED_BWT_SHA256)
        self.assertEqual(decoded["decoded_bwt"], R1_DECODED_BWT)
        self.assertEqual(decoded["decoded_length"], 48)

    def test_r2_recovered_and_clean_file_sets_and_primary_identity(self) -> None:
        recovered = artifact_manifest.load_json(M2 / "r2-recovered" / "manifest.json")
        clean = artifact_manifest.load_json(M2 / "r2-clean" / "manifest.json")

        self.assertEqual(
            sorted(item["path"] for item in recovered["artifacts"]),
            R2_RECOVERED_FILES,
        )
        self.assertEqual(
            sorted(item["path"] for item in clean["artifacts"]),
            R2_CLEAN_FILES,
        )
        rec_msbwt = next(item for item in recovered["artifacts"] if item["path"] == "msbwt.npy")
        clean_msbwt = next(item for item in clean["artifacts"] if item["path"] == "msbwt.npy")
        self.assertEqual(rec_msbwt["sha256"], R2_PRIMARY_SHA256)
        self.assertEqual(clean_msbwt["sha256"], R2_PRIMARY_SHA256)
        self.assertEqual(rec_msbwt, clean_msbwt)
        self.assertEqual(rec_msbwt["npy"]["dtype_descriptor"], "|u1")
        self.assertEqual(rec_msbwt["npy"]["shape"], [1110])
        backup = next(item for item in clean["artifacts"] if item["path"] == "backup.256.npy")
        self.assertEqual(backup["sha256"], R2_BACKUP_SHA256)
        self.assertEqual(backup["npy"]["dtype_descriptor"], "|u1")
        self.assertEqual(backup["npy"]["shape"], [1110])
        # no backup may exist in the recovered tree
        self.assertNotIn("backup.256.npy", sorted(item["path"] for item in recovered["artifacts"]))

    def test_partial_manifests_are_deterministic_across_canonical_runs(self) -> None:
        for case in ("r1", "r2"):
            with self.subTest(case=case):
                run_a = artifact_manifest.load_json(M2 / "partial" / ("{0}-run-a.manifest.json".format(case)))
                run_b = artifact_manifest.load_json(M2 / "partial" / ("{0}-run-b.manifest.json".format(case)))
                self.assertEqual(run_a["content_sha256"], run_b["content_sha256"])
                self.assertEqual(
                    sorted(item["path"] for item in run_a["artifacts"]),
                    sorted(item["path"] for item in run_b["artifacts"]),
                )
        r1 = artifact_manifest.load_json(M2 / "partial" / "r1-run-a.manifest.json")
        r1_paths = sorted(item["path"] for item in r1["artifacts"])
        self.assertEqual(
            [p for p in r1_paths if p.startswith("state.")],
            ["state.0.2.dat", "state.1.2.dat", "state.2.2.dat",
             "state.3.2.dat", "state.4.2.dat", "state.5.2.dat"],
        )
        self.assertIn("fmStarts.2.npy", r1_paths)
        self.assertIn("fmDeltas.2.npy", r1_paths)
        r2 = artifact_manifest.load_json(M2 / "partial" / "r2-run-a.manifest.json")
        self.assertEqual(
            sorted(item["path"] for item in r2["artifacts"]),
            R2_CLEAN_FILES,
        )

    def test_determinism_report_proves_repeatability(self) -> None:
        det = load_json(M2 / "determinism-run-a-run-b.json")

        self.assertEqual(det["format"], "msbwt-legacy-compression-milestone2-determinism-v1")
        self.assertEqual(det["runs"], ["run-a", "run-b"])
        self.assertTrue(det["r1"]["partial_manifests_identical"])
        self.assertTrue(det["r1"]["resumed_trees_identical"])
        self.assertTrue(det["r1"]["clean_trees_identical"])
        self.assertTrue(det["r1"]["run_a"]["resume_equals_clean"]["tree_equal"])
        self.assertTrue(det["r1"]["run_b"]["resume_equals_clean"]["tree_equal"])
        self.assertTrue(det["r2"]["partial_manifests_identical"])
        self.assertTrue(det["r2"]["resumed_trees_identical"])
        self.assertTrue(det["r2"]["clean_trees_identical"])
        self.assertTrue(det["r2"]["run_a"]["resume_equals_clean"]["clean_retains_backup"])
        self.assertTrue(det["r2"]["run_a"]["resume_equals_clean"]["recovered_removes_backup"])
        self.assertTrue(det["r2"]["run_b"]["resume_equals_clean"]["clean_retains_backup"])
        self.assertTrue(det["r2"]["run_b"]["resume_equals_clean"]["recovered_removes_backup"])
        self.assertEqual(
            det["r1"]["run_a"]["resumed_primary"]["sha256"], R1_PRIMARY_SHA256)
        self.assertEqual(
            det["r1"]["run_b"]["resumed_primary"]["sha256"], R1_PRIMARY_SHA256)
        self.assertEqual(
            det["r2"]["run_a"]["resumed_primary"]["sha256"], R2_PRIMARY_SHA256)
        self.assertEqual(
            det["r2"]["run_b"]["resumed_primary"]["sha256"], R2_PRIMARY_SHA256)
        assert_sanitized(M2 / "determinism-run-a-run-b.json")

    def test_reader_evidence_resumed_equals_clean(self) -> None:
        reader = load_json(M2 / "reader-evidence.json")

        self.assertEqual(reader["format"], "msbwt-legacy-compression-milestone2-reader-evidence-v1")
        self.assertTrue(reader["resumed_equals_clean"]["r1"]["resumed_equals_clean"])
        self.assertTrue(reader["resumed_equals_clean"]["r2"]["resumed_equals_clean"])
        for label in ("r1-resumed-run-a.json", "r1-clean-run-a.json",
                      "r1-resumed-run-b.json", "r1-clean-run-b.json"):
            record = reader["readers"][label]
            self.assertEqual(record["reader_class"], "RLE_BWT")
            self.assertEqual(record["total_size"], 48)
            self.assertEqual(record["dollar_count"], 8)
            self.assertEqual(record["status"], "passed")
            self.assertTrue(record["actual_queries_equal_expected"])
            self.assertTrue(record["recovered_equal"])
        for label in ("r2-resumed-run-a.json", "r2-clean-run-a.json",
                      "r2-resumed-run-b.json", "r2-clean-run-b.json"):
            record = reader["readers"][label]
            self.assertEqual(record["reader_class"], "ByteBWT")
            self.assertEqual(record["total_size"], 1110)
            self.assertEqual(record["dollar_count"], 259)
            self.assertEqual(record["status"], "passed")
            self.assertTrue(record["actual_queries_equal_expected"])
            self.assertTrue(record["recovered_equal"])
        assert_sanitized(M2 / "reader-evidence.json")

    def test_backup_classification_is_an_auxiliary_checkpoint_artifact(self) -> None:
        record = load_json(M2 / "backup-256-npy-classification.json")

        self.assertEqual(
            record["format"], "msbwt-legacy-compression-milestone2-backup-classification-v1")
        self.assertEqual(record["file"], "backup.256.npy")
        self.assertEqual(record["sha256"], R2_BACKUP_SHA256)
        self.assertEqual(
            record["classification"],
            "clean-path retained recovery/checkpoint artifact; not a primary MSBWT result",
        )
        assert_sanitized(M2 / "backup-256-npy-classification.json")

    def test_failpoint_records_are_sanitized_and_exit_86(self) -> None:
        # One canonical failpoint record per case is committed (run-a); the
        # adapter is deterministic for a given checkpoint message and the
        # partial/resumed/clean determinism is proven separately for both runs.
        for case, message in (
            ("r1", "Finished iteration 2 in"),
            ("r2", "Backup creation finished."),
        ):
            with self.subTest(case=case):
                record = load_json(M2 / "failpoint" / ("{0}-run-a.json".format(case)))
                self.assertEqual(record["adapter"], "failpoint_adapter.py")
                self.assertEqual(record["exit_code"], 86)
                self.assertEqual(record["case"], case)
                self.assertEqual(record["dataset"], "PARTIAL")
                self.assertTrue(record["triggering_message"].startswith(message))
                self.assertTrue(record["failpoint_log_sha256"])
                assert_sanitized(M2 / "failpoint" / ("{0}-run-a.json".format(case)))

    def test_no_committed_golden_mutated_by_milestone_two_promotion(self) -> None:
        # the existing milestone-1 and byte goldens are untouched
        self.assertEqual(
            hashlib.sha256(
                (GOLDEN_ROOT / "uniform-direct-split" / PROFILE_ID / ROUTE
                 / "artifacts" / "comp_msbwt.npy").read_bytes()).hexdigest(),
            R1_PRIMARY_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(
                (GOLDEN_ROOT / "uniform-multifile" / PROFILE_ID / ROUTE
                 / "build" / "artifacts" / "msbwt.npy").read_bytes()).hexdigest(),
            "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f",
        )


if __name__ == "__main__":
    unittest.main()
