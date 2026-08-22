"""Host-side regression tests for msbwt-modern2 milestone 9: GenericMerge
migration + the public merge CLI end-to-end.

These tests are read-only and run on any CPython 3; they validate the
executed evidence record, the committed secondary-regenerated-source merge
oracle contracts, the migrated `GenericMerge` source policy, the modern2
`merge -p 1` fix whitelist (MUS/CommandLineInterface.py differs from the
frozen original by exactly one added line), and the preserved historical
defect evidence (committed `GenericMerge.c` SIGSEGV + frozen `merge -p 1`
UnboundLocalError).
"""

import difflib
import hashlib
import json
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPOSITORY_ROOT / "packages" / "msbwt-modern2"
from modern2_source_acceptance import assert_source_within_acceptance

EVIDENCE = PACKAGE / "evidence" / "generic-merge-milestone9.json"
DRIVER = PACKAGE / "validate" / "generic-merge-milestone9.sh"
GOLDENS = REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0"
MILESTONE = GOLDENS / "merge-milestone1"

MERGED_PRIMARY_SHA256 = "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"
MERGED_PAYLOAD_SHA256 = "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e"
INTERLEAVE_SHA256 = "4a6d97a36e9ef4e3c19fb873b7713a9357d207d29433a3eca67a41cc4221afd6"
INTERLEAVE_PAYLOAD_SHA256 = "688c323fa4aed411bb303322c616e6640e31fffdf707d0a596fad2c4f386ca2b"
INPUT_A_SHA256 = "e277c7e5c529808c230fb9dae61626a24eeddad54df2f38e22357a12520f69a1"
INPUT_B_SHA256 = "15f40b98ce3310dfe71c15c34509075e68a271bcc93b125b7005cd2b8f82ff08"
FROZEN_GENERICMERGE_PYX = "fe8b699c73a0e671b63cbbe7f2eeba941b91a321156a02df44bf0e010cedce87"
FROZEN_CLI_PY = "5265558e9a04e41eab33493a4fed440e2c640c1198b99ae493810647d1b23189"
FROZEN_MULTISTRINGBWT_PY = "95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0"
SYMBOL_COUNTS_EXPECTED = {"$": 8, "A": 9, "C": 9, "G": 9, "N": 4, "T": 9}
MERGED_READS = ["AAAAA", "ACGTN", "ACGTN", "ACGTN",
                "CCCCC", "GGGGG", "NACGT", "TTTTT"]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unified_added_removed(frozen: Path, modern: Path):
    frozen_text = frozen.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    modern_text = modern.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    diff = list(difflib.unified_diff(
        frozen_text.splitlines(), modern_text.splitlines(), lineterm=""))
    added = [line[1:] for line in diff
             if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:] for line in diff
               if line.startswith("-") and not line.startswith("---")]
    return added, removed


class ValidationDriverTests(unittest.TestCase):
    def test_driver_present_and_uses_independent_tooling(self):
        text = DRIVER.read_text(encoding="utf-8")
        self.assertIn("generic-merge-milestone9", text)
        self.assertIn("bwt_oracle.py", text)
        self.assertIn("relationship-reader.json", text)
        self.assertIn("--evidence", text)
        self.assertIn("gate_input_side_effects", text)
        self.assertIn("gate_oracle", text)
        self.assertIn("secondary-regenerated-source", text)


class EvidenceTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = load_json(EVIDENCE)
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "codex/modern2")
        self.assertEqual(evidence["final"]["milestone"],
                         "modern2-milestone9-generic-merge")
        self.assertEqual(evidence["final"]["oracle_class"],
                         "secondary-regenerated-source")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["py2_tests"]["status"], "ok")

    def test_evidence_merged_trees_match_committed_oracle(self):
        evidence = load_json(EVIDENCE)
        expected_msbwt = "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f 176 msbwt.npy"
        expected_inter = "4a6d97a36e9ef4e3c19fb873b7713a9357d207d29433a3eca67a41cc4221afd6 135 inter0.npy"
        for key in ("p1_run_a_tree", "p1_run_b_tree",
                    "p2_run_a_tree", "p2_run_b_tree"):
            self.assertEqual(evidence["merged"][key],
                             [expected_inter, expected_msbwt], key)

    def test_evidence_primary_bytes(self):
        evidence = load_json(EVIDENCE)
        primary = evidence["primary"]
        self.assertEqual(primary["whole_sha256"], MERGED_PRIMARY_SHA256)
        self.assertEqual(primary["payload_sha256"], MERGED_PAYLOAD_SHA256)
        self.assertEqual(primary["header_len"], 118)
        self.assertEqual(primary["size"], 176)
        self.assertIn("(48L,)", primary["header_text"])
        self.assertIn("'descr': '|u1'", primary["header_text"])
        self.assertEqual(primary["shape"], [48])

    def test_evidence_interleave_bytes(self):
        evidence = load_json(EVIDENCE)
        inter = evidence["interleave"]
        self.assertEqual(inter["whole_sha256"], INTERLEAVE_SHA256)
        self.assertEqual(inter["payload_sha256"], INTERLEAVE_PAYLOAD_SHA256)
        self.assertEqual(inter["size"], 135)
        self.assertEqual(inter["shape"], [7])
        self.assertIn("(7,)", inter["header_text"])

    def test_evidence_determinism_p1_p2(self):
        evidence = load_json(EVIDENCE)
        det = evidence["determinism"]
        self.assertTrue(det["p1_run_a_equals_run_b"])
        self.assertTrue(det["p2_run_a_equals_run_b"])
        self.assertTrue(det["p1_equals_p2"])
        self.assertTrue(evidence["merged_vs_clean"]["whole_file_equal"])
        self.assertEqual(evidence["merged_vs_clean"]["msbwt_sha256"],
                         MERGED_PRIMARY_SHA256)
        self.assertEqual(evidence["output_files"]["output_files"],
                         ["inter0.npy", "msbwt.npy"])
        self.assertEqual(evidence["output_files"]["derived_in_output"], [])

    def test_evidence_input_side_effects(self):
        evidence = load_json(EVIDENCE)
        self.assertEqual(evidence["input_side_effects"]["in_a"],
                         ["fmIndex.npy", "totalCounts.npy"])
        self.assertEqual(evidence["input_side_effects"]["in_b"],
                         ["fmIndex.npy", "totalCounts.npy"])
        self.assertIn("loadBWT(useMemmap=True)",
                      evidence["input_side_effects"]["classification"])

    def test_evidence_reader_matches_committed_relationship_reader(self):
        evidence = load_json(EVIDENCE)
        reader = evidence["reader"]
        relationship = load_json(MILESTONE / "relationship-reader.json")
        smoke = relationship["reader_smoke"]
        self.assertEqual(reader["reader_class"],
                         "MUSCython.ByteBWTCython.ByteBWT")
        self.assertEqual(reader["total_size"], smoke["total_size"])
        self.assertEqual(reader["dollar_count"], smoke["dollar_count"])
        self.assertTrue(reader["queries_match_committed"])
        self.assertTrue(reader["recovery_matches_committed"])
        self.assertTrue(reader["side_effects_match_committed"])
        self.assertTrue(reader["regeneration_bytes_identical"])
        self.assertFalse(reader["interleave_required_by_reader"])
        self.assertEqual(reader["added_files"],
                         {name: {"sha256": digest, "size": size}
                          for name, (digest, size) in {
                              "fmIndex.npy": ("a5b4bf06726fcadf535245d03ef65e04a4a5248d368b3aa53639c190028b933f", 176),
                              "totalCounts.npy": ("ea104b616fe89d7b786acdff7ca0db61f6339a59c31fbf0fff066ad7384c1c2b", 176),
                          }.items()})
        self.assertEqual(reader["classification"],
                         {"primary_persistent": ["msbwt.npy"],
                          "merge_provenance_not_reader_required": ["inter0.npy"],
                          "lazy_deletable_regenerable": ["totalCounts.npy", "fmIndex.npy"]})
        self.assertEqual(reader["recovered_strings"],
                         ["$AAAAA", "$ACGTN", "$ACGTN", "$ACGTN",
                          "$CCCCC", "$GGGGG", "$NACGT", "$TTTTT"])

    def test_evidence_cli_query(self):
        evidence = load_json(EVIDENCE)
        query = evidence["cli_query"]
        self.assertEqual(query["count_text"], "3")
        self.assertEqual(query["dumped_strings"],
                         ["ACGTN", "ACGTN", "ACGTN"])
        self.assertEqual(len(query["count_stdout_sha256"]), 64)
        self.assertEqual(len(query["dump_stdout_sha256"]), 64)

    def test_evidence_oracle_all_checks_pass(self):
        evidence = load_json(EVIDENCE)
        oracle = evidence["oracle"]
        self.assertTrue(oracle["rotation_prediction_matches"])
        self.assertTrue(oracle["symbol_counts_match"])
        self.assertEqual(oracle["symbol_counts"], SYMBOL_COUNTS_EXPECTED)
        self.assertEqual(oracle["kmers_checked"], 36)
        self.assertEqual(oracle["backward_mismatch_count"], 0)
        self.assertTrue(oracle["lf_recovery_matches"])
        self.assertEqual(oracle["lf_recovery"], MERGED_READS)
        inter = oracle["interleave_verification"]
        self.assertEqual(inter["zero_count"], 24)
        self.assertEqual(inter["one_count"], 24)
        self.assertEqual(inter["unique_a_positions"], 12)
        self.assertEqual(inter["unique_b_positions"], 18)
        self.assertEqual(inter["tied_positions_count"], 18)
        self.assertEqual(inter["unambiguous_mismatches"], 0)
        self.assertEqual(len(inter["blocks"]), 36)
        self.assertTrue(all(block["matched"] for block in inter["blocks"]))

    def test_evidence_source_policy(self):
        evidence = load_json(EVIDENCE)
        source = evidence["source"]
        self.assertEqual(source["frozen_GenericMerge_pyx_sha256"],
                         FROZEN_GENERICMERGE_PYX)
        self.assertEqual(source["frozen_CommandLineInterface_py_sha256"],
                         FROZEN_CLI_PY)
        self.assertEqual(source["frozen_MultiStringBWT_py_sha256"],
                         FROZEN_MULTISTRINGBWT_PY)
        self.assertEqual(source["pyx_diff_added"],
                         ["#cython: language_level=2"])
        self.assertEqual(source["pyx_diff_removed"], [])
        self.assertEqual(source["cli_diff_added"], ["        numProcs = 1"])
        self.assertEqual(source["cli_diff_removed"], [])
        self.assertEqual(source["multistringbwt_added_count"], 7)
        self.assertEqual(source["multistringbwt_removed_count"], 6)


