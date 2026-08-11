"""Read-only host-side regression tests for the modern2 quality audit Q1
harness (compat/audit/modern2-q1).

These tests run under the host Python 3 like the other compat tests and
protect:

- the independent oracle (rotation-sorted BWT, symbol totals, backward
  search, LF recovery, FM ranks) against the committed legacy goldens;
- the NPY v1 parser against Python-2-generated headers (long literals);
- the base-32 RLE decoder, including multi-digit (LSB-first) runs that the
  committed goldens do not contain;
- deterministic gzip byte production;
- corpus generation determinism and category coverage;
- classification A/B/C/D/E and the deterministic audit summary;
- merge-pair generation determinism and trait coverage;
- the family subset planner.

No WSL execution or production source is required.
"""

import gzip
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path

AUDIT_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = AUDIT_DIR.parents[2]
sys.path.insert(0, str(AUDIT_DIR))

from audit_core import (  # noqa: E402
    SYMBOLS,
    backward_count,
    backward_counts_many,
    decode_rle,
    deterministic_gzip_bytes,
    expected_substring_counts,
    expected_symbol_counts,
    generate_corpus,
    json_dump,
    lf_recover_reads,
    parse_npy_v1,
    rotation_sort_bwt,
    sha256_bytes,
    substring_count_in_reads,
    symbol_counts,
)
from analyze_audit import Analyzer, build_summary, classify3  # noqa: E402

GOLDEN = (REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0" /
          "uniform-multifile" / "py27-late-05a7d6d83862" /
          "pyx-historical-cython")
POSTHOC = (REPOSITORY_ROOT / "compat" / "goldens" / "original-0.3.0" /
           "uniform-compress-posthoc" / "py27-late-05a7d6d83862" /
           "pyx-historical-cython")

UNIFORM_READS = ["ACGTN", "AAAAA", "ACGTN", "NACGT", "ACGTN", "CCCCC",
                 "GGGGG", "TTTTT"]
UNIFORM_BWT_SHA = "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"
UNIFORM_PAYLOAD_SHA = "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e"
DECODED_BWT = "ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$"


def read_npy_payload(path):
    parsed = parse_npy_v1(Path(path).read_bytes())
    return parsed["payload"], parsed["shape"], parsed["dtype"]


class OracleGoldenTests(unittest.TestCase):
    def test_rotation_bwt_reproduces_uniform_golden(self):
        payload, shape, dtype = read_npy_payload(GOLDEN / "build" / "artifacts" / "msbwt.npy")
        self.assertEqual(dtype, "|u1")
        self.assertEqual(list(shape), [48])
        self.assertEqual(sha256_bytes(payload), UNIFORM_PAYLOAD_SHA)
        oracle = rotation_sort_bwt(UNIFORM_READS)
        self.assertEqual(oracle, payload)
        self.assertEqual(sha256_bytes(oracle), UNIFORM_PAYLOAD_SHA)

    def test_npy_parser_handles_py2_long_literals(self):
        # the frozen build golden header contains Python-2 (48L,) literals
        payload, shape, _ = read_npy_payload(GOLDEN / "build" / "artifacts" / "msbwt.npy")
        self.assertEqual(payload, rotation_sort_bwt(UNIFORM_READS))

    def test_symbol_totals_match(self):
        payload, _, _ = read_npy_payload(GOLDEN / "build" / "artifacts" / "msbwt.npy")
        self.assertEqual(symbol_counts(payload), expected_symbol_counts(UNIFORM_READS))
        self.assertEqual(symbol_counts(payload), [8, 9, 9, 9, 4, 9])

    def test_backward_counts_match_read_substrings(self):
        payload, _, _ = read_npy_payload(GOLDEN / "build" / "artifacts" / "msbwt.npy")
        expected = expected_substring_counts(UNIFORM_READS)
        for pattern, count in expected.items():
            self.assertEqual(backward_count(payload, pattern), count, pattern)
        self.assertEqual(backward_count(payload, "AAAAAA"), 0)
        self.assertEqual(backward_count(payload, "$"), 8)
        many = backward_counts_many(payload, sorted(expected))
        self.assertEqual(many, expected)

    def test_lf_recovery_reproduces_reads(self):
        payload, _, _ = read_npy_payload(GOLDEN / "build" / "artifacts" / "msbwt.npy")
        self.assertEqual(lf_recover_reads(payload), sorted(UNIFORM_READS))

    def test_rle_decode_reproduces_committed_decoded_bwt(self):
        parsed = parse_npy_v1((POSTHOC / "artifacts" / "comp_msbwt.npy").read_bytes())
        self.assertEqual(parsed["dtype"], "|u1")
        run_lengths, symbols = decode_rle(parsed["payload"])
        self.assertEqual(len(symbols), 48)
        self.assertEqual("".join(SYMBOLS[v] for v in symbols), DECODED_BWT)
        self.assertEqual(sum(run_lengths), 48)


