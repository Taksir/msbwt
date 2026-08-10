"""Read-only host-side regression tests for msbwt-modern2 reader/index
boundary milestone 5.

These tests run under the host Python 3 (like the other compat tests) and
protect the committed modern2 reader-boundary evidence, the exact
minimality of the reader-side numeric/index fixes (three sites: pure
``CompressedMSBWT.getCharAtIndex`` and ``getFullFMAtIndex`` in
``MUS/MultiStringBWT.py``, plus the compiled ``RLE_BWT.decompressBlocks`` in
``MUSCython/RLE_BWTCython.pyx``), and the documented frozen legacy defect
inside the pure-Python ``getFullFMAtIndex`` fill loop (the float64
``np.bincount`` in-place cast), without requiring the WSL Python-2
environment.  The runtime validation lives in
packages/msbwt-modern2/validate/reader-milestone5.sh (WSL).
"""

import difflib
import json
import hashlib
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
PACKAGE = REPOSITORY_ROOT / "packages" / "msbwt-modern2"
EVIDENCE = PACKAGE / "evidence" / "reader-milestone5.json"

# committed evidence dataset and reader-boundary SUCCESS contract constants
EVIDENCE_PRIMARY_SHA256 = "24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35"
RLE_PRIMARY_SHA256 = "681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99"
TOTAL_SIZE = 1056000
EXPECTED_BYTES = {0: 1, 1: 4, 2047: 2, 2048: 2, 2049: 2, 999998: 0,
                  999999: 0, 1000000: 0, 1000001: 2, 1055998: 5, 1055999: 0}
EXPECTED_FM_COUNTS = {
    "A": 198000, "AC": 37125, "ACGTN": 111, "AAAAA": 243, "AAAAAA": 45,
    "C": 198000, "CG": 37125, "GT": 37125, "GTGGGTTT": 2, "N": 88000,
    "NACGT": 108, "T": 198000, "TTTTT": 249,
}
LEGACY_BINCOUNT_ERROR = ("Cannot cast ufunc add output from dtype('float64') "
                         "to dtype('uint64') with casting rule 'same_kind'")

# the frozen reader sites keep the original arithmetic (legacy contract)
FROZEN_READER_SITES = [
    "            endRange = self.refFM[binID+1]+1",   # getCharAtIndex
    "            endRange = self.refFM[binID+1]+1",   # getFullFMAtIndex
    "        ret += np.bincount(letters[0:x-1], counts[0:x-1], minlength=self.vcLen)",
]
# the modern2 pyx differs from the LF-normalized frozen pyx ONLY by the
# language_level directive and the decompressBlocks endRange correction
PYX_ADDED_LINES = [
    "#cython: language_level=2",
    "            endRange = int(self.refFM[endBlock+1])+1",
]
PYX_REMOVED_LINES = [
    "            endRange = self.refFM[endBlock+1]+1",
]


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
        driver = PACKAGE / "validate" / "reader-milestone5.sh"
        text = driver.read_text(encoding="utf-8")
        self.assertIn("reader-milestone5", text)
        self.assertIn("bwt_oracle.py", text)
        self.assertIn("EVIDENCE_PRIMARY_SHA256", text)
        self.assertIn("RLE_PRIMARY_SHA256", text)
        self.assertIn("--evidence", text)


class EvidenceTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = load_json(EVIDENCE)
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "codex/modern2")
        self.assertEqual(evidence["final"]["milestone"],
                         "modern2-milestone5-reader-index-boundaries")
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

    def test_evidence_pure_getCharAtIndex_all_boundaries(self):
        evidence = load_json(EVIDENCE)
        probes = evidence["reader"]["pure_compressed"]["getCharAtIndex"]
        for position, expected in EXPECTED_BYTES.items():
            self.assertEqual(probes[str(position)], expected, position)

    def test_evidence_pure_getFullFMAtIndex_fix_and_legacy_defect(self):
        evidence = load_json(EVIDENCE)
        probes = evidence["reader"]["pure_compressed"]["getFullFMAtIndex"]
        oracle = evidence["reader"]["independent_oracle"]["full_fm_at"]
        for position in ("0", "1", "2048", "2049"):
            self.assertEqual(probes[position]["value"], oracle[position],
                             position)
        for position in ("2047", "999998", "1000000", "1055999"):
            self.assertEqual(probes[position]["status"], "failed", position)
            self.assertEqual(probes[position]["exception_type"], "TypeError",
                             position)
            self.assertIn(LEGACY_BINCOUNT_ERROR,
                          probes[position]["exception"], position)
            self.assertTrue(probes[position]["legacy_frozen_site"], position)

    def test_evidence_compiled_rle_getBWTRange_ranges(self):
        evidence = load_json(EVIDENCE)
        ranges = evidence["reader"]["compiled_rle"]["getBWTRange"]
        for start, end in ((0, 2048), (0, 1000000), (1000000, 1056000),
                           (1054720, 1056000), (0, TOTAL_SIZE)):
            record = ranges["%d:%d" % (start, end)]
            self.assertTrue(record["payload_equal"], (start, end))
            self.assertTrue(record["pure_equal"], (start, end))

    def test_evidence_compiled_queries_match_oracle(self):
        evidence = load_json(EVIDENCE)
        oracle = evidence["reader"]["independent_oracle"]["fm_counts"]
        for reader in ("compiled_rle", "compiled_byte"):
            queries = evidence["reader"][reader]["countOccurrencesOfSeq"]
            for kmer, count in EXPECTED_FM_COUNTS.items():
                self.assertEqual(queries[kmer], count, (reader, kmer))
        self.assertEqual(oracle, EXPECTED_FM_COUNTS)

    def test_evidence_valid_collection_regression(self):
        evidence = load_json(EVIDENCE)
        col = evidence["reader"]["valid_collection"]
        self.assertEqual(col["total_size"], 48)
        self.assertEqual(col["query_counts"],
                         {"AAAAA": 1, "ACGTN": 3, "CCCCC": 1, "AGCTA": 0,
                          "AAAAAA": 0, "GGGGG": 1, "NACGT": 1, "TTTTT": 1,
                          "$": 8})
        self.assertTrue(col["byte_rle_queries_equal"])
        self.assertTrue(col["byte_rle_recovery_equal"])

    def test_evidence_pre_fix_frozen_failures_recorded(self):
        evidence = load_json(EVIDENCE)
        pre = evidence["pre_fix"]
        self.assertEqual(pre["frozen_source_sha256"],
                         "95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0")
        self.assertEqual(pre["pure_getCharAtIndex"]["exception_type"],
                         "IndexError")
        self.assertEqual(pre["pure_getFullFMAtIndex"]["exception_type"],
                         "IndexError")
        self.assertEqual(pre["compiled_rle_getBWTRange"]["exception_type"],
                         "IndexError")
        self.assertIn("line 575", pre["pure_getCharAtIndex"]["traceback"])
        self.assertIn("line 708", pre["pure_getFullFMAtIndex"]["traceback"])
        self.assertIn("line 375", pre["compiled_rle_getBWTRange"]["traceback"])
        self.assertEqual(pre["promotion"]["uint64_plus_int_runtime_type"],
                         "float64")


class ReaderFixSourceTests(unittest.TestCase):
    def test_frozen_reader_sites_untouched(self):
        frozen = (REPOSITORY_ROOT / "MUS" / "MultiStringBWT.py").read_text(
            encoding="utf-8", errors="replace")
        for site in FROZEN_READER_SITES:
            self.assertIn(site, frozen, site)

    def test_frozen_rle_pyx_untouched(self):
        frozen = (REPOSITORY_ROOT / "MUSCython" / "RLE_BWTCython.pyx").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn("endRange = self.refFM[endBlock+1]+1", frozen)

    def test_modern2_pyx_diff_is_exactly_language_level_and_fix(self):
        added, removed = unified_added_removed(
            REPOSITORY_ROOT / "MUSCython" / "RLE_BWTCython.pyx",
            PACKAGE / "MUSCython" / "RLE_BWTCython.pyx")
        self.assertEqual(added, PYX_ADDED_LINES)
        self.assertEqual(removed, PYX_REMOVED_LINES)

    def test_regenerated_c_contains_the_conversion_at_the_site(self):
        """The committed generated C (Cython 3.0.12, pinned environment)
        contains the int() conversion exactly at the decompressBlocks
        endRange site and no other semantic change."""
        c_text = (PACKAGE / "MUSCython" / "RLE_BWTCython.c").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn("__Pyx_PyNumber_Int", c_text)
        self.assertIn("endRange = int(self.refFM[endBlock+1])+1", c_text)
        # the modern2 pyx regenerates cleanly: the .c pyx-source banner is
        # derived from the committed pyx (checked by the driver --build gate)
        self.assertIn("MUSCython/RLE_BWTCython.pyx", c_text)

    def test_modern2_py_diff_whitelist_held(self):
        added, removed = unified_added_removed(
            REPOSITORY_ROOT / "MUS" / "MultiStringBWT.py",
            PACKAGE / "MUS" / "MultiStringBWT.py")
        self.assertEqual(len(added), 7)
        self.assertEqual(len(removed), 6)
        self.assertEqual(added.count("            endRange = int(self.refFM[binID+1])+1"), 2)
        self.assertEqual(removed.count("            endRange = self.refFM[binID+1]+1"), 2)
        self.assertIn("            np.add.at(ret, letters[0:x-1], counts[0:x-1])",
                      added)
        self.assertIn("            ret += np.bincount(letters[0:x-1], counts[0:x-1], minlength=self.vcLen)",
                      removed)


if __name__ == "__main__":
    unittest.main()