class SourcePolicyTests(unittest.TestCase):
    def test_frozen_sources_untouched(self):
        self.assertEqual(
            sha256_bytes((REPOSITORY_ROOT / "MUSCython" / "GenericMerge.pyx").read_bytes()),
            FROZEN_GENERICMERGE_PYX)
        self.assertEqual(
            sha256_bytes((REPOSITORY_ROOT / "MUS" / "CommandLineInterface.py").read_bytes()),
            FROZEN_CLI_PY)
        self.assertEqual(
            sha256_bytes((REPOSITORY_ROOT / "MUS" / "MultiStringBWT.py").read_bytes()),
            FROZEN_MULTISTRINGBWT_PY)

    def test_modern2_genericmerge_pyx_diff_is_language_level_only(self):
        added, removed = unified_added_removed(
            REPOSITORY_ROOT / "MUSCython" / "GenericMerge.pyx",
            PACKAGE / "MUSCython" / "GenericMerge.pyx")
        # M3-R64-W5 rebaseline: language_level header plus the accepted
        # Windows-portability np.save normalization helper.
        assert_source_within_acceptance(self, "MUSCython/GenericMerge.pyx")
        self.assertIn("#cython: language_level=2", added)
        self.assertIn("def _int_shape(shape):", added)

    def test_modern2_cli_diff_is_exactly_the_numprocs_fix(self):
        added, removed = unified_added_removed(
            REPOSITORY_ROOT / "MUS" / "CommandLineInterface.py",
            PACKAGE / "MUS" / "CommandLineInterface.py")
        # M3-R64-W5 rebaseline: numprocs fix plus W-BINARY-IO CSV open.
        assert_source_within_acceptance(self, "MUS/CommandLineInterface.py")
        self.assertIn("        numProcs = 1", added)

    def test_frozen_cli_still_contains_the_p1_bug_pattern(self):
        # frozen-source regression: the historical -p 1 UnboundLocalError must
        # remain reproducible from the frozen CLI source (numProcs bound only
        # inside the args.numProcesses > 1 branch)
        text = (REPOSITORY_ROOT / "MUS" / "CommandLineInterface.py").read_bytes()
        merge_branch = text[text.find(b"subparserID == 'merge'"):]
        before_branch = merge_branch.split(b"if args.numProcesses > 1:")[0]
        self.assertNotIn(b"numProcs = 1", before_branch)
        after_branch = merge_branch.split(b"if args.numProcesses > 1:")[1]
        self.assertIn(b"numProcs = 1", after_branch)
        self.assertIn(b"GenericMerge.mergeTwoMSBWTs", after_branch)

    def test_modern2_stub_removed(self):
        self.assertFalse((PACKAGE / "MUSCython" / "GenericMerge.py").exists())
        self.assertTrue((PACKAGE / "MUSCython" / "GenericMerge.pyx").exists())
        self.assertTrue((PACKAGE / "MUSCython" / "GenericMerge.c").exists())

    def test_setup_builds_generic_merge(self):
        text = (PACKAGE / "setup.py").read_text(encoding="utf-8")
        self.assertIn("'GenericMerge'", text)

    def test_generated_c_is_cython_3_0_12(self):
        banner = (PACKAGE / "MUSCython" / "GenericMerge.c").read_text(
            encoding="utf-8", errors="replace").splitlines()[0]
        self.assertIn("Generated by Cython 3.0.12", banner)

    def test_generated_c_differs_from_historical_committed_c(self):
        modern = (PACKAGE / "MUSCython" / "GenericMerge.c").read_bytes()
        historical = (REPOSITORY_ROOT / "MUSCython" / "GenericMerge.c").read_bytes()
        self.assertNotEqual(modern, historical)
        # the historical committed C remains the frozen Cython-0.23.4 file
        first_line = historical.split(b"\n", 1)[0]
        self.assertIn(b"Cython 0.23.4", first_line)

    def test_existing_diff_whitelists_unchanged(self):
        # M3-R64-W5 rebaseline: closed-set acceptance whitelist.
        added, removed = unified_added_removed(
            REPOSITORY_ROOT / "MUS" / "MultiStringBWT.py",
            PACKAGE / "MUS" / "MultiStringBWT.py")
        assert_source_within_acceptance(self, "MUS/MultiStringBWT.py")


