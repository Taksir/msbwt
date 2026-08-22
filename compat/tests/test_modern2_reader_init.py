"""Read-only host-side regression tests for msbwt-modern2 pure reader
initialization / index construction milestone 7.

These tests run under the host Python 3 (like the other compat tests) and
protect the committed modern2 fresh-load evidence, the runtime semantics of
the pure ``CompressedMSBWT.constructTotalCounts`` /
``constructFMIndex`` first-load paths, the byte-identical regeneration of
``totalCounts.p`` / ``comp_fmIndex.npy`` / ``comp_refIndex.npy``, the
pure-vs-compiled derived-file convention difference on the >1M evidence,
and the historical classification (frozen init paths identical; the
modern2-vs-frozen diff remains exactly the documented five correction
sites), without requiring the WSL Python-2 environment.  The runtime
validation lives in packages/msbwt-modern2/validate/reader-milestone7.sh
(WSL).
"""

import hashlib
import json
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
PACKAGE = REPOSITORY_ROOT / "packages" / "msbwt-modern2"
from modern2_source_acceptance import assert_source_within_acceptance

EVIDENCE = PACKAGE / "evidence" / "reader-milestone7.json"

EVIDENCE_PRIMARY_SHA256 = "24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35"
RLE_PRIMARY_SHA256 = "681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99"
FROZEN_SHA256 = "95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0"
MODERN2_SHA256 = "3431703364faa8e5aaaaa9ffb0e8c5efaa5acae68cf712e14115a36963858320"

DERIVED = ("totalCounts.p", "comp_fmIndex.npy", "comp_refIndex.npy")
DECODED_COUNTS = {
    "posthoc48": [8, 9, 9, 9, 4, 9],
    "direct48": [8, 9, 9, 9, 4, 9],
    "nonuni30": [7, 5, 4, 3, 2, 9],
    "big": [176000, 198000, 198000, 198000, 88000, 198000],
}
FROZEN_48 = {
    "totalCounts.p": "c038b778aa21d53a42ba552e59cfe48d036ed7b8f4d6ce77d0ab55ede2638916",
    "comp_fmIndex.npy": "f6565545114d769fbe6ba6010ce125c8690256f2d97562ceb65064b38d48c881",
    "comp_refIndex.npy": "30c0c0f336e69b86ee3da30f0f4ce1d9a138d503845c586e993ff31e8003fee1",
}
FROZEN_30_FM = "d3e57fa28f3b49910012d4fb2a51f48a22f62b112bc773d8fe825a5905c7be55"
FROZEN_30_REF = "30c0c0f336e69b86ee3da30f0f4ce1d9a138d503845c586e993ff31e8003fee1"
COLLECTION_QUERIES = {"AAAAA": 1, "ACGTN": 3, "CCCCC": 1, "AGCTA": 0,
                      "AAAAAA": 0, "GGGGG": 1, "NACGT": 1, "TTTTT": 1,
                      "$": 8}
COLLECTION_RECOVERY = ['AAAAA$', 'ACGTN$', 'ACGTN$', 'ACGTN$', 'CCCCC$',
                       'GGGGG$', 'NACGT$', 'TTTTT$']
BIG_QUERIES = {"A": 198000, "AC": 37125, "ACGTN": 111, "AAAAA": 243,
               "AAAAAA": 45, "C": 198000, "CG": 37125, "GT": 37125,
               "GTGGGTTT": 2, "N": 88000, "NACGT": 108, "T": 198000,
               "TTTTT": 249}


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def unified_added_removed(frozen_path, modern2_path):
    import difflib
    frozen = frozen_path.read_bytes().decode("utf-8", errors="replace").splitlines()
    modern2 = modern2_path.read_bytes().decode("utf-8", errors="replace").splitlines()
    added = []
    removed = []
    for line in difflib.unified_diff(frozen, modern2, lineterm=""):
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
    return added, removed


