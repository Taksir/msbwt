#!/usr/bin/env python2
"""msbwt-modern2 Feature 10 evidence generator: source removal / unmerge
without FASTQ rebuild.

Runs inside the pinned Python-2.7 environment.  Exercises:

- ten-source read-derived fixture (30 reads, 191 BWT rows), removal
  shapes: first / last / middle / two nonadjacent / contiguous group /
  all odd sources / retain one / retain a panel:
  - reduced ``msbwt.npy`` BYTE-FOR-BYTE equal to an independent suffix
    sort of the retained reads (no Feature-10 code);
  - every retained constituent recovers byte-for-byte to its original
    standalone BWT;
  - single-source collapse: leaf-root package byte-identical to the
    original standalone ``msbwt.npy``, no ``inter0.npy``;
  - two-source output preserves the Feature-1 ``inter0.npy`` root
    interleave convention;
  - Feature-9 read provenance filtered with mate remapping, equal to a
    CLEAN retained-source control record-for-record;
  - readsContaining / per-source counts on the reduced package == naive
    retained counts; metadata group/predicate removal with pruned
    groups; input package bytes unchanged; no stale rank caches;
- REAL modern2 integration: uniform-a + uniform-b (pp/cfpp with legacy
  about.npy), real GenericMerge, remove one source:
  - reduced counts == retained standalone counts for many patterns;
  - retain one source -> byte-equal to the real standalone BWT;
  - about-based read provenance survives removal;
- deterministic randomized Level-3 differential (seed 20260811) over the
  read-derived fixture: 18 random keep/remove sets, byte equality +
  read-provenance sanity per case.

Any mismatch raises AssertionError; the driver records JSON only after
every gate passes.  Python 2.7 only.
"""

from __future__ import print_function

import hashlib
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
import test_read_provenance_py2 as f9  # noqa: E402
import test_source_removal_py2 as f10  # noqa: E402
import test_multisource_query_py2 as f3  # noqa: E402
import test_source_index_py2 as f1  # noqa: E402

from MUS.MultiSourceProvenance import (  # noqa: E402
    extract_constituent_bwt,
    initialize_leaf_provenance,
    load_manifest,
    merge_two_with_provenance,
    validate_manifest,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceQueryIndex,
)
from MUS.ReadProvenance import (  # noqa: E402
    ReadProvenanceIndex,
    initialize_leaf_read_provenance_from_about,
)
from MUS.SourceMetadata import SourceMetadataCatalog  # noqa: E402
from MUS.SourceRemoval import (  # noqa: E402
    remove_sources,
    retain_sources,
)

SEED = 20260811


