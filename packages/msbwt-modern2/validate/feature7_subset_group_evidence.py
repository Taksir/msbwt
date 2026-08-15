#!/usr/bin/env python2
"""msbwt-modern2 Feature 7 evidence generator: source subsets / metadata
groups / predicates.

Runs inside the pinned Python-2.7 environment (CPython 2.7.18 / NumPy
1.16.6).  Exercises:

- ten-source read-derived fixture, >=350 patterns:
  - countSubset == sum of standalone exact counts for arbitrary subsets
    (3-source, 2-source, half, all, single, empty);
  - querySubset records == Feature-4 listing filtered to the selection;
  - named groups (even/odd/case/control) and metadata predicates (AND,
    membership) == independent selection + sum;
- one merged FM search per subset/group/predicate query;
- complete-subtree shortcut stats for an 8-source group aligned with the
  balanced tree (left subtree);
- metadata isolation: editing metadata never changes provenance.json or
  msbwt.npy bytes;
- metadata catalog validation probes (unknown source, wrong format/version,
  corrupt file);
- REAL modern2 integration: canonical two-source merge with an external
  metadata file and in-dir auto-load;
- deterministic randomized Level-3 differential (seed 20260811).

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
from MUS.SourceMetadata import (  # noqa: E402
    SourceMetadataCatalog,
    SourceMetadataError,
)

FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")
SEED = 20260811


def sum_source_counts(standalone, pattern, selected):
    total = 0
    for sid in selected:
        low, high = standalone[sid].findIndicesOfStr(pattern)
        total += high - low
    return total


def run_evidence(out_path):
    report = {
        "seed": SEED,
        "mismatch_count": 0,
        "oracles": [
            "standalone_bwt",
            "point3_exact_source_counts",
            "point4_filtered_listing",
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

    work = tempfile.mkdtemp(prefix="f7-evidence-")
    try:
        harness = f1.SourceHarness(work)

        # ---------------- ten-source read-derived fixture ----------------
        output, manifest, merged, standalone, _ = f3.build_merged_fixture(
            work, f3.TEN_SOURCE_READS, name="merged10")
        index = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False, use_saved_rank=False)
        wrapped = MultiSourceBWT(merged, index)
        metadata = wrapped.source_metadata
        table = [src["id"] for src in manifest["sources"]]
        metadata.define_group("even", [table[i] for i in range(0, 10, 2)])
        metadata.define_group("odd", [table[i] for i in range(1, 10, 2)])
        metadata.define_group("case", table[:3])
        metadata.define_group("control", table[7:])
        metadata.define_group("left8", table[:8])
        for i, sid in enumerate(table):
            metadata.set_source_metadata(
                sid, batch="B%d" % (i % 3),
                cohort="case" if i < 5 else "control")

        ten = report["ten_source_fixture"]
        patterns = f3.all_test_patterns()
        ten["patterns"] = len(patterns)
        assert ten["patterns"] >= 350

        subsets = [
            ["sample00", "sample02", "sample09"],
            ["sample01", "sample08"],
            table[:5],
            table,
            ["sample05"],
            [],
        ]
        mismatches = []
        subset_comparisons = 0
        for pattern in patterns:
            for subset in subsets:
                expected = sum_source_counts(standalone, pattern, subset)
                got = wrapped.countSubset(pattern, sources=subset)
                subset_comparisons += 1
                if got != expected:
                    mismatches.append((pattern, subset, got, expected))
            for name in ("even", "odd", "case", "control"):
                members = metadata.group_sources(name)
                expected = sum_source_counts(standalone, pattern, members)
                got = wrapped.countGroup(pattern, name)
                subset_comparisons += 1
                if got != expected:
                    mismatches.append((pattern, name, got, expected))
            for where in ({"cohort": "case"}, {"cohort": "control"},
                          {"batch": "B0"},
                          {"batch": "B1", "cohort": "case"}):
                members = metadata.select_where(**where)
                expected = sum_source_counts(standalone, pattern, members)
                got = wrapped.countWhere(pattern, where)
                subset_comparisons += 1
                if got != expected:
                    mismatches.append((pattern, where, got, expected))
            # querySubset records == filtered Feature-4 listing
            subset = ["sample00", "sample03", "sample09"]
            sparse = f4.expected_sparse(standalone, manifest, pattern)
            expected = [(n, c) for n, c, _ in sparse if n in subset]
            result = wrapped.querySubset(pattern, sources=subset)
            got = [(r["source_id"], r["count"])
                   for r in result["sources"]]
            subset_comparisons += 1
            if got != expected:
                mismatches.append((pattern, "query", got, expected))
            if result["count"] != sum(c for _, c in got):
                mismatches.append((pattern, "agg", result["count"]))
        ten["subset_comparisons"] = subset_comparisons
        ten["mismatches"] = len(mismatches)
        assert subset_comparisons >= 2000
        assert mismatches == []

        # one merged FM search per query
        fresh = MultiSourceBWT(
            merged,
            MultiSourceQueryIndex(output, mmap=False, use_saved_rank=False),
            source_metadata=metadata)
        before = merged.search_calls
        fresh.countSubset("AC", sources=["sample00", "sample02"])
        fresh.querySubset("AC", group="even")
        fresh.countWhere("AC", {"cohort": "case"})
        fresh.queryGroup("AC", "odd")
        assert merged.search_calls == before + 4
        ten["one_search_probe"] = True

        # complete-subtree shortcut
        left8 = metadata.group_sources("left8")
        interval = merged.findIndicesOfStr("A")
        _, stats = index.subset_count_interval(
            interval[0], interval[1], left8, include_stats=True)
        assert stats["subtree_shortcuts"] > 0
        assert wrapped.countSubset("A", sources=left8) == sum_source_counts(
            standalone, "A", left8)
        ten["subtree_shortcut_probe"] = True

        # metadata isolation: edits never change provenance/BWT bytes
        prov_path = os.path.join(output, "provenance.json")
        bwt_path = os.path.join(output, "msbwt.npy")
        with open(prov_path, "rb") as fp:
            prov_before = fp.read()
        with open(bwt_path, "rb") as fp:
            bwt_before = fp.read()
        metadata.define_group("newgroup", ["sample00"])
        metadata.set_source_metadata("sample01", tissue="liver")
        metadata.save(output)
        with open(prov_path, "rb") as fp:
            prov_after = fp.read()
        with open(bwt_path, "rb") as fp:
            bwt_after = fp.read()
        assert prov_before == prov_after
        assert bwt_before == bwt_after
        reloaded = MultiSourceBWT.load(output, mmap=False)
        assert "newgroup" in reloaded.source_metadata.list_groups()
        ten["metadata_isolation_probe"] = True

        # catalog validation probes
        validation = report["validation_probes"] = {}
        catalog = SourceMetadataCatalog(manifest["sources"])
        try:
            catalog.define_group("bad", ["nope"])
            validation["unknown_source_rejected"] = False
        except SourceMetadataError:
            validation["unknown_source_rejected"] = True
        try:
            catalog._normalize_document({
                "format": "msbwt-source-metadata", "version": 99,
                "sources": {}, "groups": {}})
            validation["wrong_version_rejected"] = False
        except SourceMetadataError:
            validation["wrong_version_rejected"] = True
        bad_path = os.path.join(work, "bad_meta.json")
        with open(bad_path, "wb") as fp:
            fp.write(b"{not json")
        try:
            SourceMetadataCatalog.from_file(bad_path, manifest["sources"])
            validation["corrupt_file_rejected"] = False
        except SourceMetadataError:
            validation["corrupt_file_rejected"] = True
        assert all(validation.values())

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
        document = {
            "format": "msbwt-source-metadata",
            "version": 1,
            "sources": {
                "real-a": {"cohort": "case", "batch": "B0"},
                "real-b": {"cohort": "control", "batch": "B1"},
            },
            "groups": {"all": ["real-a", "real-b"],
                       "a_only": ["real-a"]},
        }
        meta_path = os.path.join(work, "labels.json")
        with open(meta_path, "wb") as fp:
            fp.write(json.dumps(document).encode("ascii"))
        a_bwt = f1.load_standalone(a_dir)
        b_bwt = f1.load_standalone(b_dir)
        real_merged = MultiSourceBWT.load(m_dir, mmap=False,
                                          source_metadata_path=meta_path)

        queries = f1.build_queries(f1.CANONICAL_READS_A,
                                   f1.CANONICAL_READS_B)
        queries.extend([b"$", b"A$", b"T$"])
        real_mismatches = []
        real_queries = 0
        for query in queries:
            expected_a = int(a_bwt.countOccurrencesOfSeq(query))
            expected_b = int(b_bwt.countOccurrencesOfSeq(query))
            real_queries += 1
            if real_merged.countGroup(query, "a_only") != expected_a:
                real_mismatches.append((query, "a_only"))
            if real_merged.countGroup(query, "all") != expected_a + expected_b:
                real_mismatches.append((query, "all"))
            if real_merged.countWhere(query, {"cohort": "case"}) != expected_a:
                real_mismatches.append((query, "where-case"))
            if real_merged.countWhere(query, {"batch": "B1"}) != expected_b:
                real_mismatches.append((query, "where-b1"))
            real_merged.source_metadata.save(m_dir)
            reloaded = MultiSourceBWT.load(m_dir, mmap=False)
            if reloaded.countGroup(query, "a_only") != expected_a:
                real_mismatches.append((query, "reload"))
        real["canonical_two_source"] = {
            "queries": real_queries,
            "mismatches": len(real_mismatches),
        }
        assert real_mismatches == []
        assert real_queries > 60

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
            catalog_r = merged_r.source_metadata
            catalog_r.define_group("g1", ["rd-0", "rd-1"])
            for i in range(source_count):
                catalog_r.set_source_metadata("rd-%d" % i,
                                              batch="B%d" % (i % 2))
            queries_r = set(["A", "C", "G", "T", "N", "$", "AA", "AC",
                             "NN", "A$", "T$"])
            for reads in reads_by_source.values():
                for read in reads:
                    for start in range(len(read)):
                        for end in range(start + 1, len(read) + 1):
                            queries_r.add(read[start:end])
            for query in queries_r:
                members = catalog_r.group_sources("g1")
                expected = sum(
                    int(standalone_r[sid].countOccurrencesOfSeq(query))
                    for sid in members)
                random_queries += 1
                if merged_r.countGroup(query, "g1") != expected:
                    random_mismatches.append({
                        "case": case_index, "query": query,
                        "reads_by_source": reads_by_source})
                members = catalog_r.select_where(batch="B0")
                expected = sum(
                    int(standalone_r[sid].countOccurrencesOfSeq(query))
                    for sid in members)
                random_queries += 1
                if merged_r.countWhere(query, {"batch": "B0"}) != expected:
                    random_mismatches.append({
                        "case": case_index, "query": query,
                        "kind": "where",
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
        subset_queries = 0
        for i in range(20):
            pattern = patterns[i * 13 % len(patterns)]
            interval = merged.findIndicesOfStr(pattern)
            probe_index.subset_count_interval(
                interval[0], interval[1], table[:5])
            subset_queries += 1
        perf["subset_queries"] = subset_queries
        perf["wall_seconds"] = round(time.time() - started, 3)
        assert subset_queries == 20

        # summary
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
        sys.stderr.write("usage: feature7_subset_group_evidence.py "
                         "OUTPUT.json\n")
        return 2
    report = run_evidence(sys.argv[1])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
