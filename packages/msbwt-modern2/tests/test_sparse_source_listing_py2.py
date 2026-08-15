"""msbwt-modern2 enhanced Feature 4 tests: sparse nonzero-source listing
with exact counts (``MUS.MultiSourceQuery.nonzeroSources``), runnable
inside the pinned Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO.

Coverage:

- ten-source read-derived fixture: sparse listing == the gold standard
  ``{s: countOccurrencesForSource(P, s) for s if count > 0}`` (Point-3
  oracle) for the full >=350-pattern set, with exact per-source counts,
  constituent-local intervals, sum-of-counts == merged count, deterministic
  provenance/input ordering;
- ONE merged FM search per sparse query (instrumented), and zero rank nodes
  loaded for globally absent patterns;
- pruning validation: zero sources hit, one source hit, few sources hit,
  all sources hit; traversal statistics (internal nodes visited, branches
  pruned, leaves reported) checked against an independent DFS counter;
- interval-level API (``nonzero_sources_interval``) requires no BWT search;
- ``givenRange`` legacy delegation on the sparse layer;
- REAL modern2 integration: canonical two-source merge and real 5-source
  balanced merge; every pattern's sparse result equals the filtered
  per-source Point-3 counts and sums to the merged count;
- deterministic randomized Level-3 differential subset (seed 20260811);
- edge fixtures: unbalanced chain, duplicates, identical reads, N-heavy,
  single-leaf package, absent patterns, '$' patterns.

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import json
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

from MUS.MultiSourceProvenance import (  # noqa: E402
    initialize_leaf_provenance,
    load_manifest,
    merge_many_balanced,
    merge_two_with_provenance,
    unpack_interleave,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

SEED = f1.SEED


def expected_sparse(standalone, manifest, pattern):
    """Gold standard: exact sparse listing from the independent standalone
    suffix-order oracles, in authoritative manifest (input) order."""
    out = []
    for source_record in manifest["sources"]:
        source_name = source_record["id"]
        low, high = standalone[source_name].findIndicesOfStr(pattern)
        count = high - low
        if count > 0:
            out.append((source_name, count, (low, high)))
    return out


class SparseTenSourcePy2Tests(unittest.TestCase):
    """Main Feature-4 suite over the ten-source read-derived package."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f4-py2-ten-")
        cls.output, cls.manifest, cls.merged, cls.standalone, cls.leaves = (
            f3.build_merged_fixture(cls.work, f3.TEN_SOURCE_READS))
        cls.index = MultiSourceQueryIndex(
            cls.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        cls.wrapped = MultiSourceBWT(cls.merged, cls.index)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_sparse_listing_matches_point3_oracle_for_all_patterns(self):
        patterns = f3.all_test_patterns()
        self.assertGreaterEqual(len(patterns), 350)
        mismatches = []
        comparisons = 0
        for pattern in patterns:
            expected = expected_sparse(self.standalone, self.manifest,
                                       pattern)
            expected_names = [name for name, _, _ in expected]
            expected_counts = [count for _, count, _ in expected]

            result = self.wrapped.nonzeroSources(pattern)
            got_names = [rec["source_id"] for rec in result]
            got_counts = [rec["count"] for rec in result]
            comparisons += 1

            if got_names != expected_names or got_counts != expected_counts:
                mismatches.append((pattern, got_names, got_counts,
                                   expected_names, expected_counts))

            # deterministic ordering = source table order (left-to-right
            # leaves in the manifest)
            table_order = [src["id"] for src in self.manifest["sources"]]
            self.assertEqual(
                got_names, [n for n in table_order if n in got_names])

            # sum of sparse counts == merged count
            merged_low, merged_high = self.merged.findIndicesOfStr(pattern)
            self.assertEqual(sum(got_counts), merged_high - merged_low)
            comparisons += 1

            # countOccurrencesForSource agrees per source
            for name, count, _ in expected:
                self.assertEqual(
                    self.wrapped.countOccurrencesForSource(pattern, name),
                    count)
                comparisons += 1
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 1000)

    def test_sparse_intervals_match_standalone_intervals(self):
        for pattern in ("AC", "CGT", "AAAA", "N", "TTTTT", "GGGGG", "$"):
            result = self.wrapped.nonzeroSources(pattern,
                                                 include_intervals=True)
            for rec in result:
                low, high = self.standalone[rec["source_id"]].findIndicesOfStr(
                    pattern)
                self.assertEqual(rec["source_interval"], (low, high))

    def test_one_merged_search_per_sparse_query(self):
        fresh = MultiSourceBWT(
            self.merged,
            MultiSourceQueryIndex(self.output, mmap=False,
                                  use_saved_rank=False))
        before = self.merged.search_calls
        for pattern in ("ACGT", "A", "$", "NNNNN"):
            fresh.nonzeroSources(pattern)
        self.assertEqual(self.merged.search_calls, before + 4)

    def test_absent_pattern_loads_no_rank_nodes(self):
        fresh = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        result, stats = fresh.nonzero_sources_interval(
            0, 0, include_stats=True)
        self.assertEqual(result, [])
        self.assertEqual(stats["rank_nodes_loaded_for_query"], 0)
        self.assertEqual(stats["internal_nodes_visited"], 0)

        # a globally absent pattern gives an empty merged interval
        before = self.merged.search_calls
        out = self.wrapped.nonzeroSources("GGGGGGGGGGGG", include_stats=True)
        self.assertEqual(self.merged.search_calls, before + 1)
        self.assertEqual(out["sources"], [])
        self.assertEqual(out["stats"]["rank_nodes_loaded_for_query"], 0)

    def test_pruning_statistics_match_independent_dfs(self):
        """Traversal stats must equal an independent recursive counter that
        shares no code with the sparse implementation."""
        patterns = ["ACGT", "AAAA", "N", "TTTTT", "AAGGTT", "AC", "$"]

        def independent_stats(manifest, node, l, r):
            stats = {"internal_nodes_visited": 0, "branches_pruned": 0,
                     "leaves_reported": 0}
            if l == r:
                return stats  # empty intervals visit nothing (like the
                              # production early return)
            if node["type"] == "leaf":
                stats["leaves_reported"] += 1
                return stats
            stats["internal_nodes_visited"] += 1
            bits = unpack_interleave(
                os.path.join(self.output, str(node["interleave"])),
                node["length"])
            left_sel = bits == 0
            right_sel = bits == 1
            left_l = int(np.count_nonzero(left_sel[:l]))
            left_r = int(np.count_nonzero(left_sel[:r]))
            right_l = int(np.count_nonzero(right_sel[:l]))
            right_r = int(np.count_nonzero(right_sel[:r]))
            if left_l == left_r:
                stats["branches_pruned"] += 1
            else:
                sub = independent_stats(manifest, node["left"], left_l,
                                        left_r)
                for key in stats:
                    stats[key] += sub[key]
            if right_l == right_r:
                stats["branches_pruned"] += 1
            else:
                sub = independent_stats(manifest, node["right"], right_l,
                                        right_r)
                for key in stats:
                    stats[key] += sub[key]
            return stats

        fresh = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        for pattern in patterns:
            interval = self.merged.findIndicesOfStr(pattern)
            _, stats = fresh.nonzero_sources_interval(
                interval[0], interval[1], include_stats=True)
            expected = independent_stats(
                self.manifest, self.manifest["root"], interval[0],
                interval[1])
            self.assertEqual(
                stats["internal_nodes_visited"],
                expected["internal_nodes_visited"], pattern)
            self.assertEqual(stats["branches_pruned"],
                             expected["branches_pruned"], pattern)
            self.assertEqual(stats["leaves_reported"],
                             expected["leaves_reported"], pattern)

    def test_pruning_categories(self):
        # zero sources hit
        self.assertEqual(self.wrapped.nonzeroSources("GGGGGGGGGG"), [])
        # one source hit: AAGGTT only in sample09
        out = self.wrapped.nonzeroSources("AAGGTT")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source_id"], "sample09")
        # all sources hit: a single symbol present in every source
        out = self.wrapped.nonzeroSources("A")
        self.assertEqual(len(out), 10)
        # few sources hit
        out = self.wrapped.nonzeroSources("CGT")
        self.assertTrue(1 < len(out) < 10)

    def test_interval_level_api_requires_no_bwt_search(self):
        interval = self.merged.findIndicesOfStr("AC")  # one search
        before = self.merged.search_calls
        out = self.index.nonzero_sources_interval(
            interval[0], interval[1], include_intervals=True)
        self.assertEqual(self.merged.search_calls, before)  # no new search
        self.assertTrue(out)
        for rec in out:
            self.assertEqual(rec["count"],
                             rec["source_interval"][1]
                             - rec["source_interval"][0])

    def test_alias_is_same_function(self):
        wrapped = self.wrapped
        self.assertEqual(
            wrapped.listSourcesWithOccurrences("AC"),
            wrapped.nonzeroSources("AC"))
        # the two names must resolve to the same underlying function
        def underlying(name):
            attr = getattr(type(wrapped), name)
            for probe in ("im_func", "__func__"):
                if hasattr(attr, probe):
                    return getattr(attr, probe)
            return attr
        self.assertTrue(underlying("listSourcesWithOccurrences")
                        is underlying("nonzeroSources"))

    def test_single_leaf_package(self):
        work = tempfile.mkdtemp(prefix="f4-py2-leaf-")
        try:
            leaf = f3.make_read_derived_leaf(work, "solo",
                                             ["ACGTAC", "GATTACA"])
            merged = f3.NaiveSuffixBWT(leaf)
            wrapped = MultiSourceBWT(
                merged, MultiSourceQueryIndex(leaf, mmap=False))
            for pattern in ("A", "AC", "ACGT", "GATTACA", "$"):
                expected = merged.findIndicesOfStr(pattern)
                expected_count = expected[1] - expected[0]
                if expected_count:
                    out = wrapped.nonzeroSources(pattern)
                    self.assertEqual(len(out), 1)
                    self.assertEqual(out[0]["source_id"], "solo")
                    self.assertEqual(out[0]["count"], expected_count)
                else:
                    self.assertEqual(wrapped.nonzeroSources(pattern), [])
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
            work = tempfile.mkdtemp(prefix="f4-py2-edge-")
            try:
                output, manifest, merged, standalone, _ = (
                    f3.build_merged_fixture(work, source_reads,
                                            name="m%d" % case_index))
                wrapped = MultiSourceBWT(
                    merged,
                    MultiSourceQueryIndex(output, mmap=False))
                for pattern in ("A", "C", "G", "T", "N", "$", "AA", "AC",
                                "GT", "NN", "ACGT", "ACGTAC", "A$", "T$"):
                    expected = expected_sparse(standalone, manifest, pattern)
                    result = wrapped.nonzeroSources(pattern)
                    self.assertEqual(
                        [(r["source_id"], r["count"]) for r in result],
                        [(n, c) for n, c, _ in expected],
                        (case_index, pattern))
            finally:
                shutil.rmtree(work, ignore_errors=True)