class Milestone7EvidenceTests(unittest.TestCase):
    def test_evidence_record_consistency(self):
        evidence = load_json(EVIDENCE)
        self.assertEqual(evidence["final"]["branch"], "codex/modern2")
        self.assertEqual(evidence["final"]["milestone"],
                         "modern2-milestone7-reader-init")
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["build"]["status"], "skipped")
        self.assertEqual(evidence["py2_tests"]["status"], "ok")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")

    def test_evidence_dataset_hashes(self):
        evidence = load_json(EVIDENCE)
        self.assertEqual(evidence["dataset"]["evidence_primary_sha256"],
                         EVIDENCE_PRIMARY_SHA256)
        self.assertEqual(evidence["dataset"]["rle_primary_sha256"],
                         RLE_PRIMARY_SHA256)
        self.assertEqual(evidence["dataset"]["total_size"], 1056000)

    def test_constructTotalCounts_runtime_semantics(self):
        evidence = load_json(EVIDENCE)
        tc = evidence["constructTotalCounts"]
        self.assertEqual(tc["initial_type"], "list")
        self.assertEqual(tc["initial_len"], 6)
        self.assertEqual(tc["chunk_0"]["before_type"], "list")
        self.assertEqual(tc["chunk_0"]["bincount_dtype"], "float64")
        self.assertEqual(tc["chunk_0"]["after_type"], "ndarray")
        self.assertEqual(tc["chunk_0"]["after_len"], 6)
        self.assertEqual(tc["chunk_0"]["after_dtype"], "float64")
        self.assertEqual(tc["final_type"], "ndarray")
        self.assertEqual(tc["final_dtype"], "float64")
        self.assertEqual(tc["final_values"], [8.0, 9.0, 9.0, 9.0, 4.0, 9.0])

    def test_constructFMIndex_runtime_semantics(self):
        evidence = load_json(EVIDENCE)
        fm = evidence["constructFMIndex"]
        self.assertEqual(fm["totalCounts_type"], "ndarray")
        self.assertEqual(fm["countsSoFar_dtype"], "float64")
        self.assertEqual(fm["countsSoFar_values"],
                         [0.0, 8.0, 17.0, 26.0, 35.0, 39.0])
        self.assertEqual(fm["partialFM_dtype"], "uint64")
        self.assertEqual(fm["refFM_dtype"], "uint64")
        self.assertEqual(fm["offsetSum"], 125)

    def test_evidence_exact_symbol_totals(self):
        evidence = load_json(EVIDENCE)
        decoded = evidence["independent"]["decoded_counts"]
        for case, expected in DECODED_COUNTS.items():
            self.assertEqual(decoded[case], expected, case)
            self.assertEqual(evidence["independent"]["decoded_counts_total"][case],
                             sum(expected), case)

    def test_evidence_derived_files_per_case(self):
        evidence = load_json(EVIDENCE)
        for case in ("posthoc48", "direct48", "nonuni30", "big"):
            entry = evidence["derived"][case]
            self.assertEqual(entry["created_files"], sorted(DERIVED), case)
            self.assertEqual(entry["fm"]["dtype"], "uint64", case)
            self.assertEqual(entry["ref"]["dtype"], "uint64", case)
            self.assertEqual(entry["totalCounts_p"]["type"], "ndarray", case)
            self.assertEqual(entry["totalCounts_p"]["dtype"], "float64", case)
            self.assertEqual(entry["totalCounts_p"]["len"], 6, case)
            self.assertTrue(entry["exact_integer_counts"], case)
            self.assertEqual(
                entry["totalCounts_p"]["values"],
                [float(v) for v in DECODED_COUNTS[case]], case)
            self.assertTrue(entry["determinism"]["hashes_equal"], case)
            self.assertTrue(entry["regeneration"]["hashes_equal"], case)
            self.assertEqual(entry["totalSize"],
                             sum(DECODED_COUNTS[case]), case)

    def test_evidence_matches_committed_frozen_bytes(self):
        evidence = load_json(EVIDENCE)
        for case in ("posthoc48", "direct48"):
            entry = evidence["derived"][case]
            self.assertTrue(entry["matches_committed_frozen"], case)
            for name, digest in FROZEN_48.items():
                self.assertEqual(entry["hashes"][name], digest, (case, name))
        entry = evidence["derived"]["nonuni30"]
        self.assertEqual(entry["hashes"]["comp_fmIndex.npy"], FROZEN_30_FM)
        self.assertEqual(entry["hashes"]["comp_refIndex.npy"], FROZEN_30_REF)

    def test_evidence_single_bin_pure_equals_compiled_bytes(self):
        evidence = load_json(EVIDENCE)
        for case in ("posthoc48", "direct48", "nonuni30"):
            entry = evidence["derived"][case]
            self.assertTrue(entry["compiled"]["fm_bytes_equal"], case)
            self.assertTrue(entry["compiled"]["ref_bytes_equal"], case)

    def test_evidence_big_pure_vs_compiled_convention(self):
        evidence = load_json(EVIDENCE)
        d = evidence["independent"]["pure_vs_compiled_bins"]
        self.assertEqual(d["differing_bin_count"], 171)
        self.assertTrue(d["all_differing_bins_are_tile_boundaries"])
        self.assertTrue(d["pure_ref_eq_compiled_ref_minus_1"])
        self.assertTrue(d["pure_fm_row0_equal"])
        self.assertTrue(d["pure_fm_lastrow_equal"])

    def test_evidence_all_516_bins_oracle_validated(self):
        evidence = load_json(EVIDENCE)
        bins = evidence["independent"]["all_bins"]
        self.assertEqual(bins["bins_total"], 516)
        self.assertEqual(bins["bins_ok"], 516)
        self.assertEqual(bins["bad_count"], 0)

    def test_evidence_collection_semantics(self):
        evidence = load_json(EVIDENCE)
        for case in ("posthoc48", "direct48"):
            s = evidence["reader"][case]
            for k, v in COLLECTION_QUERIES.items():
                self.assertEqual(s["queries"][k], v, (case, k))
                self.assertEqual(s["queries"]["compiled_" + k], v, (case, k))
            self.assertEqual(s["dollar_count"], 8, case)
            self.assertEqual(s["recovery"], s["recovery_compiled"], case)
            self.assertEqual(s["recovery"], COLLECTION_RECOVERY, case)
        s = evidence["reader"]["nonuni30"]
        self.assertEqual(s["dollar_count"], 7)
        self.assertEqual(s["recovery"], s["recovery_compiled"])
        self.assertEqual(s["recovery"], ['A$', 'AC$', 'ACG$', 'ACGT$',
                                         'ACGTN$', 'N$', 'TTTTTTT$'])

    def test_evidence_big_reader_semantics(self):
        evidence = load_json(EVIDENCE)
        s = evidence["reader"]["big"]
        for k, v in BIG_QUERIES.items():
            self.assertEqual(s["queries"][k], v, k)
            self.assertEqual(s["queries"]["compiled_" + k], v, k)
        for p, expected in ((0, 1), (2048, 2), (999998, 0), (1055998, 5),
                            (1055999, 0)):
            self.assertEqual(s["getCharAtIndex"][str(p)], expected, p)
            self.assertEqual(s["getCharAtIndex"][str(p)],
                             s["getCharAtIndex"]["compiled_" + str(p)], p)

    def test_evidence_interchangeability(self):
        evidence = load_json(EVIDENCE)
        inter = evidence["interchangeability"]
        for p in ("0", "2048", "6144", "1000000", "1055998"):
            self.assertEqual(inter["pure_on_compiled"][p],
                             inter["compiled_on_pure"][p], p)
        self.assertEqual(inter["pure_on_compiled"]["6144"],
                         [1024, 177152, 375152, 573152, 770512, 859152])
        self.assertEqual(inter["pure_on_compiled"]["1055998"],
                         [175999, 374000, 572000, 770000, 858000, 1055999])
        for k, v in (("A", 198000), ("AC", 37125), ("ACGTN", 111),
                     ("AAAAAA", 45)):
            self.assertEqual(inter["pure_on_compiled"][k], v, k)
            self.assertEqual(inter["compiled_on_pure"][k], v, k)
        self.assertEqual(inter["pure_on_compiled"]["getCharAtIndex_6144"], 1)
        self.assertEqual(inter["compiled_on_pure"]["getCharAtIndex_6144"], 1)

    def test_evidence_historical_classification(self):
        evidence = load_json(EVIDENCE)
        hist = evidence["historical"]
        self.assertEqual(hist["frozen_sha256"], FROZEN_SHA256)
        self.assertEqual(hist["modern2_sha256"], MODERN2_SHA256)
        self.assertTrue(hist["init_constructTotalCounts_identical"])
        self.assertTrue(hist["init_constructFMIndex_identical"])


