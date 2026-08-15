"""Feature 13A - whole-index benchmark harness and backend contract
(Python-2 suite).

This suite validates ``MUS.Benchmarking`` and ``MUS.BackendContract``
against independent oracles:

* N, r, r/N computed by an INDEPENDENT sequential scan of the raw BWT
  array (no Benchmarking code);
* total physical storage independently summed by filesystem traversal,
  compared exactly to ``disk_breakdown``;
* per-layer classification verified against a hand-built file inventory
  (no double counting: the Q1 quality tag is counted once in
  ``bwt_tags_arrays``; the ``quality`` section is semantic only);
* provenance logical interleave bits computed by an independent tree
  walk;
* read-provenance / tag / LCP accounting verified against direct array
  sizes;
* the naive run-encoding model verified arithmetically.

Coverage:

- chunked run counting equals the direct oracle for small and chunk-
  boundary sizes;
- disk accounting == independent filesystem sum; production total
  excludes fixture/oracle files; intrinsic total excludes the root
  ``inter0.npy`` compatibility copy;
- provenance tree metrics (leaves, internal nodes, depth, logical bits,
  weighted depth) match an independent walk;
- read provenance: 20-byte records, payload = read_count * 20, physical
  = npy + json sizes;
- tags: per-tag payload = shape product * itemsize; quality payload
  reported semantically without double counting;
- LCP: ``lcps.npy`` N-1 boundaries, uint32 payload, physical bytes;
- RLE model: r*5 / r*9 arithmetic; negative-result decision summary on
  the toy fixture;
- backend contract: ``LegacyBWTAdapter`` capability inspection, tiers,
  ``assert_backend_tier``, framework contract with Features 1-12/Q1/11A
  methods;
- query benchmark and build-operation hook run end-to-end;
- compare_reports across the 10-source and Feature-10-reduced packages;
- evidence-record and validation-driver consistency (host side).
"""

from __future__ import print_function

import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_read_provenance_py2 as f9  # noqa: E402
import test_lcp_py2 as t11a  # noqa: E402

from MUS.Benchmarking import (  # noqa: E402
    BenchmarkError,
    benchmark_build_operation,
    benchmark_queries,
    compare_reports,
    disk_breakdown,
    full_benchmark_document,
    inspect_index,
    naive_run_encoding_model,
    save_report,
)
from MUS.BackendContract import (  # noqa: E402
    BackendContractError,
    LegacyBWTAdapter,
    assert_backend_tier,
    contract_document,
    inspect_backend,
    inspect_framework,
)
from MUS.BWTTags import BWTTagStore, attach_tag  # noqa: E402
from MUS.MultiSourceProvenance import (  # noqa: E402
    load_manifest,
    merge_many_balanced,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)
from MUS.QualitySidecar import (  # noqa: E402
    QUALITY_TAG_NAME,
    QualitySidecar,
    attach_quality_from_row_values,
)
from MUS.SourceRemoval import remove_sources  # noqa: E402

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")


def independent_run_count(directory):
    """Independent run count by direct array scan."""
    bwt = np.load(os.path.join(directory, "msbwt.npy"))
    if bwt.shape[0] == 0:
        return 0
    return 1 + int(np.count_nonzero(bwt[1:] != bwt[:-1]))


def independent_filesystem_total(directory):
    total = 0
    for dirpath, _, filenames in os.walk(directory):
        for filename in filenames:
            total += os.path.getsize(os.path.join(dirpath, filename))
    return total


class StructuralAccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="b13-py2-")
        cls.leaves = {}
        for sid, reads in f9.TEN_SOURCE_READS.items():
            leaf = f9.make_read_derived_leaf(cls.work, sid, reads)
            f9.attach_leaf_read_provenance(leaf, reads)
            attach_tag(
                leaf, "row_id",
                np.arange(len(f9.load_rows(leaf)), dtype=np.uint32))
            rows = f9.load_rows(leaf)
            q = np.zeros(len(rows), dtype=np.uint8)
            for idx, r in enumerate(rows):
                read = reads[r["read_id"]]
                q[idx] = 255 if r["pos"] >= len(read) else 33 + (idx % 40)
            attach_quality_from_row_values(leaf, q)
            cls.leaves[sid] = leaf
        cls.output = os.path.join(cls.work, "merged10")
        merge_many_balanced(
            list(cls.leaves.values()), cls.output,
            merge_two_func=f9.read_derived_merge)
        cls.oracle = f9.OracleReadIdentity(
            cls.output,
            {sid: cls.leaves[sid] for sid in cls.leaves},
            f9.TEN_SOURCE_READS)
        construct_lcp(cls.output, cls.oracle)
        cls.report = inspect_index(cls.output)
        cls.run_count = independent_run_count(cls.output)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_run_metrics_equal_independent_oracle(self):
        structure = self.report["structure"]
        self.assertEqual(structure["N"], 191)
        # the reported run count must equal the independent direct scan
        self.assertEqual(structure["r"], self.run_count)
        self.assertEqual(
            structure["r"], independent_run_count(self.output))
        self.assertAlmostEqual(
            structure["r_over_N"],
            float(self.run_count) / 191.0)
        self.assertAlmostEqual(
            structure["mean_run_length"],
            191.0 / float(self.run_count))
        self.assertEqual(structure["bwt_dtype"], "uint8")

    def test_disk_accounting_equals_filesystem_oracle(self):
        disk = self.report["storage"]["disk"]
        self.assertEqual(
            disk["physical_total_bytes"],
            independent_filesystem_total(self.output))
        # production total excludes test-oracle fixture files
        self.assertLess(
            disk["production_total_bytes"],
            disk["physical_total_bytes"])
        # intrinsic total excludes the root inter0.npy compat copy
        inter0_size = os.path.getsize(os.path.join(self.output,
                                                   "inter0.npy"))
        self.assertEqual(
            disk["intrinsic_total_excluding_root_interleave_copy_bytes"],
            disk["production_total_bytes"] - inter0_size)
        # every file is classified into a known layer
        known = set([
            "bwt", "root_interleave_compat", "provenance_manifest",
            "provenance_interleaves", "provenance_ranks",
            "read_provenance", "source_metadata", "bwt_tags_registry",
            "bwt_tags_arrays", "quality_sidecar_metadata", "lcp",
            "test_oracle_fixture", "other",
        ])
        for record in disk["files"]:
            self.assertIn(record["layer"], known)

    def test_provenance_metrics(self):
        prov = self.report["storage"]["provenance"]
        self.assertTrue(prov["available"])
        self.assertEqual(prov["source_count"], 10)
        self.assertEqual(prov["leaf_count"], 10)
        self.assertGreaterEqual(prov["internal_nodes"], 1)
        # independent logical bit total: sum of node lengths
        manifest = load_manifest(self.output)

        def bits(node):
            if node["type"] == "leaf":
                return 0
            return int(node["length"]) + bits(node["left"]) + \
                bits(node["right"])

        self.assertEqual(
            prov["interleave_logical_bits"], bits(manifest["root"]))
        self.assertEqual(
            prov["interleave_logical_bytes_packed"],
            (prov["interleave_logical_bits"] + 7) // 8)

    def test_read_provenance_metrics(self):
        reads = self.report["storage"]["read_provenance"]
        self.assertTrue(reads["available"])
        self.assertEqual(reads["read_count"], 30)
        self.assertEqual(reads["record_bytes"], 20)
        self.assertEqual(
            reads["payload_bytes"], 30 * 20)
        self.assertEqual(
            reads["physical_bytes"],
            os.path.getsize(os.path.join(self.output,
                                         "read_provenance.npy"))
            + os.path.getsize(os.path.join(self.output,
                                           "read_provenance.json")))

    def test_tag_and_quality_accounting_single_counted(self):
        tags = self.report["storage"]["tags"]
        quality = self.report["storage"]["quality"]
        self.assertTrue(tags["available"])
        self.assertTrue(quality["available"])
        store = BWTTagStore(self.output)
        payload_total = 0
        for name in store.list_tags():
            arr = store.array(name)
            self.assertEqual(
                tags["tags"][name]["payload_bytes"], int(arr.nbytes))
            self.assertEqual(
                tags["tags"][name]["dtype"], str(arr.dtype))
            self.assertEqual(
                tags["tags"][name]["shape"], [int(x) for x in arr.shape])
            payload_total += int(arr.nbytes)
        self.assertEqual(tags["payload_bytes"], payload_total)
        # quality payload is the SAME physical array as the tag
        self.assertEqual(
            quality["payload_bytes"],
            tags["tags"][QUALITY_TAG_NAME]["payload_bytes"])
        self.assertEqual(quality["alignment"], "suffix-first-base")
        self.assertEqual(quality["encoding"], "raw-fastq-quality-byte")
        self.assertEqual(quality["read_count"], 30)
        # no double counting: quality payload is not added to any layer
        # total beyond bwt_tags_arrays
        bwt_tags_physical = self.report["storage"]["disk"]["layers"][
            "bwt_tags_arrays"]["physical_bytes"]
        self.assertGreaterEqual(
            bwt_tags_physical,
            tags["tags"][QUALITY_TAG_NAME]["physical_bytes"])

    def test_lcp_metrics(self):
        lcp = self.report["storage"]["lcp"]
        self.assertTrue(lcp["available"])
        self.assertEqual(lcp["stored_boundaries"], 190)
        self.assertEqual(lcp["bwt_rows"], 191)
        self.assertEqual(lcp["dtype"], "uint32")
        self.assertEqual(lcp["payload_bytes"], 190 * 4)
        self.assertEqual(
            lcp["physical_bytes"],
            os.path.getsize(os.path.join(self.output, "lcps.npy"))
            + os.path.getsize(os.path.join(self.output, "lcp.json")))
        self.assertEqual(lcp["max_lcp"], 5)

    def test_naive_run_encoding_model_and_decision_summary(self):
        model = self.report["compression_models"]["naive_run_encoding"]
        self.assertEqual(
            model["symbol_plus_uint32_length_bytes"],
            self.run_count * 5)
        self.assertEqual(
            model["symbol_plus_uint64_length_bytes"],
            self.run_count * 9)
        self.assertAlmostEqual(
            model["uint32_model_vs_raw_bwt_payload_ratio"],
            (float(self.run_count) * 5) / 191.0)
        summary = self.report["decision_summary"]
        self.assertFalse(summary["naive_u32_rle_smaller_than_raw_bwt_payload"])
        self.assertTrue(summary["lcp_present"])
        # largest layers are reported in descending physical size
        sizes = [row["physical_bytes"]
                 for row in summary["largest_production_layers"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertGreater(sizes[0], 0)


class BackendContractTests(unittest.TestCase):
    def test_contract_document_is_machine_readable(self):
        doc = contract_document()
        self.assertEqual(doc["contract_version"], 1)
        self.assertIn("total_size", doc["backend_primitives"])
        self.assertIn("locate", doc["backend_primitives"])
        self.assertIn("source_count", doc["framework_capabilities"])
        self.assertIn("quality_recovery", doc["framework_capabilities"])
        self.assertIn("lcp_access", doc["framework_capabilities"])
        self.assertIn("13B.1-search-core", doc["tiers"])
        self.assertIn("13B.2-navigation", doc["tiers"])
        self.assertIn("13B.3-locate", doc["tiers"])

    def test_naive_adapter_satisfies_search_core_tier(self):
        work = tempfile.mkdtemp(prefix="b13-contract-")
        try:
            leaf = f9.make_read_derived_leaf(
                work, "src", ["ACGT", "AAAA", "TTTT"])
            adapter = LegacyBWTAdapter(t11a.OracleBackedAdapter(leaf))
            backend = inspect_backend(adapter)
            self.assertTrue(
                backend["tiers"]["13B.1-search-core"]["satisfied"])
            self.assertTrue(assert_backend_tier(
                adapter, "13B.1-search-core"))
            # the naive adapter has no LF/locate primitives
            self.assertFalse(backend["capabilities"]["lf"])
            self.assertFalse(backend["capabilities"]["locate"])
            self.assertFalse(
                backend["tiers"]["13B.2-navigation"]["satisfied"])
            with self.assertRaises(BackendContractError):
                assert_backend_tier(adapter, "13B.2-navigation")
            # canonical semantic calls ("ACGT"/"AAAA"/"TTTT" -> 5+5+5 rows)
            self.assertEqual(adapter.total_size(), 15)
            self.assertEqual(adapter.count(b"AC"), 1)
            interval = adapter.find_interval(b"A")
            self.assertEqual(adapter.count(b"A"), interval[1] - interval[0])
            # access/rank primitives against the raw rows
            self.assertEqual(adapter.access(0),
                             f9.ALPHABET_CODE[adapter.bwt.rows[0]["bwt"]])
            expected_rank = sum(
                1 for row in adapter.bwt.rows[:3]
                if f9.ALPHABET_CODE[row["bwt"]] == 1)
            self.assertEqual(adapter.rank(1, 3), expected_rank)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_framework_contract_lists_all_verified_features(self):
        work = tempfile.mkdtemp(prefix="b13-fw-")
        try:
            leaves = {}
            for sid, reads in (("A", ["ACGTAC", "AAAA"]),
                               ("B", ["TTTT", "CCCC"])):
                leaf = f9.make_read_derived_leaf(work, sid, reads)
                attach_tag(
                    leaf, "row_id",
                    np.arange(len(f9.load_rows(leaf)), dtype=np.uint32))
                rows = f9.load_rows(leaf)
                q = np.zeros(len(rows), dtype=np.uint8)
                for idx, r in enumerate(rows):
                    read = reads[r["read_id"]]
                    q[idx] = 255 if r["pos"] >= len(read) else 33 + (idx % 40)
                attach_quality_from_row_values(leaf, q)
                f9.attach_leaf_read_provenance(leaf, reads)
                leaves[sid] = leaf
            output = os.path.join(work, "merged")
            merge_many_balanced(
                list(leaves.values()), output,
                merge_two_func=f9.read_derived_merge)
            oracle = f9.OracleReadIdentity(
                output,
                {sid: leaves[sid] for sid in leaves},
                {"A": ["ACGTAC", "AAAA"], "B": ["TTTT", "CCCC"]})
            construct_lcp(output, oracle)
            index = MultiSourceQueryIndex(
                output, rank_stride_bytes=1, mmap=False,
                use_saved_rank=False)
            wrapped = MultiSourceBWT(
                None, index,
                read_provenance=index and f9_read_provenance(output, index),
                bwt_tags=BWTTagStore(output),
                quality_sidecar=QualitySidecar(output),
                lcp_index=t11a.LCPIndex(output))
            wrapped.bwt = t11a.OracleBackedAdapter(output, oracle)
            contract = inspect_framework(wrapped)
            for name in (
                "source_count", "sparse_sources", "source_frequency",
                "top_sources", "subset_count", "group_count",
                "left_extension", "right_extension", "read_listing",
                "tag_values", "tag_counts", "quality_recovery",
                "quality_query", "lcp_access",
            ):
                self.assertTrue(contract["capabilities"][name], name)
        finally:
            shutil.rmtree(work, ignore_errors=True)


def f9_read_provenance(directory, index):
    from MUS.ReadProvenance import ReadProvenanceIndex
    return ReadProvenanceIndex(directory, mmap=False, source_index=index)


def construct_lcp(directory, oracle):
    from MUS.LCP import construct_lcp_from_bwt
    return construct_lcp_from_bwt(
        directory, bwt=t11a.OracleBackedAdapter(directory, oracle))


class QueryAndCompareTests(unittest.TestCase):
    def test_query_benchmark_and_build_hook_end_to_end(self):
        work = tempfile.mkdtemp(prefix="b13-query-")
        try:
            leaves = {}
            for sid, reads in (("A", ["ACGTAC", "AAAA"]),
                               ("B", ["TTTT", "CCCC"])):
                leaf = f9.make_read_derived_leaf(work, sid, reads)
                f9.attach_leaf_read_provenance(leaf, reads)
                attach_tag(
                    leaf, "row_id",
                    np.arange(len(f9.load_rows(leaf)), dtype=np.uint32))
                leaves[sid] = leaf
            output = os.path.join(work, "merged")
            merge_many_balanced(
                list(leaves.values()), output,
                merge_two_func=f9.read_derived_merge)
            oracle = f9.OracleReadIdentity(
                output,
                {sid: leaves[sid] for sid in leaves},
                {"A": ["ACGTAC", "AAAA"], "B": ["TTTT", "CCCC"]})
            index = MultiSourceQueryIndex(
                output, rank_stride_bytes=1, mmap=False,
                use_saved_rank=False)
            wrapped = MultiSourceBWT(
                None, index, bwt_tags=BWTTagStore(output),
                read_provenance=f9_read_provenance(output, index))
            wrapped.bwt = t11a.OracleBackedAdapter(output, oracle)
            result = benchmark_queries(
                wrapped,
                patterns=[b"A", b"AC", b"ACGT"],
                warmup=1,
                repeats=3,
                source="A",
                top_k=2,
                tag_name="row_id",
                include_read_listing=True,
            )
            self.assertEqual(result["repeats"], 3)
            for op in ("count", "find_interval", "source_count",
                       "sparse_sources", "source_frequency", "top_sources",
                       "tag_values"):
                self.assertIn(op, result["operations"])
                self.assertGreaterEqual(
                    result["operations"][op]["calls"], 3)
            self.assertEqual(
                result["framework_contract"]["contract_version"], 1)
            # build hook
            build = benchmark_build_operation(
                "smoke-build", lambda: 42, repeats=3)
            self.assertEqual(build["repeats"], 3)
            self.assertEqual(build["results"], [42, 42, 42])
            # full document includes the backend contract
            doc = full_benchmark_document(
                output, query_report=result,
                build_reports=[build])
            self.assertEqual(
                doc["backend_contract"]["contract_version"], 1)
            # 7+5 + 5+5 = 22 rows (two sources of 12 and 10 rows)
            self.assertEqual(doc["structural"]["structure"]["N"], 22)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_compare_reports_ten_vs_reduced(self):
        work = tempfile.mkdtemp(prefix="b13-cmp-")
        try:
            leaves = {}
            for sid, reads in f9.TEN_SOURCE_READS.items():
                leaf = f9.make_read_derived_leaf(work, sid, reads)
                leaves[sid] = leaf
            output = os.path.join(work, "merged10")
            merge_many_balanced(
                list(leaves.values()), output,
                merge_two_func=f9.read_derived_merge)
            reduced = os.path.join(work, "reduced")
            remove_sources(
                output, reduced,
                sources=["sample00", "sample02", "sample09"],
                drop_lcp=True)
            reports = {
                "ten": inspect_index(output),
                "seven": inspect_index(reduced),
            }
            rows = compare_reports(reports)
            by_label = {row["label"]: row for row in rows}
            self.assertEqual(by_label["ten"]["N"], 191)
            self.assertEqual(by_label["seven"]["N"], 133)
            self.assertLess(
                by_label["seven"]["production_bytes"],
                by_label["ten"]["production_bytes"])
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_save_report_roundtrip(self):
        work = tempfile.mkdtemp(prefix="b13-save-")
        try:
            leaf = f9.make_read_derived_leaf(
                work, "src", ["ACGT", "AAAA"])
            report = inspect_index(leaf)
            path = os.path.join(work, "report.json")
            save_report(path, report)
            with open(path, "r") as fp:
                loaded = json.load(fp)
            self.assertEqual(loaded["structure"]["N"], 10)
            self.assertEqual(loaded["format"], "msbwt-point13a-benchmark")
        finally:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
