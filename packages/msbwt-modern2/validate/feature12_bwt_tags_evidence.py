#!/usr/bin/env python2
"""msbwt-modern2 Feature 12 evidence generator: generic BWT-aligned tag
arrays.

Runs inside the pinned Python-2.7 environment.  Exercises:

- ten-source read-derived fixture (191 BWT rows) with the strongest
  row-identity tag ``row_id`` (``tag[x] = source_order*10000 + local_row``
  known independently from the naive suffix rows):
  - two-way and balanced 10-source merges: ``T_final[x]`` equals the
    independently walked merged row identity for EVERY row
    (``unpack_interleave`` tree walk, no BWTTags code);
  - one-sided tags: merge without a declared missing value fails BEFORE
    the BWT merge; with a declared missing value the missing source rows
    are filled exactly;
  - retrofit via ``build_tag_from_leaf_arrays`` equals the merge-produced
    tag element-for-element (BWT bytes unchanged);
  - Feature-10 removal: ``T_reduced == T_original[keep_mask]`` for every
    tag; single-source removal output equals the original leaf array;
  - query lifecycle: whole-index exact interval tag values == ``T[l:r]``;
    source/subset/group/where filtered tag values == independently
    projected rows; scalar tagValueCounts == naive counting; vector-tag
    counts rejected;
- deterministic randomized Level-3 differential (seed 20260811): 18
  random tagged merges and removals, row-identity equality per case.

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
import test_bwt_tags_py2 as f12  # noqa: E402

from MUS.BWTTags import (  # noqa: E402
    BWTTagError,
    BWTTagStore,
    attach_tag,
    remove_tag,
    tags_exist,
)
from MUS.MultiSourceProvenance import (  # noqa: E402
    load_manifest,
    merge_many_balanced,
    merge_two_with_provenance,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)
from MUS.SourceMetadata import SourceMetadataCatalog  # noqa: E402
from MUS.SourceRemoval import remove_sources  # noqa: E402

SEED = 20260811


def run_evidence(out_path):
    report = {
        "seed": SEED,
        "mismatch_count": 0,
        "oracles": [
            "independent_row_identity_tree_walk",
            "independent_suffix_sort",
            "naive_per_row_value_counts",
        ],
        "merge_lifecycle": {},
        "one_sided_policies": {},
        "retrofit": {},
        "removal": {},
        "queries": {},
        "randomized": {},
        "notes": [
            "read-derived fixtures are tiny deterministic corpora; tag "
            "arrays are ordinary mmap-able .npy files under bwt_tags/, "
            "with the registry binding filename (hash of the logical "
            "name), dtype, tail shape, description, and missing-value "
            "policy.",
            "tags never change BWT bytes; merge/retrofit/removal keep "
            "tag[x] traveling exactly with BWT[x].",
        ],
    }

    work = tempfile.mkdtemp(prefix="f12-evidence-")
    try:
        # ---------------- ten-source tagged fixture -----------------------
        leaves = {}
        for sid, reads in f9.TEN_SOURCE_READS.items():
            leaf = f9.make_read_derived_leaf(work, sid, reads)
            leaves[sid] = leaf
        all_order = {sid: i for i, sid in enumerate(leaves)}
        for sid, leaf in leaves.items():
            attach_tag(
                leaf, "row_id",
                f12.row_identity_tag(leaf, all_order),
                description="independent row identity")
        output = os.path.join(work, "merged10")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f9.read_derived_merge)

        merged = report["merge_lifecycle"]
        store = BWTTagStore(output)
        expected = f12.expected_merged_row_identity(
            output, leaves, all_order)
        mismatches = []
        comparisons = 0
        for x in range(expected.shape[0]):
            comparisons += 1
            if int(store.array("row_id")[x]) != int(expected[x]):
                mismatches.append(("merge_row", x,
                                   int(store.array("row_id")[x]),
                                   int(expected[x])))
        merged["rows"] = expected.shape[0]
        merged["comparisons"] = comparisons
        merged["mismatches"] = len(mismatches)
        assert merged["rows"] == 191
        assert mismatches == []

        # two-way merge also preserves the tag exactly
        two_leaves = {}
        for sid, reads in (("A", ["ACGTAC", "GATTACA", "AAAA"]),
                           ("B", ["TTTT", "GCGTAC"])):
            leaf = f9.make_read_derived_leaf(work, sid, reads)
            two_leaves[sid] = leaf
        two_order = {sid: i for i, sid in enumerate(two_leaves)}
        for sid, leaf in two_leaves.items():
            attach_tag(leaf, "row_id",
                       f12.row_identity_tag(leaf, two_order))
        two_out = os.path.join(work, "two")
        merge_two_with_provenance(
            two_leaves["A"], two_leaves["B"], two_out,
            merge_two_func=f9.read_derived_merge)
        two_expected = f12.expected_merged_row_identity(
            two_out, two_leaves, two_order)
        comparisons += two_expected.shape[0]
        if not np.array_equal(
                BWTTagStore(two_out).array("row_id"), two_expected):
            mismatches.append(("two_way", "x", "y", "z"))
        merged["two_way_exact"] = True

        # ---------------- one-sided tag policies --------------------------
        one = report["one_sided_policies"]
        leaf_a = f9.make_read_derived_leaf(
            work, "OA", ["ACGTAC", "AAAA"])
        leaf_b = f9.make_read_derived_leaf(
            work, "OB", ["TTTT", "CCCC"])
        rows_a = len(f9.load_rows(leaf_a))
        attach_tag(leaf_a, "code", np.zeros(rows_a, dtype=np.uint8))
        called = [False]

        def should_not_run(*args, **kwargs):
            called[0] = True

        try:
            merge_two_with_provenance(
                leaf_a, leaf_b, os.path.join(work, "bad"),
                merge_two_func=should_not_run)
            raise AssertionError("one-sided tag without missing value "
                                 "was not rejected")
        except BWTTagError:
            pass
        assert not called[0]
        assert not os.path.exists(os.path.join(work, "bad", "msbwt.npy"))
        one["without_missing"] = True

        remove_tag(leaf_a, "code")
        attach_tag(leaf_a, "opt",
                   np.asarray(list(range(rows_a)), dtype=np.uint8),
                   missing_value=0)
        one_out = os.path.join(work, "one_merged")
        merge_two_with_provenance(
            leaf_a, leaf_b, one_out,
            merge_two_func=f9.read_derived_merge)
        ostore = BWTTagStore(one_out)
        omanifest = load_manifest(one_out)
        b_rows = [x for x in range(ostore.array("opt").shape[0])
                  if f12.row_source(one_out, omanifest, x) == "OB"]
        a_rows = [x for x in range(ostore.array("opt").shape[0])
                  if f12.row_source(one_out, omanifest, x) == "OA"]
        assert sorted(ostore.array("opt")[a_rows].tolist()) == \
            list(range(rows_a))
        assert set(ostore.array("opt")[b_rows].tolist()) == set([0])
        one["with_missing"] = True

        # ---------------- retrofit ---------------------------------------
        retrofit = report["retrofit"]
        retrofit_out = os.path.join(work, "retrofit_copy")
        shutil.copytree(output, retrofit_out)
        remove_tag(retrofit_out, "row_id")
        assert not tags_exist(retrofit_out)
        bwt_before = hashlib.sha256(open(
            os.path.join(retrofit_out, "msbwt.npy"), "rb").read()).hexdigest()
        arrays_by_source = {}
        for sid, leaf in leaves.items():
            fname = os.path.basename(
                BWTTagStore(leaf).schema("row_id")["filename"])
            arrays_by_source[sid] = os.path.join(leaf, "bwt_tags", fname)
        from MUS.BWTTags import build_tag_from_leaf_arrays
        build_tag_from_leaf_arrays(
            retrofit_out, "row_id", arrays_by_source)
        bwt_after = hashlib.sha256(open(
            os.path.join(retrofit_out, "msbwt.npy"), "rb").read()).hexdigest()
        retrofit["bwt_unchanged"] = bwt_before == bwt_after
        assert bwt_before == bwt_after
        rstore = BWTTagStore(retrofit_out)
        retrofit["rows"] = rstore.bwt_length
        retrofit["mismatches"] = 0
        for x in range(rstore.bwt_length):
            comparisons += 1
            if int(rstore.array("row_id")[x]) != int(expected[x]):
                mismatches.append(("retrofit_row", x,
                                   int(rstore.array("row_id")[x]),
                                   int(expected[x])))
        retrofit["comparisons"] = rstore.bwt_length
        assert mismatches == []

        # ---------------- Feature-10 removal ------------------------------
        removal = report["removal"]
        keep_set = set(s for s in f9.TEN_SOURCE_READS
                       if s not in ("sample00", "sample02", "sample09"))
        omanifest = load_manifest(output)
        mask = np.asarray(
            [f12.row_source(output, omanifest, x) in keep_set
             for x in range(store.bwt_length)],
            dtype=np.bool_)
        reduced = os.path.join(work, "reduced")
        stats = remove_sources(
            output, reduced,
            sources=["sample00", "sample02", "sample09"])
        assert stats["bwt_tags_preserved"]
        assert stats["bwt_tag_count"] == 1
        rstore = BWTTagStore(reduced)
        removal["rows"] = rstore.bwt_length
        removal["mismatches"] = 0
        for x in range(rstore.bwt_length):
            comparisons += 1
            if int(rstore.array("row_id")[x]) != int(
                    store.array("row_id")[mask][x]):
                mismatches.append(("removal_row", x,
                                   int(rstore.array("row_id")[x]),
                                   int(store.array("row_id")[mask][x])))
        # single-source removal equals the original leaf array
        single = os.path.join(work, "single")
        remove_sources(output, single, sources=[
            sid for sid in f9.TEN_SOURCE_READS if sid != "sample07"])
        removal["single_source_equals_leaf"] = np.array_equal(
            BWTTagStore(single).array("row_id"),
            f12.row_identity_tag(leaves["sample07"], all_order))
        assert removal["single_source_equals_leaf"]
        removal["comparisons"] = rstore.bwt_length
        assert mismatches == []

        # ---------------- query lifecycle --------------------------------
        queries = report["queries"]
        index = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        wrapped = MultiSourceBWT(None, index, bwt_tags=store)
        oracle = f9.OracleReadIdentity(
            output,
            {sid: leaves[sid] for sid in leaves},
            f9.TEN_SOURCE_READS)
        wrapped.bwt = f9.OracleBWTAdapter(
            oracle, output, omanifest)
        qcomparisons = 0
        qmismatches = []
        for pattern in ("A", "AC", "CGT", "AAAA", "N", "AAGGTT"):
            low, high = f12.naive_interval(output, pattern)
            result = wrapped.tagValues(pattern, "row_id")
            qcomparisons += 1
            if result["value_count"] != high - low:
                qmismatches.append(("interval_count", pattern))
            qcomparisons += 1
            if not np.array_equal(
                    result["values"], store.array("row_id")[low:high]):
                qmismatches.append(("interval_values", pattern))
            for sid in ("sample00", "sample03", "sample09"):
                sresult = wrapped.tagValues(pattern, "row_id", source=sid)
                expected_rows = [
                    x for x in range(low, high)
                    if f12.row_source(output, omanifest, x) == sid
                ]
                qcomparisons += 1
                if sresult["value_count"] != len(expected_rows):
                    qmismatches.append(("source_count", pattern, sid))
                qcomparisons += 1
                if not np.array_equal(
                        sresult["values"],
                        store.array("row_id")[expected_rows]):
                    qmismatches.append(("source_values", pattern, sid))
        # scalar value counts vs naive counting
        pattern = "AC"
        low, high = f12.naive_interval(output, pattern)
        values = store.array("row_id")[low:high]
        unique, counts = np.unique(values, return_counts=True)
        counts_result = wrapped.tagValueCounts(pattern, "row_id")
        table = {item["value"]: item["count"]
                 for item in counts_result["counts"]}
        qcomparisons += 1
        if table != {int(u): int(c) for u, c in zip(unique, counts)}:
            qmismatches.append(("counts", pattern))
        # subset/group/where selection equals independently projected rows
        metadata = SourceMetadataCatalog(index.list_sources())
        metadata.define_group(
            "case", ["sample00", "sample01", "sample02"])
        for sid in ("sample00", "sample01", "sample02"):
            metadata.set_source_metadata(sid, cohort="case")
        wrapped2 = MultiSourceBWT(
            None, index, source_metadata=metadata, bwt_tags=store)
        wrapped2.bwt = wrapped.bwt
        for pattern in ("A", "AC", "CGT"):
            low, high = f12.naive_interval(output, pattern)
            for kind, selector in (
                ("subset", {"sources": ["sample00", "sample02"]}),
                ("group", {"group": "case"}),
                ("where", {"where": {"cohort": "case"}}),
            ):
                sresult = wrapped2.tagValues(
                    pattern, "row_id", **selector)
                if kind == "subset":
                    selected = set(selector["sources"])
                else:
                    selected = set(["sample00", "sample01", "sample02"])
                expected_rows = [
                    x for x in range(low, high)
                    if f12.row_source(output, omanifest, x) in selected
                ]
                qcomparisons += 1
                if sresult["value_count"] != len(expected_rows):
                    qmismatches.append(("selection_count",
                                        pattern, kind))
                qcomparisons += 1
                if not np.array_equal(
                        sresult["values"],
                        store.array("row_id")[expected_rows]):
                    qmismatches.append(("selection_values",
                                        pattern, kind))
        queries["comparisons"] = qcomparisons
        queries["mismatches"] = len(qmismatches)
        assert qmismatches == []
        assert qcomparisons > 50

        # ------------- randomized Level-3 differential --------------------
        rng = random.Random(SEED)
        random_mismatches = []
        cases = 0
        for case in range(18):
            rleaves = {}
            n_sources = rng.randint(2, 5)
            for i in range(n_sources):
                sid = "R%02d_S%d" % (case, i)
                n_reads = rng.randint(1, 4)
                reads = []
                alphabet = "ACGTN"
                for _ in range(n_reads):
                    length = rng.randint(1, 8)
                    if rng.random() < 0.3 and reads:
                        reads.append(reads[rng.randrange(len(reads))])
                        continue
                    reads.append("".join(
                        rng.choice(alphabet) for _ in range(length)))
                leaf = f9.make_read_derived_leaf(work, sid, reads)
                rleaves[sid] = leaf
            rorder = {sid: i for i, sid in enumerate(rleaves)}
            for sid, leaf in rleaves.items():
                attach_tag(leaf, "row_id",
                           f12.row_identity_tag(leaf, rorder))
            rout = os.path.join(work, "rand_%02d" % case)
            merge_many_balanced(
                list(rleaves.values()), rout,
                merge_two_func=f9.read_derived_merge)
            rstore = BWTTagStore(rout)
            rexpected = f12.expected_merged_row_identity(
                rout, rleaves, rorder)
            cases += 1
            if not np.array_equal(rstore.array("row_id"), rexpected):
                random_mismatches.append(("merge", case))
            remove_ids = [
                sid for sid in rleaves if rng.random() < 0.4
            ]
            if not remove_ids or len(remove_ids) == len(rleaves):
                remove_ids = [list(rleaves)[0]]
            rred = os.path.join(work, "randred_%02d" % case)
            rstats = remove_sources(rout, rred, sources=remove_ids)
            if not rstats["bwt_tags_preserved"]:
                random_mismatches.append(("remove_stats", case))
            rrstore = BWTTagStore(rred)
            rrexpected = f12.expected_merged_row_identity(
                rred, rleaves, rorder)
            if not np.array_equal(
                    rrstore.array("row_id"), rrexpected):
                random_mismatches.append(("remove", case))
        report["randomized"] = {
            "seed": SEED,
            "cases": cases,
            "mismatches": len(random_mismatches),
        }
        assert random_mismatches == []
        assert cases == 18

        report["mismatch_count"] = (
            len(mismatches) + len(qmismatches) + len(random_mismatches))
        assert report["mismatch_count"] == 0

        with open(out_path, "w") as fp:
            json.dump(report, fp, indent=2, sort_keys=True)
            fp.write("\n")
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("usage: feature12_bwt_tags_evidence.py "
                         "OUTPUT.json\n")
        return 2
    report = run_evidence(sys.argv[1])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
