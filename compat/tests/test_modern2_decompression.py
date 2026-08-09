"""Read-only host-side regression tests for msbwt-modern2 decompression
milestone 3 (first intentional correctness fix: successful post-hoc
decompression).

These tests run under the host Python 3 (like the other compat tests) and
protect the committed modern2 decompression evidence, the committed legacy
expected-failure contract, and the minimality of the numeric/index fix in
``MUS/MultiStringBWT.py`` without requiring the WSL Python-2 environment.  The
runtime build/decompression validation lives in
packages/msbwt-modern2/validate/decompression-milestone3.sh (WSL).
"""

import difflib
import json
import hashlib
import re
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
PACKAGE = REPOSITORY_ROOT / "packages" / "msbwt-modern2"
GOLDENS = REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0"
PROFILE = "py27-late-05a7d6d83862"
ROUTE = "pyx-historical-cython"
EVIDENCE = PACKAGE / "evidence" / "decompression-milestone3.json"
FROZEN_MANIFEST = (REPOSITORY_ROOT / "reference" / "original-0.3.0" /
                   "environment" / "frozen-source.sha256")
FAILURE_EVIDENCE = (GOLDENS / "compression-milestone1" /
                    "decompression-failure" / "uniform")

DECOMPRESSED_WHOLE_SHA256 = "f536d60f356ed4a34e8253eecdd91e90db8c2ba3430c2e3d3e1855bb49007ef4"
GOLDEN_WHOLE_SHA256 = "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"
GOLDEN_PAYLOAD_SHA256 = "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e"
BYTE_READER_SIDE_EFFECTS = {
    "totalCounts.npy": "ea104b616fe89d7b786acdff7ca0db61f6339a59c31fbf0fff066ad7384c1c2b",
    "fmIndex.npy": "a5b4bf06726fcadf535245d03ef65e04a4a5248d368b3aa53639c190028b933f",
}

# the exact minimal fix in packages/msbwt-modern2/MUS/MultiStringBWT.py
# (decompressBlocks fill loop) relative to the LF-normalized frozen source
FIX_ADDED_LINES = [
    "            runLength = int(counts[lInd])",
    "            ret[s:s+runLength] = letters[lInd]",
    "            s += runLength",
]
FIX_REMOVED_LINES = [
    "            ret[s:s+counts[lInd]] = letters[lInd]",
    "            s += counts[lInd]",
]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ValidationDriverTests(unittest.TestCase):
    def test_driver_present_and_runs_each_route(self):
        driver = PACKAGE / "validate" / "decompression-milestone3.sh"
        text = driver.read_text(encoding="utf-8")
        for route in ("run_decompress", "fresh_source",
                      "build_direct_rle", "build_posthoc_rle"):
            self.assertIn(route, text)
        self.assertIn("decompression-milestone3", text)
        self.assertIn("run-p2", text)
        self.assertIn("verify_reader", text)
        self.assertIn("verify_decompression", text)

    def test_driver_uses_independent_tooling_and_legacy_evidence(self):
        driver = (PACKAGE / "validate" / "decompression-milestone3.sh").read_text(
            encoding="utf-8")
        self.assertIn("artifact_manifest.py", driver)
        self.assertIn("bwt_oracle.py", driver)
        self.assertIn("decompression-failure/uniform", driver)
        self.assertIn("DECOMPRESSED_WHOLE_SHA256", driver)


class EvidenceTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = load_json(EVIDENCE)
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "codex/modern2")
        self.assertEqual(evidence["final"]["milestone"],
                         "modern2-milestone3-decompression")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["py2_tests"]["status"], "ok")

    def test_evidence_decompression_matches_success_contract(self):
        evidence = load_json(EVIDENCE)
        decomp = evidence["decompression"]
        self.assertTrue(decomp["cross_route"]["direct_equals_posthoc_whole"])
        self.assertEqual(decomp["cross_route"]["whole_sha256"],
                         DECOMPRESSED_WHOLE_SHA256)
        self.assertEqual(decomp["cross_route"]["payload_sha256"],
                         GOLDEN_PAYLOAD_SHA256)
        self.assertEqual(decomp["cross_route"]["golden_whole_sha256"],
                         GOLDEN_WHOLE_SHA256)
        self.assertTrue(decomp["cross_route"]["payload_equals_committed_byte_golden"])
        self.assertTrue(
            decomp["cross_route"]["header_differs_from_golden_only_in_shape_literal"])
        for route in ("direct", "posthoc"):
            entry = decomp[route]
            self.assertTrue(entry["destination_determinism"], route)
            self.assertTrue(entry["source_side_effect_determinism"], route)
            for run in ("run-a", "run-b", "run-p2"):
                record = entry["runs"][run]
                self.assertEqual(record["whole_sha256"],
                                 DECOMPRESSED_WHOLE_SHA256, (route, run))
                self.assertEqual(record["dtype"], "|u1", (route, run))
                self.assertEqual(record["shape"], [48], (route, run))
                self.assertIn("'shape': (48,),", record["header_text"], (route, run))
                self.assertNotIn("(48L,)", record["header_text"], (route, run))
                self.assertEqual(record["payload_sha256"], GOLDEN_PAYLOAD_SHA256,
                                 (route, run))
                self.assertTrue(record["payload_matches_golden"], (route, run))
                self.assertEqual(record["destination_files"], ["msbwt.npy"],
                                 (route, run))
                self.assertEqual(record["source_files"],
                                 ["comp_fmIndex.npy", "comp_msbwt.npy",
                                  "comp_refIndex.npy", "totalCounts.p"], (route, run))
                self.assertEqual(record["symbol_counts"],
                                 {"$": 8, "A": 9, "C": 9, "G": 9, "N": 4, "T": 9},
                                 (route, run))

    def test_evidence_decompressed_header_matches_legacy_preallocation(self):
        legacy = load_json(FAILURE_EVIDENCE / "destination-manifest.json")
        legacy_header = legacy["artifacts"][0]["npy"]["header_text"]
        evidence = load_json(EVIDENCE)
        header = evidence["decompression"]["direct"]["runs"]["run-a"]["header_text"]
        self.assertEqual(header, legacy_header)

    def test_evidence_round_trip_and_legacy_failure_contract(self):
        evidence = load_json(EVIDENCE)
        rt = evidence["decompression"]["round_trip"]
        self.assertTrue(rt["byte_golden_compress_decompress_payload_equal"])
        self.assertEqual(rt["whole_sha256"], DECOMPRESSED_WHOLE_SHA256)
        legacy = evidence["decompression"]["legacy_failure_evidence"]
        self.assertEqual(legacy["exit_code"], 1)
        self.assertEqual(
            legacy["exception"],
            "TypeError: slice indices must be integers or None or have an __index__ method")
        self.assertTrue(legacy["traceback_line_662"])
        self.assertEqual(legacy["source_side_effects"],
                         ["comp_fmIndex.npy", "comp_refIndex.npy", "totalCounts.p"])
        self.assertEqual(legacy["preallocated_payload_all_zero_sha256"],
                         "17b0761f87b081d5cf10757ccc89f12be355c70e2e29df288b65b30710dcbcd1")
        self.assertTrue(legacy["stderr_preserved"])

    def test_evidence_reader_matches_legacy_byte_reader_side_effects(self):
        evidence = load_json(EVIDENCE)
        for label, record in evidence["reader"].items():
            self.assertEqual(record["reader_class"],
                             "MUSCython.ByteBWTCython.ByteBWT", label)
            self.assertEqual(record["total_size"], 48, label)
            self.assertEqual(record["dollar_count"], 8, label)
            self.assertTrue(record["queries_match"], label)
            self.assertTrue(record["recovered_match"], label)
            added = {item["path"]: item["sha256"]
                     for item in record["side_effects"]["added"]}
            self.assertEqual(added, BYTE_READER_SIDE_EFFECTS, label)
            self.assertEqual(record["side_effects"]["changed"], [], label)
            self.assertEqual(record["side_effects"]["removed"], [], label)


