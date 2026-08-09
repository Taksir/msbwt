"""Strict integrity checks for the Merge/Indexing milestone goldens.

The canonical merge baseline is established through the SECONDARY
REGENERATED-SOURCE ORACLE: the frozen ``GenericMerge.pyx`` was regenerated
with the verified profile's pinned Cython 0.29.36 in a disposable build
location.  These tests protect the promoted artifacts and evidence and ensure
the two oracle classes can never be conflated:

- ``secondary-regenerated-source``: the successful merge semantics;
- ``historical-generated-c``: the preserved committed ``GenericMerge.c``
  segfault failure evidence.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = REPOSITORY_ROOT / "compat" / "tools" / "artifact_manifest.py"
SPEC = importlib.util.spec_from_file_location("merge_artifact_manifest", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
artifact_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifact_manifest)

GOLDEN_ROOT = REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0"
MILESTONE = GOLDEN_ROOT / "merge-milestone1"
SECONDARY = MILESTONE / "secondary-regenerated-source"
ARTIFACTS = SECONDARY / "artifacts"

PROFILE_ID = "py27-late-05a7d6d83862"
ROUTE = "pyx-historical-cython"
SOURCE_COMMIT = "7503346ec072ddb89520db86fef85569a9ba093a"
ORACLE_CLASS = "secondary-regenerated-source"

MERGED_PRIMARY_SHA256 = "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"
MERGED_PAYLOAD_SHA256 = "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e"
INTERLEAVE_SHA256 = "4a6d97a36e9ef4e3c19fb873b7713a9357d207d29433a3eca67a41cc4221afd6"
FROZEN_PYX_SHA256 = "fe8b699c73a0e671b63cbbe7f2eeba941b91a321156a02df44bf0e010cedce87"
COMMITTED_C_SHA256 = "9fcf5ec63751c0c3fb56476fa901761fcb218603b5b1c168c645de407343b6ea"
REGENERATED_C_SHA256 = "3116532cb2eeaab0ccfb8a32901b5bee83aabe95a8d34aad878a2d48c03b724c"
SEGFAULT_STDERR_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
P1_STDERR_SHA256 = "186d471d861c4eaf8ef200076742e259182b6e3c050ebe26540fbdf1e7eb3a4c"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def assert_sanitized(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for token in ("/home/", "/mnt/", "Google Drive", "msbwt-oracle", "C:\\", "\\wsl$"):
        assert token not in text, (path, token)


class MergeMilestone1GoldenTests(unittest.TestCase):
    def test_promoted_merged_primary_matches_committed_golden_bytes(self) -> None:
        primary = (ARTIFACTS / "msbwt.npy").read_bytes()
        self.assertEqual(hashlib.sha256(primary).hexdigest(), MERGED_PRIMARY_SHA256)
        committed = (GOLDEN_ROOT / "uniform-multifile" / PROFILE_ID / ROUTE
                     / "build" / "artifacts" / "msbwt.npy").read_bytes()
        self.assertEqual(primary, committed)

    def test_promoted_artifacts_manifest_is_safe_and_consistent(self) -> None:
        manifest = artifact_manifest.load_json(SECONDARY / "manifest.json")
        self.assertEqual(manifest["format"], "msbwt-legacy-artifact-manifest-v1")
        entries = {item["path"]: item for item in manifest["artifacts"]}
        self.assertEqual(sorted(entries.keys()), ["inter0.npy", "msbwt.npy"])
        self.assertEqual(entries["msbwt.npy"]["sha256"], MERGED_PRIMARY_SHA256)
        self.assertEqual(entries["msbwt.npy"]["npy"]["dtype_descriptor"], "|u1")
        self.assertEqual(entries["msbwt.npy"]["npy"]["shape"], [48])
        self.assertEqual(entries["msbwt.npy"]["npy"]["payload_sha256"],
                         MERGED_PAYLOAD_SHA256)
        self.assertEqual(entries["inter0.npy"]["sha256"], INTERLEAVE_SHA256)
        self.assertEqual(entries["inter0.npy"]["npy"]["shape"], [7])

    def test_profile_provenance_pins_the_secondary_oracle_and_defects(self) -> None:
        prov = load_json(MILESTONE / "profile-provenance.json")
        self.assertEqual(prov["format"],
                         "msbwt-legacy-merge-milestone1-profile-provenance-v1")
        self.assertEqual(prov["profile_id"], PROFILE_ID)
        self.assertEqual(prov["route"], ROUTE)
        self.assertEqual(prov["source_commit"], SOURCE_COMMIT)
        self.assertEqual(prov["oracle_class"], ORACLE_CLASS)
        self.assertEqual(prov["canonical_runs"], ["run-a", "run-b"])
        self.assertEqual(prov["merged_primary"]["sha256"], MERGED_PRIMARY_SHA256)
        self.assertEqual(prov["merged_primary"]["shape_literal"], "(48L,)")
        self.assertEqual(prov["interleave"]["sha256"], INTERLEAVE_SHA256)
        self.assertEqual(prov["legacy_defects"]["generated_code"]["classification"],
                         "LEGACY GENERATED-CODE DEFECT")
        self.assertEqual(prov["legacy_defects"]["generated_code"]["provenance"],
                         "Cython 0.23.4")
        self.assertEqual(prov["legacy_defects"]["generated_code"]["merge_p2_exit"], -11)
        self.assertEqual(prov["legacy_defects"]["source_bug"]["classification"],
                         "LEGACY SOURCE BUG")
        self.assertEqual(prov["legacy_defects"]["source_bug"]["stderr_sha256"],
                         P1_STDERR_SHA256)
        assert_sanitized(MILESTONE / "profile-provenance.json")

    def test_regeneration_record_proves_frozen_pyx_unchanged(self) -> None:
        regen = load_json(MILESTONE / "regeneration.json")
        self.assertEqual(regen["oracle_class"], ORACLE_CLASS)
        self.assertEqual(regen["cython_version"], "0.29.36")
        self.assertEqual(regen["pyx_sha256_before"], FROZEN_PYX_SHA256)
        self.assertEqual(regen["pyx_sha256_after"], FROZEN_PYX_SHA256)
        self.assertTrue(regen["pyx_unchanged"])
        self.assertEqual(regen["committed_generated_c_sha256"], COMMITTED_C_SHA256)
        self.assertEqual(regen["regenerated_c_sha256"], REGENERATED_C_SHA256)
        self.assertTrue(regen["regenerated_c_different_from_committed"])
        self.assertIn("force=True", regen["cythonize_source"])
        self.assertEqual(regen["build_argv"], ["setup.py", "build_ext", "--inplace"])
        assert_sanitized(MILESTONE / "regeneration.json")

    def test_determinism_report_proves_repeatability(self) -> None:
        det = load_json(MILESTONE / "determinism-run-a-run-b.json")
        self.assertEqual(det["format"],
                         "msbwt-legacy-merge-milestone1-determinism-v1")
        self.assertEqual(det["oracle_class"], ORACLE_CLASS)
        self.assertEqual(det["runs"], ["run-a", "run-b"])
        self.assertTrue(det["all_gates_passed"])
        for key in ("input_a", "input_b", "clean", "merged",
                    "nameerror", "segfault", "reader"):
            self.assertIn(key, det["determinism"])
            for field, value in det["determinism"][key].items():
                self.assertTrue(value, (key, field))
        self.assertTrue(
            det["determinism"]["merged"]["primary_identical"])
        self.assertTrue(
            det["determinism"]["merged"]["interleave_identical"])
        self.assertTrue(
            det["determinism"]["segfault"]["exit_code_identical"])
        assert_sanitized(MILESTONE / "determinism-run-a-run-b.json")

    def test_merged_equals_clean_and_committed_golden(self) -> None:
        rel = load_json(MILESTONE / "relationship-merge-vs-clean.json")
        self.assertEqual(rel["format"],
                         "msbwt-legacy-merge-milestone1-relationship-merge-vs-clean-v1")
        self.assertEqual(rel["oracle_class"], ORACLE_CLASS)
        self.assertEqual(rel["status"], "passed")
        self.assertEqual(rel["merged_primary_sha256"], MERGED_PRIMARY_SHA256)
        self.assertEqual(rel["clean_primary_sha256"], MERGED_PRIMARY_SHA256)
        self.assertEqual(rel["committed_golden_primary_sha256"], MERGED_PRIMARY_SHA256)
        self.assertTrue(rel["merged_equals_clean_whole_file"])
        self.assertTrue(rel["merged_equals_committed_golden_whole_file"])
        self.assertTrue(rel["promoted_artifact_equals_committed_golden_whole_file"])
        self.assertEqual(rel["merged_primary"]["shape_literal"], "(48L,)")
        self.assertEqual(rel["merged_primary"]["payload_sha256"], MERGED_PAYLOAD_SHA256)
        self.assertEqual(rel["interleave"]["sha256"], INTERLEAVE_SHA256)
        self.assertEqual(rel["output_files"], ["inter0.npy", "msbwt.npy"])
        self.assertEqual(rel["input_side_effects"]["input_a"],
                         ["fmIndex.npy", "totalCounts.npy"])
        assert_sanitized(MILESTONE / "relationship-merge-vs-clean.json")

    def test_independent_oracle_validates_merged_semantics(self) -> None:
        rel = load_json(MILESTONE / "relationship-independent-oracle.json")
        self.assertEqual(rel["format"],
                         "msbwt-legacy-merge-milestone1-relationship-independent-oracle-v1")
        self.assertEqual(rel["oracle_class"], ORACLE_CLASS)
        self.assertEqual(rel["status"], "passed")
        self.assertTrue(rel["merged_payload_equals_oracle_prediction"])
        self.assertEqual(rel["merged_payload_sha256"], MERGED_PAYLOAD_SHA256)
        self.assertTrue(rel["symbol_counts_match"])
        self.assertEqual(rel["symbol_counts"],
                         {"A": 9, "C": 9, "G": 9, "N": 4, "T": 9, "$": 8})
        self.assertTrue(rel["backward_counts_valid"])
        self.assertTrue(rel["lf_recovery_matches"])
        self.assertEqual(rel["decoded_bwt"],
                         "ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$")
        interleave = rel["interleave_verification"]
        self.assertEqual(interleave["zero_count"], 24)
        self.assertEqual(interleave["one_count"], 24)
        self.assertEqual(interleave["tied_positions_count"], 18)
        self.assertEqual(interleave["unambiguous_mismatches"], 0)
        assert_sanitized(MILESTONE / "relationship-independent-oracle.json")

    def test_reader_evidence_and_derived_index_classification(self) -> None:
        rel = load_json(MILESTONE / "relationship-reader.json")
        self.assertEqual(rel["format"],
                         "msbwt-legacy-merge-milestone1-relationship-reader-v1")
        self.assertEqual(rel["oracle_class"], ORACLE_CLASS)
        self.assertEqual(rel["status"], "passed")
        smoke = rel["reader_smoke"]
        self.assertEqual(smoke["reader_class"], "ByteBWT")
        self.assertEqual(smoke["total_size"], 48)
        self.assertEqual(smoke["dollar_count"], 8)
        self.assertTrue(smoke["queries_match"])
        self.assertTrue(smoke["recovery_match"])
        self.assertEqual(rel["cli_query"]["count_text"], "3")
        self.assertEqual(rel["cli_query"]["dumped_strings"],
                         ["ACGTN", "ACGTN", "ACGTN"])
        classification = smoke["classification"]
        self.assertEqual(
            classification["derived_indexes"]["first_load_created"],
            ["fmIndex.npy", "totalCounts.npy"])
        self.assertTrue(
            classification["derived_indexes"]["regenerated_bytes_identical_to_first_load"])
        self.assertFalse(
            classification["interleave"]["required_by_reader"])
        self.assertEqual(rel["derived_index_classification"],
                         {"primary_persistent": ["msbwt.npy"],
                          "merge_provenance_not_reader_required": ["inter0.npy"],
                          "lazy_deletable_regenerable": ["totalCounts.npy", "fmIndex.npy"]})
        assert_sanitized(MILESTONE / "relationship-reader.json")

    def test_historical_generated_c_segfault_preserved_separately(self) -> None:
        rel = load_json(MILESTONE / "relationship-generic-merge-segfault.json")
        self.assertEqual(rel["format"],
                         "msbwt-legacy-merge-milestone1-relationship-generic-merge-segfault-v1")
        self.assertEqual(rel["oracle_class"], "historical-generated-c")
        self.assertEqual(rel["classification"], "LEGACY GENERATED-CODE DEFECT")
        self.assertEqual(rel["committed_generated_c_sha256"], COMMITTED_C_SHA256)
        self.assertEqual(rel["committed_generated_c_provenance"], "Cython 0.23.4")
        self.assertEqual(rel["exit_code"], -11)
        self.assertEqual(rel["signal"], "SIGSEGV")
        self.assertEqual(rel["stderr_sha256"], SEGFAULT_STDERR_SHA256)
        self.assertEqual(rel["output_files"], [])
        self.assertEqual(rel["input_side_effects"],
                         ["fmIndex.npy", "totalCounts.npy"])
        self.assertTrue(rel["deterministic_across_runs"])
        assert_sanitized(MILESTONE / "relationship-generic-merge-segfault.json")

    def test_merge_p1_unboundlocalerror_preserved_separately(self) -> None:
        rel = load_json(MILESTONE / "relationship-merge-p1-unboundlocalerror.json")
        self.assertEqual(rel["format"],
                         "msbwt-legacy-merge-milestone1-relationship-merge-p1-unboundlocalerror-v1")
        self.assertEqual(rel["classification"], "LEGACY SOURCE BUG")
        self.assertEqual(rel["exit_code"], 1)
        self.assertIn("UnboundLocalError", rel["exception"])
        self.assertIn("numProcs", rel["exception"])
        self.assertEqual(rel["stderr_sha256"], P1_STDERR_SHA256)
        self.assertEqual(rel["output_files"], [])
        self.assertTrue(rel["inputs_unchanged"])
        self.assertTrue(rel["deterministic_across_runs"])
        self.assertIn("modern2", rel["note"])
        assert_sanitized(MILESTONE / "relationship-merge-p1-unboundlocalerror.json")

    def test_committed_generic_merge_c_remains_historical_and_untouched(self) -> None:
        # The committed historical generated C is NOT the source of the
        # promoted artifacts; it remains the frozen Cython-0.23.4 file.
        first_line = (REPOSITORY_ROOT / "MUSCython" / "GenericMerge.c").read_bytes().split(b"\n", 1)[0]
        self.assertIn(b"Cython 0.23.4", first_line)
        self.assertEqual(
            hashlib.sha256(
                (REPOSITORY_ROOT / "MUSCython" / "GenericMerge.c").read_bytes()
            ).hexdigest(),
            COMMITTED_C_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(
                (REPOSITORY_ROOT / "MUSCython" / "GenericMerge.pyx").read_bytes()
            ).hexdigest(),
            FROZEN_PYX_SHA256,
        )
        # The promoted merged primary is byte-identical to the previously
        # committed uniform-multifile golden, which itself is untouched.
        self.assertEqual(
            hashlib.sha256(
                (GOLDEN_ROOT / "uniform-multifile" / PROFILE_ID / ROUTE
                 / "build" / "artifacts" / "msbwt.npy").read_bytes()
            ).hexdigest(),
            MERGED_PRIMARY_SHA256,
        )

    def test_oracle_classes_never_conflated(self) -> None:
        # Successful artifacts are labeled secondary-regenerated-source.
        prov = load_json(MILESTONE / "profile-provenance.json")
        self.assertEqual(prov["oracle_class"], "secondary-regenerated-source")
        self.assertEqual(prov["merged_primary"]["path"],
                         "secondary-regenerated-source/artifacts/msbwt.npy")
        # The segfault record is the only historical-generated-c record.
        segfault = load_json(MILESTONE / "relationship-generic-merge-segfault.json")
        self.assertEqual(segfault["oracle_class"], "historical-generated-c")
        for name in ("relationship-merge-vs-clean.json",
                     "relationship-independent-oracle.json",
                     "relationship-reader.json"):
            self.assertEqual(load_json(MILESTONE / name)["oracle_class"],
                             "secondary-regenerated-source")
        # No promoted record claims the untouched historical build produced it.
        segfault_text = (MILESTONE / "relationship-generic-merge-segfault.json").read_text()
        self.assertIn("NOT the semantic behavior", segfault_text)
        self.assertNotIn("secondary-regenerated-source/artifacts", segfault_text)


if __name__ == "__main__":
    unittest.main()