class RleDigitOrderTests(unittest.TestCase):
    def test_multidigit_run_is_lsb_first(self):
        # 36 symbols of T: digits [4, 1] little-endian (4 + 1*32 = 36).
        # The committed goldens contain only single-digit runs, so this is
        # the regression that protects against the MSB-first misreading.
        payload = bytes([(4 << 3) | 3, (1 << 3) | 3])
        run_lengths, symbols = decode_rle(payload)
        self.assertEqual(run_lengths, [36])
        self.assertEqual(symbols, [3] * 36)

    def test_reads_back_from_encoder_convention(self):
        # digits of 129: 129 = 1 + 4*32 -> [1, 4]
        payload = bytes([(1 << 3) | 2, (4 << 3) | 2])
        run_lengths, symbols = decode_rle(payload)
        self.assertEqual(run_lengths, [129])
        self.assertEqual(symbols, [2] * 129)


class GzipDeterminismTests(unittest.TestCase):
    def test_gzip_bytes_decompress_to_original(self):
        raw = b"@r1\nACGTN\n+\nIIIII\n"
        encoded = deterministic_gzip_bytes(raw)
        self.assertEqual(encoded[9], 255)
        self.assertEqual(gzip.decompress(encoded), raw)

    def test_gzip_bytes_deterministic(self):
        raw = b"@r1\nACGTN\n+\nIIIII\n"
        self.assertEqual(deterministic_gzip_bytes(raw),
                         deterministic_gzip_bytes(raw))


class CorpusTests(unittest.TestCase):
    def test_corpus_generation_is_deterministic(self):
        a = generate_corpus(20260810, 8, 2)
        b = generate_corpus(20260810, 8, 2)
        self.assertEqual(json.dumps(a, sort_keys=True),
                         json.dumps(b, sort_keys=True))

    def test_different_seeds_differ(self):
        a = generate_corpus(20260810, 8, 2)
        b = generate_corpus(20260811, 8, 2)
        self.assertNotEqual([c["reads"] for c in a["cases"]],
                            [c["reads"] for c in b["cases"]])

    def test_all_required_categories_present(self):
        corpus = generate_corpus(20260810, 150, 15)
        categories = {c["category"] for c in corpus["cases"]
                      if not c.get("merge_case")}
        required = {
            "uniform-reads", "nonuniform-reads", "duplicates", "all-identical",
            "prefix-sharing", "suffix-sharing", "many-dollars", "full-alphabet",
            "n-heavy", "single-base", "short-reads", "moderate-reads",
            "odd-length", "even-length", "mixed-length", "repeated-motifs",
            "revcomp-pairs", "lexicographic-similar",
        }
        self.assertTrue(required.issubset(categories), required - categories)

    def test_case_constraints(self):
        corpus = generate_corpus(20260810, 150, 15)
        for case in corpus["cases"]:
            if case.get("merge_case"):
                continue
            self.assertTrue(all(set(r) <= set("ACGTN") for r in case["reads"]))
            if case["uniform"]:
                lengths = {len(r) for r in case["reads"]}
                self.assertEqual(len(lengths), 1, case["id"])
            total = sum(len(r) + 1 for r in case["reads"])
            if case["medium"]:
                self.assertLessEqual(total, 2200, case["id"])
            else:
                self.assertLessEqual(total, 320, case["id"])
            self.assertGreaterEqual(total, 3, case["id"])

    def test_query_generation_deterministic_and_valid(self):
        corpus = generate_corpus(20260810, 150, 15)
        for case in corpus["cases"]:
            if case.get("merge_case"):
                continue
            for query in case["queries"]:
                self.assertTrue(set(query) <= set("$ACGTN"), (case["id"], query))
            self.assertGreaterEqual(len(case["queries"]), 14, case["id"])

    def test_oracle_self_consistency_on_all_small_cases(self):
        # every generated collection must satisfy the ordering-independent
        # invariants the audit relies on
        corpus = generate_corpus(20260810, 150, 15)
        for case in corpus["cases"]:
            if case.get("merge_case"):
                continue
            payload = rotation_sort_bwt(case["reads"])
            self.assertEqual(symbol_counts(payload),
                             expected_symbol_counts(case["reads"]), case["id"])
            self.assertEqual(lf_recover_reads(payload),
                             sorted(case["reads"]), case["id"])
            for query in case["queries"]:
                expected = substring_count_in_reads(case["reads"], query)
                self.assertEqual(backward_count(payload, query), expected,
                                 (case["id"], query))


