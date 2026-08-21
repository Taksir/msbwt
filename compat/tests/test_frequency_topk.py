"""Host-side regression tests for enhanced-modern2 Features 5 & 6: sample
frequency and top-k exact sources (``MUS.MultiSourceQuery``).

These tests are read-only and run on any CPython 3 with NumPy; they do NOT
require the compiled MUSCython extensions (real-merge integration runs in
the pinned Python-2.7 suite and the Features-5/6 validation driver).

Coverage:

- ten-source read-derived fixture, >=350 patterns: Feature 5 == number of
  standalone sources with count > 0; Feature 6 == ranked sparse
  truncation for k = 0, 1, 2, 3, 5, 10, 20;
- one merged FM search per operation; Feature 5 count-only traversal does
  not call the Feature-4 listing;
- absent patterns, all-sources patterns, ties at cutoff (manifest order),
  k > support, k = 0, negative k rejection, alias identity, rich stats
  contracts, intervals retained in top-k;
- randomized read-derived differentials (seeds 20260811/20260812/20260813);
- edge fixtures: unbalanced chain, duplicates, identical reads, N-heavy,
  single-leaf package, '$' patterns;
- evidence-record and validation-driver consistency.
"""

import gc
import json
import os
import random
import shutil
import sys
import tempfile
import unittest

import numpy as np

PACKAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "..", "packages", "msbwt-modern2")
# sys.path injection is handled by conftest.py --msbwt-package option

from MUS.MultiSourceProvenance import (  # noqa: E402
    initialize_leaf_provenance,
    merge_many_balanced,
    merge_two_with_provenance,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)

SEEDS = (20260811, 20260812, 20260813)
TOP_K_VALUES = (0, 1, 2, 3, 5, 10, 20)

import test_multisource_query as f3  # noqa: E402
import test_sparse_source_listing as f4  # noqa: E402


class FrequencyTopKTenSourceHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f56-host-ten-")
        cls.output, cls.manifest, cls.merged, cls.standalone, cls.leaves = (
            f3.build_fixture(cls.work, f3.TEN_SOURCE_READS))
        cls.index = MultiSourceQueryIndex(
            cls.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        cls.wrapped = MultiSourceBWT(cls.merged, cls.index)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def expected_frequency(self, pattern):
        return len(f4.expected_sparse(self.standalone, self.manifest,
                                      pattern))

    def expected_top(self, pattern, k):
        sparse = f4.expected_sparse(self.standalone, self.manifest, pattern)
        table = [src["id"] for src in self.manifest["sources"]]
        table_index = {sid: i for i, sid in enumerate(table)}
        ranked = sorted(sparse,
                        key=lambda item: (-item[1], table_index[item[0]]))
        return ranked[:k] if k < len(ranked) else ranked

    def test_frequency_matches_listing_length_for_all_patterns(self):
        patterns = f3.all_test_patterns()
        self.assertGreaterEqual(len(patterns), 350)
        mismatches = []
        for pattern in patterns:
            got = self.wrapped.sourceFrequency(pattern)
            expected = self.expected_frequency(pattern)
            if got != expected:
                mismatches.append((pattern, got, expected))
        self.assertEqual(mismatches, [])

    def test_frequency_equals_nonzero_sources_length(self):
        for pattern in ("A", "AC", "CGT", "AAAA", "N", "TTTTT", "$",
                        "GGGGGGGGGGGG"):
            self.assertEqual(
                self.wrapped.sourceFrequency(pattern),
                len(self.wrapped.nonzeroSources(pattern)))

    def test_top_k_matches_ranked_sparse_truncation(self):
        patterns = f3.all_test_patterns()
        mismatches = []
        comparisons = 0
        for pattern in patterns:
            for k in TOP_K_VALUES:
                got = self.wrapped.topSources(pattern, k=k)
                expected = self.expected_top(pattern, k)
                got_list = [(r["source_id"], r["count"]) for r in got]
                expected_list = [(n, c) for n, c, _ in expected]
                comparisons += 1
                if got_list != expected_list:
                    mismatches.append((pattern, k, got_list, expected_list))
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 2500)

    def test_top_k_edge_cases(self):
        self.assertEqual(self.wrapped.topSources("AC", k=0), [])
        with self.assertRaises(ValueError):
            self.wrapped.topSources("AC", k=-1)
        self.assertEqual(self.wrapped.topSources("GGGGGGGGGGGG"), [])
        out = self.wrapped.topSources("CGT", k=99)
        ids = [r["source_id"] for r in out]
        self.assertEqual(len(ids), len(set(ids)))
        for rec in out:
            self.assertGreater(rec["count"], 0)
        self.assertEqual(len(self.wrapped.topSources("A")), 10)

    def test_top_k_ties_follow_manifest_order(self):
        # ordering contract: (-count, manifest index) must be nondecreasing
        got = self.wrapped.topSources("A", k=10)
        self.assertEqual(len(got), 10)
        table = [src["id"] for src in self.manifest["sources"]]
        keys = [(-r["count"], table.index(r["source_id"])) for r in got]
        self.assertEqual(keys, sorted(keys))

        work = tempfile.mkdtemp(prefix="f56-host-ties-")
        try:
            reads = {"s0": ["ACGTAC"], "s1": ["ACGTAC"],
                     "s2": ["ACGTAC"], "s3": ["ACGTAC"]}
            output, manifest, merged, _, _ = f3.build_fixture(
                work, reads, name="ties4")
            wrapped = MultiSourceBWT(
                merged, MultiSourceQueryIndex(output, mmap=False))
            table = [src["id"] for src in manifest["sources"]]
            out = wrapped.topSources("ACGT", k=2)
            self.assertEqual([r["source_id"] for r in out], table[:2])
            out = wrapped.topSources("ACGT", k=10)
            self.assertEqual([r["source_id"] for r in out], table)
            self.assertEqual([r["count"] for r in out], [1, 1, 1, 1])
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_top_k_intervals_retained(self):
        for pattern in ("AC", "CGT", "A"):
            for rec in self.wrapped.topSources(pattern, k=3,
                                               include_intervals=True):
                low, high = self.standalone[rec["source_id"]].findIndicesOfStr(
                    pattern)
                self.assertEqual(rec["source_interval"], (low, high))

    def test_one_merged_search_per_operation(self):
        fresh = MultiSourceBWT(
            self.merged,
            MultiSourceQueryIndex(self.output, mmap=False,
                                  use_saved_rank=False))
        before = self.merged.search_calls
        for pattern in ("ACGT", "A", "$", "NNNNN"):
            fresh.sourceFrequency(pattern)
            fresh.topSources(pattern, k=3)
        self.assertEqual(self.merged.search_calls, before + 8)

    def test_frequency_does_not_build_listing(self):
        index = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        original = index.nonzero_sources_interval
        calls = {"count": 0}

        def spy(*args, **kwargs):
            calls["count"] += 1
            return original(*args, **kwargs)

        index.nonzero_sources_interval = spy
        wrapped = MultiSourceBWT(self.merged, index)
        for pattern in ("AC", "CGT", "A", "NNNNN"):
            wrapped.sourceFrequency(pattern)
        self.assertEqual(calls["count"], 0)

    def test_aliases_and_stats_contracts(self):
        self.assertEqual(
            self.wrapped.countSourcesWithOccurrences("AC"),
            self.wrapped.sourceFrequency("AC"))
        self.assertEqual(
            self.wrapped.topSourcesByAbundance("AC", k=3),
            self.wrapped.topSources("AC", k=3))

        freq = self.wrapped.sourceFrequency("AC", include_stats=True)
        self.assertEqual(freq["source_frequency"],
                         freq["stats"]["source_frequency"])
        self.assertEqual(freq["stats"]["nonzero_leaves"],
                         freq["source_frequency"])
        self.assertEqual(freq["source_count"], 10)

        top = self.wrapped.topSources("AC", k=3, include_stats=True)
        self.assertEqual(top["k"], 3)
        self.assertEqual(top["stats"]["sources_returned"],
                         len(top["sources"]))
        self.assertEqual(top["stats"]["nonzero_sources_considered"],
                         len(self.wrapped.nonzeroSources("AC")))

    def test_single_leaf_package(self):
        work = tempfile.mkdtemp(prefix="f56-host-leaf-")
        try:
            leaf = f3.make_read_derived_leaf(work, "solo",
                                             ["ACGTAC", "GATTACA"])
            merged = f3.NaiveSuffixBWT(leaf)
            wrapped = MultiSourceBWT(
                merged, MultiSourceQueryIndex(leaf, mmap=False))
            self.assertEqual(wrapped.sourceFrequency("AC"), 1)
            self.assertEqual(wrapped.sourceFrequency("ZZZZ"), 0)
            out = wrapped.topSources("AC", k=1)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["source_id"], "solo")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_edge_fixtures(self):
        cases = [
            {"s0": ["ACGT", "ACGT"], "s1": ["ACGT", "TGCA"],
             "s2": ["GATTACA", "ACGT"]},
            {"s0": ["ACGT", "ACGT", "ACGT"], "s1": ["ACGT", "ACGT"],
             "s2": ["TTTT", "ACGT"]},
            {"s0": ["ACGTAC"], "s1": ["ACGTAC"], "s2": ["ACGTAC"],
             "s3": ["ACGTAC"]},
            {"s0": ["N", "NN", "NACGT", "NNNNN", "ACNNT"],
             "s1": ["NACGT", "GGNCC", "TTAACC"],
             "s2": ["NA", "ANG", "NNNA"]},
        ]
        for case_index, source_reads in enumerate(cases):
            work = tempfile.mkdtemp(prefix="f56-host-edge-")
            try:
                output, manifest, merged, standalone, _ = (
                    f3.build_fixture(work, source_reads,
                                     name="m%d" % case_index))
                wrapped = MultiSourceBWT(
                    merged, MultiSourceQueryIndex(output, mmap=False))
                for pattern in ("A", "C", "G", "T", "N", "$", "AA", "AC",
                                "GT", "NN", "ACGT", "ACGTAC", "A$", "T$"):
                    expected = f4.expected_sparse(standalone, manifest,
                                                  pattern)
                    self.assertEqual(
                        wrapped.sourceFrequency(pattern), len(expected),
                        (case_index, pattern))
                    table = [src["id"] for src in manifest["sources"]]
                    tindex = {sid: i for i, sid in enumerate(table)}
                    ranked = sorted(
                        expected,
                        key=lambda item: (-item[1], tindex[item[0]]))
                    for k in (0, 1, 3, 20):
                        got = wrapped.topSources(pattern, k=k)
                        expected_top = [(n, c) for n, c, _ in ranked[:k]]
                        if k >= len(ranked):
                            expected_top = [(n, c) for n, c, _ in ranked]
                        self.assertEqual(
                            [(r["source_id"], r["count"]) for r in got],
                            expected_top, (case_index, pattern, k))
            finally:
                shutil.rmtree(work, ignore_errors=True)


