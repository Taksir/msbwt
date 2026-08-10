"""Read-only host-side regression tests for msbwt-modern2 multi-block
decompression (milestone 4: the second documented decompression
index-boundary correction, `int(self.refFM[endBlock+1])+1` at the
MUS/MultiStringBWT.py:630 site).

These tests run under the host Python 3 (like the other compat tests) and
protect the committed modern2 multi-block decompression evidence, the
committed legacy m3c2 failure contract, and the minimality of the milestone-4
source correction without requiring the WSL Python-2 environment.  The runtime
build/decompression validation lives in
packages/msbwt-modern2/validate/decompression-milestone4.sh (WSL).
"""

import json
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
PACKAGE = REPOSITORY_ROOT / "packages" / "msbwt-modern2"
GOLDENS = REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0"
EVIDENCE = PACKAGE / "evidence" / "decompression-milestone4.json"
M3C2_RELATIONSHIP = GOLDENS / "compression-milestone3" / "relationship-m3c2.json"
M3C2_MANIFEST = GOLDENS / "compression-milestone3" / "partial" / "m3c2-run-a.manifest.json"

EVIDENCE_PRIMARY_SHA256 = "24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35"
RLE_PRIMARY_SHA256 = "681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99"
PAYLOAD_SHA256 = "7c27ccd61dec44ede4a02c883459eef78f5d909b8f30be327584c1a24391cc78"
TOTAL_SIZE = 1056000
WORK_SIZE = 1000000
EXPECTED_COUNTS = {"$": 176000, "A": 198000, "C": 198000,
                   "G": 198000, "N": 88000, "T": 198000}

