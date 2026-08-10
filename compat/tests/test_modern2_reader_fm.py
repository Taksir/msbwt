"""Read-only host-side regression tests for msbwt-modern2 pure-Python FM
reader milestone 6.

These tests run under the host Python 3 (like the other compat tests) and
protect the committed modern2 pure-FM evidence, the exact minimality of the
fill-line correction in ``MUS/MultiStringBWT.py`` (``np.add.at`` replacing
the frozen float64 ``np.bincount`` in-place add), the modern2 pre-fix failure
probe, and the preserved frozen historical failure contract, without
requiring the WSL Python-2 environment.  The runtime validation lives in
packages/msbwt-modern2/validate/reader-milestone6.sh (WSL).
"""

import difflib
import json
import hashlib
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
PACKAGE = REPOSITORY_ROOT / "packages" / "msbwt-modern2"
EVIDENCE = PACKAGE / "evidence" / "reader-milestone6.json"
PREFIX_PROBE = PACKAGE / "evidence" / "reader-milestone6-prefix-probe.json"

# committed evidence dataset and FM-reader SUCCESS contract constants
EVIDENCE_PRIMARY_SHA256 = "24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35"
RLE_PRIMARY_SHA256 = "681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99"
TOTAL_SIZE = 1056000
POSITIONS = ('0', '1', '2047', '2048', '2049', '999998', '999999',
             '1000000', '1000001', '1055998', '1055999')
COLLECTION_POSITIONS = ('0', '1', '2', '5', '10', '20', '40', '47')
EXPECTED_BYTES = {0: 1, 1: 4, 2047: 2, 2048: 2, 2049: 2, 999998: 0,
                  999999: 0, 1000000: 0, 1000001: 2, 1055998: 5, 1055999: 0}
EXPECTED_FM_COUNTS = {
    "A": 198000, "AC": 37125, "ACGTN": 111, "AAAAA": 243, "AAAAAA": 45,
    "C": 198000, "CG": 37125, "GT": 37125, "GTGGGTTT": 2, "N": 88000,
    "NACGT": 108, "T": 198000, "TTTTT": 249,
}
COLLECTION_QUERIES = {"AAAAA": 1, "ACGTN": 3, "CCCCC": 1, "AGCTA": 0,
                      "AAAAAA": 0, "GGGGG": 1, "NACGT": 1, "TTTTT": 1,
                      "$": 8}
LEGACY_BINCOUNT_ERROR = ("Cannot cast ufunc add output from dtype('float64') "
                         "to dtype('uint64') with casting rule 'same_kind'")
FROZEN_SHA256 = "95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0"
# the modern2 fill-line correction (milestone 6)
FILL_ADDED = "            np.add.at(ret, letters[0:x-1], counts[0:x-1])"
FILL_REMOVED = ("            ret += np.bincount(letters[0:x-1], counts[0:x-1], "
                "minlength=self.vcLen)")


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
        driver = PACKAGE / "validate" / "reader-milestone6.sh"
        text = driver.read_text(encoding="utf-8")
        self.assertIn("reader-milestone6", text)
        self.assertIn("bwt_oracle.py", text)
        self.assertIn("EVIDENCE_PRIMARY_SHA256", text)
        self.assertIn("RLE_PRIMARY_SHA256", text)
        self.assertIn("reader-milestone6-prefix-probe.json", text)
        self.assertIn("--evidence", text)
        self.assertIn("np.add.at(ret, letters[0:x-1], counts[0:x-1])", text)
        self.assertIn("frozen line 725", text)


class EvidenceTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = load_json(EVIDENCE)
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "codex/modern2")
        self.assertEqual(evidence["final"]["milestone"],
                         "modern2-milestone6-pure-fm-reader")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["py2_tests"]["status"], "ok")

    def test_evidence_dataset_hashes(self):
        evidence = load_json(EVIDENCE)
        self.assertEqual(evidence["dataset"]["evidence_primary_sha256"],
                         EVIDENCE_PRIMARY_SHA256)
        self.assertEqual(evidence["dataset"]["rle_primary_sha256"],
                         RLE_PRIMARY_SHA256)
        self.assertEqual(evidence["dataset"]["total_size"], TOTAL_SIZE)
        self.assertEqual(evidence["dataset"]["rle_bins"], 516)
        self.assertEqual(evidence["dataset"]["collection_size"], 48)

    def test_evidence_dtype_root_cause(self):
        evidence = load_json(EVIDENCE)
        dtypes = evidence["dtypes"]
        self.assertEqual(dtypes["ret_dtype"], "uint64")
        self.assertEqual(dtypes["counts_dtype"], "uint64")
        self.assertEqual(dtypes["letters_dtype"], "uint8")
        self.assertEqual(dtypes["bincount_dtype"], "float64")
        self.assertEqual(dtypes["weights_dtype"], "uint64")
        self.assertEqual(dtypes["bincount_sum"], 1278)
        self.assertEqual(dtypes["inplace_add"]["status"], "failed")
        self.assertEqual(dtypes["inplace_add"]["exception_type"], "TypeError")
        self.assertIn("Cannot cast ufunc add output from dtype('float64')",
                      dtypes["inplace_add"]["exception"])
        self.assertEqual(dtypes["np_add_at"]["dtype"], "uint64")
        self.assertTrue(dtypes["np_add_at"]["equals_float_math_result"])
        self.assertEqual(dtypes["np_add_at"]["values"],
                         [int(v) for v in dtypes["math_add_result"]])

    def test_evidence_pure_full_fm_equals_compiled_and_oracle(self):
        evidence = load_json(EVIDENCE)
        ffm = evidence["reader"]["pure_compressed"]["getFullFMAtIndex"]
        oracle = evidence["reader"]["independent_oracle"]["full_fm_at"]
        compiled = evidence["reader"]["compiled"]["rle_getFullFMAtIndex"]
        for position in POSITIONS:
            rec = ffm[position]
            self.assertEqual(rec["status"], "ok", position)
            self.assertEqual(rec["dtype"], "uint64", position)
            self.assertTrue(rec["pure_eq_compiled"], position)
            self.assertTrue(rec["pure_eq_oracle"], position)
            self.assertEqual(rec["value"], oracle[position], position)
            self.assertEqual(rec["compiled"], compiled[position], position)

    def test_evidence_all_symbols_represented(self):
        evidence = load_json(EVIDENCE)
        sym = evidence["reader"]["pure_compressed"]["all_symbols_represented"]
        self.assertEqual(len(sym["final_fm"]), 6)
        self.assertTrue(sym["all_positive"])
        self.assertEqual(sym["final_fm"], sorted(sym["final_fm"]))

    def test_evidence_pure_backward_search_queries_match_oracle(self):
        evidence = load_json(EVIDENCE)
        pure = evidence["reader"]["pure_compressed"]["countOccurrencesOfSeq"]
        oracle = evidence["reader"]["independent_oracle"]["fm_counts"]
        compiled_rle = evidence["reader"]["compiled"]["rle_countOccurrencesOfSeq"]
        compiled_byte = evidence["reader"]["compiled"]["byte_countOccurrencesOfSeq"]
        for kmer, count in EXPECTED_FM_COUNTS.items():
            self.assertEqual(pure[kmer], count, kmer)
            self.assertEqual(compiled_rle[kmer], count, kmer)
            self.assertEqual(compiled_byte[kmer], count, kmer)
        self.assertEqual(pure, oracle)
        self.assertEqual(compiled_rle, oracle)
        self.assertEqual(compiled_byte, oracle)

    def test_evidence_compiled_byte_side_effects_unchanged(self):
        evidence = load_json(EVIDENCE)
        self.assertEqual(evidence["reader"]["compiled"]["byte_side_effects"], {
            "totalCounts.npy": "e7fe29a99498d61a278845772782b10d22256a9556e865704d75a54e160fe348",
            "fmIndex.npy": "16e19742f54504b19ff72d278cea134b6063a0c51eac77f784699659013d8040"})

    def test_evidence_collection_fm_queries_recovery(self):
        evidence = load_json(EVIDENCE)
        col = evidence["reader"]["valid_collection"]
        self.assertEqual(col["total_size"], 48)
        oracle = evidence["reader"]["independent_oracle"]["collection_full_fm_at"]
        for position, rec in col["pure_getFullFMAtIndex"].items():
            self.assertEqual(rec["status"], "ok", position)
            self.assertEqual(rec["dtype"], "uint64", position)
            self.assertTrue(rec["pure_eq_compiled"], position)
            self.assertTrue(rec["pure_eq_oracle"], position)
            self.assertEqual(rec["value"], oracle[position], position)
        self.assertEqual(col["pure_queries"], COLLECTION_QUERIES)
        self.assertEqual(col["byte_queries"], COLLECTION_QUERIES)
        self.assertEqual(col["rle_queries"], COLLECTION_QUERIES)
        self.assertEqual(col["recovery"]["dollar_count"], 8)
        self.assertTrue(col["recovery"]["byte_rle_recovery_equal"])
        self.assertTrue(col["recovery"]["pure_equals_byte_recovery"])
        self.assertEqual(col["byte_reader_side_effects"], {
            "totalCounts.npy": "ea104b616fe89d7b786acdff7ca0db61f6339a59c31fbf0fff066ad7384c1c2b",
            "fmIndex.npy": "a5b4bf06726fcadf535245d03ef65e04a4a5248d368b3aa53639c190028b933f"})

    def test_evidence_frozen_failure_contract_preserved(self):
        evidence = load_json(EVIDENCE)
        pre = evidence["pre_fix"]
        self.assertEqual(pre["frozen_source_sha256"], FROZEN_SHA256)
        self.assertEqual(pre["frozen_getFullFMAtIndex_nonlast_bin"]["exception_type"],
                         "IndexError")
        self.assertIn("line 708",
                      pre["frozen_getFullFMAtIndex_nonlast_bin"]["traceback"])
        self.assertEqual(pre["frozen_getFullFMAtIndex_last_bin"]["exception_type"],
                         "TypeError")
        self.assertIn("line 725",
                      pre["frozen_getFullFMAtIndex_last_bin"]["traceback"])
        self.assertIn(LEGACY_BINCOUNT_ERROR,
                      pre["frozen_getFullFMAtIndex_last_bin"]["exception"])
        self.assertEqual(pre["frozen_collection_getFullFMAtIndex"]["exception_type"],
                         "TypeError")
        self.assertIn("line 725",
                      pre["frozen_collection_getFullFMAtIndex"]["traceback"])

    def test_evidence_modern2_pre_fix_probe_preserved(self):
        evidence = load_json(EVIDENCE)
        m2 = evidence["pre_fix"]["modern2_prefix_probe"]
        self.assertEqual(m2["frozen_source_sha256"], FROZEN_SHA256)
        self.assertEqual(m2["checkout_sha"], "eb45db9 (pre-fix)")
        self.assertEqual(m2["position_2047_exception_type"], "TypeError")
        self.assertIn(LEGACY_BINCOUNT_ERROR, m2["position_2047_exception"])
        self.assertEqual(m2["position_1055998_exception_type"], "TypeError")
        self.assertEqual(m2["ret_dtype"], "uint64")
        self.assertEqual(m2["bincount_dtype"], "float64")
        self.assertEqual(m2["bincount_sum"], 1278)

    def test_prefix_probe_file_records_pre_fix_failure(self):
        probe = load_json(PREFIX_PROBE)
        self.assertEqual(probe["frozen_source_sha256"], FROZEN_SHA256)
        self.assertEqual(probe["checkout_sha"], "eb45db9 (pre-fix)")
        self.assertEqual(probe["dtypes"]["ret"]["dtype"], "uint64")
        self.assertEqual(probe["dtypes"]["bincount_result"]["dtype"], "float64")
        self.assertEqual(probe["dtypes"]["bincount_result_sum"], 1278)
        for position in ("2047", "999998", "1000000", "1055998", "1055999"):
            rec = probe["checkout_pure_getFullFMAtIndex"][position]
            self.assertEqual(rec["status"], "failed", position)
            self.assertEqual(rec["exception_type"], "TypeError", position)
            self.assertIn(LEGACY_BINCOUNT_ERROR, rec["exception"], position)
            self.assertIn("line 726", rec["traceback"], position)
        for position in ("0", "1", "2048", "2049"):
            rec = probe["checkout_pure_getFullFMAtIndex"][position]
            self.assertEqual(rec["status"], "ok", position)
            self.assertEqual(rec["value"],
                             probe["oracle"]["full_fm_at"][position], position)
        # frozen original on the same evidence
        self.assertEqual(probe["frozen_pure_getFullFMAtIndex"]["1055998"]["exception_type"],
                         "TypeError")
        self.assertEqual(probe["frozen_collection_pure_getFullFMAtIndex"]["2"]["exception_type"],
                         "TypeError")


