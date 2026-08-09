"""Strict integrity checks for Compression/Recovery Milestone 3 goldens.

Milestone 3 is non-resumable interruption failure characterization.  These
tests protect the observed frozen behavior:

  m3c1  post-hoc compression interrupted after the first worker bin: the
        destination retains the complete comp_msbwt.npy.temp.0.npy chunk, the
        final primary is absent, and the interrupted chunk is byte-identical to
        the committed uniform-compress-posthoc golden.
  m3c2  post-hoc decompression: the frozen decompressBWTPoolProcess fails on
        the first tuple before completing any region (IndexError at
        MUS/MultiStringBWT.py:630 under this profile), leaving the preallocated
        msbwt.npy all-zero; the source gains the three pure-Python caches.
  m3c3  the unchanged CLI refuses to rerun into either nonempty interrupted
        destination during argument parsing (exit 2).
  m3c4  the uniform byte builder interrupted at "Finished iteration 2 in"
        restarts from scratch (no checkpoint scan); the restarted msbwt.npy is
        byte-identical to the clean control and to the committed uniform byte
        golden, but is labelled restart-from-scratch, never resume.
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
M3 = GOLDEN_ROOT / "compression-milestone3"

POSTHOC_GOLDEN_SHA256 = "53d82b388a9d565afa96ead611d5db964bee199869fd07f96b8c84258ba099a3"
UNIFORM_RLE_PAYLOAD_SHA256 = "6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb"
UNIFORM_BYTE_GOLDEN_SHA256 = "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"
M3C2_EVIDENCE_SHA256 = "24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35"
M3C2_CLEAN_COMPRESSED_SHA256 = "681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99"
M3C2_DESTINATION_SHA256 = "d77f2be75db0b24fac38eb10296701625652fc7c98d77ebf9cf59b53fcd0a691"
ALL_ZERO_1056000_PAYLOAD_SHA256 = "75855919076ba96440de78fc73f23378edaddb409dbef7dc865f43d5d60b2948"
M3C2_SOURCE_SIDE_EFFECTS = ["comp_fmIndex.npy", "comp_refIndex.npy", "totalCounts.p"]
M3C4_STATE_FILES = ["state.0.2.npy", "state.1.2.npy", "state.2.2.npy",
                    "state.3.2.npy", "state.4.2.npy", "state.5.2.npy"]
M3C4_INSERT_FILES = ["inserts.11.2.npy", "inserts.22.2.npy", "inserts.33.2.npy",
                     "inserts.35.2.npy", "inserts.54.2.npy", "inserts.55.2.npy"]
PARTIAL_CONTENT_SHA256 = {
    "m3c1": "3d48b9bf72f11d2a15be3b7239a499f7b1a59b430b4122ce2bd74039009be6f5",
    "m3c2": "aa9815561102054a366db6992b7c5504dbe0b1c77a836c074e27eb92a290f33e",
    "m3c4": "a95ba6d59d59d5c01f6415c0054cdec40b246405fcddecd122ae325a1691a0ab",
}
REFUSAL_STDERR_SHA256 = {
    "m3c1": "a97c170df1ef89f671c2b043cb6ded9a319eeaec7b3ea6bb801359f0d091e73d",
    "m3c2": "99c8220331a0274dc415eb5f1596f14f3b1e90418993ddff094c3f0e04ffbf46",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def assert_sanitized(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "/home/" not in text, path
    assert "/mnt/" not in text, path
    assert "Google Drive" not in text, path
    assert "msbwt-oracle" not in text, path
    assert "milestone3-fresh" not in text, path
    assert "msbwt-env-copy" not in text, path
    assert "C:\\" not in text, path


class CompressionMilestone3GoldenTests(unittest.TestCase):
    def test_profile_provenance_pins_profile_and_key_evidence(self) -> None:
        prov = load_json(M3 / "profile-provenance.json")

        self.assertEqual(
            prov["format"], "msbwt-legacy-compression-milestone3-profile-provenance-v1"
        )
        self.assertEqual(prov["profile_id"], PROFILE_ID)
        self.assertEqual(prov["route"], ROUTE)
        self.assertEqual(prov["source_commit"], SOURCE_COMMIT)
        self.assertEqual(prov["canonical_runs"], ["run-a", "run-b"])
        self.assertEqual(prov["failpoint_exit_code"], 86)
        self.assertEqual(prov["natural_failure_exit_code"], 87)
        self.assertEqual(prov["m3c1"]["interrupted_temp_sha256"], POSTHOC_GOLDEN_SHA256)
        self.assertFalse(prov["m3c1"]["final_primary_present"])
        self.assertEqual(prov["m3c2"]["worker_mode"], "first-tuple-worker-failed-naturally")
        self.assertEqual(prov["m3c2"]["evidence_total_symbols"], 1056000)
        self.assertEqual(prov["m3c2"]["evidence_primary_sha256"], M3C2_EVIDENCE_SHA256)
        self.assertEqual(prov["m3c2"]["clean_compressed_sha256"], M3C2_CLEAN_COMPRESSED_SHA256)
        self.assertEqual(prov["m3c2"]["destination_primary_sha256"], M3C2_DESTINATION_SHA256)
        self.assertEqual(prov["m3c4"]["restart_mode"], "restart-from-scratch")
        self.assertEqual(prov["m3c4"]["restart_primary_sha256"], UNIFORM_BYTE_GOLDEN_SHA256)
        self.assertEqual(prov["parser_refusals"]["m3c1_exit_code"], 2)
        self.assertEqual(prov["parser_refusals"]["m3c2_exit_code"], 2)
        assert_sanitized(M3 / "profile-provenance.json")

    def test_m3c1_interrupted_temp_equals_committed_posthoc_golden(self) -> None:
        rel = load_json(M3 / "relationship-m3c1.json")

        self.assertEqual(rel["format"], "msbwt-legacy-compression-milestone3-relationship-v1")
        self.assertEqual(rel["case"], "m3c1")
        self.assertEqual(rel["status"], "passed")
        self.assertTrue(rel["interrupted_temp_equals_committed_golden"])
        self.assertEqual(rel["interrupted_temp_sha256"], POSTHOC_GOLDEN_SHA256)
        self.assertEqual(rel["interrupted_temp_payload_sha256"], UNIFORM_RLE_PAYLOAD_SHA256)
        self.assertEqual(rel["interrupted_temp_shape_literal"], "(22,)")
        self.assertFalse(rel["final_primary_present"])
        self.assertTrue(rel["source_unchanged"])
        self.assertEqual(rel["failpoint_exit_code"], 86)
        self.assertTrue(rel["partial_deterministic"])
        self.assertTrue(rel["temp_primary_deterministic"])
        self.assertEqual(rel["partial_manifest_content_sha256_run_a"], PARTIAL_CONTENT_SHA256["m3c1"])
        self.assertEqual(rel["partial_manifest_content_sha256_run_b"], PARTIAL_CONTENT_SHA256["m3c1"])
        assert_sanitized(M3 / "relationship-m3c1.json")

    def test_m3c1_promoted_temp_artifact_bytes_match_the_golden(self) -> None:
        evidence = artifact_manifest.load_json(
            M3 / "m3c1-temp-primary-evidence" / "manifest.json")
        temp = next(
            item for item in evidence["artifacts"]
            if item["path"] == "comp_msbwt.npy.temp.0.npy")
        self.assertEqual(temp["sha256"], POSTHOC_GOLDEN_SHA256)
        self.assertEqual(temp["npy"]["dtype_descriptor"], "|u1")
        self.assertEqual(temp["npy"]["shape"], [22])
        self.assertEqual(
            temp["npy"]["payload_sha256"], UNIFORM_RLE_PAYLOAD_SHA256)
        # the interrupted temp chunk is byte-identical to the committed
        # uniform-compress-posthoc comp_msbwt.npy golden
        golden = artifact_manifest.load_json(
            GOLDEN_ROOT / "uniform-compress-posthoc" / PROFILE_ID / ROUTE / "manifest.json")
        golden_comp = next(
            item for item in golden["artifacts"] if item["path"] == "comp_msbwt.npy")
        self.assertEqual(temp["sha256"], golden_comp["sha256"])
        self.assertEqual(evidence["content_sha256"], PARTIAL_CONTENT_SHA256["m3c1"])
        assert_sanitized(M3 / "m3c1-temp-primary-evidence" / "manifest.json")

    def test_m3c2_worker_fails_before_any_region_with_all_zero_primary(self) -> None:
        rel = load_json(M3 / "relationship-m3c2.json")

        self.assertEqual(rel["format"], "msbwt-legacy-compression-milestone3-relationship-v1")
        self.assertEqual(rel["case"], "m3c2")
        self.assertEqual(rel["status"], "passed")
        self.assertEqual(rel["worker"]["mode"], "first-tuple-worker-failed-naturally")
        self.assertEqual(rel["worker"]["exit_code"], 87)
        self.assertEqual(rel["worker"]["exception_type"], "IndexError")
        self.assertEqual(
            rel["worker"]["traceback_locations"][-1], 'MUS/MultiStringBWT.py", line 630')
        self.assertEqual(rel["completed_regions"], 0)
        self.assertEqual(rel["unwritten_regions"], 2)
        self.assertEqual(rel["destination"]["primary_sha256"], M3C2_DESTINATION_SHA256)
        self.assertEqual(rel["destination"]["shape"], [1056000])
        self.assertEqual(rel["destination"]["dtype"], "|u1")
        self.assertFalse(rel["destination"]["region_fingerprint"]["prefix_region_any_nonzero"])
        self.assertFalse(rel["destination"]["region_fingerprint"]["tail_region_any_nonzero"])
        self.assertEqual(rel["source_side_effects"], M3C2_SOURCE_SIDE_EFFECTS)
        self.assertEqual(rel["evidence_primary"]["sha256"], M3C2_EVIDENCE_SHA256)
        self.assertEqual(rel["clean_compression"]["primary_sha256"], M3C2_CLEAN_COMPRESSED_SHA256)
        self.assertEqual(rel["clean_compression"]["shape"], [484000])
        self.assertEqual(rel["clean_compression"]["retained_files"], ["comp_msbwt.npy"])
        self.assertTrue(rel["partial_deterministic"])
        self.assertTrue(rel["destination_primary_deterministic"])
        self.assertEqual(rel["partial_manifest_content_sha256_run_a"], PARTIAL_CONTENT_SHA256["m3c2"])
        self.assertEqual(rel["partial_manifest_content_sha256_run_b"], PARTIAL_CONTENT_SHA256["m3c2"])
        assert_sanitized(M3 / "relationship-m3c2.json")

    def test_m3c2_partial_manifest_records_the_all_zero_preallocation(self) -> None:
        manifest = artifact_manifest.load_json(M3 / "partial" / "m3c2-run-a.manifest.json")
        self.assertEqual(manifest["content_sha256"], PARTIAL_CONTENT_SHA256["m3c2"])
        self.assertEqual([item["path"] for item in manifest["artifacts"]], ["msbwt.npy"])
        primary = manifest["artifacts"][0]
        self.assertEqual(primary["sha256"], M3C2_DESTINATION_SHA256)
        self.assertEqual(primary["npy"]["dtype_descriptor"], "|u1")
        self.assertEqual(primary["npy"]["shape"], [1056000])
        self.assertEqual(primary["npy"]["payload_sha256"], ALL_ZERO_1056000_PAYLOAD_SHA256)

    def test_m3c4_restart_from_scratch_matches_clean_and_committed(self) -> None:
        rel = load_json(M3 / "relationship-m3c4.json")

        self.assertEqual(rel["format"], "msbwt-legacy-compression-milestone3-relationship-v1")
        self.assertEqual(rel["case"], "m3c4")
        self.assertEqual(rel["status"], "passed")
        self.assertEqual(rel["restart"]["mode"], "restart-from-scratch")
        self.assertEqual(rel["restart"]["seen_resume_markers"], [])
        self.assertIn("Generating level 1 insertions", rel["restart"]["seen_from_scratch_markers"])
        self.assertEqual(rel["failpoint_exit_code"], 86)
        self.assertEqual(rel["restart_primary"]["sha256"], UNIFORM_BYTE_GOLDEN_SHA256)
        self.assertEqual(rel["clean_primary"]["sha256"], UNIFORM_BYTE_GOLDEN_SHA256)
        self.assertTrue(rel["relationship"]["tree_equal"])
        self.assertTrue(rel["relationship"]["primary_equal"])
        self.assertTrue(rel["relationship"]["restart_matches_committed_primary"])
        self.assertTrue(rel["relationship"]["clean_matches_committed_primary"])
        self.assertEqual(rel["partial_state_files"], M3C4_STATE_FILES)
        self.assertEqual(rel["partial_insert_files"], M3C4_INSERT_FILES)
        self.assertTrue(rel["partial_deterministic"])
        self.assertEqual(rel["partial_manifest_content_sha256_run_a"], PARTIAL_CONTENT_SHA256["m3c4"])
        self.assertEqual(rel["partial_manifest_content_sha256_run_b"], PARTIAL_CONTENT_SHA256["m3c4"])
        assert_sanitized(M3 / "relationship-m3c4.json")

    def test_partial_manifests_are_identical_across_canonical_runs(self) -> None:
        for case, key in (("m3c1", "m3c1-destination"),
                          ("m3c2", "m3c2-destination"),
                          ("m3c4", "m3c4-partial")):
            run_a = artifact_manifest.load_json(
                M3 / "partial" / ("{0}-run-a.manifest.json".format(case)))
            run_b = artifact_manifest.load_json(
                M3 / "partial" / ("{0}-run-b.manifest.json".format(case)))
            self.assertEqual(run_a["content_sha256"], run_b["content_sha256"])
            self.assertEqual(run_a["content_sha256"], PARTIAL_CONTENT_SHA256[case])
            self.assertEqual(
                sorted(item["path"] for item in run_a["artifacts"]),
                sorted(item["path"] for item in run_b["artifacts"]),
            )
        m3c4 = artifact_manifest.load_json(M3 / "partial" / "m3c4-run-a.manifest.json")
        m3c4_paths = sorted(item["path"] for item in m3c4["artifacts"])
        self.assertEqual([p for p in m3c4_paths if p.startswith("state.")], M3C4_STATE_FILES)
        self.assertEqual([p for p in m3c4_paths if p.startswith("inserts.")], M3C4_INSERT_FILES)
        self.assertIn("seqs.npy.0.npy", m3c4_paths)
        self.assertIn("about.npy", m3c4_paths)

    def test_determinism_report_proves_repeatability(self) -> None:
        det = load_json(M3 / "determinism-run-a-run-b.json")

        self.assertEqual(det["format"], "msbwt-legacy-compression-milestone3-determinism-v1")
        self.assertEqual(det["runs"], ["run-a", "run-b"])
        for case in ("m3c1", "m3c2", "m3c4"):
            self.assertTrue(det["determinism"]["cases"][case]["partial_manifests_identical"])
            self.assertTrue(det["determinism"]["cases"][case]["failpoint_mode_identical"])
            self.assertTrue(det["determinism"]["cases"][case]["failpoint_exit_identical"])
        self.assertTrue(det["determinism"]["cases"]["m3c1"]["temp_primary_identical"])
        self.assertTrue(det["determinism"]["cases"]["m3c2"]["destination_primary_identical"])
        self.assertTrue(det["determinism"]["cases"]["m3c4"]["restart_trees_identical"])
        self.assertTrue(det["determinism"]["cases"]["m3c4"]["clean_trees_identical"])
        self.assertTrue(det["determinism"]["parser_refusals"]["m3c1"]["sanitized_stderr_identical"])
        self.assertTrue(det["determinism"]["parser_refusals"]["m3c2"]["sanitized_stderr_identical"])
        assert_sanitized(M3 / "determinism-run-a-run-b.json")

    def test_failpoint_records_are_sanitized_and_exit_correctly(self) -> None:
        m3c1 = load_json(M3 / "failpoint" / "m3c1-run-a.json")
        self.assertEqual(m3c1["case"], "m3c1")
        self.assertEqual(m3c1["exit_code"], 86)
        self.assertEqual(m3c1["mode"], "first-worker-completed")
        self.assertEqual(m3c1["worker_returned_size"], 22)
        assert_sanitized(M3 / "failpoint" / "m3c1-run-a.json")

        m3c2 = load_json(M3 / "failpoint" / "m3c2-run-a.json")
        self.assertEqual(m3c2["case"], "m3c2")
        self.assertEqual(m3c2["exit_code"], 87)
        self.assertEqual(m3c2["mode"], "first-tuple-worker-failed-naturally")
        self.assertEqual(m3c2["exception_type"], "IndexError")
        self.assertIn('MUS/MultiStringBWT.py", line 630', m3c2["traceback_locations"])
        self.assertEqual(m3c2["first_tuple"], ["SOURCE", "DESTINATION", 0, 1000000])
        assert_sanitized(M3 / "failpoint" / "m3c2-run-a.json")

        m3c4 = load_json(M3 / "failpoint" / "m3c4-run-a.json")
        self.assertEqual(m3c4["case"], "m3c4")
        self.assertEqual(m3c4["exit_code"], 86)
        self.assertTrue(m3c4["triggering_message"].startswith("Finished iteration 2 in"))
        self.assertIn("Generating level 1 insertions...", m3c4["message_texts"])
        assert_sanitized(M3 / "failpoint" / "m3c4-run-a.json")

    def test_parser_refusals_exit_two_with_exact_message(self) -> None:
        for case, cli in (("m3c1", ["compress", "-p", "1", "SOURCE", "DESTINATION"]),
                          ("m3c2", ["decompress", "-p", "1", "SOURCE", "DESTINATION"])):
            with self.subTest(case=case):
                record = load_json(M3 / ("parser-refusal-{0}.json".format(case)))
                self.assertEqual(record["format"],
                                 "msbwt-legacy-compression-milestone3-parser-refusal-v1")
                self.assertEqual(record["case"], case)
                self.assertEqual(record["cli"], cli)
                self.assertEqual(record["exit_code"], 2)
                self.assertEqual(record["run_b_exit_code"], 2)
                self.assertTrue(record["deterministic"])
                self.assertIn("Non-empty directory already exists: 'DESTINATION'",
                              record["sanitized_stderr"])
                self.assertEqual(
                    record["sanitized_stderr_sha256"], REFUSAL_STDERR_SHA256[case])
                assert_sanitized(M3 / ("parser-refusal-{0}.json".format(case)))

    def test_no_committed_golden_mutated_by_milestone_three_promotion(self) -> None:
        self.assertEqual(
            hashlib.sha256(
                (GOLDEN_ROOT / "uniform-multifile" / PROFILE_ID / ROUTE
                 / "build" / "artifacts" / "msbwt.npy").read_bytes()).hexdigest(),
            UNIFORM_BYTE_GOLDEN_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(
                (GOLDEN_ROOT / "uniform-compress-posthoc" / PROFILE_ID / ROUTE
                 / "artifacts" / "comp_msbwt.npy").read_bytes()).hexdigest(),
            POSTHOC_GOLDEN_SHA256,
        )


if __name__ == "__main__":
    unittest.main()
