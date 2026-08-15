#!/usr/bin/env python2
"""msbwt-modern2 Feature 13A evidence generator: whole-index benchmark
harness and backend contract.

Runs inside the pinned Python-2.7 environment.  Exercises:

- 10-source fully-layered package (provenance + read provenance + tags +
  Q1 quality + Feature-11A LCP):
  - run metrics (N, r, r/N) equal an INDEPENDENT direct scan;
  - disk accounting equals an INDEPENDENT filesystem traversal sum;
    production totals exclude test-oracle files; intrinsic totals
    exclude the root inter0.npy compatibility copy;
  - provenance logical bits match an independent tree walk;
  - read-provenance / tag / quality / LCP accounting verified against
    direct array sizes; Q1 quality payload SINGLE-COUNTED (semantic
    section only, never added to totals twice);
  - naive run-encoding model arithmetic; decision summary;
- Feature-10 reduced package (133 rows) benchmarked the same way;
- backend contract: capabilities, tiers (search-core satisfied by the
  legacy adapter), framework contract covering Features 1-12/Q1/11A;
- query benchmark (count/interval/source/sparse/frequency/top-k/tag/
  read listing) and build-operation hook;
- comparison table across the two packages.

Any mismatch raises AssertionError; the driver records JSON only after
every gate passes.  Python 2.7 only.
"""

from __future__ import print_function

import json
import os
import shutil
import sys
import tempfile

import numpy as np

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

PACKAGE = os.path.join(REPO, "packages", "msbwt-modern2")
sys.path.insert(0, PACKAGE)
sys.path.insert(0, os.path.join(PACKAGE, "tests"))
import test_read_provenance_py2 as f9  # noqa: E402
import test_lcp_py2 as t11a  # noqa: E402