class RandomReadFrequencyTopKHostTests(unittest.TestCase):
    def test_random_reads_differential(self):
        mismatches = []
        comparisons = 0
        for seed in SEEDS:
            rng = random.Random(seed)
            for case in range(10):
                source_count = rng.randint(2, 6)
                source_reads = {}
                for i in range(source_count):
                    read_count = rng.randint(1, 5)
                    reads = []
                    for _ in range(read_count):
                        length = rng.randint(1, 10)
                        chars = []
                        for _ in range(length):
                            chars.append(
                                "N" if rng.random() < 0.15 else
                                "ACGT"[rng.randint(0, 3)])
                        reads.append("".join(chars))
                    source_reads["s%d" % i] = reads
                work = tempfile.mkdtemp(prefix="f56-host-rand-")
                try:
                    output, manifest, merged, standalone, _ = (
                        f3.build_fixture(work, source_reads,
                                         name="m%d" % case))
                    wrapped = MultiSourceBWT(
                        merged,
                        MultiSourceQueryIndex(output, mmap=False))
                    patterns = set(["A", "C", "G", "T", "N", "$", "AA",
                                    "AC", "NN", "A$", "T$"])
                    for reads in source_reads.values():
                        for read in reads:
                            for start in range(len(read)):
                                for end in range(start + 1, len(read) + 1):
                                    patterns.add(read[start:end])
                    table = [src["id"] for src in manifest["sources"]]
                    table_index = {sid: i for i, sid in enumerate(table)}
                    for pattern in patterns:
                        sparse = f4.expected_sparse(standalone, manifest,
                                                    pattern)
                        comparisons += 1
                        if wrapped.sourceFrequency(pattern) != len(sparse):
                            mismatches.append(
                                ("freq", seed, case, pattern, source_reads))
                        ranked = sorted(
                            sparse,
                            key=lambda item: (-item[1],
                                              table_index[item[0]]))
                        for k in (0, 1, 2, 5):
                            got = wrapped.topSources(pattern, k=k)
                            selected = (ranked[:k] if k < len(ranked)
                                        else ranked)
                            expected_top = [(n, c) for n, c, _ in selected]
                            comparisons += 1
                            if [(r["source_id"], r["count"])
                                    for r in got] != expected_top:
                                mismatches.append(
                                    ("top", seed, case, pattern, k,
                                     source_reads))
                finally:
                    shutil.rmtree(work, ignore_errors=True)
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 3000)


class EvidenceRecordHostTests(unittest.TestCase):
    EVIDENCE = os.path.join(PACKAGE, "evidence",
                            "feature5-6-frequency-topk.json")
    EVIDENCE_GENERATOR = os.path.join(
        PACKAGE, "validate", "feature5_6_frequency_topk_evidence.py")

    def test_evidence_record_consistent(self):
        evidence = json.load(open(self.EVIDENCE, encoding="utf-8"))
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "enhanced-modern2")
        self.assertEqual(
            evidence["final"]["milestone"],
            "enhanced-modern2-feature5-6-frequency-topk")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")

    def test_evidence_contract(self):
        report = json.load(open(self.EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["seed"], 20260811)
        ten = report["ten_source_fixture"]
        self.assertGreaterEqual(ten["patterns"], 350)
        self.assertGreaterEqual(ten["top_k_comparisons"], 2500)
        self.assertGreaterEqual(report["real_queries"], 60)
        self.assertTrue(ten["one_search_probe"])
        self.assertTrue(ten["count_only_probe"])
        self.assertTrue(ten["tie_rule_probe"])

    def test_evidence_generator_is_python2_and_driver_checks(self):
        text = open(self.EVIDENCE_GENERATOR, encoding="utf-8").read()
        self.assertIn("from __future__ import print_function", text)
        self.assertNotIn("f'{", text)
        self.assertIn("def run_evidence", text)
        driver = open(os.path.join(PACKAGE, "validate",
                                   "feature5-6-frequency-topk.sh"),
                      encoding="utf-8").read()
        self.assertIn("--evidence", driver)
        self.assertIn("run_evidence", driver)


if __name__ == "__main__":
    unittest.main()
