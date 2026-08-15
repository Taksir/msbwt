"""Host-side regression tests for enhanced-modern2 Feature 13A: whole-
index benchmark harness and backend contract (``MUS.Benchmarking`` /
``MUS.BackendContract``).

These tests are read-only and run on any CPython 3 with NumPy; they do NOT
require the compiled MUSCython extensions (real-merge integration runs in
the pinned Python-2.7 suite and the Feature-13A validation driver).

Coverage:

- run metrics (N, r, r/N) equal an independent direct scan;
- disk accounting equals an independent filesystem traversal sum;
  production totals exclude test-oracle fixture files; intrinsic totals
  exclude the root ``inter0.npy`` compatibility copy; every file is
  classified into a known layer;
- provenance tree metrics match an independent walk;
- read-provenance / tag / quality / LCP accounting verified against
  direct array sizes, with the Q1 quality payload single-counted (never
  added to totals twice);
- naive run-encoding model arithmetic and the decision summary;
- backend contract: capabilities, tiers, ``assert_backend_tier``,
  framework contract covering Features 1-12/Q1/11A;
- query benchmark, build-operation hook, full benchmark document,
  save/load round trip, ten-vs-reduced comparison;
- evidence-record and validation-driver consistency.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

PACKAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "..", "packages", "msbwt-modern2")
sys.path.insert(0, PACKAGE)

from MUS.Benchmarking import (  # noqa: E402
    benchmark_build_operation,
    benchmark_queries,
    compare_reports,
    full_benchmark_document,
    inspect_index,
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

import test_multisource_query as f3  # noqa: E402
import test_read_provenance as f9  # noqa: E402
import test_lcp as t11a  # noqa: E402

EVIDENCE = os.path.join(PACKAGE, "evidence", "feature13a-benchmark.json")
EVIDENCE_GENERATOR = os.path.join(
    PACKAGE, "validate", "feature13a_benchmark_evidence.py")
VALIDATION_DRIVER = os.path.join(
    PACKAGE, "validate", "feature13a-benchmark.sh")


def independent_run_count(directory):
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


def walk_row(merged_dir, manifest, row_index):
    node = manifest["root"]
    local_index = int(row_index)
    while node["type"] == "merge":
        packed = np.load(os.path.join(
            merged_dir, str(node["interleave"])), mmap_mode="r")
        needed = (node["length"] + 7) // 8
        used = np.asarray(packed[:needed], dtype=np.uint8)
        shifts = np.arange(8, dtype=np.uint8)
        bits = ((used[:, None] >> shifts[None, :]) & np.uint8(1))
        bits = bits.reshape(-1)[:node["length"]]
        bit = int(bits[local_index])
        if bit == 0:
            local_index = int(np.count_nonzero(bits[:local_index] == 0))
            node = node["left"]
        else:
            local_index = int(np.count_nonzero(bits[:local_index] == 1))
            node = node["right"]
    return str(node["source_id"]), local_index


def construct_lcp(directory, oracle):
    from MUS.LCP import construct_lcp_from_bwt
    return construct_lcp_from_bwt(
        directory, bwt=t11a.OracleBackedAdapter(directory, oracle))


class StructuralAccountingHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="b13-host-")
        cls.leaves = {}
        for sid, reads in f3.TEN_SOURCE_READS.items():
            leaf = f3.make_read_derived_leaf(cls.work, sid, reads)
            f9.attach_leaf_read_provenance(leaf, reads)
            attach_tag(
                leaf, "row_id",
                np.arange(len(f3.load_rows(leaf)), dtype=np.uint32))
            rows = f3.load_rows(leaf)
            q = np.zeros(len(rows), dtype=np.uint8)
            for idx, r in enumerate(rows):
                read = reads[r["read_id"]]
                q[idx] = 255 if r["pos"] >= len(read) else 33 + (idx % 40)
            attach_quality_from_row_values(leaf, q)
            cls.leaves[sid] = leaf
        cls.output = os.path.join(cls.work, "merged10")
        merge_many_balanced(
            list(cls.leaves.values()), cls.output,
            merge_two_func=f3.read_derived_merge)
        cls.oracle = f9.OracleReadIdentity(
            cls.output,
            {sid: cls.leaves[sid] for sid in cls.leaves},
            f3.TEN_SOURCE_READS)
        construct_lcp(cls.output, cls.oracle)
        cls.report = inspect_index(cls.output)
        cls.run_count = independent_run_count(cls.output)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_run_and_disk_oracles(self):
        structure = self.report["structure"]
        self.assertEqual(structure["N"], 191)
        self.assertEqual(structure["r"], self.run_count)
        self.assertAlmostEqual(
            structure["r_over_N"],
            float(self.run_count) / 191.0)
        disk = self.report["storage"]["disk"]
        self.assertEqual(
            disk["physical_total_bytes"],
            independent_filesystem_total(self.output))
        self.assertLess(
            disk["production_total_bytes"],
            disk["physical_total_bytes"])
        inter0_size = os.path.getsize(os.path.join(self.output,
                                                   "inter0.npy"))
        self.assertEqual(
            disk["intrinsic_total_excluding_root_interleave_copy_bytes"],
            disk["production_total_bytes"] - inter0_size)

    def test_layer_classification_and_provenance_bits(self):
        known = set([
            "bwt", "root_interleave_compat", "provenance_manifest",
            "provenance_interleaves", "provenance_ranks",
            "read_provenance", "source_metadata", "bwt_tags_registry",
            "bwt_tags_arrays", "quality_sidecar_metadata", "lcp",
            "test_oracle_fixture", "other",
        ])
        disk = self.report["storage"]["disk"]
        for record in disk["files"]:
            self.assertIn(record["layer"], known)
        prov = self.report["storage"]["provenance"]
        self.assertTrue(prov["available"])
        manifest = load_manifest(self.output)

        def bits(node):
            if node["type"] == "leaf":
                return 0
            return int(node["length"]) + bits(node["left"]) + \
                bits(node["right"])

        self.assertEqual(
            prov["interleave_logical_bits"], bits(manifest["root"]))

    def test_read_tag_quality_lcp_accounting(self):
        reads = self.report["storage"]["read_provenance"]
        self.assertTrue(reads["available"])
        self.assertEqual(reads["read_count"], 30)
        self.assertEqual(reads["payload_bytes"], 600)
        tags = self.report["storage"]["tags"]
        quality = self.report["storage"]["quality"]
        self.assertTrue(tags["available"] and quality["available"])
        self.assertEqual(
            quality["payload_bytes"],
            tags["tags"][QUALITY_TAG_NAME]["payload_bytes"])
        self.assertEqual(quality["read_count"], 30)
        lcp = self.report["storage"]["lcp"]
        self.assertTrue(lcp["available"])
        self.assertEqual(lcp["stored_boundaries"], 190)
        self.assertEqual(lcp["payload_bytes"], 190 * 4)
        self.assertEqual(lcp["max_lcp"], 5)

    def test_rle_model_and_decision_summary(self):
        model = self.report["compression_models"]["naive_run_encoding"]
        self.assertEqual(
            model["symbol_plus_uint32_length_bytes"],
            self.run_count * 5)
        self.assertEqual(
            model["symbol_plus_uint64_length_bytes"],
            self.run_count * 9)
        self.assertFalse(
            self.report["decision_summary"][
                "naive_u32_rle_smaller_than_raw_bwt_payload"])
        self.assertTrue(self.report["decision_summary"]["lcp_present"])
        sizes = [row["physical_bytes"]
                 for row in self.report["decision_summary"][
                     "largest_production_layers"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True))


class BackendContractHostTests(unittest.TestCase):
    def test_contract_document_and_tiers(self):
        doc = contract_document()
        self.assertEqual(doc["contract_version"], 1)
        for name in ("total_size", "find_interval", "count",
                     "backward_extend", "access", "rank", "lf",
                     "sequence_dollar_id", "recover_string", "locate"):
            self.assertIn(name, doc["backend_primitives"])
        for name in ("source_count", "sparse_sources",
                     "source_frequency", "top_sources", "subset_count",
                     "group_count", "left_extension", "right_extension",
                     "read_listing", "tag_values", "tag_counts",
                     "quality_recovery", "quality_query", "lcp_access"):
            self.assertIn(name, doc["framework_capabilities"])
        self.assertIn("13B.1-search-core", doc["tiers"])
        self.assertIn("13B.2-navigation", doc["tiers"])
        self.assertIn("13B.3-locate", doc["tiers"])

    def test_adapter_inspection(self):
        work = tempfile.mkdtemp(prefix="b13-host-contract-")
        try:
            leaf = f3.make_read_derived_leaf(
                work, "src", ["ACGT", "AAAA", "TTTT"])
            adapter = LegacyBWTAdapter(t11a.OracleBackedAdapter(leaf))
            backend = inspect_backend(adapter)
            self.assertTrue(
                backend["tiers"]["13B.1-search-core"]["satisfied"])
            self.assertTrue(
                assert_backend_tier(adapter, "13B.1-search-core"))
            self.assertFalse(backend["capabilities"]["locate"])
            self.assertFalse(
                backend["tiers"]["13B.3-locate"]["satisfied"])
            with self.assertRaises(BackendContractError):
                assert_backend_tier(adapter, "13B.3-locate")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_framework_contract_all_features(self):
        work = tempfile.mkdtemp(prefix="b13-host-fw-")
        try:
            leaves = {}
            for sid, reads in (("A", ["ACGTAC", "AAAA"]),
                               ("B", ["TTTT", "CCCC"])):
                leaf = f3.make_read_derived_leaf(work, sid, reads)
                f9.attach_leaf_read_provenance(leaf, reads)
                attach_tag(
                    leaf, "row_id",
                    np.arange(len(f3.load_rows(leaf)), dtype=np.uint32))
                rows = f3.load_rows(leaf)
                q = np.zeros(len(rows), dtype=np.uint8)
                for idx, r in enumerate(rows):
                    read = reads[r["read_id"]]
                    q[idx] = 255 if r["pos"] >= len(read) else 33 + (idx % 40)
                attach_quality_from_row_values(leaf, q)
                leaves[sid] = leaf
            output = os.path.join(work, "merged")
            merge_many_balanced(
                list(leaves.values()), output,
                merge_two_func=f3.read_derived_merge)
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
                read_provenance=f9.ReadProvenanceIndex(
                    output, mmap=False, source_index=index),
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


class QueryAndCompareHostTests(unittest.TestCase):
    def test_query_benchmark_and_full_document(self):
        work = tempfile.mkdtemp(prefix="b13-host-query-")
        try:
            leaves = {}
            for sid, reads in (("A", ["ACGTAC", "AAAA"]),
                               ("B", ["TTTT", "CCCC"])):
                leaf = f3.make_read_derived_leaf(work, sid, reads)
                f9.attach_leaf_read_provenance(leaf, reads)
                attach_tag(
                    leaf, "row_id",
                    np.arange(len(f3.load_rows(leaf)), dtype=np.uint32))
                leaves[sid] = leaf
            output = os.path.join(work, "merged")
            merge_many_balanced(
                list(leaves.values()), output,
                merge_two_func=f3.read_derived_merge)
            oracle = f9.OracleReadIdentity(
                output,
                {sid: leaves[sid] for sid in leaves},
                {"A": ["ACGTAC", "AAAA"], "B": ["TTTT", "CCCC"]})
            index = MultiSourceQueryIndex(
                output, rank_stride_bytes=1, mmap=False,
                use_saved_rank=False)
            wrapped = MultiSourceBWT(
                None, index, bwt_tags=BWTTagStore(output),
                read_provenance=f9.ReadProvenanceIndex(
                    output, mmap=False, source_index=index))
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
            for op in ("count", "find_interval", "source_count",
                       "sparse_sources", "source_frequency", "top_sources",
                       "tag_values", "read_listing"):
                self.assertIn(op, result["operations"])
                self.assertGreaterEqual(
                    result["operations"][op]["calls"], 3)
            build = benchmark_build_operation(
                "smoke", lambda: 1, repeats=2)
            doc = full_benchmark_document(
                output, query_report=result, build_reports=[build])
            self.assertEqual(
                doc["backend_contract"]["contract_version"], 1)
            self.assertEqual(doc["structural"]["structure"]["N"], 22)
            # save/load round trip
            path = os.path.join(work, "doc.json")
            save_report(path, doc)
            with open(path, "r") as fp:
                loaded = json.load(fp)
            self.assertEqual(loaded["format"],
                             "msbwt-point13a-benchmark")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_compare_reports_ten_vs_reduced(self):
        work = tempfile.mkdtemp(prefix="b13-host-cmp-")
        try:
            leaves = {}
            for sid, reads in f3.TEN_SOURCE_READS.items():
                leaf = f3.make_read_derived_leaf(work, sid, reads)
                leaves[sid] = leaf
            output = os.path.join(work, "merged10")
            merge_many_balanced(
                list(leaves.values()), output,
                merge_two_func=f3.read_derived_merge)
            reduced = os.path.join(work, "reduced")
            remove_sources(
                output, reduced,
                sources=["sample00", "sample02", "sample09"],
                drop_lcp=True)
            rows = compare_reports({
                "ten": inspect_index(output),
                "seven": inspect_index(reduced),
            })
            by_label = {row["label"]: row for row in rows}
            self.assertEqual(by_label["ten"]["N"], 191)
            self.assertEqual(by_label["seven"]["N"], 133)
            self.assertLess(
                by_label["seven"]["production_bytes"],
                by_label["ten"]["production_bytes"])
        finally:
            shutil.rmtree(work, ignore_errors=True)


class EvidenceConsistencyTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = json.load(open(EVIDENCE, encoding="utf-8"))
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "enhanced-modern2")
        self.assertEqual(
            evidence["final"]["milestone"],
            "enhanced-modern2-feature13a-benchmark")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")

    def test_evidence_contract(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["seed"], 20260811)
        structural = report["structural"]
        self.assertEqual(structural["N"], 191)
        self.assertEqual(structural["filesystem_oracle_exact"], True)
        self.assertEqual(structural["run_oracle_exact"], True)
        self.assertEqual(structural["quality_single_counted"], True)
        self.assertEqual(structural["lcp_boundaries"], 190)
        reduced = report["reduced"]
        self.assertEqual(reduced["N"], 133)
        self.assertEqual(reduced["filesystem_oracle_exact"], True)
        contract = report["backend_contract"]
        self.assertEqual(contract["contract_version"], 1)
        self.assertTrue(contract["search_core_satisfied"])
        self.assertTrue(contract["framework_all_features"])
        query = report["query_benchmark"]
        self.assertGreaterEqual(query["operations"], 6)
        self.assertEqual(query["repeats"], 3)
        self.assertEqual(
            report["structural"]["naive_u32_rle_smaller"],
            False)

    def test_evidence_generator_is_python2_and_driver_checks(self):
        with open(EVIDENCE_GENERATOR, "rb") as fp:
            text = fp.read().decode("utf-8")
        self.assertIn("Python 2.7 only", text)
        self.assertIn("def run_evidence", text)
        with open(VALIDATION_DRIVER, "rb") as fp:
            driver = fp.read().decode("utf-8")
        self.assertIn("--evidence", driver)
        self.assertIn("run_evidence", driver)
        self.assertIn("feature13a-benchmark", driver)


if __name__ == "__main__":
    unittest.main()
