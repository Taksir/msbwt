"""Strict integrity checks for Compression/Recovery Milestone 1 goldens."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[2]
TOOL_PATH = REPOSITORY_ROOT / "compat" / "tools" / "artifact_manifest.py"
SPEC = importlib.util.spec_from_file_location("compression_artifact_manifest", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
artifact_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifact_manifest)

PROFILE_ID = "py27-late-05a7d6d83862"
ROUTE = "pyx-historical-cython"
SOURCE_COMMIT = "7503346ec072ddb89520db86fef85569a9ba093a"
GOLDEN_ROOT = REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0"
CASE_MANIFEST = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment" / "compression-milestone1-cases.json"
FIXTURE_MANIFEST = REPOSITORY_ROOT / "compat" / "fixtures" / "synthetic" / "fixture-manifest.json"
ORACLE_CASE_MANIFEST = REPOSITORY_ROOT / "reference" / "original-0.3.0" / "environment" / "oracle-cases.json"

ROUTE_CASES = {
    "uniform-compress-posthoc": {
        "operation": "uniform-posthoc",
        "fixture_case": "uniform-multifile",
        "whole_sha256": "53d82b388a9d565afa96ead611d5db964bee199869fd07f96b8c84258ba099a3",
        "shape_literal": "(22,)",
        "artifact_files": ["comp_msbwt.npy"],
        "reader_total_size": 48,
        "reader_dollar_count": 8,
    },
    "nonuniform-compress-posthoc": {
        "operation": "nonuniform-posthoc",
        "fixture_case": "nonuniform-prefix",
        "whole_sha256": "9d19222eaa78c1d89304e79ff14a8a0a5f0c21c3ae979d179f570f1d8d5c1e66",
        "shape_literal": "(16,)",
        "artifact_files": ["comp_msbwt.npy"],
        "reader_total_size": 30,
        "reader_dollar_count": 7,
    },
    "uniform-direct-split": {
        "operation": "uniform-direct-split",
        "fixture_case": "uniform-multifile",
        "whole_sha256": "0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372",
        "shape_literal": "(22L,)",
        "artifact_files": [
            "about.npy", "comp_msbwt.npy", "offsets.npy",
            "seqs.npy.0.npy", "seqs.npy.1.npy", "seqs.npy.2.npy",
            "seqs.npy.3.npy", "seqs.npy.4.npy", "seqs.npy.5.npy",
        ],
        "reader_total_size": 48,
        "reader_dollar_count": 8,
    },
    "uniform-direct-wrapper": {
        "operation": "uniform-direct-wrapper",
        "fixture_case": "uniform-multifile",
        "whole_sha256": "0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372",
        "shape_literal": "(22L,)",
        "artifact_files": ["about.npy", "comp_msbwt.npy"],
        "reader_total_size": 48,
        "reader_dollar_count": 8,
    },
}

UNIFORM_PAYLOAD_SHA256 = "6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb"
UNIFORM_DECODED_BWT = "ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$"
UNIFORM_DECODED_SHA256 = "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e"
NONUNIFORM_DECODED_SHA256 = "7a97b19addd3c41a79dbd6ce5e43609766eca78a971576e1ab2b32e3df80ca03"

DECOMP_STDERR_SHA256 = "227471aa531ec114ada93c2507f6b621df8109d70324b7217285efd518904ac4"
DECOMP_TRACEBACK_LOCATIONS = [
    'MUS/CommandLineInterface.py", line 175',
    'MUS/MSBWTGen.py", line 1203',
    'MUS/MSBWTGen.py", line 1222',
    'MUS/MultiStringBWT.py", line 608',
    'MUS/MultiStringBWT.py", line 662',
]
DECOMP_CASES = {
    "uniform": {
        "compressed_sha256": "53d82b388a9d565afa96ead611d5db964bee199869fd07f96b8c84258ba099a3",
        "compressed_shape": [22],
        "source_manifest_content_sha256": "722451840cfca8ff03edfe11c80ba08fed3949636717febaaf8200f1efdd0bf5",
        "destination_manifest_content_sha256": "2d33197387eafb59f1c9db2834f9da9f24d60a68ff01282f31f1787a0be0093a",
        "output_sha256": "f9450ec830d3eca779fdb8a7df2127cb0117620b3ce3588a1c9d76625b96aa22",
        "output_shape": [48],
        "output_payload_sha256": "17b0761f87b081d5cf10757ccc89f12be355c70e2e29df288b65b30710dcbcd1",
    },
    "nonuniform": {
        "compressed_sha256": "9d19222eaa78c1d89304e79ff14a8a0a5f0c21c3ae979d179f570f1d8d5c1e66",
        "compressed_shape": [16],
        "source_manifest_content_sha256": "38e5d6b9d432215173d0c2f7fcb29b3b746ed7d6b5e72ed9c42259ba9c4567dd",
        "destination_manifest_content_sha256": "e968933ebbd14dc2e73bf50171920cde2795eed23c1164b88268efbe7c5d3292",
        "output_sha256": "df951972060da0644c1da6d1f7e2a318d26f6220c51fd2fccd5e374ebc7b83a3",
        "output_shape": [30],
        "output_payload_sha256": "0679246d6c4216de0daa08e5523fb2674db2b6599c3b72ff946b488a15290b62",
    },
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class CompressionMilestone1GoldenTests(unittest.TestCase):
    def test_case_manifest_pins_the_route_specific_contract(self) -> None:
        manifest = load_json(CASE_MANIFEST)
        self.assertEqual(manifest["format"], "msbwt-legacy-compression-milestone1-cases-v1")
        self.assertEqual(manifest["profile_id"], PROFILE_ID)
        self.assertEqual(manifest["route"], ROUTE)
        contract = manifest["successful_route_contract"]
        for case_id, config in ROUTE_CASES.items():
            route = contract["routes"][config["operation"]]
            self.assertEqual(route["whole_sha256"], config["whole_sha256"], case_id)
            self.assertEqual(route["shape_literal"], config["shape_literal"], case_id)
        self.assertEqual(contract["uniform_payload_sha256"], UNIFORM_PAYLOAD_SHA256)
        self.assertEqual(contract["uniform_decoded_bwt"], UNIFORM_DECODED_BWT)
        self.assertEqual(contract["uniform_decoded_bwt_sha256"], UNIFORM_DECODED_SHA256)
        self.assertEqual(contract["uniform_logical_shape"], [22])
        self.assertEqual(contract["nonuniform_logical_shape"], [16])
        self.assertEqual(manifest["decompression_expected_failure"]["stderr_sha256"], DECOMP_STDERR_SHA256)

    def test_each_route_golden_promotes_exact_bytes_and_decoded_rle(self) -> None:
        for case_id, config in ROUTE_CASES.items():
            with self.subTest(case_id=case_id):
                root = GOLDEN_ROOT / case_id / PROFILE_ID / ROUTE
                artifacts = root / "artifacts"
                expected_manifest = artifact_manifest.load_json(root / "manifest.json")
                actual_manifest = artifact_manifest.inventory_directory(artifacts)
                comparison = artifact_manifest.compare_manifest(expected_manifest, actual_manifest)
                self.assertTrue(comparison["matches"], comparison)
                self.assertEqual(
                    sorted(item["path"] for item in actual_manifest["artifacts"]),
                    config["artifact_files"],
                )
                comp = artifacts / "comp_msbwt.npy"
                self.assertEqual(artifact_manifest.sha256_file(comp), config["whole_sha256"])
                self.assertEqual(expected_manifest["content_sha256"], actual_manifest["content_sha256"])

                decoded = artifact_manifest.load_json(root / "decoded-rle.json")
                fresh = artifact_manifest.decode_npy_rle_primary(comp)
                self.assertEqual(fresh, decoded)
                self.assertEqual(decoded["dtype"], "|u1")
                self.assertEqual(decoded["shape_literal"], config["shape_literal"])
                self.assertEqual(decoded["whole_sha256"], config["whole_sha256"])
                for f in ("manifest.json", "decoded-rle.json", "provenance.json", "reader-smoke.json"):
                    blob = (root / f).read_text(encoding="utf-8")
                    self.assertNotIn("/home/", blob)
                    self.assertNotIn("/mnt/", blob)

                provenance = load_json(root / "provenance.json")
                self.assertEqual(provenance["profile_id"], PROFILE_ID)
                self.assertEqual(provenance["route"], ROUTE)
                self.assertEqual(provenance["source_commit"], SOURCE_COMMIT)
                self.assertEqual(provenance["whole_sha256"], config["whole_sha256"])
                self.assertEqual(provenance["artifact_manifest_sha256"], actual_manifest["content_sha256"])
                self.assertEqual(provenance["operation"], config["operation"])
                self.assertEqual(provenance["fixture_case"], config["fixture_case"])

    def test_uniform_cross_route_semantic_equality_and_route_specific_whole_files(self) -> None:
        root = GOLDEN_ROOT / "compression-milestone1"
        rel = load_json(root / "relationship-uniform-cross-route.json")
        self.assertEqual(rel["status"], "passed")
        self.assertTrue(rel["split_equals_wrapper_whole"])
        self.assertTrue(rel["split_equals_wrapper_shape_literal"])
        self.assertEqual(rel["split_whole_sha256"], rel["wrapper_whole_sha256"])
        self.assertNotEqual(rel["posthoc_whole_sha256"], rel["split_whole_sha256"])
        self.assertEqual(rel["posthoc_shape_literal"], "(22,)")
        self.assertEqual(rel["direct_shape_literal"], "(22L,)")
        self.assertEqual(rel["uniform_payload_sha256"], UNIFORM_PAYLOAD_SHA256)
        self.assertEqual(rel["uniform_decoded_sha256"], UNIFORM_DECODED_SHA256)
        self.assertEqual(rel["uniform_decoded_bwt"], UNIFORM_DECODED_BWT)
        self.assertEqual(rel["uniform_run_count"], 22)
        self.assertEqual(rel["uniform_decoded_length"], 48)
        self.assertTrue(rel["cross_route_payload_equal"])
        self.assertTrue(rel["cross_route_run_signature_equal"])
        self.assertTrue(rel["decoded_matches_committed_byte_primary"])
        self.assertTrue(rel["about_equal"])
        # independently re-derive the three uniform primaries and the committed byte primary
        posts = {n: artifact_manifest.decode_npy_rle_primary(
            GOLDEN_ROOT / n / PROFILE_ID / ROUTE / "artifacts" / "comp_msbwt.npy")
            for n in ("uniform-compress-posthoc", "uniform-direct-split", "uniform-direct-wrapper")}
        self.assertEqual(len({p["payload_sha256"] for p in posts.values()}), 1)
        self.assertEqual(len({p["decoded_sha256"] for p in posts.values()}), 1)
        sigs = [artifact_manifest.run_signature(p["runs"]) for p in posts.values()]
        self.assertEqual(len({tuple(tuple(row) for row in s) for s in sigs}), 1)
        self.assertEqual({p["shape_literal"] for p in posts.values()}, {"(22,)", "(22L,)"})
        byte_primary = artifact_manifest.load_json(
            GOLDEN_ROOT / "uniform-multifile" / PROFILE_ID / ROUTE / "build" / "manifest.json")
        byte_entry = next(e for e in byte_primary["artifacts"] if e["path"] == "msbwt.npy")
        self.assertEqual(byte_entry["npy"]["payload_sha256"], UNIFORM_DECODED_SHA256)

    def test_determinism_within_route_across_runs_and_process_counts(self) -> None:
        det = load_json(GOLDEN_ROOT / "compression-milestone1" / "determinism-run-a-run-b.json")
        self.assertEqual(det["status"], "passed")
        self.assertEqual(det["runs"], ["run-a", "run-b"])
        for op, record in det["operations"].items():
            self.assertTrue(record["run_a_equals_run_b"], op)
            self.assertTrue(record["run_a_equals_run_p2"], op)

    def test_reader_evidence_for_each_route_and_coexistence_preference(self) -> None:
        rle_side_effects = {"comp_fmIndex.npy", "comp_refIndex.npy", "totalCounts.npy"}
        for case_id, config in ROUTE_CASES.items():
            with self.subTest(case_id=case_id):
                reader = load_json(GOLDEN_ROOT / case_id / PROFILE_ID / ROUTE / "reader-smoke.json")
                self.assertEqual(reader["status"], "passed")
                self.assertEqual(reader["reader_class"], "RLE_BWT")
                self.assertEqual(reader["total_size"], config["reader_total_size"])
                self.assertEqual(reader["dollar_count"], config["reader_dollar_count"])
                self.assertEqual(reader["actual_queries"], reader["expected_queries"])
                self.assertEqual(reader["actual_recovered_strings"], reader["expected_recovered_strings"])
                self.assertEqual(
                    {item["path"] for item in reader["side_effects"]["added"]},
                    rle_side_effects,
                )
                self.assertEqual(reader["side_effects"]["changed"], [])
                self.assertEqual(reader["side_effects"]["removed"], [])
        coexist = load_json(GOLDEN_ROOT / "compression-milestone1" / "coexistence-loader-preference.json")
        self.assertEqual(coexist["status"], "passed")
        self.assertEqual(coexist["coexistence_before_removal"]["reader_class"], "ByteBWT")
        self.assertEqual(coexist["coexistence_after_byte_removal"]["reader_class"], "RLE_BWT")
        self.assertEqual(coexist["coexistence_before_removal"]["total_size"], 48)
        self.assertEqual(coexist["coexistence_after_byte_removal"]["total_size"], 48)

    def test_decompression_failure_contract_matches_authoritative_record(self) -> None:
        for case, contract in DECOMP_CASES.items():
            with self.subTest(case=case):
                droot = GOLDEN_ROOT / "compression-milestone1" / "decompression-failure" / case
                record = load_json(droot / "record.json")
                provenance = load_json(droot / "provenance.json")
                self.assertEqual(record["format"], "msbwt-legacy-decompression-failure-record-v1")
                self.assertEqual(record["exit_code"], 1)
                self.assertEqual(record["stderr_sha256"], DECOMP_STDERR_SHA256)
                self.assertEqual(
                    record["exception"],
                    "TypeError: slice indices must be integers or None or have an __index__ method",
                )
                self.assertEqual(record["traceback_locations"], DECOMP_TRACEBACK_LOCATIONS)
                self.assertEqual(
                    record["source_side_effects"],
                    ["comp_fmIndex.npy", "comp_refIndex.npy", "totalCounts.p"],
                )
                self.assertEqual(record["compressed_input_sha256"], contract["compressed_sha256"])
                self.assertEqual(record["compressed_input_shape"], contract["compressed_shape"])
                self.assertEqual(
                    record["source_manifest_content_sha256"], contract["source_manifest_content_sha256"]
                )
                self.assertEqual(
                    record["destination_manifest_content_sha256"], contract["destination_manifest_content_sha256"]
                )
                self.assertEqual(record["preallocated_primary"]["dtype"], "|u1")
                self.assertEqual(record["preallocated_primary"]["shape"], contract["output_shape"])
                self.assertEqual(record["preallocated_primary"]["sha256"], contract["output_sha256"])
                self.assertEqual(
                    record["preallocated_primary"]["payload_sha256"], contract["output_payload_sha256"]
                )
                self.assertTrue(record["stderr_determinism"])
                self.assertTrue(record["source_after_determinism"])
                self.assertTrue(record["destination_determinism"])
                self.assertEqual(provenance["profile_id"], PROFILE_ID)
                self.assertEqual(provenance["source_commit"], SOURCE_COMMIT)

                stderr = (droot / "stderr.txt").read_bytes()
                import hashlib
                self.assertEqual(hashlib.sha256(stderr).hexdigest(), DECOMP_STDERR_SHA256)
                stderr_text = stderr.decode("utf-8")
                for location in DECOMP_TRACEBACK_LOCATIONS:
                    self.assertIn(location, stderr_text)
                self.assertNotIn("/home/", stderr_text)
                self.assertNotIn("/mnt/", stderr_text)

                src_manifest = artifact_manifest.load_json(droot / "source-after-manifest.json")
                dst_manifest = artifact_manifest.load_json(droot / "destination-manifest.json")
                self.assertEqual(src_manifest["content_sha256"], contract["source_manifest_content_sha256"])
                self.assertEqual(dst_manifest["content_sha256"], contract["destination_manifest_content_sha256"])
                self.assertEqual(
                    sorted(item["path"] for item in src_manifest["artifacts"]),
                    ["comp_fmIndex.npy", "comp_msbwt.npy", "comp_refIndex.npy", "totalCounts.p"],
                )
                self.assertEqual(
                    sorted(item["path"] for item in dst_manifest["artifacts"]), ["msbwt.npy"]
                )
                # the unwritten preallocated destination is all zero per |u1 shape
                dst_entry = next(item for item in dst_manifest["artifacts"] if item["path"] == "msbwt.npy")
                self.assertEqual(dst_entry["npy"]["shape"], contract["output_shape"])
                self.assertEqual(dst_entry["npy"]["dtype_descriptor"], "|u1")

    def test_unsupported_nonuniform_direct_compression_is_log_only(self) -> None:
        for key, saved_files in (
            ("nonuniform-cfpp", ["offsets.npy", "seqs.npy"]),
            ("nonuniform-cffq", []),
        ):
            with self.subTest(case=key):
                record = load_json(GOLDEN_ROOT / "compression-milestone1" / "unsupported" / (key + ".json"))
                self.assertEqual(record["format"], "msbwt-legacy-unsupported-record-v1")
                self.assertEqual(record["exit_code"], 0)
                self.assertFalse(record["comp_msbwt_exists"])
                if record.get("after") is not None:
                    after_files = [item["path"] for item in record["after"]["files"]]
                    self.assertEqual(sorted(after_files), saved_files)

    def test_profile_provenance_records_authoritative_environment(self) -> None:
        prov = load_json(GOLDEN_ROOT / "compression-milestone1" / "profile-provenance.json")
        self.assertEqual(prov["format"], "msbwt-legacy-compression-milestone1-profile-provenance-v1")
        self.assertEqual(prov["profile_id"], PROFILE_ID)
        self.assertEqual(prov["route"], ROUTE)
        self.assertEqual(prov["source_commit"], SOURCE_COMMIT)
        self.assertEqual(prov["canonical_runs"], ["run-a", "run-b"])
        self.assertEqual(prov["comparison_run"], "run-p2")
        self.assertEqual(
            prov["fixture_manifest_sha256"],
            artifact_manifest.sha256_file(FIXTURE_MANIFEST),
        )
        self.assertEqual(
            prov["oracle_case_manifest_sha256"],
            artifact_manifest.sha256_file(ORACLE_CASE_MANIFEST),
        )
        self.assertEqual(prov["route_contract"]["uniform_payload_sha256"], UNIFORM_PAYLOAD_SHA256)
        # byte primaries are derived from the committed uncompressed goldens, not regenerated
        self.assertEqual(prov["byte_primaries"]["uniform"]["decoded_sha256"], UNIFORM_DECODED_SHA256)
        self.assertEqual(prov["byte_primaries"]["nonuniform"]["decoded_sha256"], NONUNIFORM_DECODED_SHA256)
        blob = json.dumps(prov, ensure_ascii=True)
        self.assertNotIn("/home/", blob)
        self.assertNotIn("/mnt/", blob)


if __name__ == "__main__":
    unittest.main()