class ReaderFixSourceTests(unittest.TestCase):
    def test_frozen_original_untouched_and_still_fails(self):
        frozen = (REPOSITORY_ROOT / "MUS" / "MultiStringBWT.py").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn(FILL_REMOVED, frozen)
        self.assertNotIn(FILL_ADDED, frozen)
        self.assertEqual(sha256_bytes((REPOSITORY_ROOT / "MUS" /
                                       "MultiStringBWT.py").read_bytes()),
                         FROZEN_SHA256)

    def test_modern2_fill_line_is_exact_integer_accumulation(self):
        modern = (PACKAGE / "MUS" / "MultiStringBWT.py").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn(FILL_ADDED, modern)
        self.assertNotIn(FILL_REMOVED, modern)

    def test_modern2_py_diff_whitelist_held(self):
        added, removed = unified_added_removed(
            REPOSITORY_ROOT / "MUS" / "MultiStringBWT.py",
            PACKAGE / "MUS" / "MultiStringBWT.py")
        self.assertEqual(len(added), 7)
        self.assertEqual(len(removed), 6)
        self.assertEqual(added.count("            endRange = int(self.refFM[binID+1])+1"), 2)
        self.assertEqual(removed.count("            endRange = self.refFM[binID+1]+1"), 2)
        self.assertIn(FILL_ADDED, added)
        self.assertIn(FILL_REMOVED, removed)


if __name__ == "__main__":
    unittest.main()
