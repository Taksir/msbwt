#!/usr/bin/env python2
"""msbwt-modern2 Feature 5/6 evidence generator: sample frequency and top-k
exact sources.

Runs inside the pinned Python-2.7 environment (CPython 2.7.18 / NumPy
1.16.6).  Exercises:

- ten-source read-derived fixture, >=350 patterns:
  - Feature 5 == number of standalone sources with count > 0;
  - Feature 6 == sparse listing sorted by (-count, provenance order)
    truncated to k, for k = 0, 1, 2, 3, 5, 10, 20;
- one merged FM search per operation;
- Feature 5 count-only traversal does not call the Feature-4 listing
  (instrumented);
- absent patterns, all-sources patterns, ties at cutoff, k > support,
  k = 0, negative k rejection;
- REAL modern2 integration: canonical uniform-a + uniform-b merge and a
  real 5-source balanced merge;
- deterministic randomized Level-3 differential (seed 20260811);
- storage/performance sanity.

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

FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")
SEED = 20260811
TOP_K_VALUES = (0, 1, 2, 3, 5, 10, 20)


def ranked_expected(sparse, manifest, k):
    table = [src["id"] for src in manifest["sources"]]
    table_index = {sid: i for i, sid in enumerate(table)}
    ranked = sorted(sparse,
                    key=lambda item: (-item[1], table_index[item[0]]))
    return ranked[:k] if k < len(ranked) else ranked


def run_evidence(out_path):
    report = {
        "seed": SEED,
        "mismatch_count": 0,
        "oracles": [
            "standalone_bwt",
            "point4_sparse_listing",
            "ranked_sparse_truncation",
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

    work = tempfile.mkdtemp(prefix="f56-evidence-")
    try:
        harness = f1.SourceHarness(work)

        # ---------------- ten-source read-derived fixture ----------------
        output, manifest, merged, standalone, _ = f3.build_merged_fixture(
            work, f3.TEN_SOURCE_READS, name="merged10")
        index = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False, use_saved_rank=False)
        wrapped = MultiSourceBWT(merged, index)

        ten = report["ten_source_fixture"]
        patterns = f3.all_test_patterns()
        ten["patterns"] = len(patterns)
        assert ten["patterns"] >= 350

        mismatches = []
        top_k_comparisons = 0
        for pattern in patterns:
            sparse = f4.expected_sparse(standalone, manifest, pattern)
            frequency = wrapped.sourceFrequency(pattern)
            if frequency != len(sparse):
                mismatches.append((pattern, "freq", frequency, len(sparse)))
            for k in TOP_K_VALUES:
                got = wrapped.topSources(pattern, k=k)
                expected = ranked_expected(sparse, manifest, k)
                got_list = [(r["source_id"], r["count"]) for r in got]
                expected_list = [(n, c) for n, c, _ in expected]
                top_k_comparisons += 1
                if got_list != expected_list:
                    mismatches.append((pattern, "top", k, got_list,
                                       expected_list))
        ten["top_k_comparisons"] = top_k_comparisons
        ten["mismatches"] = len(mismatches)
        assert top_k_comparisons >= 2500
        assert mismatches == []

        # one merged FM search per operation
        fresh = MultiSourceBWT(
            merged,
            MultiSourceQueryIndex(output, mmap=False, use_saved_rank=False))
        before = merged.search_calls
        for pattern in ("ACGT", "A", "$", "NNNNN"):
            fresh.sourceFrequency(pattern)
            fresh.topSources(pattern, k=3)
        assert merged.search_calls == before + 8
        ten["one_search_probe"] = True

        # count-only traversal does not call the listing
        index2 = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False, use_saved_rank=False)
        original = index2.nonzero_sources_interval
        calls = {"count": 0}

        def spy(*args, **kwargs):
            calls["count"] += 1
            return original(*args, **kwargs)

        index2.nonzero_sources_interval = spy
        wrapped2 = MultiSourceBWT(merged, index2)
        for pattern in ("AC", "CGT", "A", "NNNNN"):
            wrapped2.sourceFrequency(pattern)
        assert calls["count"] == 0
        ten["count_only_probe"] = True

        # tie rule + edge cases
        assert wrapped.topSources("AC", k=0) == []
        try:
            wrapped.topSources("AC", k=-1)
            raise AssertionError("negative k not rejected")
        except ValueError:
            pass
        assert wrapped.topSources("GGGGGGGGGGGG") == []
        out = wrapped.topSources("A", k=10)
        assert len(out) == 10
        table = [src["id"] for src in manifest["sources"]]
        keys = [(-r["count"], table.index(r["source_id"])) for r in out]
        assert keys == sorted(keys)
        ten["tie_rule_probe"] = True

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
            frequency = real_merged.sourceFrequency(query)
            expected_freq = (1 if expected_a else 0) + (1 if expected_b
                                                        else 0)
            real_queries += 1
            if frequency != expected_freq:
                real_mismatches.append((query, "freq", frequency,
                                        expected_freq))
            candidates = []
            if expected_a:
                candidates.append(("real-a", expected_a))
            if expected_b:
                candidates.append(("real-b", expected_b))
            ranked = sorted(candidates,
                            key=lambda item: (-item[1],
                                              {"real-a": 0,
                                               "real-b": 1}[item[0]]))
            for k in (0, 1, 2, 5):
                top = real_merged.topSources(query, k=k)
                expected_top = ranked[:k] if k < len(ranked) else ranked
                got_top = [(r["source_id"], r["count"]) for r in top]
                if got_top != expected_top:
                    real_mismatches.append((query, "top", k, got_top,
                                            expected_top))
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
            counts = {}
            for sid in ("r5-%d" % i for i in range(5)):
                count = int(standalone5[sid].countOccurrencesOfSeq(query))
                if count:
                    counts[sid] = count
            five_queries += 1
            if merged5.sourceFrequency(query) != len(counts):
                five_mismatches.append((query, "freq"))
            order = {"r5-%d" % i: i for i in range(5)}
            ranked = sorted(counts.items(),
                            key=lambda item: (-item[1], order[item[0]]))
            for k in (0, 1, 2, 5):
                top = merged5.topSources(query, k=k)
                expected_top = ranked[:k] if k < len(ranked) else ranked
                got_top = [(r["source_id"], r["count"]) for r in top]
                if got_top != expected_top:
                    five_mismatches.append((query, "top", k))
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
            order = {"rd-%d" % i: i for i in range(source_count)}
            for query in queries_r:
                counts = {}
                for sid in reads_by_source:
                    count = int(standalone_r[sid].countOccurrencesOfSeq(
                        query))
                    if count:
                        counts[sid] = count
                random_queries += 1
                if merged_r.sourceFrequency(query) != len(counts):
                    random_mismatches.append({
                        "case": case_index, "query": query,
                        "kind": "freq", "reads_by_source": reads_by_source})
                ranked = sorted(counts.items(),
                                key=lambda item: (-item[1],
                                                  order[item[0]]))
                for k in (0, 1, 2, 5):
                    top = merged_r.topSources(query, k=k)
                    expected_top = (ranked[:k] if k < len(ranked)
                                    else ranked)
                    got_top = [(r["source_id"], r["count"]) for r in top]
                    if got_top != expected_top:
                        random_mismatches.append({
                            "case": case_index, "query": query,
                            "kind": "top", "k": k,
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
        freq_queries = 0
        top_queries = 0
        for i in range(20):
            pattern = patterns[i * 11 % len(patterns)]
            probe_index.source_frequency_interval(
                *merged.findIndicesOfStr(pattern))
            probe_index.top_sources_interval(
                *merged.findIndicesOfStr(pattern), k=3)
            freq_queries += 1
            top_queries += 1
        perf["frequency_queries"] = freq_queries
        perf["top_queries"] = top_queries
        perf["wall_seconds"] = round(time.time() - started, 3)
        assert freq_queries == 20 and top_queries == 20

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
        sys.stderr.write("usage: feature5_6_frequency_topk_evidence.py "
                         "OUTPUT.json\n")
        return 2
    report = run_evidence(sys.argv[1])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