from MUS.Benchmarking import (  # noqa: E402
    BenchmarkError,
    benchmark_build_operation,
    benchmark_queries,
    compare_reports,
    full_benchmark_document,
    inspect_index,
)
from MUS.BackendContract import (  # noqa: E402
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
from MUS.ReadProvenance import ReadProvenanceIndex  # noqa: E402
from MUS.SourceRemoval import remove_sources  # noqa: E402

SEED = 20260811


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


def construct_lcp(directory, oracle):
    from MUS.LCP import construct_lcp_from_bwt
    return construct_lcp_from_bwt(
        directory, bwt=t11a.OracleBackedAdapter(directory, oracle))


def run_evidence(out_path):
    report = {
        "seed": SEED,
        "mismatch_count": 0,
        "oracles": [
            "independent_bwt_run_scan",
            "independent_filesystem_traversal",
            "independent_provenance_tree_walk",
            "direct_array_size_accounting",
        ],
        "structural": {},
        "reduced": {},
        "backend_contract": {},
        "query_benchmark": {},
        "comparison": {},
        "decision_summary": {},
        "notes": [
            "the 10-source package is a deliberately tiny correctness "
            "fixture; naive RLE would EXPAND it, so no compressed-backend "
            "selection is implied by these numbers.",
            "Q1 quality physically resides as a Point-12 tag; its payload "
            "is reported semantically and NEVER added to storage totals "
            "twice.",
            "Feature 13A does not implement a new backend; the contract "
            "documents semantics any future backend must preserve.",
        ],
    }

    work = tempfile.mkdtemp(prefix="b13-evidence-")
    try:
        # ---------------- fully layered 10-source package ----------------
        leaves = {}
        for sid, reads in f9.TEN_SOURCE_READS.items():
            leaf = f9.make_read_derived_leaf(work, sid, reads)
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
            leaves[sid] = leaf
        output = os.path.join(work, "merged10")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f9.read_derived_merge)
        oracle = f9.OracleReadIdentity(
            output,
            {sid: leaves[sid] for sid in leaves},
            f9.TEN_SOURCE_READS)
        construct_lcp(output, oracle)

        structural = report["structural"]
        inspection = inspect_index(output)
        s = inspection["structure"]
        structural["N"] = s["N"]
        structural["r"] = s["r"]
        structural["run_oracle_exact"] = (
            s["r"] == independent_run_count(output))
        assert structural["run_oracle_exact"]
        disk = inspection["storage"]["disk"]
        structural["filesystem_oracle_exact"] = (
            disk["physical_total_bytes"]
            == independent_filesystem_total(output))
        assert structural["filesystem_oracle_exact"]
        assert disk["production_total_bytes"] < \
            disk["physical_total_bytes"]
        inter0_size = os.path.getsize(os.path.join(output, "inter0.npy"))
        assert disk[
            "intrinsic_total_excluding_root_interleave_copy_bytes"] == \
            disk["production_total_bytes"] - inter0_size

        prov = inspection["storage"]["provenance"]
        manifest = load_manifest(output)

        def bits(node):
            if node["type"] == "leaf":
                return 0
            return int(node["length"]) + bits(node["left"]) + \
                bits(node["right"])

        structural["provenance_bits_oracle_exact"] = (
            prov["interleave_logical_bits"] == bits(manifest["root"]))
        assert structural["provenance_bits_oracle_exact"]

        reads = inspection["storage"]["read_provenance"]
        assert reads["available"]
        assert reads["read_count"] == 30
        assert reads["payload_bytes"] == 600

        tags = inspection["storage"]["tags"]
        quality = inspection["storage"]["quality"]
        assert tags["available"] and quality["available"]
        assert quality["payload_bytes"] == \
            tags["tags"][QUALITY_TAG_NAME]["payload_bytes"]
        structural["quality_single_counted"] = True
        assert quality["read_count"] == 30

        lcp = inspection["storage"]["lcp"]
        assert lcp["available"]
        assert lcp["stored_boundaries"] == 190
        assert lcp["payload_bytes"] == 190 * 4
        structural["lcp_boundaries"] = lcp["stored_boundaries"]
        structural["lcp_payload_bytes"] = lcp["payload_bytes"]

        model = inspection["compression_models"]["naive_run_encoding"]
        assert model["symbol_plus_uint32_length_bytes"] == s["r"] * 5
        assert model["symbol_plus_uint64_length_bytes"] == s["r"] * 9
        summary = inspection["decision_summary"]
        structural["naive_u32_rle_smaller"] = bool(
            summary["naive_u32_rle_smaller_than_raw_bwt_payload"])
        assert structural["naive_u32_rle_smaller"] is False
        assert summary["lcp_present"]

        # ---------------- Feature-10 reduced package ---------------------
        reduced = os.path.join(work, "reduced")
        remove_sources(
            output, reduced,
            sources=["sample00", "sample02", "sample09"],
            drop_lcp=True)
        reduced_inspection = inspect_index(reduced)
        reduced_report = report["reduced"]
        reduced_report["N"] = reduced_inspection["structure"]["N"]
        reduced_report["filesystem_oracle_exact"] = (
            reduced_inspection["storage"]["disk"][
                "physical_total_bytes"]
            == independent_filesystem_total(reduced))
        assert reduced_report["filesystem_oracle_exact"]
        assert reduced_report["N"] == 133
        reduced_report["run_oracle_exact"] = (
            reduced_inspection["structure"]["r"]
            == independent_run_count(reduced))
        assert reduced_report["run_oracle_exact"]
        assert reduced_inspection["storage"]["lcp"]["available"] is False
        assert reduced_inspection["storage"]["quality"]["available"]
        assert reduced_inspection["storage"]["read_provenance"][
            "read_count"] == 21

        # ---------------- backend contract -------------------------------
        contract = report["backend_contract"]
        doc = contract_document()
        contract["contract_version"] = doc["contract_version"]
        adapter = LegacyBWTAdapter(t11a.OracleBackedAdapter(output, oracle))
        backend = inspect_backend(adapter)
        contract["search_core_satisfied"] = bool(
            backend["tiers"]["13B.1-search-core"]["satisfied"])
        assert contract["search_core_satisfied"]
        assert assert_backend_tier(adapter, "13B.1-search-core")
        contract["navigation_tier_missing_lf"] = not bool(
            backend["capabilities"]["lf"])
        contract["locate_absent"] = not bool(
            backend["capabilities"]["locate"])

        index = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        wrapped = MultiSourceBWT(
            None, index,
            read_provenance=ReadProvenanceIndex(
                output, mmap=False, source_index=index),
            bwt_tags=BWTTagStore(output),
            quality_sidecar=QualitySidecar(output),
            lcp_index=t11a.LCPIndex(output))
        wrapped.bwt = t11a.OracleBackedAdapter(output, oracle)
        fw = inspect_framework(wrapped)
        contract["framework_all_features"] = all(
            fw["capabilities"].values())
        assert contract["framework_all_features"]

        # ---------------- query benchmark --------------------------------
        query = report["query_benchmark"]
        qresult = benchmark_queries(
            wrapped,
            patterns=[b"A", b"AC", b"CGT", b"AAAA", b"N", b"AAGGTT"],
            warmup=1,
            repeats=3,
            source="sample09",
            top_k=3,
            tag_name="row_id",
            include_read_listing=True,
        )
        query["repeats"] = qresult["repeats"]
        query["operations"] = len(qresult["operations"])
        assert qresult["repeats"] == 3
        assert query["operations"] >= 8
        for op in ("count", "find_interval", "source_count",
                   "sparse_sources", "source_frequency", "top_sources",
                   "tag_values", "read_listing"):
            assert op in qresult["operations"], op
        build = benchmark_build_operation(
            "lcp-construct-smoke", lambda: 1, repeats=2)
        assert build["repeats"] == 2

        doc_full = full_benchmark_document(
            output, query_report=qresult, build_reports=[build])
        assert doc_full["backend_contract"]["contract_version"] == 1

        # ---------------- comparison table -------------------------------
        rows = compare_reports({
            "ten": inspection,
            "seven": reduced_inspection,
        })
        by_label = {row["label"]: row for row in rows}
        report["comparison"] = {
            "rows": rows,
            "ten_N": by_label["ten"]["N"],
            "seven_N": by_label["seven"]["N"],
        }
        assert by_label["ten"]["N"] == 191
        assert by_label["seven"]["N"] == 133
        assert by_label["seven"]["production_bytes"] < \
            by_label["ten"]["production_bytes"]

        report["mismatch_count"] = 0
        assert report["mismatch_count"] == 0

        with open(out_path, "w") as fp:
            json.dump(report, fp, indent=2, sort_keys=True)
            fp.write("\n")
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("usage: feature13a_benchmark_evidence.py "
                         "OUTPUT.json\n")
        return 2
    report = run_evidence(sys.argv[1])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
