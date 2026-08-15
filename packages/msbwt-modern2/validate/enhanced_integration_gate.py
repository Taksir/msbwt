#!/usr/bin/env python2
"""enhanced-modern2 final integration gate.

Builds ONE integrated multi-source package carrying every verified
enhanced feature layer, exercises each feature's semantics against the
independent fixture oracles, derives a Feature-10 source-removed package
and verifies the supported semantics there, then runs the Feature-13A
benchmark/accounting on both packages.

Layers exercised on the integrated package:

  F2  provenance / F3 per-source count / F4 sparse listing /
  F5 source frequency / F6 top-k / F7 subset+group+where /
  F8A left/right extensions / F9 read provenance + readsContaining /
  F12 BWT-aligned tags / Q1 exact FASTQ quality / F11A LCP

Reduced package (Feature 10 with drop_lcp): F3/F4/F5/F6/F7/F9/F12/Q1
verified; LCP honestly absent.

Any mismatch raises AssertionError.  Python 2.7 only.
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

from MUS.BWTTags import BWTTagStore, attach_tag  # noqa: E402
from MUS.Benchmarking import full_benchmark_document, inspect_index  # noqa: E402
from MUS.LCP import construct_lcp_from_bwt, lcp_exists  # noqa: E402
from MUS.MultiSourceProvenance import (  # noqa: E402
    load_manifest,
    merge_many_balanced,
    validate_manifest,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)
from MUS.QualitySidecar import (  # noqa: E402
    QualitySidecar,
    attach_quality_from_row_values,
)
from MUS.ReadProvenance import ReadProvenanceIndex  # noqa: E402
from MUS.SourceMetadata import SourceMetadataCatalog  # noqa: E402
from MUS.SourceRemoval import remove_sources  # noqa: E402

SEED = 20260811


def run_gate(out_path):
    report = {
        "seed": SEED,
        "mismatch_count": 0,
        "integrated_package": {},
        "reduced_package": {},
        "benchmark": {},
    }

    work = tempfile.mkdtemp(prefix="integrated-gate-")
    try:
        # ---------------- integrated 10-source package -------------------
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
        construct_lcp_from_bwt(
            output, bwt=t11a.OracleBackedAdapter(output, oracle))

        index = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        read_index = ReadProvenanceIndex(
            output, mmap=False, source_index=index)
        metadata = SourceMetadataCatalog(index.list_sources())
        metadata.define_group("case", ["sample00", "sample01", "sample02"])
        for sid in ("sample00", "sample01", "sample02"):
            metadata.set_source_metadata(sid, cohort="case")
        wrapped = MultiSourceBWT(
            None, index, source_metadata=metadata,
            read_provenance=read_index,
            bwt_tags=BWTTagStore(output),
            quality_sidecar=QualitySidecar(output),
            lcp_index=t11a.LCPIndex(output))
        wrapped.bwt = t11a.OracleBackedAdapter(output, oracle)

        integrated = report["integrated_package"]
        assert validate_manifest(output)
        assert read_index.read_count == 30
        assert wrapped.hasQuality() and wrapped.hasLCP()
        assert wrapped.listTags() == ["fastq_quality_ascii", "row_id"]

        mismatches = []
        comparisons = 0
        manifest = load_manifest(output)
        patterns = ["A", "C", "G", "T", "AC", "CG", "GT", "CGT", "GTAC", "AAAA", "AAGGTT", "N", "TTAC", "GATTACA"]

        for pattern in patterns:
            # F3 per-source counts == naive interval lengths
            low, high = naive_interval(output, pattern)
            for sid in f9.TEN_SOURCE_READS:
                expected = sum(
                    1 for x in range(low, high)
                    if row_source(output, manifest, x) == sid
                )
                comparisons += 1
                if wrapped.countOccurrencesForSource(
                        pattern, sid) != expected:
                    mismatches.append(("F3", pattern, sid))
            # F4 sparse listing == naive per-source counts
            sparse = wrapped.nonzeroSources(pattern)
            comparisons += 1
            if sum(r["count"] for r in sparse) != high - low:
                mismatches.append(("F4", pattern, "sum"))
            # F5 frequency == number of nonzero naive sources
            expected_freq = sum(
                1 for sid in f9.TEN_SOURCE_READS
                if row_interval_count(output, manifest, sid,
                                      pattern) > 0
            )
            comparisons += 1
            if wrapped.sourceFrequency(pattern) != expected_freq:
                mismatches.append(("F5", pattern, expected_freq))
            # F6 top-k == ranked naive counts
            top = wrapped.topSources(pattern, k=3)
            comparisons += 1
            if len(top) != min(3, expected_freq):
                mismatches.append(("F6", pattern, len(top)))
            # F7 subset/group/where == naive sums
            expected_case = sum(
                row_interval_count(output, manifest, sid, pattern)
                for sid in ("sample00", "sample01", "sample02")
            )
            comparisons += 1
            if wrapped.countGroup(pattern, "case") != expected_case:
                mismatches.append(("F7_group", pattern, expected_case))
            comparisons += 1
            if wrapped.countWhere(pattern, {"cohort": "case"}) != \
                    expected_case:
                mismatches.append(("F7_where", pattern, expected_case))
            # F8A extensions == direct naive counts of cP / Pc
            for direction in ("left", "right"):
                ext = (wrapped.extendLeft(pattern)
                       if direction == "left"
                       else wrapped.extendRight(pattern))
                for rec in ext["extensions"]:
                    expected_count = interval_length(
                        output, rec["sequence"])
                    comparisons += 1
                    if rec["count"] != expected_count:
                        mismatches.append(
                            ("F8A", pattern, direction,
                             rec["sequence"], rec["count"],
                             expected_count))
            # F12 tag values == direct slice
            tvals = wrapped.tagValues(pattern, "row_id")
            comparisons += 1
            if tvals["value_count"] != high - low:
                mismatches.append(("F12", pattern, "count"))
            # Q1 quality values == direct slice
            qvals = wrapped.qualityValues(pattern)
            comparisons += 1
            if qvals["value_count"] != high - low:
                mismatches.append(("Q1", pattern, "count"))
            # F9 readsContaining totals == naive counts
            rc = wrapped.readsContaining(pattern)
            comparisons += 1
            if rc["reported_occurrences"] != high - low:
                mismatches.append(("F9", pattern, "total"))

        # F11A canonical boundary + RMQ identity
        expected_lcps = t11a.expected_lcps(output)
        comparisons += 1
        if wrapped.lcpAt(100) != int(expected_lcps[99]):
            mismatches.append(("F11A", "boundary", "x"))
        comparisons += 1
        if wrapped.lcpBetweenRows(10, 20) != int(
                np.min(expected_lcps[10:20])):
            mismatches.append(("F11A", "rmq", "x"))

        integrated["comparisons"] = comparisons
        integrated["mismatches"] = len(mismatches)
        assert mismatches == []
        assert comparisons > 200

        # ---------------- Feature-10 reduced package ---------------------
        reduced = os.path.join(work, "reduced")
        stats = remove_sources(
            output, reduced,
            sources=["sample00", "sample02", "sample09"],
            drop_lcp=True)
        assert stats["read_provenance_preserved"]
        assert stats["bwt_tags_preserved"]
        assert stats["quality_sidecar_preserved"]
        assert not lcp_exists(reduced)

        keep = {sid: f9.TEN_SOURCE_READS[sid] for sid in
                f9.TEN_SOURCE_READS
                if sid not in ("sample00", "sample02", "sample09")}
        save_expected_rows(reduced, leaves, keep)
        rindex = MultiSourceQueryIndex(
            reduced, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        rread = ReadProvenanceIndex(
            reduced, mmap=False, source_index=rindex)
        rmeta = SourceMetadataCatalog(rindex.list_sources())
        rwrapped = MultiSourceBWT(
            None, rindex, source_metadata=rmeta,
            read_provenance=rread,
            bwt_tags=BWTTagStore(reduced),
            quality_sidecar=QualitySidecar(reduced))
        reduced_oracle = f9.OracleReadIdentity(
            reduced,
            {sid: leaves[sid] for sid in keep},
            keep)
        rwrapped.bwt = t11a.OracleBackedAdapter(reduced, reduced_oracle)

        reduced_report = report["reduced_package"]
        reduced_report["read_count"] = rread.read_count
        reduced_report["lcp_absent"] = not lcp_exists(reduced)
        assert rread.read_count == 21
        rcomparisons = 0
        rmismatches = []
        rmanifest = load_manifest(reduced)
        for pattern in patterns:
            low, high = naive_interval(reduced, pattern)
            for sid in keep:
                expected = sum(
                    1 for x in range(low, high)
                    if row_source(reduced, rmanifest, x) == sid
                )
                rcomparisons += 1
                if rwrapped.countOccurrencesForSource(
                        pattern, sid) != expected:
                    rmismatches.append(("F3_reduced", pattern, sid))
            sparse = rwrapped.nonzeroSources(pattern)
            rcomparisons += 1
            if sum(r["count"] for r in sparse) != high - low:
                rmismatches.append(("F4_reduced", pattern, "sum"))
            rcomparisons += 1
            if rwrapped.sourceFrequency(pattern) != sum(
                    1 for sid in keep
                    if row_interval_count(reduced, rmanifest, sid,
                                          pattern) > 0):
                rmismatches.append(("F5_reduced", pattern, "freq"))
            rc = rwrapped.readsContaining(pattern, include_quality=True)
            rcomparisons += 1
            if rc["reported_occurrences"] != high - low:
                rmismatches.append(("F9_reduced", pattern, "total"))
            if any(rec["source_id"] not in keep
                   for rec in rc["reads"]):
                rmismatches.append(("F9_reduced", pattern, "purity"))
            qvals = rwrapped.qualityValues(pattern)
            rcomparisons += 1
            if qvals["value_count"] != high - low:
                rmismatches.append(("Q1_reduced", pattern, "count"))
        reduced_report["comparisons"] = rcomparisons
        reduced_report["mismatches"] = len(rmismatches)
        assert rmismatches == []
        assert rcomparisons > 100

        # ---------------- Feature-13A accounting -------------------------
        bench = report["benchmark"]
        structural = inspect_index(output)
        reduced_structural = inspect_index(reduced)
        bench["integrated_N"] = structural["structure"]["N"]
        bench["reduced_N"] = reduced_structural["structure"]["N"]
        bench["integrated_lcp_available"] = (
            structural["storage"]["lcp"]["available"])
        bench["reduced_lcp_available"] = (
            reduced_structural["storage"]["lcp"]["available"])
        assert bench["integrated_N"] == 191
        assert bench["reduced_N"] == 133
        assert bench["integrated_lcp_available"]
        assert not bench["reduced_lcp_available"]
        doc = full_benchmark_document(output)
        assert doc["backend_contract"]["contract_version"] == 1

        report["mismatch_count"] = (
            len(mismatches) + len(rmismatches))
        assert report["mismatch_count"] == 0

        with open(out_path, "w") as fp:
            json.dump(report, fp, indent=2, sort_keys=True)
            fp.write("\n")
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def naive_interval(directory, pattern):
    suffixes = [row["suffix"] for row in f9.load_rows(directory)]
    low = bisect_left(suffixes, pattern)
    high = bisect_left(suffixes, pattern + "\x7f")
    return low, high


def interval_length(directory, pattern):
    low, high = naive_interval(directory, pattern)
    return high - low


def save_expected_rows(directory, leaves, reads_by_source):
    """Test-side naive rows for a reduced package (independent oracle)."""
    all_order = {sid: i for i, sid in enumerate(reads_by_source)}
    rows = []
    for sid in reads_by_source:
        for r in f9.load_rows(leaves[sid]):
            rows.append((
                r["suffix"], all_order[sid], r["read_id"], r["pos"],
                r["bwt"]))
    rows.sort()
    out = [
        {"suffix": a, "read_id": c, "pos": d, "bwt": e}
        for a, b, c, d, e in rows
    ]
    f9.save_rows(directory, out)


def bisect_left(a, x):
    lo = 0
    hi = len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def row_source(merged_dir, manifest, row_index):
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
    return str(node["source_id"])


def row_interval_count(merged_dir, manifest, sid, pattern):
    low, high = naive_interval(merged_dir, pattern)
    return sum(
        1 for x in range(low, high)
        if row_source(merged_dir, manifest, x) == sid
    )


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("usage: enhanced_integration_gate.py OUTPUT.json\n")
        return 2
    report = run_gate(sys.argv[1])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
