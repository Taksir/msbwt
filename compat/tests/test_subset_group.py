"""Host-side regression tests for enhanced-modern2 Feature 7: source
subsets / metadata groups / predicates (``MUS.MultiSourceQuery`` +
``MUS.SourceMetadata``).

These tests are read-only and run on any CPython 3 with NumPy; they do NOT
require the compiled MUSCython extensions (real-merge integration runs in
the pinned Python-2.7 suite and the Feature-7 validation driver).

Coverage:

- metadata catalog lifecycle: format/version/schema validation, unknown
  source rejection, group canonicalization to provenance order,
  define/delete/list, set/get per-source metadata, select_where (AND,
  scalar membership for list values), resolve_selection exclusivity,
  atomic save/reload, corrupt-file rejection, external files;
- ten-source read-derived fixture: countSubset == sum of standalone exact
  counts for arbitrary subsets over >=350 patterns; querySubset records ==
  filtered Feature-4 listing; groups/predicates == independent selection +
  sum; complete-subtree shortcut stats; one merged FM search per query;
  metadata edits never change provenance.json/msbwt.npy bytes;
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
    merge_two_with_provenance,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)
from MUS.SourceMetadata import (  # noqa: E402
    METADATA_FILENAME,
    SourceMetadataCatalog,
    SourceMetadataError,
)

SEEDS = (20260811, 20260812, 20260813)

import test_multisource_query as f3  # noqa: E402
import test_sparse_source_listing as f4  # noqa: E402


def sum_source_counts(standalone, pattern, selected):
    total = 0
    for sid in selected:
        low, high = standalone[sid].findIndicesOfStr(pattern)
        total += high - low
    return total


class MetadataCatalogHostTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f7-host-meta-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.source_records = [
            {"id": "s0", "name": "s0", "length": 3},
            {"id": "s1", "name": "s1", "length": 4},
            {"id": "s2", "name": "s2", "length": 5},
        ]

    def test_group_lifecycle_and_canonicalization(self):
        catalog = SourceMetadataCatalog(self.source_records)
        self.assertEqual(catalog.resolve_selection(), ["s0", "s1", "s2"])
        self.assertEqual(catalog.define_group("g", ["s2", "s0", "s2"]),
                         ["s0", "s2"])
        with self.assertRaises(KeyError):
            catalog.group_sources("missing")
        catalog.delete_group("g")
        self.assertEqual(catalog.list_groups(), [])

    def test_validation_matrix(self):
        catalog = SourceMetadataCatalog(self.source_records)
        with self.assertRaises(SourceMetadataError):
            catalog.define_group("bad", ["s0", "nope"])
        for bad in (
            {"format": "other", "version": 1, "sources": {}, "groups": {}},
            {"format": "msbwt-source-metadata", "version": 2,
             "sources": {}, "groups": {}},
            {"format": "msbwt-source-metadata", "version": 1,
             "sources": {"nope": {}}, "groups": {}},
            {"format": "msbwt-source-metadata", "version": 1,
             "sources": {}, "groups": {"g": "not-a-list"}},
            "not-a-dict",
        ):
            with self.assertRaises(SourceMetadataError):
                catalog._normalize_document(bad)

    def test_select_where(self):
        catalog = SourceMetadataCatalog(self.source_records)
        catalog.set_source_metadata("s0", cohort="case", batch="B0")
        catalog.set_source_metadata("s1", cohort="case", batch="B1",
                                    tissue=["blood", "liver"])
        catalog.set_source_metadata("s2", cohort="control", batch="B1")
        self.assertEqual(catalog.select_where(cohort="case"), ["s0", "s1"])
        self.assertEqual(catalog.select_where(cohort="case", batch="B1"),
                         ["s1"])
        self.assertEqual(catalog.select_where(tissue="liver"), ["s1"])
        self.assertEqual(catalog.select_where(batch=["B1", "B9"]),
                         ["s1", "s2"])
        self.assertEqual(catalog.select_where(cohort="missing"), [])

    def test_resolve_selection_exclusivity(self):
        catalog = SourceMetadataCatalog(self.source_records)
        with self.assertRaises(SourceMetadataError):
            catalog.resolve_selection(sources=["s0"], group="g")
        with self.assertRaises(SourceMetadataError):
            catalog.resolve_selection(group="g", where={"cohort": "case"})
        self.assertEqual(
            catalog.resolve_selection(sources=["s1", "s1", "s0"]),
            ["s0", "s1"])

    def test_save_reload_and_corruption(self):
        catalog = SourceMetadataCatalog(self.source_records)
        catalog.define_group("case", ["s0", "s1"])
        catalog.save(self.work)
        self.assertEqual(
            [n for n in os.listdir(self.work) if n.endswith(".tmp")], [])
        reloaded = SourceMetadataCatalog.load(self.work,
                                              self.source_records)
        self.assertEqual(reloaded.group_sources("case"), ["s0", "s1"])
        with open(os.path.join(self.work, METADATA_FILENAME), "wb") as fp:
            fp.write(b"{not json")
        with self.assertRaises(SourceMetadataError):
            SourceMetadataCatalog.load(self.work, self.source_records)
        os.remove(os.path.join(self.work, METADATA_FILENAME))
        self.assertEqual(
            SourceMetadataCatalog.load(self.work,
                                       self.source_records).list_groups(),
            [])


class SubsetGroupHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f7-host-ten-")
        cls.output, cls.manifest, cls.merged, cls.standalone, cls.leaves = (
            f3.build_fixture(cls.work, f3.TEN_SOURCE_READS))
        cls.index = MultiSourceQueryIndex(
            cls.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        cls.wrapped = MultiSourceBWT(cls.merged, cls.index)
        cls.metadata = cls.wrapped.source_metadata
        table = [src["id"] for src in cls.manifest["sources"]]
        cls.table = table
        cls.metadata.define_group("even", [table[i] for i in
                                           range(0, 10, 2)])
        cls.metadata.define_group("odd", [table[i] for i in
                                          range(1, 10, 2)])
        cls.metadata.define_group("case", table[:3])
        cls.metadata.define_group("control", table[7:])
        cls.metadata.define_group("left8", table[:8])
        for i, sid in enumerate(table):
            cls.metadata.set_source_metadata(
                sid, batch="B%d" % (i % 3),
                cohort="case" if i < 5 else "control")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_count_subset_matches_sum_of_source_counts(self):
        patterns = f3.all_test_patterns()
        subsets = [
            ["sample00", "sample02", "sample09"],
            ["sample01", "sample08"],
            self.table[:5],
            self.table,
            ["sample05"],
            [],
        ]
        mismatches = []
        comparisons = 0
        for pattern in patterns:
            for subset in subsets:
                expected = sum_source_counts(self.standalone, pattern,
                                             subset)
                got = self.wrapped.countSubset(pattern, sources=subset)
                comparisons += 1
                if got != expected:
                    mismatches.append((pattern, subset, got, expected))
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 2000)

    def test_query_subset_records_match_filtered_listing(self):
        subset = ["sample00", "sample03", "sample09"]
        mismatches = []
        for pattern in f3.all_test_patterns():
            sparse = f4.expected_sparse(self.standalone, self.manifest,
                                        pattern)
            expected = [(n, c) for n, c, _ in sparse if n in subset]
            result = self.wrapped.querySubset(pattern, sources=subset)
            got = [(r["source_id"], r["count"]) for r in result["sources"]]
            if got != expected:
                mismatches.append((pattern, got, expected))
            self.assertEqual(result["count"], sum(c for _, c in got))
        self.assertEqual(mismatches, [])

    def test_groups_and_where(self):
        mismatches = []
        comparisons = 0
        for pattern in f3.all_test_patterns():
            for name in ("even", "odd", "case", "control"):
                members = self.metadata.group_sources(name)
                expected = sum_source_counts(self.standalone, pattern,
                                             members)
                got = self.wrapped.countGroup(pattern, name)
                comparisons += 1
                if got != expected:
                    mismatches.append((pattern, name, got, expected))
                self.assertEqual(self.wrapped.queryGroup(pattern,
                                                         name)["count"],
                                 expected)
                comparisons += 1
            for where in ({"cohort": "case"}, {"cohort": "control"},
                          {"batch": "B0"},
                          {"batch": "B1", "cohort": "case"}):
                members = self.metadata.select_where(**where)
                expected = sum_source_counts(self.standalone, pattern,
                                             members)
                got = self.wrapped.countWhere(pattern, where)
                comparisons += 1
                if got != expected:
                    mismatches.append((pattern, where, got, expected))
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 2000)

    def test_empty_group_no_selection_duplicates(self):
        self.metadata.define_group("empty", [])
        self.assertEqual(self.wrapped.countGroup("AC", "empty"), 0)
        self.assertEqual(self.wrapped.queryGroup("AC", "empty")["sources"],
                         [])
        self.assertEqual(
            self.wrapped.countSubset("AC"),
            self.wrapped.bwt.countOccurrencesOfSeq("AC"))
        self.assertEqual(
            self.wrapped.countSubset("AC", sources=["sample00", "sample00",
                                                    "sample01"]),
            self.wrapped.countSubset("AC", sources=["sample00",
                                                    "sample01"]))
        with self.assertRaises(KeyError):
            self.wrapped.countGroup("AC", "missing-group")
        with self.assertRaises(KeyError):
            self.wrapped.countSubset("AC", sources=["not-a-source"])

    def test_complete_subtree_shortcut(self):
        left8 = self.metadata.group_sources("left8")
        interval = self.merged.findIndicesOfStr("A")
        _, stats = self.index.subset_count_interval(
            interval[0], interval[1], left8, include_stats=True)
        self.assertGreater(stats["subtree_shortcuts"], 0)
        self.assertEqual(
            self.wrapped.countSubset("A", sources=left8),
            sum_source_counts(self.standalone, "A", left8))

    def test_one_merged_search_per_query(self):
        fresh = MultiSourceBWT(
            self.merged,
            MultiSourceQueryIndex(self.output, mmap=False,
                                  use_saved_rank=False),
            source_metadata=self.metadata)
        before = self.merged.search_calls
        fresh.countSubset("AC", sources=["sample00", "sample02"])
        fresh.querySubset("AC", group="even")
        fresh.countWhere("AC", {"cohort": "case"})
        fresh.queryGroup("AC", "odd")
        self.assertEqual(self.merged.search_calls, before + 4)

    def test_metadata_never_touches_bwt_or_provenance(self):
        prov_path = os.path.join(self.output, "provenance.json")
        bwt_path = os.path.join(self.output, "msbwt.npy")
        with open(prov_path, "rb") as fp:
            prov_before = fp.read()
        with open(bwt_path, "rb") as fp:
            bwt_before = fp.read()
        self.metadata.define_group("newgroup", ["sample00"])
        self.metadata.set_source_metadata("sample01", tissue="liver")
        self.metadata.save(self.output)
        with open(prov_path, "rb") as fp:
            prov_after = fp.read()
        with open(bwt_path, "rb") as fp:
            bwt_after = fp.read()
        self.assertEqual(prov_before, prov_after)
        self.assertEqual(bwt_before, bwt_after)


class RandomSubsetHostTests(unittest.TestCase):
    def test_random_reads_subset_differential(self):
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
                work = tempfile.mkdtemp(prefix="f7-host-rand-")
                try:
                    output, manifest, merged, standalone, _ = (
                        f3.build_fixture(work, source_reads,
                                         name="m%d" % case))
                    wrapped = MultiSourceBWT(
                        merged,
                        MultiSourceQueryIndex(output, mmap=False))
                    catalog = wrapped.source_metadata
                    table = [src["id"] for src in manifest["sources"]]
                    rng.shuffle(table)
                    half = table[: max(1, len(table) // 2)]
                    catalog.define_group("half", half)
                    for i, sid in enumerate(table):
                        catalog.set_source_metadata(
                            sid, batch="B%d" % (i % 2))
                    patterns = set(["A", "C", "G", "T", "N", "$", "AA",
                                    "AC", "NN", "A$", "T$"])
                    for reads in source_reads.values():
                        for read in reads:
                            for start in range(len(read)):
                                for end in range(start + 1, len(read) + 1):
                                    patterns.add(read[start:end])
                    for pattern in patterns:
                        for subset in (half, table):
                            expected = sum_source_counts(
                                standalone, pattern, subset)
                            comparisons += 1
                            if wrapped.countSubset(pattern,
                                                   sources=subset) != \
                                    expected:
                                mismatches.append(
                                    (seed, case, pattern, "subset",
                                     source_reads))
                        members = catalog.group_sources("half")
                        expected = sum_source_counts(standalone, pattern,
                                                     members)
                        comparisons += 1
                        if wrapped.countGroup(pattern, "half") != expected:
                            mismatches.append(
                                (seed, case, pattern, "group",
                                 source_reads))
                        members = catalog.select_where(batch="B0")
                        expected = sum_source_counts(standalone, pattern,
                                                     members)
                        comparisons += 1
                        if wrapped.countWhere(pattern,
                                              {"batch": "B0"}) != expected:
                            mismatches.append(
                                (seed, case, pattern, "where",
                                 source_reads))
                finally:
                    shutil.rmtree(work, ignore_errors=True)
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 3000)


class EvidenceRecordHostTests(unittest.TestCase):
    EVIDENCE = os.path.join(PACKAGE, "evidence",
                            "feature7-subset-groups.json")
    EVIDENCE_GENERATOR = os.path.join(
        PACKAGE, "validate", "feature7_subset_group_evidence.py")

    def test_evidence_record_consistent(self):
        evidence = json.load(open(self.EVIDENCE, encoding="utf-8"))
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "enhanced-modern2")
        self.assertEqual(
            evidence["final"]["milestone"],
            "enhanced-modern2-feature7-subset-groups")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")

    def test_evidence_contract(self):
        report = json.load(open(self.EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["seed"], 20260811)
        ten = report["ten_source_fixture"]
        self.assertGreaterEqual(ten["patterns"], 350)
        self.assertGreaterEqual(ten["subset_comparisons"], 2000)
        self.assertTrue(ten["one_search_probe"])
        self.assertTrue(ten["subtree_shortcut_probe"])
        self.assertTrue(ten["metadata_isolation_probe"])

    def test_evidence_generator_is_python2_and_driver_checks(self):
        text = open(self.EVIDENCE_GENERATOR, encoding="utf-8").read()
        self.assertIn("from __future__ import print_function", text)
        self.assertNotIn("f'{", text)
        self.assertIn("def run_evidence", text)
        driver = open(os.path.join(PACKAGE, "validate",
                                   "feature7-subset-groups.sh"),
                      encoding="utf-8").read()
        self.assertIn("--evidence", driver)
        self.assertIn("run_evidence", driver)


if __name__ == "__main__":
    unittest.main()