# string-level FM counts on the tiled payload (recorded in the evidence
# reader gate; collection-semantics counts are not applicable to the tiled
# byte string)
EXPECTED_FM_COUNTS = {
    "A": 198000, "AC": 37125, "ACGTN": 111, "AAAAA": 243, "AAAAAA": 45,
    "C": 198000, "CG": 37125, "GT": 37125, "GTGGGTTT": 2, "N": 88000,
    "NACGT": 108, "T": 198000, "TTTTT": 249,
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class ValidationDriverTests(unittest.TestCase):
    def test_driver_present_and_runs_both_process_counts(self):
        driver = PACKAGE / "validate" / "decompression-milestone4.sh"
        text = driver.read_text(encoding="utf-8")
        for token in ("run_decompress", "p1-run-a", "p1-run-b",
                      "p2-run-a", "p2-run-b", "verify_reader",
                      "verify_reader_evidence", "build_evidence",
                      "decompression-milestone4"):
            self.assertIn(token, text)
        self.assertIn("681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99",
                      text)
        self.assertIn("24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35",
                      text)

    def test_driver_uses_independent_tooling_and_legacy_evidence(self):
        driver = (PACKAGE / "validate" / "decompression-milestone4.sh").read_text(
            encoding="utf-8")
        self.assertIn("artifact_manifest.py", driver)
        self.assertIn("bwt_oracle.py", driver)
        self.assertIn("compression-milestone3/relationship-m3c2.json", driver)
        self.assertIn("decode_npy_rle_primary", driver)


class EvidenceTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = load_json(EVIDENCE)
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "codex/modern2")
        self.assertEqual(evidence["final"]["milestone"],
                         "modern2-milestone4-multiblock-decompression")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["py2_tests"]["status"], "ok")

    def test_evidence_decompression_matches_success_contract(self):
        evidence = load_json(EVIDENCE)
        decomp = evidence["decompression"]
        det = decomp["determinism"]
        self.assertTrue(det["p1_run_a_eq_p1_run_b"])
        self.assertTrue(det["p2_run_a_eq_p2_run_b"])
        self.assertTrue(det["p1_eq_p2"])
        self.assertTrue(det["source_side_effect_determinism"])
        for run in ("p1-run-a", "p1-run-b", "p2-run-a", "p2-run-b"):
            record = decomp["runs"][run]
            self.assertEqual(record["whole_sha256"], EVIDENCE_PRIMARY_SHA256, run)
            self.assertEqual(record["dtype"], "|u1", run)
            self.assertEqual(record["shape"], [TOTAL_SIZE], run)
            self.assertIn("'shape': (1056000,),", record["header_text"], run)
            self.assertEqual(record["payload_sha256"], PAYLOAD_SHA256, run)
            self.assertTrue(record["payload_matches_expectation"], run)
            self.assertEqual(record["symbol_counts"], EXPECTED_COUNTS, run)
            self.assertEqual(record["destination_files"], ["msbwt.npy"], run)
            self.assertEqual(record["source_files"],
                             ["comp_fmIndex.npy", "comp_msbwt.npy",
                              "comp_refIndex.npy", "totalCounts.p"], run)

    def test_evidence_block_boundaries_exact(self):
        evidence = load_json(EVIDENCE)
        boundaries = evidence["decompression"]["block_boundaries"]
        self.assertEqual(boundaries["boundary"], 1000000)
        self.assertEqual(boundaries["worksize"], 1000000)
        self.assertEqual(boundaries["regions"],
                         [[0, 1000000], [1000000, 1056000]])
        neighborhood = boundaries["neighborhood"]
        self.assertEqual(sorted(int(key) for key in neighborhood),
                         [0, 1, 999998, 999999, 1000000, 1000001, 1000002,
                          1055998, 1055999])
        for position, entry in neighborhood.items():
            self.assertTrue(entry["match"], position)
            self.assertEqual(entry["decoded"], entry["expected"], position)

    def test_evidence_reader_gate(self):
        evidence = load_json(EVIDENCE)
        report = evidence["reader_determinism"]
        self.assertTrue(report["deterministic_across_reader_loads"])
        self.assertTrue(report["query_counts_are_string_level_fm_counts"])
        self.assertTrue(report["collection_semantics_not_applicable"])
        self.assertEqual(report["queries"], EXPECTED_FM_COUNTS)
        for label, record in evidence["reader"].items():
            self.assertEqual(record["reader_class"],
                             "MUSCython.ByteBWTCython.ByteBWT", label)
            self.assertEqual(record["total_size"], TOTAL_SIZE, label)
            self.assertEqual(record["dollar_count"], 176000, label)
            self.assertEqual(record["queries"], EXPECTED_FM_COUNTS, label)
            added = {item["path"]: item["sha256"]
                     for item in record["side_effects"]["added"]}
            self.assertEqual(sorted(added), ["fmIndex.npy", "totalCounts.npy"], label)
            self.assertEqual(record["side_effects"]["changed"], [], label)
            self.assertEqual(record["side_effects"]["removed"], [], label)

    def test_evidence_legacy_m3c2_failure_contract(self):
        relationship = load_json(M3C2_RELATIONSHIP)
        self.assertEqual(relationship["worker"]["exception_type"], "IndexError")
        self.assertEqual(
            relationship["worker"]["exception"],
            "only integers, slices (`:`), ellipsis (`...`), numpy.newaxis (`None`) and integer or boolean arrays are valid indices")
        self.assertIn("MUS/MultiStringBWT.py\", line 630",
                      relationship["worker"]["traceback_locations"])
        self.assertEqual(relationship["worker"]["exit_code"], 87)
        self.assertEqual(relationship["worker"]["first_tuple"],
                         ["SOURCE", "DESTINATION", 0, 1000000])
        self.assertEqual(relationship["clean_compression"]["shape"], [484000])
        self.assertEqual(relationship["clean_compression"]["primary_sha256"],
                         RLE_PRIMARY_SHA256)
        self.assertEqual(relationship["evidence_primary"]["shape"], [TOTAL_SIZE])
        self.assertEqual(relationship["evidence_primary"]["sha256"],
                         EVIDENCE_PRIMARY_SHA256)
        self.assertEqual(relationship["destination"]["primary_sha256"],
                         "d77f2be75db0b24fac38eb10296701625652fc7c98d77ebf9cf59b53fcd0a691")
        manifest = load_json(M3C2_MANIFEST)
        self.assertEqual(manifest["content_sha256"],
                         "aa9815561102054a366db6992b7c5504dbe0b1c77a836c074e27eb92a290f33e")
        self.assertEqual(manifest["artifacts"][0]["npy"]["payload_size"], TOTAL_SIZE)
        self.assertEqual(manifest["artifacts"][0]["npy"]["payload_sha256"],
                         "75855919076ba96440de78fc73f23378edaddb409dbef7dc865f43d5d60b2948")


class MultiBlockFixSourceTests(unittest.TestCase):
    """The milestone-4 correction is exactly the one-line boundary fix.

    ``packages/msbwt-modern2/MUS/MultiStringBWT.py`` must differ from the
    frozen original (LF-normalized) ONLY in the two documented decompression
    index-boundary corrections; the milestone-4 site is
    ``endRange = int(self.refFM[endBlock+1])+1``.  The frozen source keeps the
    original failing arithmetic so the historical contract stays reproducible.
    """

    def test_frozen_multi_string_bwt_untouched(self):
        import hashlib
        digest = hashlib.sha256((REPOSITORY_ROOT / "MUS" /
                                 "MultiStringBWT.py").read_bytes()).hexdigest()
        self.assertEqual(digest,
                         "95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0")

    def test_modern2_contains_both_documented_corrections(self):
        text = (PACKAGE / "MUS" / "MultiStringBWT.py").read_text(encoding="utf-8")
        self.assertIn("endRange = int(self.refFM[endBlock+1])+1", text)
        self.assertIn("runLength = int(counts[lInd])", text)

    def test_frozen_failure_site_still_holds_original_arithmetic(self):
        frozen = (REPOSITORY_ROOT / "MUS" / "MultiStringBWT.py").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn("endRange = self.refFM[endBlock+1]+1", frozen)
        self.assertIn("ret[s:s+counts[lInd]] = letters[lInd]", frozen)


if __name__ == "__main__":
    unittest.main()