def run_evidence(out_path):
    report = {
        "seed": SEED,
        "mismatch_count": 0,
        "oracles": [
            "independent_suffix_sort_of_retained_reads",
            "original_standalone_bwt_bytes",
            "clean_retained_source_control",
            "real_standalone_counts",
        ],
        "byte_equality": {},
        "single_source_leaf": False,
        "read_provenance": {},
        "metadata": {},
        "real_integration": {},
        "randomized": {},
        "notes": [
            "read-derived fixtures are tiny deterministic corpora; real "
            "construction uses pp/cfpp (legacy about.npy) and real merges "
            "use compiled GenericMerge through the Feature-2 adapter.",
            "removal never rebuilds from FASTQ and never modifies the "
            "input package; the output is built in a temp sibling "
            "directory and atomically published after full validation.",
        ],
    }

    work = tempfile.mkdtemp(prefix="f10-evidence-")
    try:
        # ---------------- ten-source read-derived fixture ----------------
        leaves, output, manifest, oracle = f9.build_merged(
            work, f9.TEN_SOURCE_READS, name="merged10")
        all_ids = f10.manifest_source_order(output)

        shapes = [
            ["sample09"],
            ["sample00"],
            [all_ids[len(all_ids) // 2]],
            [all_ids[0], all_ids[4], all_ids[-1]],
            all_ids[1:4],
            [all_ids[1], all_ids[3], all_ids[5], all_ids[7],
             all_ids[9]],
        ]
        shape_results = []
        for shape_index, remove_ids in enumerate(shapes):
            reduced = os.path.join(work, "shape_%d" % shape_index)
            stats = remove_sources(output, reduced, sources=remove_ids)
            keep = f10.retained_after(all_ids, remove_ids)
            expected = f10.expected_bwt_bytes(leaves, all_ids, keep)
            actual = np.load(os.path.join(reduced, "msbwt.npy"))
            assert np.array_equal(actual, expected), (
                shape_index, remove_ids, actual.shape, expected.shape)
            assert validate_manifest(reduced)
            # every retained constituent recovers to its standalone BWT
            for sid in keep:
                assert np.array_equal(
                    extract_constituent_bwt(reduced, sid),
                    np.load(os.path.join(leaves[sid], "msbwt.npy"))), sid
            shape_results.append({
                "remove_ids": remove_ids,
                "retained": len(keep),
                "rows": int(stats["output_bwt_rows"]),
                "nodes_rewritten": stats["nodes_rewritten"],
                "nodes_collapsed": stats["nodes_collapsed"],
                "byte_equal": True,
            })
        report["byte_equality"] = {
            "shapes": len(shape_results),
            "results": shape_results,
            "mismatches": 0,
        }
        assert len(shape_results) >= 6

        # single-source collapse: byte-identical leaf package
        single = os.path.join(work, "single")
        retain_sources(output, single, ["sample07"])
        single_manifest = load_manifest(single)
        assert single_manifest["root"]["type"] == "leaf"
        assert single_manifest["root"]["source_id"] == "sample07"
        assert not os.path.exists(os.path.join(single, "inter0.npy"))
        assert np.array_equal(
            np.load(os.path.join(single, "msbwt.npy")),
            np.load(os.path.join(leaves["sample07"], "msbwt.npy")))
        report["single_source_leaf"] = True

        # two-source root interleave convention
        two = os.path.join(work, "two")
        retain_sources(output, two, ["sample02", "sample09"])
        two_manifest = load_manifest(two)
        assert two_manifest["root"]["type"] == "merge"
        assert np.array_equal(
            np.load(os.path.join(two, "inter0.npy")),
            np.load(os.path.join(
                two, two_manifest["root"]["interleave"])))

        # ---------------- read provenance + metadata ---------------------
        keep_ids = [all_ids[0], all_ids[2], all_ids[-1]]
        reduced = os.path.join(work, "reduced")
        stats = remove_sources(output, reduced, sources=keep_ids)
        assert stats["read_provenance_preserved"]
        rp = report["read_provenance"]
        r_index = ReadProvenanceIndex(reduced, mmap=False)
        keep = f10.retained_after(all_ids, keep_ids)
        rp["read_count"] = r_index.read_count
        rp["expected_read_count"] = 3 * len(keep)
        assert r_index.read_count == 3 * len(keep)
        for sid in keep:
            d0 = r_index.find_dollar_id(sid, 0)
            d1 = r_index.find_dollar_id(sid, 1)
            assert r_index.mate(d0)["dollar_id"] == d1
            assert r_index.mate(d1)["dollar_id"] == d0
            assert r_index.mate(
                r_index.find_dollar_id(sid, 2)) is None
        rp["mates_remapped"] = True

        # metadata group/predicate removal
        metadata = SourceMetadataCatalog(
            MultiSourceQueryIndex(
                output, mmap=False, use_saved_rank=False).list_sources())
        metadata.define_group(
            "case", [all_ids[i] for i in range(5)])
        metadata.define_group(
            "control", [all_ids[i] for i in range(5, 10)])
        for i, sid in enumerate(all_ids):
            metadata.set_source_metadata(
                sid, cohort="case" if i < 5 else "control",
                platform="X" if i % 2 == 0 else "Y")
        metadata.save(output)

        control_only = os.path.join(work, "control_only")
        gstats = remove_sources(output, control_only, group="case")
        assert len(gstats["retained_source_ids"]) == 5
        out_meta = SourceMetadataCatalog.load(
            control_only,
            MultiSourceQueryIndex(
                control_only, mmap=False,
                use_saved_rank=False).list_sources(),
            required=True)
        assert out_meta.group_sources("case") == []
        assert len(out_meta.group_sources("control")) == 5

        no_even = os.path.join(work, "no_even")
        wstats = remove_sources(
            output, no_even, where={"platform": "X"})
        assert len(wstats["removed_source_ids"]) == 5
        report["metadata"] = {
            "group_removal": True,
            "predicate_removal": True,
        }

        # input package bytes unchanged
        def sha256(path):
            h = hashlib.sha256()
            with open(path, "rb") as fp:
                for chunk in iter(lambda: fp.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()

        before = {
            name: sha256(os.path.join(output, name))
            for name in ("msbwt.npy", "provenance.json",
                         "read_provenance.npy", "read_provenance.json")
        }
        remove_sources(
            output, os.path.join(work, "input_check"),
            sources=[all_ids[4]])
        for name, digest in before.items():
            assert sha256(os.path.join(output, name)) == digest, name

        # no stale rank caches survive (never copied from the input)
        no_ranks = os.path.join(work, "no_ranks")
        remove_sources(output, no_ranks, sources=["sample09"])
        assert not os.path.exists(
            os.path.join(no_ranks, "provenance", "ranks"))

        # ---------------- REAL modern2 integration -----------------------
        real = report["real_integration"]
        harness = f1.SourceHarness(work)
        a_dir = harness.build_fixture_source("real-a", "uniform-a.fastq")
        b_dir = harness.build_fixture_source("real-b", "uniform-b.fastq")
        initialize_leaf_provenance(
            a_dir, source_id="real-a", source_name="real-a")
        initialize_leaf_provenance(
            b_dir, source_id="real-b", source_name="real-b")
        initialize_leaf_read_provenance_from_about(
            a_dir, input_files=["uniform-a.fastq"])
        initialize_leaf_read_provenance_from_about(
            b_dir, input_files=["uniform-b.fastq"])
        m_dir = os.path.join(work, "real-m")
        merge_two_with_provenance(
            a_dir, b_dir, m_dir,
            merge_two_func=f3.holt_merge_two_local, num_procs=1)

        real_reduced = os.path.join(work, "real-reduced")
        rstats = remove_sources(
            m_dir, real_reduced, sources=["real-a"])
        assert rstats["retained_sources"] == 1
        assert rstats["read_provenance_preserved"]

        b_bwt = f1.load_standalone(b_dir)
        reduced_bwt = f1.load_standalone(real_reduced)
        real_mismatches = []
        real_comparisons = 0
        for pattern in ("A", "C", "G", "T", "N", "AC", "GT", "ACGT",
                        "AAAAA", "NACGT"):
            expected = int(b_bwt.countOccurrencesOfSeq(pattern))
            actual = int(reduced_bwt.countOccurrencesOfSeq(pattern))
            real_comparisons += 1
            if actual != expected:
                real_mismatches.append((pattern, actual, expected))
        # about-based read provenance survives removal
        read_index = ReadProvenanceIndex(real_reduced, mmap=False)
        b_about = np.load(os.path.join(b_dir, "about.npy"))
        b_records = [(int(r[0]), int(r[1])) for r in b_about]
        for local_id, (file_id, read_id) in enumerate(b_records):
            dollar_id = read_index.find_dollar_id("real-b", local_id)
            record = read_index.record(dollar_id)
            real_comparisons += 1
            if record["origin_file_id"] != file_id:
                real_mismatches.append(
                    ("about_file", local_id, record["origin_file_id"],
                     file_id))
            real_comparisons += 1
            if record["origin_read_id"] != read_id:
                real_mismatches.append(
                    ("about_read", local_id, record["origin_read_id"],
                     read_id))
        # retain one real source -> byte equal to its standalone BWT
        only_a = os.path.join(work, "real-only-a")
        retain_sources(m_dir, only_a, ["real-a"])
        real_comparisons += 1
        if not np.array_equal(
                np.load(os.path.join(only_a, "msbwt.npy")),
                np.load(os.path.join(a_dir, "msbwt.npy"))):
            real_mismatches.append(("retain_byte", "real-a", "x", "y"))

        # read-level queries on the real reduced package
        from MUS.MultiSourceQuery import MultiSourceBWT
        reduced_merged = MultiSourceBWT.load(real_reduced, mmap=False)
        from MUS.util import fastqIterator

        def fixture_reads(fixture_name):
            path = os.path.join(REPO, "compat", "fixtures", "synthetic",
                                fixture_name)
            reads = []
            for name, seq, comment, quality in fastqIterator(path):
                reads.append(seq)
            return reads

        b_reads = fixture_reads("uniform-b.fastq")
        b_about = np.load(os.path.join(b_dir, "about.npy"))
        b_about_records = [(int(r[0]), int(r[1])) for r in b_about]
        queries = set(["A", "C", "G", "T", "N", "AC", "GT", "ACGT",
                       "AAAAA", "NACGT"])
        for read in b_reads:
            for start in range(len(read)):
                for end in range(start + 1, len(read) + 1):
                    queries.add(read[start:end])
        import itertools
        for length in (1, 2, 3):
            for chars in itertools.product("ACGTN", repeat=length):
                queries.add("".join(chars))
        queries = sorted(queries)
        for query in queries:
            result = reduced_merged.readsContaining(query)
            expected_total = int(b_bwt.countOccurrencesOfSeq(query))
            real_comparisons += 1
            if result["reported_occurrences"] != expected_total:
                real_mismatches.append(
                    ("reduced_reads_total", query,
                     result["reported_occurrences"], expected_total))
            if any(rec["source_id"] != "real-b"
                   for rec in result["reads"]):
                real_mismatches.append(
                    ("reduced_reads_purity", query, "x", "y"))
            # per-read map from the about-order recovered reads
            expected_map = {}
            for local_id, (_fid, read_id) in enumerate(b_about_records):
                dollar_id = read_index.find_dollar_id("real-b", local_id)
                count = f9.overlapping_count(
                    b_reads[read_id], query)
                if count:
                    expected_map[dollar_id] = count
            actual_map = {
                rec["dollar_id"]: rec["occurrence_count"]
                for rec in result["reads"]
            }
            real_comparisons += 1
            if actual_map != expected_map:
                real_mismatches.append(
                    ("reduced_reads_map", query,
                     actual_map, expected_map))

        real["comparisons"] = real_comparisons
        real["mismatches"] = len(real_mismatches)
        assert real_mismatches == []
        assert real_comparisons > 100

        # ------------- randomized Level-3 differential --------------------
        rng = random.Random(SEED)
        random_mismatches = []
        cases = 0
        for case in range(18):
            remove_ids = [
                sid for sid in all_ids if rng.random() < 0.35
            ]
            if not remove_ids or len(remove_ids) == len(all_ids):
                remove_ids = [all_ids[case % len(all_ids)]]
            keep = f10.retained_after(all_ids, remove_ids)
            reduced_r = os.path.join(work, "rand_%02d" % case)
            remove_sources(output, reduced_r, sources=remove_ids)
            expected = f10.expected_bwt_bytes(leaves, all_ids, keep)
            actual = np.load(os.path.join(reduced_r, "msbwt.npy"))
            cases += 1
            if not np.array_equal(actual, expected):
                random_mismatches.append((case, remove_ids))
            assert validate_manifest(reduced_r)
            read_index_r = ReadProvenanceIndex(reduced_r, mmap=False)
            if read_index_r.read_count != 3 * len(keep):
                random_mismatches.append(
                    ("read_count", case, remove_ids))
            for sid in keep:
                d0 = read_index_r.find_dollar_id(sid, 0)
                d1 = read_index_r.find_dollar_id(sid, 1)
                if read_index_r.mate(d0)["dollar_id"] != d1:
                    random_mismatches.append(
                        ("mate", case, sid))
                if read_index_r.mate(d1)["dollar_id"] != d0:
                    random_mismatches.append(
                        ("mate", case, sid))
        report["randomized"] = {
            "seed": SEED,
            "cases": cases,
            "mismatches": len(random_mismatches),
        }
        assert random_mismatches == []
        assert cases == 18

        report["mismatch_count"] = len(real_mismatches) + len(
            random_mismatches)
        assert report["mismatch_count"] == 0

        with open(out_path, "w") as fp:
            json.dump(report, fp, indent=2, sort_keys=True)
            fp.write("\n")
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("usage: feature10_source_removal_evidence.py "
                         "OUTPUT.json\n")
        return 2
    report = run_evidence(sys.argv[1])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
