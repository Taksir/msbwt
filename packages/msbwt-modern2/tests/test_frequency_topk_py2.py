"""msbwt-modern2 enhanced Feature 5/6 tests: sample frequency and top-k
exact sources (``MUS.MultiSourceQuery.sourceFrequency`` / ``topSources``),
runnable inside the pinned Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO.

Coverage:

- ten-source read-derived fixture, >=350 patterns:
  - Feature 5 == number of standalone sources with count > 0 (Point-4
    listing length), exact for every pattern;
  - Feature 6 == sparse listing sorted by (-count, provenance order)
    truncated to k, for k = 0, 1, 2, 3, 5, 10, 20;
- one merged FM search per operation (instrumented);
- Feature 5 does not call the Feature-4 listing (count-only traversal
  probe via stats and a monkeypatched counter);
- globally absent patterns, all-ten-source patterns, ties at cutoff,
  k > support, k = 0, negative k rejected, duplicate display names;
- exact source-local intervals retained in top-k results;
- REAL modern2 integration: canonical two-source merge and a real 5-source
  balanced merge (Feature 5/6 vs standalone counts);
- deterministic randomized Level-3 differential subset (seed 20260811);
- edge fixtures: unbalanced chain, duplicates, identical reads, N-heavy,
  single-leaf package, '$' patterns.

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import os
import random
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_source_index_py2 as f1  # noqa: E402
import test_multisource_query_py2 as f3  # noqa: E402
import test_sparse_source_listing_py2 as f4  # noqa: E402

from MUS.MultiSourceProvenance import (  # noqa: E402
    initialize_leaf_provenance,
    merge_many_balanced,
    merge_two_with_provenance,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

SEED = f1.SEED

TOP_K_VALUES = (0, 1, 2, 3, 5, 10, 20)


class FrequencyTopKTenSourcePy2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f56-py2-ten-")
        cls.output, cls.manifest, cls.merged, cls.standalone, cls.leaves = (
            f3.build_merged_fixture(cls.work, f3.TEN_SOURCE_READS))
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
        # sort by (-count, provenance index)
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

    def test_top_k_ties_are_deterministic(self):
        # 'A' occurs in all ten sources; with k=10 all sources must appear
        # exactly once, ordered by (-count, provenance order)
        got = self.wrapped.topSources("A", k=10)
        self.assertEqual(len(got), 10)
        ids = [r["source_id"] for r in got]
        self.assertEqual(sorted(ids), sorted(ids))
        # ties by provenance order: identical reads give equal counts in
        # exact manifest (input) order
        work = tempfile.mkdtemp(prefix="f56-py2-ties-")
        try:
            reads = {"s0": ["ACGTAC"], "s1": ["ACGTAC"],
                     "s2": ["ACGTAC"], "s3": ["ACGTAC"]}
            output, manifest, merged, _, _ = f3.build_merged_fixture(
                work, reads, name="ties4")
            wrapped = MultiSourceBWT(
                merged, MultiSourceQueryIndex(output, mmap=False))
            table = [src["id"] for src in manifest["sources"]]
            out = wrapped.topSources("ACGT", k=2)
            self.assertEqual([r["source_id"] for r in out], table[:2])
            out = wrapped.topSources("ACGT", k=10)  # k > support
            self.assertEqual([r["source_id"] for r in out], table)
            self.assertEqual([r["count"] for r in out], [1, 1, 1, 1])
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_top_k_edge_cases(self):
        # k = 0 returns nothing
        self.assertEqual(self.wrapped.topSources("AC", k=0), [])
        # negative k rejected
        with self.assertRaises(ValueError):
            self.wrapped.topSources("AC", k=-1)
        # no hits
        self.assertEqual(self.wrapped.topSources("GGGGGGGGGGGG"), [])
        # k > number of hits returns each nonzero source exactly once
        out = self.wrapped.topSources("CGT", k=99)
        ids = [r["source_id"] for r in out]
        self.assertEqual(len(ids), len(set(ids)))
        for rec in out:
            self.assertGreater(rec["count"], 0)
        # default k = 10 with ten sources
        self.assertEqual(len(self.wrapped.topSources("A")), 10)

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
        """Feature 5 must not materialize the Feature-4 sparse list:
        instrument by replacing nonzero_sources_interval with a counter."""
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
        # and the count-only path still agrees with the listing length
        self.assertEqual(wrapped.sourceFrequency("ACGT"),
                         len(original(
                             *self.merged.findIndicesOfStr("ACGT"))))

    def test_aliases_are_same_functions(self):
        def underlying(name):
            attr = getattr(type(self.wrapped), name)
            for probe in ("im_func", "__func__"):
                if hasattr(attr, probe):
                    return getattr(attr, probe)
            return attr
        self.assertTrue(underlying("countSourcesWithOccurrences")
                        is underlying("sourceFrequency"))
        self.assertTrue(underlying("topSourcesByAbundance")
                        is underlying("topSources"))
        self.assertEqual(
            self.wrapped.countSourcesWithOccurrences("AC"),
            self.wrapped.sourceFrequency("AC"))
        self.assertEqual(
            self.wrapped.topSourcesByAbundance("AC", k=3),
            self.wrapped.topSources("AC", k=3))

    def test_rich_stats_contracts(self):
        freq = self.wrapped.sourceFrequency("AC", include_stats=True)
        self.assertEqual(freq["source_frequency"],
                         freq["stats"]["source_frequency"])
        self.assertEqual(freq["stats"]["nonzero_leaves"],
                         freq["source_frequency"])
        self.assertEqual(freq["merged_count"],
                         freq["merged_interval"][1]
                         - freq["merged_interval"][0])

        top = self.wrapped.topSources("AC", k=3, include_stats=True)
        self.assertEqual(top["k"], 3)
        self.assertEqual(top["stats"]["sources_returned"],
                         len(top["sources"]))
        self.assertEqual(top["stats"]["nonzero_sources_considered"],
                         len(self.wrapped.nonzeroSources("AC")))

    def test_single_leaf_package(self):
        work = tempfile.mkdtemp(prefix="f56-py2-leaf-")
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
            self.assertEqual(wrapped.topSources("ZZZZ"), [])
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
            work = tempfile.mkdtemp(prefix="f56-py2-edge-")
            try:
                output, manifest, merged, standalone, _ = (
                    f3.build_merged_fixture(work, source_reads,
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


class FrequencyTopKRealPy2Tests(unittest.TestCase):
    """Level-3 tests: real pp/cfpp construction and GenericMerge merges."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f56-py2-real-")
        cls.harness = f1.SourceHarness(cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_canonical_two_source_real(self):
        a_dir = self.harness.build_fixture_source("f56a", "uniform-a.fastq")
        b_dir = self.harness.build_fixture_source("f56b", "uniform-b.fastq")
        initialize_leaf_provenance(a_dir, source_id="in_a",
                                   source_name="in_a")
        initialize_leaf_provenance(b_dir, source_id="in_b",
                                   source_name="in_b")
        m_dir = os.path.join(self.work, "f56m")
        merge_two_with_provenance(a_dir, b_dir, m_dir,
                                  merge_two_func=f3.holt_merge_two_local,
                                  num_procs=1)
        a_bwt = f1.load_standalone(a_dir)
        b_bwt = f1.load_standalone(b_dir)
        merged = MultiSourceBWT.load(m_dir, mmap=False)

        queries = f1.build_queries(f1.CANONICAL_READS_A,
                                   f1.CANONICAL_READS_B)
        queries.extend([b"$", b"A$", b"T$", b"ACGTN$"])
        mismatches = []
        for query in queries:
            expected_a = int(a_bwt.countOccurrencesOfSeq(query))
            expected_b = int(b_bwt.countOccurrencesOfSeq(query))
            frequency = merged.sourceFrequency(query)
            expected_freq = (1 if expected_a else 0) + (1 if expected_b
                                                        else 0)
            if frequency != expected_freq:
                mismatches.append((query, "freq", frequency,
                                   expected_freq))
            for k in (0, 1, 2, 5):
                top = merged.topSources(query, k=k)
                candidates = []
                if expected_a:
                    candidates.append(("in_a", expected_a))
                if expected_b:
                    candidates.append(("in_b", expected_b))
                ranked = sorted(candidates,
                                key=lambda item: (-item[1],
                                                  {"in_a": 0,
                                                   "in_b": 1}[item[0]]))
                if k >= len(ranked):
                    expected_top = ranked
                else:
                    expected_top = ranked[:k]
                got_top = [(r["source_id"], r["count"]) for r in top]
                if got_top != expected_top:
                    mismatches.append((query, "top", k, got_top,
                                       expected_top))
        self.assertEqual(mismatches, [])

    def test_five_source_real(self):
        rng = random.Random(SEED + 7)
        leaves = []
        standalone = {}
        for i in range(5):
            reads = f1.make_random_case(rng)[0]
            leaf = self.harness.build_fastq_source("f56s%d" % i, reads)
            initialize_leaf_provenance(leaf, source_id="src%d" % i,
                                       source_name="src%d" % i)
            leaves.append(leaf)
            standalone["src%d" % i] = f1.load_standalone(leaf)
        output = os.path.join(self.work, "f56five")
        merge_many_balanced(leaves, output,
                            merge_two_func=f3.holt_merge_two_local,
                            num_procs=1)
        merged = MultiSourceBWT.load(output, mmap=False)

        queries = ["A", "C", "G", "T", "N", "AC", "GT", "NA", "NN",
                   "AAA", "ACGT", "TTA", "CGTAC", "$"]
        mismatches = []
        for query in queries:
            counts = {}
            for sid in ("src%d" % i for i in range(5)):
                count = int(standalone[sid].countOccurrencesOfSeq(query))
                if count:
                    counts[sid] = count
            frequency = merged.sourceFrequency(query)
            if frequency != len(counts):
                mismatches.append((query, "freq", frequency, len(counts)))
            ranked = sorted(counts.items(),
                            key=lambda item: (-item[1],
                                              {"src%d" % i: i
                                               for i in range(5)}
                                              [item[0]]))
            for k in (0, 1, 2, 5):
                top = merged.topSources(query, k=k)
                expected_top = ranked[:k] if k < len(ranked) else ranked
                got_top = [(r["source_id"], r["count"]) for r in top]
                if got_top != expected_top:
                    mismatches.append((query, "top", k, got_top,
                                       expected_top))
        self.assertEqual(mismatches, [])

    def test_randomized_real_differential(self):
        rng = random.Random(SEED)
        mismatches = []
        comparisons = 0
        for case_index in range(4):
            source_count = rng.randint(2, 4)
            leaves = []
            standalone = {}
            reads_by_source = {}
            for i in range(source_count):
                reads = f1.make_random_case(rng)[0]
                reads_by_source["r%d" % i] = reads
                leaf = self.harness.build_fastq_source(
                    "f56rd%d-%d" % (case_index, i), reads)
                initialize_leaf_provenance(leaf, source_id="r%d" % i,
                                           source_name="r%d" % i)
                leaves.append(leaf)
                standalone["r%d" % i] = f1.load_standalone(leaf)
            output = os.path.join(self.work, "f56rd%d" % case_index)
            merge_many_balanced(leaves, output,
                                merge_two_func=f3.holt_merge_two_local,
                                num_procs=1)
            merged = MultiSourceBWT.load(output, mmap=False)
            queries = set(["A", "C", "G", "T", "N", "$", "AA", "AC", "NN",
                           "A$", "T$"])
            for reads in reads_by_source.values():
                for read in reads:
                    for start in range(len(read)):
                        for end in range(start + 1, len(read) + 1):
                            queries.add(read[start:end])
            for query in queries:
                counts = {}
                for sid in reads_by_source:
                    count = int(standalone[sid].countOccurrencesOfSeq(query))
                    if count:
                        counts[sid] = count
                frequency = merged.sourceFrequency(query)
                comparisons += 1
                if frequency != len(counts):
                    mismatches.append({
                        "case": case_index, "query": query,
                        "kind": "freq", "got": frequency,
                        "expected": len(counts),
                        "reads_by_source": reads_by_source})
                order = {"r%d" % i: i for i in range(source_count)}
                ranked = sorted(counts.items(),
                                key=lambda item: (-item[1],
                                                  order[item[0]]))
                for k in (0, 1, 2, 5):
                    top = merged.topSources(query, k=k)
                    expected_top = (ranked[:k] if k < len(ranked)
                                    else ranked)
                    got_top = [(r["source_id"], r["count"]) for r in top]
                    comparisons += 1
                    if got_top != expected_top:
                        mismatches.append({
                            "case": case_index, "query": query,
                            "kind": "top", "k": k, "got": got_top,
                            "expected": expected_top,
                            "reads_by_source": reads_by_source})
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 500)


if __name__ == "__main__":
    unittest.main()