class MergePairTests(unittest.TestCase):
    def test_merge_pairs_deterministic_and_trait_coverage(self):
        import importlib
        import run_audit
        pairs_a = run_audit.generate_merge_pairs(20260810)
        pairs_b = run_audit.generate_merge_pairs(20260810)
        self.assertEqual(json.dumps(pairs_a, sort_keys=True),
                         json.dumps(pairs_b, sort_keys=True))
        self.assertEqual(len(pairs_a), 20)
        traits = {p["category"] for p in pairs_a.values()}
        self.assertTrue({"unequal-sizes", "duplicates-across",
                         "identical-in-both", "prefix-sharing",
                         "n-containing", "very-short"}.issubset(traits), traits)
        uniform = [p for p in pairs_a.values() if p["uniform"]]
        self.assertGreaterEqual(len(uniform), 5)


class PlannerTests(unittest.TestCase):
    def test_planner_subsets_are_deterministic(self):
        import importlib
        import run_audit
        corpus = generate_corpus(20260810, 150, 15)
        a = run_audit.plan_subsets(corpus)
        b = run_audit.plan_subsets(corpus)
        self.assertEqual(json.dumps(a, sort_keys=True),
                         json.dumps(b, sort_keys=True))
        self.assertEqual(len(a["construct"]), 165)
        self.assertEqual(len(a["reader"]), 165)
        self.assertGreaterEqual(len(a["cffq"]), 30)
        self.assertGreaterEqual(len(a["gzip"]), 25)
        self.assertEqual(len(a["permute"]), 4 * 2 + 16 * 3)


class ClassificationTests(unittest.TestCase):
    def test_a_legacy_equals_modern2_equals_oracle(self):
        self.assertEqual(classify3(1, 1, 1), "A")

    def test_b_legacy_equals_modern2_not_oracle(self):
        self.assertEqual(classify3(1, 1, 2), "B")

    def test_c_modern2_equals_oracle_not_legacy(self):
        self.assertEqual(classify3(1, 2, 2), "C")

    def test_d_legacy_equals_oracle_not_modern2(self):
        self.assertEqual(classify3(2, 1, 2), "D")

    def test_e_all_differ(self):
        self.assertEqual(classify3(1, 2, 3), "E")


class SummaryDeterminismTests(unittest.TestCase):
    def test_build_summary_is_deterministic(self):
        corpus = generate_corpus(20260810, 4, 1)
        frozen = {"construct": {}}
        modern2 = {"construct": {}, "permute_ops": [], "reader_rle_cases": []}
        for case in corpus["cases"]:
            if case.get("merge_case"):
                continue
            frozen["construct"][case["id"]] = {"exit": 0, "p1": {
                "payload_b64": __import__("base64").b64encode(
                    rotation_sort_bwt(case["reads"])).decode("ascii")}}
            modern2["construct"][case["id"]] = dict(frozen["construct"][case["id"]])
        results_a = Analyzer(corpus, frozen, dict(modern2)).run()
        results_b = Analyzer(corpus, frozen, dict(modern2)).run()
        summary_a = build_summary(results_a, corpus)
        summary_b = build_summary(results_b, corpus)
        self.assertEqual(json.dumps(summary_a, sort_keys=True),
                         json.dumps(summary_b, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
