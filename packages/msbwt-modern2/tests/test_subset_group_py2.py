"""msbwt-modern2 enhanced Feature 7 tests: source subsets / metadata groups
/ predicates (``MUS.MultiSourceQuery`` + ``MUS.SourceMetadata``), runnable
inside the pinned Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO.

Coverage:

- metadata catalog: format/version validation, unknown source IDs in
  groups/metadata rejected, group membership canonicalized to provenance
  order, define/delete/list groups, per-source metadata set/get,
  select_where (AND semantics, list-valued membership), resolve_selection
  exclusivity, save/reload stability, corrupt file rejection;
- ten-source read-derived fixture:
  - countSubset/querySubset == sum of Feature-3 exact source counts for the
    selected sources, for arbitrary 3-source subsets over the full
    >=350-pattern set;
  - querySubset nonzero records == Feature-4 listing filtered to the
    selection; exact intervals; aggregate == sum;
  - named groups (case/control/even/odd), metadata predicates (AND),
    empty groups, all-source selection, complete-subtree shortcut
    (8-source group), duplicate source removal, unknown group/source
    rejection;
  - one merged FM search per subset/group/predicate query;
  - changing metadata never changes provenance or BWT bytes (byte-compare
    provenance.json and msbwt.npy before/after metadata edits);
- REAL modern2 integration: canonical two-source merge with a metadata
  file; randomized Level-3 differential subset (seed 20260811).

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
from MUS.SourceMetadata import (  # noqa: E402
    METADATA_FILENAME,
    SourceMetadataCatalog,
    SourceMetadataError,
)

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

SEED = f1.SEED


def sum_source_counts(standalone, pattern, selected):
    total = 0
    for sid in selected:
        low, high = standalone[sid].findIndicesOfStr(pattern)
        total += high - low
    return total


class MetadataCatalogPy2Tests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f7-py2-meta-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.source_records = [
            {"id": "s0", "name": "s0", "length": 3},
            {"id": "s1", "name": "s1", "length": 4},
            {"id": "s2", "name": "s2", "length": 5},
        ]

    def test_empty_catalog_and_group_lifecycle(self):
        catalog = SourceMetadataCatalog(self.source_records)
        self.assertEqual(catalog.list_groups(), [])
        self.assertEqual(catalog.resolve_selection(), ["s0", "s1", "s2"])
        members = catalog.define_group("case", ["s2", "s0", "s2"])
        self.assertEqual(members, ["s0", "s2"])  # dedup + provenance order
        self.assertEqual(catalog.group_sources("case"), ["s0", "s2"])
        with self.assertRaises(KeyError):
            catalog.group_sources("missing")
        catalog.delete_group("case")
        self.assertEqual(catalog.list_groups(), [])

    def test_unknown_source_rejected(self):
        catalog = SourceMetadataCatalog(self.source_records)
        with self.assertRaises(SourceMetadataError):
            catalog.define_group("bad", ["s0", "nope"])
        with self.assertRaises(SourceMetadataError):
            catalog.set_source_metadata("nope", cohort="case")
        with self.assertRaises(SourceMetadataError):
            catalog._normalize_document({
                "format": "msbwt-source-metadata",
                "version": 1,
                "sources": {"nope": {}},
                "groups": {},
            })

    def test_wrong_format_version_rejected(self):
        catalog = SourceMetadataCatalog(self.source_records)
        for bad in (
            {"format": "other", "version": 1, "sources": {}, "groups": {}},
            {"format": "msbwt-source-metadata", "version": 2,
             "sources": {}, "groups": {}},
            {"format": "msbwt-source-metadata", "version": 1,
             "sources": "x", "groups": {}},
            {"format": "msbwt-source-metadata", "version": 1,
             "sources": {}, "groups": {"g": "not-a-list"}},
        ):
            with self.assertRaises(SourceMetadataError):
                catalog._normalize_document(bad)

    def test_select_where_and_membership(self):
        catalog = SourceMetadataCatalog(self.source_records)
        catalog.set_source_metadata("s0", cohort="case", batch="B0")
        catalog.set_source_metadata("s1", cohort="case", batch="B1",
                                    tissue=["blood", "liver"])
        catalog.set_source_metadata("s2", cohort="control", batch="B1")
        self.assertEqual(catalog.select_where(cohort="case"),
                         ["s0", "s1"])
        self.assertEqual(catalog.select_where(cohort="case", batch="B1"),
                         ["s1"])
        self.assertEqual(catalog.select_where(batch="B1"),
                         ["s1", "s2"])
        self.assertEqual(catalog.select_where(tissue="liver"), ["s1"])
        self.assertEqual(catalog.select_where(tissue="blood"), ["s1"])
        # an expected iterable means "actual equals any one of these values"
        # (scalar actual only; a list actual is matched by scalar membership)
        self.assertEqual(catalog.select_where(batch=["B1", "B9"]),
                         ["s1", "s2"])
        self.assertEqual(catalog.select_where(tissue=["blood", "liver"]),
                         [])
        self.assertEqual(catalog.select_where(cohort="missing"), [])

    def test_resolve_selection_exclusivity(self):
        catalog = SourceMetadataCatalog(self.source_records)
        with self.assertRaises(SourceMetadataError):
            catalog.resolve_selection(sources=["s0"], group="g")
        with self.assertRaises(SourceMetadataError):
            catalog.resolve_selection(group="g", where={"cohort": "case"})
        self.assertEqual(catalog.resolve_selection(sources=["s1", "s1",
                                                            "s0"]),
                         ["s0", "s1"])

    def test_save_reload_and_corruption(self):
        catalog = SourceMetadataCatalog(self.source_records)
        catalog.define_group("case", ["s0", "s1"])
        path = catalog.save(self.work)
        self.assertTrue(os.path.exists(path))
        # no tmp leftovers
        self.assertEqual(
            [n for n in os.listdir(self.work) if n.endswith(".tmp")], [])
        reloaded = SourceMetadataCatalog.load(self.work,
                                              self.source_records)
        self.assertEqual(reloaded.group_sources("case"), ["s0", "s1"])

        # corrupt file fails loudly
        with open(os.path.join(self.work, METADATA_FILENAME), "wb") as fp:
            fp.write(b"{not json")
        with self.assertRaises(SourceMetadataError):
            SourceMetadataCatalog.load(self.work, self.source_records)

        # missing file loads an empty catalog (not an error)
        os.remove(os.path.join(self.work, METADATA_FILENAME))
        catalog2 = SourceMetadataCatalog.load(self.work,
                                              self.source_records)
        self.assertEqual(catalog2.list_groups(), [])

    def test_external_file(self):
        document = {
            "format": "msbwt-source-metadata",
            "version": 1,
            "sources": {"s1": {"cohort": "case"}},
            "groups": {"g": ["s1"]},
        }
        path = os.path.join(self.work, "external.json")
        with open(path, "wb") as fp:
            fp.write(json.dumps(document).encode("ascii"))
        catalog = SourceMetadataCatalog.from_file(path, self.source_records)
        self.assertEqual(catalog.group_sources("g"), ["s1"])
        with self.assertRaises(IOError):
            SourceMetadataCatalog.from_file(
                os.path.join(self.work, "missing.json"),
                self.source_records)


class SubsetGroupPy2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f7-py2-ten-")
        cls.output, cls.manifest, cls.merged, cls.standalone, cls.leaves = (
            f3.build_merged_fixture(cls.work, f3.TEN_SOURCE_READS))
        cls.index = MultiSourceQueryIndex(
            cls.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        cls.wrapped = MultiSourceBWT(cls.merged, cls.index)
        cls.metadata = cls.wrapped.source_metadata
        # deterministic groups over the ten sources
        table = [src["id"] for src in cls.manifest["sources"]]
        cls.metadata.define_group("even", [table[i] for i in
                                           range(0, 10, 2)])
        cls.metadata.define_group("odd", [table[i] for i in
                                          range(1, 10, 2)])
        cls.metadata.define_group("case", table[:3])
        cls.metadata.define_group("control", table[7:])
        for i, sid in enumerate(table):
            cls.metadata.set_source_metadata(sid, batch="B%d" % (i % 3),
                                             cohort="case" if i < 5
                                             else "control")
        cls.metadata.define_group("left8", table[:8])
        # a group aligned with the full left subtree of the balanced tree
        cls.table = table

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_count_subset_matches_sum_of_source_counts(self):
        patterns = f3.all_test_patterns()
        self.assertGreaterEqual(len(patterns), 350)
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
        patterns = f3.all_test_patterns()
        subset = ["sample00", "sample03", "sample09"]
        mismatches = []
        for pattern in patterns:
            sparse = f4.expected_sparse(self.standalone, self.manifest,
                                        pattern)
            expected = [(n, c) for n, c, _ in sparse if n in subset]
            result = self.wrapped.querySubset(pattern, sources=subset)
            got = [(r["source_id"], r["count"]) for r in result["sources"]]
            if got != expected:
                mismatches.append((pattern, got, expected))
            self.assertEqual(result["count"], sum(c for _, c in got))
            # aggregate == sum of per-source exact counts (Feature 3)
            agg = sum(
                self.wrapped.countOccurrencesForSource(pattern, sid)
                for sid in subset)
            self.assertEqual(result["count"], agg)
        self.assertEqual(mismatches, [])

    def test_query_subset_intervals(self):
        subset = ["sample00", "sample02"]
        for pattern in ("AC", "CGT", "N", "$"):
            result = self.wrapped.querySubset(pattern, sources=subset,
                                              include_intervals=True)
            for rec in result["sources"]:
                low, high = self.standalone[rec["source_id"]].findIndicesOfStr(
                    pattern)
                self.assertEqual(rec["source_interval"], (low, high))

    def test_groups_and_where(self):
        patterns = f3.all_test_patterns()
        group_names = ("even", "odd", "case", "control")
        mismatches = []
        comparisons = 0
        for pattern in patterns:
            for name in group_names:
                members = self.metadata.group_sources(name)
                expected = sum_source_counts(self.standalone, pattern,
                                             members)
                got = self.wrapped.countGroup(pattern, name)
                comparisons += 1
                if got != expected:
                    mismatches.append((pattern, name, got, expected))
                qgot = self.wrapped.queryGroup(pattern, name)
                self.assertEqual(qgot["count"], expected)
                comparisons += 1
            # predicates
            for where in ({"cohort": "case"}, {"cohort": "control"},
                          {"batch": "B0"}, {"batch": "B1", "cohort":
                                            "case"}):
                members = self.metadata.select_where(**where)
                expected = sum_source_counts(self.standalone, pattern,
                                             members)
                got = self.wrapped.countWhere(pattern, where)
                comparisons += 1
                if got != expected:
                    mismatches.append((pattern, where, got, expected))
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 2000)

    def test_empty_group_and_no_selection(self):
        self.metadata.define_group("empty", [])
        self.assertEqual(
            self.wrapped.countGroup("AC", "empty"), 0)
        result = self.wrapped.queryGroup("AC", "empty")
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["count"], 0)
        # no selector == all sources
        self.assertEqual(
            self.wrapped.countSubset("AC"),
            self.wrapped.bwt.countOccurrencesOfSeq("AC"))

    def test_complete_subtree_shortcut(self):
        """'left8' selects the full left subtree of the 10-source balanced
        tree: stats must report a subtree shortcut and exact counts."""
        left8 = self.metadata.group_sources("left8")
        interval = self.merged.findIndicesOfStr("A")
        _, stats = self.index.subset_count_interval(
            interval[0], interval[1], left8, include_stats=True)
        self.assertGreater(stats["subtree_shortcuts"], 0)
        self.assertEqual(
            self.wrapped.countSubset("A", sources=left8),
            sum_source_counts(self.standalone, "A", left8))

    def test_duplicate_sources_removed(self):
        self.assertEqual(
            self.wrapped.countSubset("AC", sources=["sample00",
                                                    "sample00",
                                                    "sample01"]),
            self.wrapped.countSubset("AC", sources=["sample00",
                                                    "sample01"]))

    def test_unknown_group_and_source_rejected(self):
        with self.assertRaises(KeyError):
            self.wrapped.countGroup("AC", "missing-group")
        with self.assertRaises(KeyError):
            self.wrapped.countSubset("AC", sources=["not-a-source"])

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

    def test_metadata_changes_do_not_touch_bwt_or_provenance(self):
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
        # reload picks up the new group
        reloaded = MultiSourceBWT.load(self.output, mmap=False)
        self.assertIn("newgroup", reloaded.source_metadata.list_groups())


class SubsetRealIntegrationPy2Tests(unittest.TestCase):
    """Level-3 tests: real merges with a real metadata file."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f7-py2-real-")
        cls.harness = f1.SourceHarness(cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_canonical_two_source_with_metadata_file(self):
        a_dir = self.harness.build_fixture_source("f7a", "uniform-a.fastq")
        b_dir = self.harness.build_fixture_source("f7b", "uniform-b.fastq")
        initialize_leaf_provenance(a_dir, source_id="in_a",
                                   source_name="in_a")
        initialize_leaf_provenance(b_dir, source_id="in_b",
                                   source_name="in_b")
        m_dir = os.path.join(self.work, "f7m")
        merge_two_with_provenance(a_dir, b_dir, m_dir,
                                  merge_two_func=f3.holt_merge_two_local,
                                  num_procs=1)

        document = {
            "format": "msbwt-source-metadata",
            "version": 1,
            "sources": {
                "in_a": {"cohort": "case", "batch": "B0"},
                "in_b": {"cohort": "control", "batch": "B1"},
            },
            "groups": {"all": ["in_a", "in_b"], "a_only": ["in_a"]},
        }
        meta_path = os.path.join(self.work, "labels.json")
        with open(meta_path, "wb") as fp:
            fp.write(json.dumps(document).encode("ascii"))

        a_bwt = f1.load_standalone(a_dir)
        b_bwt = f1.load_standalone(b_dir)
        merged = MultiSourceBWT.load(m_dir, mmap=False,
                                     source_metadata_path=meta_path)

        queries = f1.build_queries(f1.CANONICAL_READS_A,
                                   f1.CANONICAL_READS_B)
        queries.extend([b"$", b"A$", b"T$"])
        mismatches = []
        for query in queries:
            expected_a = int(a_bwt.countOccurrencesOfSeq(query))
            expected_b = int(b_bwt.countOccurrencesOfSeq(query))
            for name, expected in (
                ("a_only", expected_a),
                ("all", expected_a + expected_b),
            ):
                got = merged.countGroup(query, name)
                if got != expected:
                    mismatches.append((query, name, got, expected))
            got = merged.countWhere(query, {"cohort": "case"})
            if got != expected_a:
                mismatches.append((query, "where", got, expected_a))
            got = merged.countWhere(query, {"batch": "B1"})
            if got != expected_b:
                mismatches.append((query, "where-b1", got, expected_b))
            # in-dir metadata auto-load
            catalog = merged.source_metadata
            catalog.save(m_dir)
            reloaded = MultiSourceBWT.load(m_dir, mmap=False)
            if reloaded.countGroup(query, "a_only") != expected_a:
                mismatches.append((query, "reload", got, expected_a))
        self.assertEqual(mismatches, [])

    def test_randomized_real_subset_differential(self):
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
                    "f7rd%d-%d" % (case_index, i), reads)
                initialize_leaf_provenance(leaf, source_id="r%d" % i,
                                           source_name="r%d" % i)
                leaves.append(leaf)
                standalone["r%d" % i] = f1.load_standalone(leaf)
            output = os.path.join(self.work, "f7rd%d" % case_index)
            merge_many_balanced(leaves, output,
                                merge_two_func=f3.holt_merge_two_local,
                                num_procs=1)
            merged = MultiSourceBWT.load(output, mmap=False)
            catalog = merged.source_metadata
            catalog.define_group("g1", ["r0", "r1"])
            catalog.define_group("g2", ["r%d" % (source_count - 1)])
            for i in range(source_count):
                catalog.set_source_metadata("r%d" % i,
                                            batch="B%d" % (i % 2))

            queries = set(["A", "C", "G", "T", "N", "$", "AA", "AC", "NN",
                           "A$", "T$"])
            for reads in reads_by_source.values():
                for read in reads:
                    for start in range(len(read)):
                        for end in range(start + 1, len(read) + 1):
                            queries.add(read[start:end])
            for query in queries:
                for name in ("g1", "g2"):
                    members = catalog.group_sources(name)
                    expected = sum(
                        int(standalone[sid].countOccurrencesOfSeq(query))
                        for sid in members)
                    got = merged.countGroup(query, name)
                    comparisons += 1
                    if got != expected:
                        mismatches.append({
                            "case": case_index, "query": query,
                            "group": name, "got": got,
                            "expected": expected,
                            "reads_by_source": reads_by_source})
                for where in ({"batch": "B0"}, {"batch": "B1"}):
                    members = catalog.select_where(**where)
                    expected = sum(
                        int(standalone[sid].countOccurrencesOfSeq(query))
                        for sid in members)
                    got = merged.countWhere(query, where)
                    comparisons += 1
                    if got != expected:
                        mismatches.append({
                            "case": case_index, "query": query,
                            "where": where, "got": got,
                            "expected": expected,
                            "reads_by_source": reads_by_source})
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 400)


if __name__ == "__main__":
    unittest.main()
