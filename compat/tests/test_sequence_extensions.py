"""Host-side regression tests for enhanced-modern2 Feature 8A: source-aware
left/right sequence extensions without a reverse FM-index
(``MUS.MultiSourceQuery.extend``).

These tests are read-only and run on any CPython 3 with NumPy; they do NOT
require the compiled MUSCython extensions (real-merge integration runs in
the pinned Python-2.7 suite and the Feature-8A validation driver).

Coverage:

- ten-source read-derived fixture: merged left/right extensions == direct
  exact searches of cP / Pc; per-source extension counts == standalone
  counts for all ten sources; subset/group/where extension counts == sums;
  source-local intervals exact;
- search-asymmetry instrumentation (left: 1 full + 5 incremental; right:
  5 full + 0 incremental);
- include_zero filtering; right '$' extension; left '$' rejected;
  validation errors; selection-mode exclusivity;
- randomized read-derived differentials (seeds 20260811/20260812/20260813);
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
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)

SEEDS = (20260811, 20260812, 20260813)

import test_multisource_query as f3  # noqa: E402


def extension_patterns():
    patterns = set(["A", "C", "G", "T", "N", "AC", "GT", "NA", "ACG",
                    "CGT", "ACGT", "TTA", "NNN"])
    for reads in f3.TEN_SOURCE_READS.values():
        for read in reads:
            for start in range(len(read)):
                for end in range(start + 1, min(len(read), start + 5) + 1):
                    patterns.add(read[start:end])
    return sorted(patterns)


class ExtensionHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f8a-host-ten-")
        cls.output, cls.manifest, cls.merged, cls.standalone, cls.leaves = (
            f3.build_fixture(cls.work, f3.TEN_SOURCE_READS))
        cls.index = MultiSourceQueryIndex(
            cls.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        cls.wrapped = MultiSourceBWT(cls.merged, cls.index)
        cls.metadata = cls.wrapped.source_metadata
        table = [src["id"] for src in cls.manifest["sources"]]
        cls.metadata.define_group("g1", table[:3])
        for i, sid in enumerate(table):
            cls.metadata.set_source_metadata(sid, cohort="case"
                                             if i < 5 else "control")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_left_extensions_equal_direct_searches(self):
        mismatches = []
        for pattern in extension_patterns():
            for rec in self.wrapped.extendLeft(pattern)["extensions"]:
                direct = self.merged.findIndicesOfStr(rec["sequence"])
                expected = direct[1] - direct[0]
                if rec["count"] != expected:
                    mismatches.append((pattern, rec["sequence"],
                                       rec["count"], expected))
        self.assertEqual(mismatches, [])

    def test_right_extensions_equal_direct_searches(self):
        mismatches = []
        for pattern in extension_patterns():
            for rec in self.wrapped.extendRight(pattern)["extensions"]:
                direct = self.merged.findIndicesOfStr(rec["sequence"])
                expected = direct[1] - direct[0]
                if rec["count"] != expected:
                    mismatches.append((pattern, rec["sequence"],
                                       rec["count"], expected))
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
                        low, high = self.standalone[sid].findIndicesOfStr(
                            rec["sequence"])
                        if rec["count"] != high - low:
                            mismatches.append(
                                (pattern, direction, sid, rec["sequence"],
                                 rec["count"], high - low))
        self.assertEqual(mismatches, [])

    def test_subset_group_where_match_sums(self):
        mismatches = []
        for pattern in ("AC", "CGT", "AAAA", "N", "GTAC"):
            for direction in ("left", "right"):
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
                            (pattern, direction, "subset",
                             rec["sequence"], rec["count"], expected))
                members = self.metadata.group_sources("g1")
                result = (self.wrapped.extendLeft(pattern, group="g1")
                          if direction == "left"
                          else self.wrapped.extendRight(pattern, group="g1"))
                for rec in result["extensions"]:
                    expected = sum(
                        (lambda iv: iv[1] - iv[0])(
                            self.standalone[sid].findIndicesOfStr(
                                rec["sequence"]))
                        for sid in members)
                    if rec["count"] != expected:
                        mismatches.append(
                            (pattern, direction, "g1", rec["sequence"],
                             rec["count"], expected))
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

    def test_source_intervals_and_asymmetry(self):
        for pattern in ("AC", "CGT"):
            result = self.wrapped.extendLeft(pattern, source="sample07",
                                             include_intervals=True)
            for rec in result["extensions"]:
                low, high = self.standalone["sample07"].findIndicesOfStr(
                    rec["sequence"])
                self.assertEqual(rec["source_interval"], (low, high))
        fresh = MultiSourceBWT(
            self.merged,
            MultiSourceQueryIndex(self.output, mmap=False,
                                  use_saved_rank=False))
        before = self.merged.search_calls
        left = fresh.extendLeft("ACGT", include_stats=True)
        self.assertEqual(left["stats"]["full_fm_searches"], 1)
        self.assertEqual(left["stats"]["incremental_extension_calls"], 5)
        self.assertEqual(self.merged.search_calls - before, 6)
        before = self.merged.search_calls
        right = fresh.extendRight("ACGT", include_stats=True)
        self.assertEqual(right["stats"]["full_fm_searches"], 5)
        self.assertEqual(right["stats"]["incremental_extension_calls"], 0)
        self.assertEqual(self.merged.search_calls - before, 5)

    def test_filtering_validation_and_dollar(self):
        for rec in self.wrapped.extendLeft("CGT",
                                           include_zero=False)["extensions"]:
            self.assertGreater(rec["count"], 0)
        result = self.wrapped.extendRight("AAAA", alphabet="A$")
        bases = [rec["base"] for rec in result["extensions"]]
        self.assertIn(b"A", bases)
        self.assertIn(b"$", bases)
        with self.assertRaises(ValueError):
            self.wrapped.extendLeft("ACGT", alphabet="A$")
        with self.assertRaises(ValueError):
            self.wrapped.extend("ACGT", direction="up")
        with self.assertRaises(ValueError):
            self.wrapped.extendLeft("ACGT", alphabet="X")
        with self.assertRaises(ValueError):
            self.wrapped.extendLeft("")
        with self.assertRaises(ValueError):
            self.wrapped.extendLeft("ACGT", source="sample00", group="g1")


class RandomExtensionHostTests(unittest.TestCase):
    def test_random_reads_extension_differential(self):
        mismatches = []
        comparisons = 0
        for seed in SEEDS:
            rng = random.Random(seed)
            for case in range(8):
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
                work = tempfile.mkdtemp(prefix="f8a-host-rand-")
                try:
                    output, manifest, merged, standalone, _ = (
                        f3.build_fixture(work, source_reads,
                                         name="m%d" % case))
                    wrapped = MultiSourceBWT(
                        merged,
                        MultiSourceQueryIndex(output, mmap=False))
                    patterns = set(["A", "C", "G", "T", "N", "AA", "AC",
                                    "NN"])
                    for reads in source_reads.values():
                        for read in reads:
                            for start in range(len(read)):
                                for end in range(start + 1,
                                                 min(len(read), start + 4)
                                                 + 1):
                                    patterns.add(read[start:end])
                    for pattern in patterns:
                        for direction in ("left", "right"):
                            result = (wrapped.extendLeft(pattern)
                                      if direction == "left"
                                      else wrapped.extendRight(pattern))
                            for rec in result["extensions"]:
                                expected = sum(
                                    (lambda iv: iv[1] - iv[0])(
                                        standalone[sid].findIndicesOfStr(
                                            rec["sequence"]))
                                    for sid in source_reads)
                                comparisons += 1
                                if rec["count"] != expected:
                                    mismatches.append(
                                        (seed, case, pattern, direction,
                                         rec["sequence"], source_reads))
                finally:
                    shutil.rmtree(work, ignore_errors=True)
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 2000)


class EvidenceRecordHostTests(unittest.TestCase):
    EVIDENCE = os.path.join(PACKAGE, "evidence",
                            "feature8a-extensions.json")
    EVIDENCE_GENERATOR = os.path.join(
        PACKAGE, "validate", "feature8a_extension_evidence.py")

    def test_evidence_record_consistent(self):
        evidence = json.load(open(self.EVIDENCE, encoding="utf-8"))
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "enhanced-modern2")
        self.assertEqual(
            evidence["final"]["milestone"],
            "enhanced-modern2-feature8a-extensions")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")

    def test_evidence_contract(self):
        report = json.load(open(self.EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["seed"], 20260811)
        ten = report["ten_source_fixture"]
        self.assertGreaterEqual(ten["patterns"], 100)
        self.assertGreaterEqual(ten["comparisons"], 1000)
        self.assertTrue(ten["asymmetry_probe"])
        self.assertTrue(ten["dollar_probe"])

    def test_evidence_generator_is_python2_and_driver_checks(self):
        text = open(self.EVIDENCE_GENERATOR, encoding="utf-8").read()
        self.assertIn("from __future__ import print_function", text)
        self.assertNotIn("f'{", text)
        self.assertIn("def run_evidence", text)
        driver = open(os.path.join(PACKAGE, "validate",
                                   "feature8a-extensions.sh"),
                      encoding="utf-8").read()
        self.assertIn("--evidence", driver)
        self.assertIn("run_evidence", driver)


if __name__ == "__main__":
    unittest.main()