class DecompressionFixSourceTests(unittest.TestCase):
    """The modern2 decompression fix is the NARROWEST possible correction.

    ``packages/msbwt-modern2/MUS/MultiStringBWT.py`` must differ from the
    frozen original (LF-normalized) ONLY in the ``decompressBlocks`` fill
    loop, converting the ``<u8`` run-count scalar to a Python int before it
    enters slice arithmetic (``s + counts[lInd]`` promotes to float64 under
    CPython 2.7 / NumPy 1.16.6 and has no ``__index__``).  The conversion
    preserves the exact mathematical integer value; nothing else may change.
    """

    def test_frozen_multi_string_bwt_untouched(self):
        digest = sha256_bytes((REPOSITORY_ROOT / "MUS" /
                               "MultiStringBWT.py").read_bytes())
        self.assertEqual(digest, "95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0")

    def test_modern2_diff_vs_frozen_is_exactly_the_index_fix(self):
        frozen = (REPOSITORY_ROOT / "MUS" / "MultiStringBWT.py").read_bytes()
        modern = (PACKAGE / "MUS" / "MultiStringBWT.py").read_bytes()
        frozen_lines = frozen.replace(b"\r\n", b"\n").decode("utf-8").splitlines()
        modern_lines = modern.replace(b"\r\n", b"\n").decode("utf-8").splitlines()
        diff = list(difflib.unified_diff(frozen_lines, modern_lines, lineterm=""))
        added = [line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")]
        removed = [line[1:] for line in diff if line.startswith("-") and not line.startswith("---")]
        self.assertEqual(added, FIX_ADDED_LINES)
        self.assertEqual(removed, FIX_REMOVED_LINES)
        context = [line[1:] for line in diff if line.startswith(" ")]
        self.assertIn("            if lInd >= letters.shape[0]:", context)

    def test_index_conversion_sites_are_explicit_and_local(self):
        text = (PACKAGE / "MUS" / "MultiStringBWT.py").read_text(encoding="utf-8")
        fill_loop = text[text.index("        #we're at the correct letter index now"):
                         text.index("        return ret", text.index(
                             "        #we're at the correct letter index now"))]
        self.assertIn("runLength = int(counts[lInd])", fill_loop)
        # every numeric conversion in the file is either the fix site or a
        # pre-existing legacy conversion (lines 90/126/335/381/463/497/604/
        # 676/1144/1145/1189/1335 of the LF-normalized frozen file); the fix
        # introduced no other int()/long()/float() churn anywhere
        fix_site = "            runLength = int(counts[lInd])"
        legacy_sites = [
            "                self.searchCache[seq[-self.cacheDepth:]] = (int(res[0]), int(res[1]))",
            "                self.searchCache[seq[-self.cacheDepth:]] = (int(res[0]), int(res[1]))",
            "        return int(ret)",
            "                        searches.insert(0, (newSeq, int(nls[c]), int(nhs[c])))",
            "        self.totalSize = int(np.sum(self.totalCounts))",
            "            samplingSize = int(math.ceil(float(self.totalSize)/self.binSize))",
            "        endBlockIndex = int(math.floor(float(end)/self.binSize))",
            "        return int(self.getFullFMAtIndex(index)[sym])",
            "    tot1 = float(fp1.readline().strip('\\n').split(',')[1])",
            "    tot2 = float(fp2.readline().strip('\\n').split(',')[1])",
            "        return (pieces[0], int(pieces[1]))",
            "            perc = float(maxV)/total",
        ]
        allowed = set(legacy_sites) | {fix_site}
        found = set()
        for line in text.splitlines():
            if re.search(r"\b(?:int|long|float)\(", line):
                found.add(line)
        self.assertEqual(found, allowed)
        self.assertNotIn("ret[s:s+counts[lInd]]", text)
        self.assertNotIn("s += counts[lInd]", text)

    def test_frozen_failure_site_still_holds_original_arithmetic(self):
        # the frozen source must keep the exact legacy failing expression so
        # the historical contract remains reproducible
        frozen = (REPOSITORY_ROOT / "MUS" / "MultiStringBWT.py").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn("ret[s:s+counts[lInd]] = letters[lInd]", frozen)


if __name__ == "__main__":
    unittest.main()