class CommittedOracleTests(unittest.TestCase):
    def test_committed_secondary_oracle_artifacts_pinned(self):
        manifest = load_json(MILESTONE / "secondary-regenerated-source" / "manifest.json")
        entries = {item["path"]: item for item in manifest["artifacts"]}
        self.assertEqual(entries["msbwt.npy"]["sha256"], MERGED_PRIMARY_SHA256)
        self.assertEqual(entries["msbwt.npy"]["npy"]["payload_sha256"],
                         MERGED_PAYLOAD_SHA256)
        self.assertEqual(entries["msbwt.npy"]["npy"]["shape"], [48])
        self.assertIn("(48L,)", entries["msbwt.npy"]["npy"]["header_text"])
        self.assertEqual(entries["inter0.npy"]["sha256"], INTERLEAVE_SHA256)

    def test_committed_historical_failure_evidence_preserved(self):
        # the two historical merge defect classes stay separate and intact
        segfault = load_json(MILESTONE / "relationship-generic-merge-segfault.json")
        self.assertEqual(segfault["oracle_class"], "historical-generated-c")
        self.assertEqual(segfault["classification"], "LEGACY GENERATED-CODE DEFECT")
        self.assertEqual(segfault["exit_code"], -11)
        p1 = load_json(MILESTONE / "relationship-merge-p1-unboundlocalerror.json")
        self.assertEqual(p1["classification"], "LEGACY SOURCE BUG")
        self.assertIn("numProcs", p1["exception"])
        self.assertIn("modern2", p1["note"])
        # promoted artifacts are labeled secondary-regenerated-source only
        for name in ("relationship-merge-vs-clean.json",
                     "relationship-independent-oracle.json",
                     "relationship-reader.json"):
            self.assertEqual(load_json(MILESTONE / name)["oracle_class"],
                             "secondary-regenerated-source")

    def test_evidence_matches_committed_interleave_blocks(self):
        evidence = load_json(EVIDENCE)
        committed = load_json(MILESTONE / "relationship-independent-oracle.json")
        blocks = {b["rotation"]: b for b in evidence["oracle"]["interleave_verification"]["blocks"]}
        committed_blocks = {b["rotation"]: b
                            for b in committed["interleave_verification"]["blocks"]}
        self.assertEqual(sorted(blocks.keys()), sorted(committed_blocks.keys()))
        for rotation, block in blocks.items():
            other = committed_blocks[rotation]
            self.assertEqual(block["zeros"], other["zeros"], rotation)
            self.assertEqual(block["ones"], other["ones"], rotation)
            self.assertEqual(block["expected_bit"], other["expected_bit"], rotation)


if __name__ == "__main__":
    unittest.main()
