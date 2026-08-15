#!/usr/bin/env python2
"""msbwt-modern2 Feature 8A evidence generator: source-aware left/right
sequence extensions without a reverse FM-index.

Runs inside the pinned Python-2.7 environment.  Exercises:

- ten-source read-derived fixture, many patterns:
  - merged left extensions == direct exact searches of cP (counts);
  - merged right extensions == direct exact searches of Pc (counts);
  - per-source extension counts == standalone counts (all ten sources);
  - subset/group/where extension counts == sums of standalone counts;
- search-asymmetry instrumentation (left: 1 full + 5 incremental; right:
  5 full + 0 incremental);
- right '$' extension with explicit alphabet; left '$' rejected;
- REAL modern2 integration: canonical two-source merge;
- deterministic randomized Level-3 differential subset (seed 20260811);
- performance sanity (extension queries, direction cost model).

Any mismatch raises AssertionError; the driver records JSON only after
every gate passes.  Python 2.7 only.
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
sys.path.insert(0, PACKAGE)
sys.path.insert(0, os.path.join(PACKAGE, "tests"))
import test_source_index_py2 as f1  # noqa: E402
import test_multisource_query_py2 as f3  # noqa: E402
import test_sequence_extensions_py2 as f8a  # noqa: E402

from MUS.MultiSourceProvenance import (  # noqa: E402
    initialize_leaf_provenance,
    merge_two_with_provenance,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)

FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")
SEED = 20260811


def run_evidence(out_path):
    report = {
        "seed": SEED,
        "mismatch_count": 0,
        "oracles": ["standalone_bwt", "direct_exact_search"],
        "ten_source_fixture": {},
        "real_integration": {},
        "randomized": {},
        "performance": {},
        "notes": [
            "read-derived fixtures are tiny deterministic corpora; real "
            "merges use compiled GenericMerge through the Feature-2 "
            "adapter.",
        ],
    }

    work = tempfile.mkdtemp(prefix="f8a-evidence-")
    try:
        harness = f1.SourceHarness(work)

        output, manifest, merged, standalone, _ = f3.build_merged_fixture(
            work, f3.TEN_SOURCE_READS, name="merged10")
        index = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False, use_saved_rank=False)
        wrapped = MultiSourceBWT(merged, index)
        metadata = wrapped.source_metadata
        table = [src["id"] for src in manifest["sources"]]
        metadata.define_group("g1", table[:3])
        for i, sid in enumerate(table):
            metadata.set_source_metadata(sid, cohort="case"
                                         if i < 5 else "control")

        ten = report["ten_source_fixture"]
        patterns = f8a.extension_patterns()
        ten["patterns"] = len(patterns)
        assert ten["patterns"] >= 100

        mismatches = []
        comparisons = 0
        for pattern in patterns:
            for direction in ("left", "right"):
                result = (wrapped.extendLeft(pattern)
                          if direction == "left"
                          else wrapped.extendRight(pattern))
                for rec in result["extensions"]:
                    direct = merged.findIndicesOfStr(rec["sequence"])
                    expected = direct[1] - direct[0]
                    comparisons += 1
                    if rec["count"] != expected:
                        mismatches.append(
                            (pattern, direction, rec["sequence"],
                             rec["count"], expected))
        # per-source counts for a representative pattern set
        for pattern in ("AC", "CGT", "AAAA", "N", "GTAC", "TTA"):
            for direction in ("left", "right"):
                for sid in f3.TEN_SOURCE_READS:
                    result = (wrapped.extendLeft(pattern, source=sid)
                              if direction == "left"
                              else wrapped.extendRight(pattern, source=sid))
                    for rec in result["extensions"]:
                        low, high = standalone[sid].findIndicesOfStr(
                            rec["sequence"])
                        comparisons += 1
                        if rec["count"] != high - low:
                            mismatches.append(
                                (pattern, direction, sid, rec["sequence"],
                                 rec["count"], high - low))
        # subset/group/where sums
        subset = ["sample00", "sample02", "sample09"]
        for pattern in ("AC", "CGT", "AAAA", "N", "GTAC"):
            for direction in ("left", "right"):
                for kind, selector in (
                    ("subset", {"sources": subset}),
                    ("group", {"group": "g1"}),
                    ("where", {"where": {"cohort": "case"}}),
                ):
                    result = (wrapped.extendLeft(pattern, **selector)
                              if direction == "left"
                              else wrapped.extendRight(pattern,
                                                        **selector))
                    members = (subset if kind == "subset"
                               else metadata.group_sources("g1")
                               if kind == "group"
                               else metadata.select_where(
                                   cohort="case"))
                    for rec in result["extensions"]:
                        expected = sum(
                            (lambda iv: iv[1] - iv[0])(
                                standalone[sid].findIndicesOfStr(
                                    rec["sequence"]))
                            for sid in members)
                        comparisons += 1
                        if rec["count"] != expected:
                            mismatches.append(
                                (pattern, direction, kind,
                                 rec["sequence"], rec["count"], expected))
        ten["comparisons"] = comparisons
        ten["mismatches"] = len(mismatches)
        assert comparisons >= 1000
        assert mismatches == []

        # asymmetry probe
        fresh = MultiSourceBWT(
            merged,
            MultiSourceQueryIndex(output, mmap=False, use_saved_rank=False))
        before = merged.search_calls
        left = fresh.extendLeft("ACGT", include_stats=True)
        left_searches = merged.search_calls - before
        assert left["stats"]["full_fm_searches"] == 1
        assert left["stats"]["incremental_extension_calls"] == 5
        assert left_searches == 6
        before = merged.search_calls
        right = fresh.extendRight("ACGT", include_stats=True)
        right_searches = merged.search_calls - before
        assert right["stats"]["full_fm_searches"] == 5
        assert right["stats"]["incremental_extension_calls"] == 0
        assert right_searches == 5
        ten["asymmetry_probe"] = True

        # dollar probes
        dollar = wrapped.extendRight("AAAA", alphabet="A$")
        assert [rec["base"] for rec in dollar["extensions"]] == ["A", "$"]
        try:
            wrapped.extendLeft("ACGT", alphabet="A$")
            raise AssertionError("left '$' not rejected")
        except ValueError:
            pass
        ten["dollar_probe"] = True

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
        queries = ["A", "C", "G", "T", "N", "AC", "GT", "ACGT", "AAAAA",
                   "NACGT"]
        real_mismatches = []
        real_queries = 0
        for query in queries:
            for direction in ("left", "right"):
                for sid, bwt in (("real-a", a_bwt), ("real-b", b_bwt)):
                    result = (real_merged.extendLeft(query, source=sid)
                              if direction == "left"
                              else real_merged.extendRight(query,
                                                           source=sid))
                    for rec in result["extensions"]:
                        expected = int(bwt.countOccurrencesOfSeq(
                            rec["sequence"]))
                        real_queries += 1
                        if rec["count"] != expected:
                            real_mismatches.append(
                                (query, direction, sid, rec["sequence"],
                                 rec["count"], expected))
        real["canonical_two_source"] = {
            "queries": real_queries,
            "mismatches": len(real_mismatches),
        }
        assert real_mismatches == []
        assert real_queries > 100

        # ------------- randomized Level-3 differential --------------------
        rng = random.Random(SEED)
        random_mismatches = []
        random_queries = 0
        datasets = 0
        for case_index in range(3):
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
            merge_two_with_provenance(
                leaves_r[0], leaves_r[1], out_r,
                merge_two_func=f3.holt_merge_two_local, num_procs=1)
            for i in range(2, source_count):
                merged_tmp = os.path.join(work, "rand-%d-m%d" %
                                          (case_index, i))
                merge_two_with_provenance(
                    out_r, leaves_r[i], merged_tmp,
                    merge_two_func=f3.holt_merge_two_local, num_procs=1)
                out_r = merged_tmp
            merged_r = MultiSourceBWT.load(out_r, mmap=False)
            datasets += 1
            queries_r = set(["A", "C", "G", "T", "N", "AA", "AC", "NN"])
            for reads in reads_by_source.values():
                for read in reads:
                    for start in range(len(read)):
                        for end in range(start + 1,
                                         min(len(read), start + 4) + 1):
                            queries_r.add(read[start:end])
            for query in queries_r:
                for direction in ("left", "right"):
                    result = (merged_r.extendLeft(query)
                              if direction == "left"
                              else merged_r.extendRight(query))
                    for rec in result["extensions"]:
                        expected = sum(
                            int(bwt.countOccurrencesOfSeq(rec["sequence"]))
                            for bwt in standalone_r.values())
                        random_queries += 1
                        if rec["count"] != expected:
                            random_mismatches.append({
                                "case": case_index, "query": query,
                                "direction": direction,
                                "sequence": rec["sequence"],
                                "reads_by_source": reads_by_source})
        report["randomized"] = {
            "seed": SEED,
            "datasets": datasets,
            "queries": random_queries,
            "mismatches": len(random_mismatches),
        }
        assert random_mismatches == []
        assert datasets == 3
        assert random_queries > 200

        # ------------- performance / storage sanity -----------------------
        perf = report["performance"]
        started = time.time()
        probe_index = MultiSourceQueryIndex(
            output, rank_stride_bytes=64, mmap=True, use_saved_rank=False)
        probe = MultiSourceBWT(merged, probe_index)
        left_queries = 0
        right_queries = 0
        for i in range(10):
            pattern = patterns[i * 7 % len(patterns)]
            probe.extendLeft(pattern)
            probe.extendRight(pattern)
            left_queries += 1
            right_queries += 1
        perf["left_queries"] = left_queries
        perf["right_queries"] = right_queries
        perf["wall_seconds"] = round(time.time() - started, 3)
        assert left_queries == 10 and right_queries == 10

        report["mismatch_count"] = (
            len(mismatches) + len(real_mismatches) + len(random_mismatches))
        assert report["mismatch_count"] == 0

        with open(out_path, "w") as fp:
            json.dump(report, fp, indent=2, sort_keys=True)
            fp.write("\n")
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("usage: feature8a_extension_evidence.py "
                         "OUTPUT.json\n")
        return 2
    report = run_evidence(sys.argv[1])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
