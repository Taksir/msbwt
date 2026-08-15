"""Host-side regression tests for enhanced-modern2 Feature 4: sparse
nonzero-source listing with exact counts (``MUS.MultiSourceQuery``).

These tests are read-only and run on any CPython 3 with NumPy; they do NOT
require the compiled MUSCython extensions (real-merge integration runs in
the pinned Python-2.7 suite and the Feature-4 validation driver).

Coverage:

- ten-source read-derived fixture: sparse listing == gold standard
  ``{s: standalone count > 0}`` in authoritative manifest order for the
  full >=350-pattern set, exact counts, constituent-local intervals,
  sum-of-counts == merged count, deterministic ordering;
- one merged FM search per sparse query; zero rank nodes loaded for
  globally absent patterns;
- pruning validation (zero/one/few/all sources hit) with traversal
  statistics checked against an independent recursive DFS counter;
- interval-level API (``nonzero_sources_interval``) requires no BWT search;
- alias identity and rich ``include_stats`` result contract;
- synthetic random trees with random intervals: sparse listing == naive
  per-leaf bit-array projection counts, seeds 20260811/20260812/20260813;
- randomized read-derived differential (3 seeds, 30 cases);
- edge fixtures: unbalanced chain, duplicates, identical reads, N-heavy,
  single-leaf package, absent patterns, '$' patterns;
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
sys.path.insert(0, PACKAGE)

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

SEEDS = (20260811, 20260812, 20260813)

import test_multisource_query as f3  # noqa: E402


def expected_sparse(standalone, manifest, pattern):
    out = []
    for source_record in manifest["sources"]:
        source_name = source_record["id"]
        low, high = standalone[source_name].findIndicesOfStr(pattern)
        count = high - low
        if count > 0:
            out.append((source_name, count, (low, high)))
    return out


class SparseTenSourceHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f4-host-ten-")
        cls.output, cls.manifest, cls.merged, cls.standalone, cls.leaves = (
            f3.build_fixture(cls.work, f3.TEN_SOURCE_READS))
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
        table_order = [src["id"] for src in self.manifest["sources"]]
        for pattern in patterns:
            expected = expected_sparse(self.standalone, self.manifest,
                                       pattern)
            result = self.wrapped.nonzeroSources(pattern)
            got = [(r["source_id"], r["count"]) for r in result]
            comparisons += 1
            if got != [(n, c) for n, c, _ in expected]:
                mismatches.append((pattern, got, expected))
            # deterministic ordering: subset of the manifest source table
            self.assertEqual(
                [r["source_id"] for r in result],
                [n for n in table_order if n in
                 {r["source_id"] for r in result}])
            # sum of sparse counts == merged count
            merged_low, merged_high = self.merged.findIndicesOfStr(pattern)
            self.assertEqual(sum(c for _, c in got),
                             merged_high - merged_low)
            comparisons += 1
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 800)

    def test_sparse_intervals_match_standalone(self):
        for pattern in ("AC", "CGT", "AAAA", "N", "TTTTT", "GGGGG", "$"):
            for rec in self.wrapped.nonzeroSources(pattern,
                                                   include_intervals=True):
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

    def test_absent_patterns_load_no_rank_nodes(self):
        out = self.wrapped.nonzeroSources("GGGGGGGGGGGG", include_stats=True)
        self.assertEqual(out["sources"], [])
        self.assertEqual(out["stats"]["rank_nodes_loaded_for_query"], 0)
        self.assertEqual(out["stats"]["internal_nodes_visited"], 0)

    def test_pruning_statistics_match_independent_dfs(self):
        def independent_stats(node, l, r):
            stats = {"internal_nodes_visited": 0, "branches_pruned": 0,
                     "leaves_reported": 0}
            if l == r:
                return stats
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
            for child, cl, cr in ((node["left"], left_l, left_r),
                                  (node["right"], right_l, right_r)):
                if cl == cr:
                    stats["branches_pruned"] += 1
                else:
                    sub = independent_stats(child, cl, cr)
                    for key in stats:
                        stats[key] += sub[key]
            return stats

        fresh = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        for pattern in ("ACGT", "AAAA", "N", "TTTTT", "AAGGTT", "AC", "$",
                        "GGGGGGGGGG"):
            interval = self.merged.findIndicesOfStr(pattern)
            _, stats = fresh.nonzero_sources_interval(
                interval[0], interval[1], include_stats=True)
            expected = independent_stats(self.manifest["root"], interval[0],
                                         interval[1])
            self.assertEqual(stats["internal_nodes_visited"],
                             expected["internal_nodes_visited"], pattern)
            self.assertEqual(stats["branches_pruned"],
                             expected["branches_pruned"], pattern)
            self.assertEqual(stats["leaves_reported"],
                             expected["leaves_reported"], pattern)

    def test_pruning_categories(self):
        self.assertEqual(self.wrapped.nonzeroSources("GGGGGGGGGG"), [])
        out = self.wrapped.nonzeroSources("AAGGTT")  # only sample09
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source_id"], "sample09")
        self.assertEqual(len(self.wrapped.nonzeroSources("A")), 10)
        out = self.wrapped.nonzeroSources("CGT")
        self.assertTrue(1 < len(out) < 10)

    def test_interval_level_api_requires_no_bwt_search(self):
        interval = self.merged.findIndicesOfStr("AC")
        before = self.merged.search_calls
        out = self.index.nonzero_sources_interval(
            interval[0], interval[1], include_intervals=True)
        self.assertEqual(self.merged.search_calls, before)
        self.assertTrue(out)
        for rec in out:
            self.assertEqual(rec["count"],
                             rec["source_interval"][1]
                             - rec["source_interval"][0])

    def test_alias_and_stats_contract(self):
        plain = self.wrapped.nonzeroSources("AC")
        alias = self.wrapped.listSourcesWithOccurrences("AC")
        self.assertEqual(plain, alias)
        rich = self.wrapped.nonzeroSources("AC", include_stats=True)
        self.assertEqual(rich["sequence"], b"AC")
        self.assertEqual(rich["merged_count"],
                         rich["merged_interval"][1]
                         - rich["merged_interval"][0])
        self.assertEqual(rich["stats"]["leaves_reported"],
                         len(rich["sources"]))
        self.assertEqual(rich["stats"]["sources_reported"],
                         len(rich["sources"]))

    def test_single_leaf_package(self):
        work = tempfile.mkdtemp(prefix="f4-host-leaf-")
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
            work = tempfile.mkdtemp(prefix="f4-host-edge-")
            try:
                output, manifest, merged, standalone, _ = (
                    f3.build_fixture(work, source_reads,
                                     name="m%d" % case_index))
                wrapped = MultiSourceBWT(
                    merged, MultiSourceQueryIndex(output, mmap=False))
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


class SyntheticSparseHostTests(unittest.TestCase):
    """Random provenance trees + random intervals: sparse listing == naive
    per-leaf bit-array projection counts."""

    def random_bits_merge(self, rng):
        def merge_two(left_dir, right_dir, output_dir, num_procs=1,
                      logger=None):
            left = np.load(os.path.join(left_dir, "msbwt.npy"))
            right = np.load(os.path.join(right_dir, "msbwt.npy"))
            nl, nr = len(left), len(right)
            bits = [0] * nl + [1] * nr
            rng.shuffle(bits)
            if not os.path.isdir(output_dir):
                os.makedirs(output_dir)
            merged = np.empty(len(bits), dtype=np.uint8)
            li = ri = 0
            for i, bit in enumerate(bits):
                if bit:
                    merged[i] = right[ri]
                    ri += 1
                else:
                    merged[i] = left[li]
                    li += 1
            np.save(os.path.join(output_dir, "msbwt.npy"), merged)
            np.save(os.path.join(output_dir, "inter0.npy"),
                    f3.pack_little_endian_bits(bits))
        return merge_two

    def test_random_tree_sparse_listing_differential(self):
        mismatches = []
        comparisons = 0
        for seed in SEEDS:
            rng = random.Random(seed)
            for case in range(20):
                source_count = rng.randint(1, 8)
                work = tempfile.mkdtemp(prefix="f4-host-synth-")
                try:
                    leaves = []
                    for i in range(source_count):
                        length = rng.randint(1, 40)
                        leaf = os.path.join(work, "s%d" % i)
                        os.mkdir(leaf)
                        np.save(os.path.join(leaf, "msbwt.npy"),
                                np.zeros(length, dtype=np.uint8))
                        initialize_leaf_provenance(
                            leaf, source_id="s%d" % i,
                            source_name="s%d" % i)
                        leaves.append(leaf)
                    output = os.path.join(work, "merged")
                    work_dir = os.path.join(work, "w")
                    manifest = merge_many_balanced(
                        leaves, output,
                        merge_two_func=self.random_bits_merge(rng),
                        work_dir=work_dir, keep_work=True)
                    total = int(manifest["bwt_length"])
                    index = MultiSourceQueryIndex(
                        output, rank_stride_bytes=1, mmap=False,
                        use_saved_rank=False)

                    def naive_sparse(node, l, r):
                        if l == r:
                            return []
                        if node["type"] == "leaf":
                            return [(node["source_id"], r - l)]
                        bits = unpack_interleave(
                            os.path.join(output, str(node["interleave"])),
                            node["length"])
                        left_sel = bits == 0
                        right_sel = bits == 1
                        return (naive_sparse(node["left"],
                                             int(np.count_nonzero(
                                                 left_sel[:l])),
                                             int(np.count_nonzero(
                                                 left_sel[:r]))) +
                                naive_sparse(node["right"],
                                             int(np.count_nonzero(
                                                 right_sel[:l])),
                                             int(np.count_nonzero(
                                                 right_sel[:r]))))

                    for _ in range(8):
                        start = rng.randint(0, total)
                        end = rng.randint(start, total)
                        expected = naive_sparse(manifest["root"], start, end)
                        got = index.nonzero_sources_interval(start, end)
                        comparisons += 1
                        if got != [{"source_id": sid, "source_name": sid,
                                    "count": c} for sid, c in expected]:
                            mismatches.append(
                                (seed, case, start, end, got, expected))
                        # sum of counts == interval length
                        comparisons += 1
                        if sum(c for _, c in expected) != end - start:
                            mismatches.append(
                                ("sum", seed, case, start, end, expected))
                finally:
                    shutil.rmtree(work, ignore_errors=True)
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 800)


class RandomReadSparseHostTests(unittest.TestCase):
    def test_random_reads_sparse_differential(self):
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
                work = tempfile.mkdtemp(prefix="f4-host-rand-")
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
                    for pattern in patterns:
                        expected = expected_sparse(standalone, manifest,
                                                   pattern)
                        result = wrapped.nonzeroSources(pattern)
                        got = [(r["source_id"], r["count"])
                               for r in result]
                        comparisons += 1
                        if got != [(n, c) for n, c, _ in expected]:
                            mismatches.append(
                                (seed, case, pattern, got, expected,
                                 source_reads))
                finally:
                    shutil.rmtree(work, ignore_errors=True)
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 3000)


class EvidenceRecordHostTests(unittest.TestCase):
    EVIDENCE = os.path.join(PACKAGE, "evidence",
                            "feature4-sparse-source-listing.json")
    EVIDENCE_GENERATOR = os.path.join(
        PACKAGE, "validate", "feature4_sparse_source_evidence.py")

    def test_evidence_record_consistent(self):
        evidence = json.load(open(self.EVIDENCE, encoding="utf-8"))
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "enhanced-modern2")
        self.assertEqual(
            evidence["final"]["milestone"],
            "enhanced-modern2-feature4-sparse-source-listing")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")

    def test_evidence_contract(self):
        report = json.load(open(self.EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["seed"], 20260811)
        ten = report["ten_source_fixture"]
        self.assertGreaterEqual(ten["patterns"], 350)
        self.assertGreaterEqual(report["real_queries"], 60)
        self.assertIn("point3_counts", report["oracles"])
        self.assertIn("standalone_bwt", report["oracles"])
        self.assertTrue(ten["one_search_probe"])
        self.assertTrue(ten["pruning_probe"])
        perf = report["performance"]
        self.assertGreater(perf["sparse_queries"], 0)

    def test_evidence_generator_is_python2_and_driver_checks(self):
        text = open(self.EVIDENCE_GENERATOR, encoding="utf-8").read()
        self.assertIn("from __future__ import print_function", text)
        self.assertNotIn("f'{", text)
        self.assertIn("def run_evidence", text)
        driver = open(os.path.join(PACKAGE, "validate",
                                   "feature4-sparse-source-listing.sh"),
                      encoding="utf-8").read()
        self.assertIn("--evidence", driver)
        self.assertIn("run_evidence", driver)


if __name__ == "__main__":
    unittest.main()
