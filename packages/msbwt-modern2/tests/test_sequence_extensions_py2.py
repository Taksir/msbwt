"""msbwt-modern2 enhanced Feature 8A tests: source-aware left/right
sequence extensions without a reverse FM-index (``MUS.MultiSourceQuery.
extend``), runnable inside the pinned Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO.

Coverage:

- ten-source read-derived fixture, many patterns:
  - merged left-extension intervals/counts == direct exact searches of cP;
  - merged right-extension intervals/counts == direct exact searches of Pc;
  - per-source extension counts == standalone constituent counts for all
    ten sources (both directions);
  - subset/group/where extension counts == sums of standalone counts;
  - source-local intervals remain exact;
  - search-asymmetry instrumentation: left = 1 full search + 5 incremental
    extension calls; right = 5 full searches + 0 incremental calls;
  - include_zero filtering; right '$' extension with explicit alphabet;
    left '$' extension rejected; invalid direction/symbol/empty pattern/
    empty alphabet rejected; only one selector allowed;
- REAL modern2 integration: canonical two-source merge, extension counts
  vs standalone counts;
- deterministic randomized Level-3 differential subset (seed 20260811).

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
ALPHABET = "ACGNT"


def extension_patterns():
    patterns = set(["A", "C", "G", "T", "N", "AC", "GT", "NA", "ACG",
                    "CGT", "ACGT", "TTA", "NNN"])
    for reads in f3.TEN_SOURCE_READS.values():
        for read in reads:
            for start in range(len(read)):
                for end in range(start + 1, min(len(read), start + 5) + 1):
                    patterns.add(read[start:end])
    return sorted(patterns)


class ExtensionTenSourcePy2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f8a-py2-ten-")
        cls.output, cls.manifest, cls.merged, cls.standalone, cls.leaves = (
            f3.build_merged_fixture(cls.work, f3.TEN_SOURCE_READS))
        cls.index = MultiSourceQueryIndex(
            cls.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        cls.wrapped = MultiSourceBWT(cls.merged, cls.index)
        cls.metadata = cls.wrapped.source_metadata
        table = [src["id"] for src in cls.manifest["sources"]]
        cls.metadata.define_group("g1", table[:3])
        cls.metadata.define_group("g2", table[7:])
        for i, sid in enumerate(table):
            cls.metadata.set_source_metadata(sid, cohort="case"
                                             if i < 5 else "control")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_left_extensions_equal_direct_searches(self):
        mismatches = []
        for pattern in extension_patterns():
            result = self.wrapped.extendLeft(pattern)
            for rec in result["extensions"]:
                extended = rec["sequence"]
                direct = self.merged.findIndicesOfStr(extended)
                expected_count = direct[1] - direct[0]
                if rec["count"] != expected_count:
                    mismatches.append((pattern, extended, rec["count"],
                                       expected_count))
        self.assertEqual(mismatches, [])

    def test_right_extensions_equal_direct_searches(self):
        mismatches = []
        for pattern in extension_patterns():
            result = self.wrapped.extendRight(pattern)
            for rec in result["extensions"]:
                extended = rec["sequence"]
                direct = self.merged.findIndicesOfStr(extended)
                expected_count = direct[1] - direct[0]
                if rec["count"] != expected_count:
                    mismatches.append((pattern, extended, rec["count"],
                                       expected_count))
        self.assertEqual(mismatches, [])

    def test_source_extensions_match_standalone(self):
        mismatches = []
        for pattern in ("AC", "CGT", "AAAA", "N", "GTAC", "TTA"):
            for direction in ("left", "right"):
                for sid in f3.TEN_SOURCE_READS:
                    result = (self.wrapped.extendLeft(pattern, source=sid)
                              if direction == "left"
                              else self.wrapped.extendRight(pattern,
                                                            source=sid))
                    for rec in result["extensions"]:
                        extended = rec["sequence"]
                        low, high = self.standalone[sid].findIndicesOfStr(
                            extended)
                        expected = high - low
                        if rec["count"] != expected:
                            mismatches.append(
                                (pattern, direction, sid, extended,
                                 rec["count"], expected))
        self.assertEqual(mismatches, [])

    def test_subset_group_where_extensions_match_sums(self):
        mismatches = []
        for pattern in ("AC", "CGT", "AAAA", "N", "GTAC"):
            for direction in ("left", "right"):
                # subset
                subset = ["sample00", "sample02", "sample09"]
                result = (self.wrapped.extendLeft(pattern, sources=subset)
                          if direction == "left"
                          else self.wrapped.extendRight(pattern,
                                                        sources=subset))
                for rec in result["extensions"]:
                    expected = sum(
                        (lambda iv: iv[1] - iv[0])(
                            self.standalone[sid].findIndicesOfStr(
                                rec["sequence"]))
                        for sid in subset)
                    if rec["count"] != expected:
                        mismatches.append(
                            (pattern, direction, "subset", rec["sequence"],
                             rec["count"], expected))
                # group
                for name in ("g1", "g2"):
                    members = self.metadata.group_sources(name)
                    result = (self.wrapped.extendLeft(pattern, group=name)
                              if direction == "left"
                              else self.wrapped.extendRight(pattern,
                                                            group=name))
                    for rec in result["extensions"]:
                        expected = sum(
                            (lambda iv: iv[1] - iv[0])(
                                self.standalone[sid].findIndicesOfStr(
                                    rec["sequence"]))
                            for sid in members)
                        if rec["count"] != expected:
                            mismatches.append(
                                (pattern, direction, name,
                                 rec["sequence"], rec["count"], expected))
                # where
                where = {"cohort": "case"}
                members = self.metadata.select_where(**where)
                result = (self.wrapped.extendLeft(pattern, where=where)
                          if direction == "left"
                          else self.wrapped.extendRight(pattern,
                                                        where=where))
                for rec in result["extensions"]:
                    expected = sum(
                        (lambda iv: iv[1] - iv[0])(
                            self.standalone[sid].findIndicesOfStr(
                                rec["sequence"]))
                        for sid in members)
                    if rec["count"] != expected:
                        mismatches.append(
                            (pattern, direction, "where",
                             rec["sequence"], rec["count"], expected))
        self.assertEqual(mismatches, [])

    def test_source_intervals_exact(self):
        for pattern in ("AC", "CGT"):
            result = self.wrapped.extendLeft(pattern, source="sample07",
                                             include_intervals=True)
            for rec in result["extensions"]:
                low, high = self.standalone["sample07"].findIndicesOfStr(
                    rec["sequence"])
                self.assertEqual(rec["source_interval"], (low, high))
                self.assertEqual(rec["count"], high - low)
                self.assertEqual(rec["merged_count"],
                                 rec["merged_interval"][1]
                                 - rec["merged_interval"][0])

    def test_search_asymmetry_instrumentation(self):
        fresh = MultiSourceBWT(
            self.merged,
            MultiSourceQueryIndex(self.output, mmap=False,
                                  use_saved_rank=False))
        before = self.merged.search_calls
        left = fresh.extendLeft("ACGT", include_stats=True)
        left_searches = self.merged.search_calls - before
        self.assertEqual(left["stats"]["full_fm_searches"], 1)
        self.assertEqual(left["stats"]["incremental_extension_calls"], 5)
        self.assertEqual(left_searches, 6)  # 1 full + 5 givenRange steps

        before = self.merged.search_calls
        right = fresh.extendRight("ACGT", include_stats=True)
        right_searches = self.merged.search_calls - before
        self.assertEqual(right["stats"]["full_fm_searches"], 5)
        self.assertEqual(right["stats"]["incremental_extension_calls"], 0)
        self.assertEqual(right_searches, 5)

    def test_include_zero_filtering(self):
        result = self.wrapped.extendLeft("CGT", include_zero=False)
        for rec in result["extensions"]:
            self.assertGreater(rec["count"], 0)
        full = self.wrapped.extendLeft("CGT")
        self.assertLessEqual(len(result["extensions"]),
                             len(full["extensions"]))

    def test_dollar_right_extension_allowed(self):
        result = self.wrapped.extendRight("AAAA", alphabet="A$")
        bases = [rec["base"] for rec in result["extensions"]]
        self.assertIn("A", bases)
        self.assertIn("$", bases)
        for rec in result["extensions"]:
            direct = self.merged.findIndicesOfStr(rec["sequence"])
            self.assertEqual(rec["count"], direct[1] - direct[0])

    def test_validation_errors(self):
        with self.assertRaises(ValueError):
            self.wrapped.extendLeft("ACGT", alphabet="A$")  # left '$'
        with self.assertRaises(ValueError):
            self.wrapped.extend("ACGT", direction="up")
        with self.assertRaises(ValueError):
            self.wrapped.extendLeft("ACGT", alphabet="X")
        with self.assertRaises(ValueError):
            self.wrapped.extendLeft("")
        with self.assertRaises(ValueError):
            self.wrapped.extendLeft("ACGT", alphabet="")
        with self.assertRaises(ValueError):
            self.wrapped.extendLeft("ACGT", source="sample00",
                                    group="g1")
        with self.assertRaises(ValueError):
            self.wrapped.extendRight("ACGT", where="not-a-dict")

    def test_merged_selection_mode(self):
        result = self.wrapped.extendLeft("AC")
        self.assertEqual(result["selection_mode"], "merged")
        result = self.wrapped.extendLeft("AC", source="sample00")
        self.assertEqual(result["selection_mode"], "source")
        self.assertEqual(result["source_id"], "sample00")
        result = self.wrapped.extendLeft("AC", sources=["sample00",
                                                        "sample01"])
        self.assertEqual(result["selection_mode"], "subset")
        self.assertEqual(result["selected_source_ids"],
                         ["sample00", "sample01"])


class ExtensionRealIntegrationPy2Tests(unittest.TestCase):
    """Level-3 tests: real merges."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f8a-py2-real-")
        cls.harness = f1.SourceHarness(cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_canonical_two_source_extensions(self):
        a_dir = self.harness.build_fixture_source("f8a-a",
                                                  "uniform-a.fastq")
        b_dir = self.harness.build_fixture_source("f8a-b",
                                                  "uniform-b.fastq")
        initialize_leaf_provenance(a_dir, source_id="in_a",
                                   source_name="in_a")
        initialize_leaf_provenance(b_dir, source_id="in_b",
                                   source_name="in_b")
        m_dir = os.path.join(self.work, "f8a-m")
        merge_two_with_provenance(a_dir, b_dir, m_dir,
                                  merge_two_func=f3.holt_merge_two_local,
                                  num_procs=1)
        a_bwt = f1.load_standalone(a_dir)
        b_bwt = f1.load_standalone(b_dir)
        merged = MultiSourceBWT.load(m_dir, mmap=False)

        queries = ["A", "C", "G", "T", "N", "AC", "GT", "ACGT", "AAAAA",
                   "NACGT"]
        mismatches = []
        for query in queries:
            for direction in ("left", "right"):
                for sid, bwt in (("in_a", a_bwt), ("in_b", b_bwt)):
                    result = (merged.extendLeft(query, source=sid)
                              if direction == "left"
                              else merged.extendRight(query, source=sid))
                    for rec in result["extensions"]:
                        expected = int(bwt.countOccurrencesOfSeq(
                            rec["sequence"]))
                        if rec["count"] != expected:
                            mismatches.append(
                                (query, direction, sid, rec["sequence"],
                                 rec["count"], expected))
        self.assertEqual(mismatches, [])

    def test_randomized_real_extension_differential(self):
        rng = random.Random(SEED)
        mismatches = []
        comparisons = 0
        for case_index in range(3):
            source_count = rng.randint(2, 4)
            leaves = []
            standalone = {}
            reads_by_source = {}
            for i in range(source_count):
                reads = f1.make_random_case(rng)[0]
                reads_by_source["r%d" % i] = reads
                leaf = self.harness.build_fastq_source(
                    "f8ard%d-%d" % (case_index, i), reads)
                initialize_leaf_provenance(leaf, source_id="r%d" % i,
                                           source_name="r%d" % i)
                leaves.append(leaf)
                standalone["r%d" % i] = f1.load_standalone(leaf)
            output = os.path.join(self.work, "f8ard%d" % case_index)
            merge_many_balanced(leaves, output,
                                merge_two_func=f3.holt_merge_two_local,
                                num_procs=1)
            merged = MultiSourceBWT.load(output, mmap=False)
            queries = set(["A", "C", "G", "T", "N", "AA", "AC", "NN"])
            for reads in reads_by_source.values():
                for read in reads:
                    for start in range(len(read)):
                        for end in range(start + 1, min(len(read),
                                                        start + 4) + 1):
                            queries.add(read[start:end])
            for query in queries:
                for direction in ("left", "right"):
                    result = (merged.extendLeft(query)
                              if direction == "left"
                              else merged.extendRight(query))
                    for rec in result["extensions"]:
                        expected = sum(
                            int(bwt.countOccurrencesOfSeq(rec["sequence"]))
                            for bwt in standalone.values())
                        comparisons += 1
                        if rec["count"] != expected:
                            mismatches.append({
                                "case": case_index, "query": query,
                                "direction": direction,
                                "sequence": rec["sequence"],
                                "got": rec["count"],
                                "expected": expected,
                                "reads_by_source": reads_by_source})
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 300)


if __name__ == "__main__":
    unittest.main()