class SparseRealIntegrationPy2Tests(unittest.TestCase):
    """Level-3 tests: real pp/cfpp construction and GenericMerge merges."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f4-py2-real-")
        cls.harness = f1.SourceHarness(cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_given_range_delegation_real(self):
        a_dir = self.harness.build_fixture_source("f4gr-a", "uniform-a.fastq")
        b_dir = self.harness.build_fixture_source("f4gr-b", "uniform-b.fastq")
        initialize_leaf_provenance(a_dir, source_id="in_a",
                                   source_name="in_a")
        initialize_leaf_provenance(b_dir, source_id="in_b",
                                   source_name="in_b")
        m_dir = os.path.join(self.work, "f4gr-m")
        merge_two_with_provenance(a_dir, b_dir, m_dir,
                                  merge_two_func=f3.holt_merge_two_local,
                                  num_procs=1)
        merged = MultiSourceBWT.load(m_dir, mmap=False)
        t_interval = tuple(int(v) for v in merged.bwt.findIndicesOfStr(b"T"))
        direct = merged.nonzeroSources(b"GT")
        ranged = merged.nonzeroSources(b"G", givenRange=t_interval)
        self.assertEqual(
            [(r["source_id"], r["count"]) for r in ranged],
            [(r["source_id"], r["count"]) for r in direct])

    def test_canonical_two_source_real_sparse_listing(self):
        a_dir = self.harness.build_fixture_source("f4a", "uniform-a.fastq")
        b_dir = self.harness.build_fixture_source("f4b", "uniform-b.fastq")
        initialize_leaf_provenance(a_dir, source_id="in_a",
                                   source_name="in_a")
        initialize_leaf_provenance(b_dir, source_id="in_b",
                                   source_name="in_b")
        m_dir = os.path.join(self.work, "f4m")
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
        comparisons = 0
        for query in queries:
            expected_a = int(a_bwt.countOccurrencesOfSeq(query))
            expected_b = int(b_bwt.countOccurrencesOfSeq(query))
            result = merged.nonzeroSources(query)
            got = {r["source_id"]: r["count"] for r in result}
            expected = {}
            if expected_a:
                expected["in_a"] = expected_a
            if expected_b:
                expected["in_b"] = expected_b
            comparisons += 1
            if got != expected:
                mismatches.append((query, got, expected))
            legacy = int(merged.bwt.countOccurrencesOfSeq(query))
            if sum(got.values()) != legacy:
                mismatches.append(("sum", query, sum(got.values()), legacy))
            comparisons += 1
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 100)

    def test_five_source_real_sparse_listing(self):
        rng = random.Random(SEED + 7)
        leaves = []
        standalone = {}
        for i in range(5):
            reads = f1.make_random_case(rng)[0]
            leaf = self.harness.build_fastq_source("f4s%d" % i, reads)
            initialize_leaf_provenance(leaf, source_id="src%d" % i,
                                       source_name="src%d" % i)
            leaves.append(leaf)
            standalone["src%d" % i] = f1.load_standalone(leaf)
        output = os.path.join(self.work, "f4five")
        merge_many_balanced(leaves, output,
                            merge_two_func=f3.holt_merge_two_local,
                            num_procs=1)
        merged = MultiSourceBWT.load(output, mmap=False)

        queries = ["A", "C", "G", "T", "N", "AC", "GT", "NA", "NN",
                   "AAA", "ACGT", "TTA", "CGTAC", "$"]
        mismatches = []
        for query in queries:
            expected = {}
            for sid in ("src%d" % i for i in range(5)):
                count = int(standalone[sid].countOccurrencesOfSeq(query))
                if count:
                    expected[sid] = count
            result = merged.nonzeroSources(query)
            got = {r["source_id"]: r["count"] for r in result}
            if got != expected:
                mismatches.append((query, got, expected))
        self.assertEqual(mismatches, [])

    def test_randomized_real_sparse_differential(self):
        """Deterministic randomized Level-3 sparse differential."""
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
                    "f4rd%d-%d" % (case_index, i), reads)
                initialize_leaf_provenance(leaf, source_id="r%d" % i,
                                           source_name="r%d" % i)
                leaves.append(leaf)
                standalone["r%d" % i] = f1.load_standalone(leaf)
            output = os.path.join(self.work, "f4rd%d" % case_index)
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
                expected = {}
                for sid in reads_by_source:
                    count = int(standalone[sid].countOccurrencesOfSeq(query))
                    if count:
                        expected[sid] = count
                result = merged.nonzeroSources(query)
                got = {r["source_id"]: r["count"] for r in result}
                comparisons += 1
                if got != expected:
                    mismatches.append({
                        "case": case_index, "query": query, "got": got,
                        "expected": expected,
                        "reads_by_source": reads_by_source})
                legacy = int(merged.bwt.countOccurrencesOfSeq(query))
                if sum(got.values()) != legacy:
                    mismatches.append({
                        "case": case_index, "query": query,
                        "kind": "sum", "got": sum(got.values()),
                        "legacy": legacy,
                        "reads_by_source": reads_by_source})
                comparisons += 1
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 500)


if __name__ == "__main__":
    unittest.main()
