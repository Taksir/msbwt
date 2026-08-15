#!/usr/bin/env python2
"""msbwt-modern2 Feature 4 evidence generator: sparse nonzero-source
listing with exact counts.

Runs inside the pinned Python-2.7 environment (CPython 2.7.18 / NumPy
1.16.6).  Exercises:

- the ten-source read-derived fixture: sparse listing == the Point-3
  per-source count oracle filtered to positive counts, for >=350 patterns,
  with constituent-local intervals, sum-of-counts == merged count, and
  deterministic manifest-order output;
- one merged FM search per sparse query and zero rank nodes loaded for
  globally absent patterns;
- pruning validation: traversal statistics (internal nodes visited,
  branches pruned, leaves reported) equal an independent recursive DFS
  counter; categories zero/one/few/all sources hit;
- REAL modern2 integration: canonical uniform-a + uniform-b merge and a
  real 5-source balanced merge; every pattern's sparse result equals the
  filtered per-source counts;
- deterministic randomized Level-3 differential (seed 20260811);
- storage/performance sanity (sparse queries, average internal nodes
  visited vs the naive 36-projection baseline for ten sources).

Any mismatch raises AssertionError with the full reproducer; the driver
script records the JSON only after every gate passes.

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import json
import os
import random
import shutil
import sys
import tempfile
import time

import numpy as np

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

PACKAGE = os.path.join(REPO, "packages", "msbwt-modern2")
# the in-tree package must win over any installed msbwt-modern2
sys.path.insert(0, PACKAGE)
sys.path.insert(0, os.path.join(PACKAGE, "tests"))
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

FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")
SEED = 20260811


def expected_sparse(standalone, manifest, pattern):
    """Gold standard: Point-3 per-source exact counts filtered to
    positives, in authoritative manifest order."""
    out = []
    for source_record in manifest["sources"]:
        source_name = source_record["id"]
        low, high = standalone[source_name].findIndicesOfStr(pattern)
        count = high - low
        if count > 0:
            out.append((source_name, count, (low, high)))
    return out


def independent_dfs_stats(output, node, l, r):
    """Independent recursive traversal counter (no shared code)."""
    stats = {"internal_nodes_visited": 0, "branches_pruned": 0,
             "leaves_reported": 0}
    if l == r:
        return stats
    if node["type"] == "leaf":
        stats["leaves_reported"] += 1
        return stats
    stats["internal_nodes_visited"] += 1
    bits = unpack_interleave(
        os.path.join(output, str(node["interleave"])), node["length"])
    left_sel = bits == 0
    right_sel = bits == 1
    children = (
        (node["left"], left_sel),
        (node["right"], right_sel),
    )
    for child, selected in children:
        cl = int(np.count_nonzero(selected[:l]))
        cr = int(np.count_nonzero(selected[:r]))
        if cl == cr:
            stats["branches_pruned"] += 1
        else:
            sub = independent_dfs_stats(output, child, cl, cr)
            for key in stats:
                stats[key] += sub[key]
    return stats


def run_evidence(out_path):
    report = {
        "seed": SEED,
        "mismatch_count": 0,
        "oracles": [
            "point3_counts",
            "standalone_bwt",
            "independent_dfs_stats",
        ],
        "ten_source_fixture": {},
        "real_integration": {},
        "randomized": {},
        "performance": {},
        "notes": [
            "read-derived fixtures are tiny deterministic corpora, not "
            "compiled Holt/McMillan replacements; real merges use the "
            "compiled GenericMerge through the Feature-2 adapter.",
        ],
    }

    work = tempfile.mkdtemp(prefix="f4-evidence-")
    try:
        harness = f1.SourceHarness(work)

        # ---------------- ten-source read-derived fixture ----------------
        output, manifest, merged, standalone, _ = f3.build_merged_fixture(
            work, f3.TEN_SOURCE_READS, name="merged10")
        index = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False, use_saved_rank=False)
        wrapped = MultiSourceBWT(merged, index)

        ten = report["ten_source_fixture"]
        ten["source_count"] = len(standalone)
        assert ten["source_count"] == 10

        patterns = f3.all_test_patterns()
        ten["patterns"] = len(patterns)
        assert ten["patterns"] >= 350

        # one merged FM search per sparse query (dedicated probe)
        probe_before = merged.search_calls
        for probe_pattern in ("ACGT", "A", "$", "NNNNN", "CGT"):
            wrapped.nonzeroSources(probe_pattern)
        assert merged.search_calls == probe_before + 5
        ten["one_search_probe"] = True

        mismatches = []
        sparse_comparisons = 0
        interval_comparisons = 0
        internal_nodes_total = 0
        internal_nodes_nonempty = 0
        nonempty_count = 0
        absent_count = 0
        one_source_count = 0
        for pattern in patterns:
            expected = expected_sparse(standalone, manifest, pattern)
            result = wrapped.nonzeroSources(pattern,
                                            include_intervals=True)
            got = [(r["source_id"], r["count"]) for r in result]
            sparse_comparisons += 1
            if got != [(n, c) for n, c, _ in expected]:
                mismatches.append((pattern, got, expected))

            # sum of counts == merged count
            merged_low, merged_high = merged.findIndicesOfStr(pattern)
            if sum(c for _, c in got) != merged_high - merged_low:
                mismatches.append(("sum", pattern, got,
                                   merged_high - merged_low))

            # exact intervals vs standalone
            for rec in result:
                low, high = standalone[rec["source_id"]].findIndicesOfStr(
                    pattern)
                interval_comparisons += 1
                if rec["source_interval"] != (low, high):
                    mismatches.append(("interval", pattern, rec,
                                       (low, high)))

            # traversal stats vs independent DFS
            _, stats = index.nonzero_sources_interval(
                merged_low, merged_high, include_stats=True)
            expected_stats = independent_dfs_stats(
                output, manifest["root"], merged_low, merged_high)
            if (stats["internal_nodes_visited"]
                    != expected_stats["internal_nodes_visited"]):
                mismatches.append(("stats", pattern, stats, expected_stats))
            if (stats["branches_pruned"] != expected_stats["branches_pruned"]
                    or stats["leaves_reported"]
                    != expected_stats["leaves_reported"]):
                mismatches.append(("stats2", pattern, stats, expected_stats))
            internal_nodes_total += stats["internal_nodes_visited"]
            if expected:
                internal_nodes_nonempty += stats["internal_nodes_visited"]
                nonempty_count += 1
            else:
                absent_count += 1
                if stats["rank_nodes_loaded_for_query"] != 0:
                    mismatches.append(("absent-rank-load", pattern, stats))
            if len(expected) == 1:
                one_source_count += 1

        ten["sparse_comparisons"] = sparse_comparisons
        ten["interval_comparisons"] = interval_comparisons
        ten["mismatches"] = len(mismatches)
        ten["absent_patterns"] = absent_count
        ten["one_source_patterns"] = one_source_count
        ten["average_internal_nodes_all"] = round(
            float(internal_nodes_total) / len(patterns), 3)
        ten["average_internal_nodes_nonempty"] = round(
            float(internal_nodes_nonempty) / nonempty_count, 3)
        ten["naive_projection_edges_baseline"] = 36
        ten["reduction_vs_naive_all"] = round(
            100.0 * (1.0 - float(internal_nodes_total)
                     / (36.0 * len(patterns))), 2)
        ten["reduction_vs_naive_nonempty"] = round(
            100.0 * (1.0 - float(internal_nodes_nonempty)
                     / (36.0 * nonempty_count)), 2)
        assert sparse_comparisons >= 350
        assert interval_comparisons >= 250
        assert mismatches == []
        ten["pruning_probe"] = True

        # absent/private/all-hit categories
        assert wrapped.nonzeroSources("GGGGGGGGGGGG") == []
        private = wrapped.nonzeroSources("AAGGTT")
        assert len(private) == 1 and private[0]["source_id"] == "sample09"
        assert len(wrapped.nonzeroSources("A")) == 10
        report["pruning_categories"] = {
            "zero_sources": True,
            "one_source": True,
            "all_sources": True,
        }

        # ---------------- REAL modern2 integration ------------------------
        real = report["real_integration"]

        a_dir = harness.build_fixture_source("real-a", "uniform-a.fastq")
        b_dir = harness.build_fixture_source("real-b", "uniform-b.fastq")
        initialize_leaf_provenance(a_dir, source_id="real-a",
                                   source_name="real-a")
        initialize_leaf_provenance(b_dir, source_id="real-b",
                                   source_name="real-b")
        m_dir = os.path.join(work, "real-m")
        merge_two_with_provenance(a_dir, b_dir, m_dir,
                                  merge_two_func=f3.holt_merge_two_local,
                                  num_procs=1)
        a_bwt = f1.load_standalone(a_dir)
        b_bwt = f1.load_standalone(b_dir)
        real_merged = MultiSourceBWT.load(m_dir, mmap=False)

        queries = f1.build_queries(f1.CANONICAL_READS_A,
                                   f1.CANONICAL_READS_B)
        queries.extend([b"$", b"A$", b"T$", b"ACGTN$"])
        real_mismatches = []
        real_queries = 0
        for query in queries:
            expected_a = int(a_bwt.countOccurrencesOfSeq(query))
            expected_b = int(b_bwt.countOccurrencesOfSeq(query))
            expected = {}
            if expected_a:
                expected["real-a"] = expected_a
            if expected_b:
                expected["real-b"] = expected_b
            result = real_merged.nonzeroSources(query)
            got = {r["source_id"]: r["count"] for r in result}
            real_queries += 1
            if got != expected:
                real_mismatches.append((query, got, expected))
            legacy = int(real_merged.bwt.countOccurrencesOfSeq(query))
            if sum(got.values()) != legacy:
                real_mismatches.append(("sum", query, got, legacy))
        # givenRange delegation on the sparse layer
        t_interval = tuple(int(v) for v in real_merged.bwt.findIndicesOfStr(
            b"T"))
        direct = real_merged.nonzeroSources(b"GT")
        ranged = real_merged.nonzeroSources(b"G", givenRange=t_interval)
        assert [(r["source_id"], r["count"]) for r in ranged] == [
            (r["source_id"], r["count"]) for r in direct]
        real["canonical_two_source"] = {
            "queries": real_queries,
            "mismatches": len(real_mismatches),
        }
        assert real_mismatches == []
        assert real_queries > 60

        # real 5-source balanced merge
        rng = random.Random(SEED + 7)
        leaves5 = []
        standalone5 = {}
        for i in range(5):
            reads = f1.make_random_case(rng)[0]
            leaf = harness.build_fastq_source("real5-%d" % i, reads)
            initialize_leaf_provenance(leaf, source_id="r5-%d" % i,
                                       source_name="r5-%d" % i)
            leaves5.append(leaf)
            standalone5["r5-%d" % i] = f1.load_standalone(leaf)
        out5 = os.path.join(work, "real5")
        merge_many_balanced(leaves5, out5,
                            merge_two_func=f3.holt_merge_two_local,
                            num_procs=1)
        merged5 = MultiSourceBWT.load(out5, mmap=False)
        q5 = ["A", "C", "G", "T", "N", "AC", "GT", "NA", "NN", "AAA",
              "ACGT", "TTA", "CGTAC", "$"]
        five_mismatches = []
        five_queries = 0
        for query in q5:
            expected = {}
            for sid in ("r5-%d" % i for i in range(5)):
                count = int(standalone5[sid].countOccurrencesOfSeq(query))
                if count:
                    expected[sid] = count
            result = merged5.nonzeroSources(query)
            got = {r["source_id"]: r["count"] for r in result}
            five_queries += 1
            if got != expected:
                five_mismatches.append((query, got, expected))
        real["five_source_balanced"] = {
            "queries": five_queries,
            "mismatches": len(five_mismatches),
        }
        assert five_mismatches == []

        # ------------- randomized Level-3 differential --------------------
        rng = random.Random(SEED)
        random_mismatches = []
        random_queries = 0
        datasets = 0
        for case_index in range(4):
            source_count = rng.randint(2, 4)
            leaves_r = []
            standalone_r = {}
            reads_by_source = {}
            for i in range(source_count):
                reads = f1.make_random_case(rng)[0]
                reads_by_source["rd-%d" % i] = reads
                leaf = harness.build_fastq_source(
                    "rand-%d-%d" % (case_index, i), reads)
                initialize_leaf_provenance(leaf, source_id="rd-%d" % i,
                                           source_name="rd-%d" % i)
                leaves_r.append(leaf)
                standalone_r["rd-%d" % i] = f1.load_standalone(leaf)
            out_r = os.path.join(work, "rand-%d" % case_index)
            merge_many_balanced(leaves_r, out_r,
                                merge_two_func=f3.holt_merge_two_local,
                                num_procs=1)
            merged_r = MultiSourceBWT.load(out_r, mmap=False)
            datasets += 1
            queries_r = set(["A", "C", "G", "T", "N", "$", "AA", "AC",
                             "NN", "A$", "T$"])
            for reads in reads_by_source.values():
                for read in reads:
                    for start in range(len(read)):
                        for end in range(start + 1, len(read) + 1):
                            queries_r.add(read[start:end])
            for query in queries_r:
                expected = {}
                for sid in reads_by_source:
                    count = int(standalone_r[sid].countOccurrencesOfSeq(
                        query))
                    if count:
                        expected[sid] = count
                result = merged_r.nonzeroSources(query)
                got = {r["source_id"]: r["count"] for r in result}
                random_queries += 1
                if got != expected:
                    random_mismatches.append({
                        "case": case_index, "query": query, "got": got,
                        "expected": expected,
                        "reads_by_source": reads_by_source})
                legacy = int(merged_r.bwt.countOccurrencesOfSeq(query))
                if sum(got.values()) != legacy:
                    random_mismatches.append({
                        "case": case_index, "query": query,
                        "kind": "sum", "got": sum(got.values()),
                        "legacy": legacy,
                        "reads_by_source": reads_by_source})
        report["randomized"] = {
            "seed": SEED,
            "datasets": datasets,
            "queries": random_queries,
            "mismatches": len(random_mismatches),
        }
        assert random_mismatches == []
        assert datasets == 4
        assert random_queries > 300

        # ------------- performance / storage sanity -----------------------
        perf = report["performance"]
        started = time.time()
        probe_index = MultiSourceQueryIndex(
            output, rank_stride_bytes=64, mmap=True, use_saved_rank=False)
        sparse_queries = 0
        nodes_total = 0
        for i in range(40):
            pattern = patterns[i * 7 % len(patterns)]
            interval = merged.findIndicesOfStr(pattern)
            _, stats = probe_index.nonzero_sources_interval(
                interval[0], interval[1], include_stats=True)
            sparse_queries += 1
            nodes_total += stats["internal_nodes_visited"]
        perf["sparse_queries"] = sparse_queries
        perf["avg_internal_nodes_per_query"] = round(
            float(nodes_total) / sparse_queries, 3)
        perf["wall_seconds"] = round(time.time() - started, 3)
        assert sparse_queries == 40

        # summary
        report["real_queries"] = real_queries + five_queries
        report["mismatch_count"] = (
            len(mismatches) + len(real_mismatches) + len(five_mismatches)
            + len(random_mismatches))
        assert report["mismatch_count"] == 0

        with open(out_path, "w") as fp:
            json.dump(report, fp, indent=2, sort_keys=True)
            fp.write("\n")
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("usage: feature4_sparse_source_evidence.py "
                         "OUTPUT.json\n")
        return 2
    report = run_evidence(sys.argv[1])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