class Milestone7SourceTests(unittest.TestCase):
    def test_driver_present(self):
        driver = PACKAGE / "validate" / "reader-milestone7.sh"
        self.assertTrue(driver.is_file())
        text = driver.read_text(encoding="utf-8", errors="replace")
        self.assertIn("modern2-milestone7-reader-init", text)
        self.assertIn("constructTotalCounts", text)
        self.assertIn("constructFMIndex", text)

    def test_frozen_original_untouched(self):
        frozen = REPOSITORY_ROOT / "MUS" / "MultiStringBWT.py"
        self.assertEqual(sha256_bytes(frozen.read_bytes()), FROZEN_SHA256)
        # the suspicious init sites are unchanged in the frozen original
        text = frozen.read_text(encoding="utf-8", errors="replace")
        self.assertIn("self.totalCounts += np.bincount(letters, "
                      "np.multiply(counts, self.numPower**powers), "
                      "minlength=self.vcLen)", text)
        self.assertIn("self.partialFM[samplingID][:] = np.add(countsSoFar, "
                      "np.bincount(letters[0:prevStart], counts[0:prevStart], "
                      "self.vcLen))", text)

    def test_modern2_diff_whitelist_unchanged(self):
        """The modern2-vs-frozen diff remains exactly the documented FIVE
        correction sites (7 added / 6 removed) from milestones 3-6; this
        milestone added no source change."""
        added, removed = unified_added_removed(
            REPOSITORY_ROOT / "MUS" / "MultiStringBWT.py",
            PACKAGE / "MUS" / "MultiStringBWT.py")
        # M3-R64-W5 rebaseline: closed-set acceptance whitelist; the five
        # milestone correction landmarks below must remain present.
        assert_source_within_acceptance(self, "MUS/MultiStringBWT.py")
        self.assertEqual(added.count("            endRange = int(self.refFM[binID+1])+1"), 2)
        self.assertEqual(removed.count("            endRange = self.refFM[binID+1]+1"), 2)
        self.assertEqual(added.count("            endRange = int(self.refFM[endBlock+1])+1"), 1)
        self.assertIn("            runLength = int(counts[lInd])", added)
        self.assertIn("            np.add.at(ret, letters[0:x-1], counts[0:x-1])", added)
        self.assertNotIn("self.totalCounts", "".join(added) + "".join(removed))
        self.assertNotIn("bincount", "".join(added))


if __name__ == "__main__":
    unittest.main()
