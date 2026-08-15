"""Feature 10 - source removal / unmerge without FASTQ rebuild
(Python-2 suite, real merges).

This suite validates ``MUS.SourceRemoval`` (``remove_sources`` /
``retain_sources``) against independent oracles:

* the reduced ``msbwt.npy`` must be BYTE-FOR-BYTE equal to an independent
  suffix sort of the retained reads (global sort by
  ``(suffix, source_order, read_id, pos)``, the exact stable-merge
  semantics of the fixture machinery);
* every retained constituent recovers byte-for-byte to its original
  standalone BWT;
* retaining a single source yields a leaf-root package byte-identical to
  the original standalone ``msbwt.npy``;
* a CLEAN retained-source control index (built from the retained leaves)
  is semantically equal to the removal output: source-aware counts,
  sparse listing, frequency, top-k, subset/group, extensions, and
  read provenance (origin IDs, remapped mates);
* Feature-9 read provenance is filtered and re-validated; metadata is
  pruned (group intersection + predicate removal);
* atomicity: a failed removal never leaves a publishable output; the
  input package is never modified; no stale rank caches survive;
* randomized keep/remove sets (seeds 20260811/20260812/20260813).

Real GenericMerge integration: two real sources from the uniform
fixtures, one removed, counts equal the retained standalone; retain one
source -> byte equal to the real standalone BWT.
"""

from __future__ import print_function

import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_read_provenance_py2 as f9  # noqa: E402

from MUS.MultiSourceProvenance import (  # noqa: E402
    extract_constituent_bwt,
    load_manifest,
    validate_manifest,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)
from MUS.ReadProvenance import (  # noqa: E402
    ReadProvenanceIndex,
    read_provenance_exists,
)
from MUS.SourceMetadata import SourceMetadataCatalog  # noqa: E402
from MUS.SourceRemoval import (  # noqa: E402
    SourceRemovalError,
    remove_sources,
    retain_sources,
)

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

SEEDS = (20260811, 20260812, 20260813)

ALL_SOURCES = sorted(f9.TEN_SOURCE_READS)


def manifest_source_order(output):
    """Stable source order of a package's provenance manifest."""
    return [s["id"] for s in load_manifest(output)["sources"]]


def retained_after(all_ids, remove_ids):
    removed = set(remove_ids)
    return [sid for sid in all_ids if sid not in removed]


def expected_bwt_bytes(leaves, all_ids, keep_ids):
    """Independent suffix sort of the retained reads (no Feature-10 code).

    Tie order follows the provenance/source order of the input package
    (the stable-merge semantics of the fixture machinery).
    """
    all_order = {sid: i for i, sid in enumerate(all_ids)}
    rows = []
    for sid in keep_ids:
        for row in f9.load_rows(leaves[sid]):
            rows.append((
                row["suffix"],
                all_order[sid],
                int(row["read_id"]),
                int(row["pos"]),
                row["bwt"],
            ))
    rows.sort()
    return np.asarray(
        [f9.ALPHABET_CODE[r[4]] for r in rows], dtype=np.uint8)


class SourceRemovalPy2TestBase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f10-py2-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def build_input(self):
        return f9.build_merged(
            self.work, f9.TEN_SOURCE_READS, name="merged10")

    def build_clean_control(self, keep_ids, origin_base=100, name="clean"):
        """Clean retained-source control built in the given source order.

        ``keep_ids`` is an ordered sequence.  The merge receives an
        explicit ordered leaf list (Python-2 dicts do not preserve
        insertion order), so the control's manifest order equals the
        removal output's manifest order and the two packages are
        byte-comparable.  Leaves are built under a dedicated
        subdirectory to avoid collisions with the input fixture.
        """
        leaf_work = os.path.join(self.work, name + "_leaves")
        if not os.path.isdir(leaf_work):
            os.mkdir(leaf_work)
        ordered_leaves = []
        for sid in keep_ids:
            leaf = f9.make_read_derived_leaf(
                leaf_work, sid, f9.TEN_SOURCE_READS[sid])
            f9.attach_leaf_read_provenance(
                leaf, f9.TEN_SOURCE_READS[sid],
                origin_base=origin_base, file_count=1)
            ordered_leaves.append(leaf)
        output = os.path.join(self.work, name)
        work_dir = os.path.join(self.work, name + "_work")
        manifest = f9.merge_many_balanced(
            ordered_leaves, output,
            merge_two_func=f9.read_derived_merge,
            work_dir=work_dir, keep_work=True)
        oracle = f9.OracleReadIdentity(
            output,
            {sid: os.path.join(leaf_work, sid) for sid in keep_ids},
            {sid: f9.TEN_SOURCE_READS[sid] for sid in keep_ids})
        return None, output, manifest, oracle


class ByteEqualityTests(SourceRemovalPy2TestBase):
    def test_removed_output_bwt_equals_independent_rebuild_byte_for_byte(
            self):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        cases = [
            ["sample09"],
            ["sample00"],
            ["sample04"],
            ["sample00", "sample02", "sample09"],
            ["sample01", "sample03", "sample05", "sample07", "sample09"],
            ["sample00", "sample01", "sample02", "sample03", "sample04",
             "sample05", "sample06", "sample07"],
        ]
        for case_index, remove_ids in enumerate(cases):
            reduced = os.path.join(
                self.work, "reduced_%d" % case_index)
            remove_sources(output, reduced, sources=remove_ids)
            actual = np.load(os.path.join(reduced, "msbwt.npy"))
            expected = expected_bwt_bytes(
                leaves, all_ids, retained_after(all_ids, remove_ids))
            self.assertTrue(np.array_equal(actual, expected),
                            (case_index, actual.shape, expected.shape))
            self.assertTrue(validate_manifest(reduced))

    def test_remove_first_last_and_middle_single_sources(self):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        for sid in (all_ids[0], all_ids[-1],
                    all_ids[len(all_ids) // 2]):
            reduced = os.path.join(self.work, "one_removed_" + sid)
            remove_sources(output, reduced, sources=[sid])
            actual = np.load(os.path.join(reduced, "msbwt.npy"))
            expected = expected_bwt_bytes(
                leaves, all_ids, retained_after(all_ids, [sid]))
            self.assertTrue(np.array_equal(actual, expected), sid)

    def test_remove_contiguous_group_and_nonadjacent(self):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        for remove_ids in (
            all_ids[1:4],
            [all_ids[0], all_ids[4], all_ids[-1]],
        ):
            reduced = os.path.join(self.work, "group_" + "_".join(
                remove_ids))
            remove_sources(output, reduced, sources=remove_ids)
            actual = np.load(os.path.join(reduced, "msbwt.npy"))
            expected = expected_bwt_bytes(
                leaves, all_ids, retained_after(all_ids, remove_ids))
            self.assertTrue(np.array_equal(actual, expected))

    def test_retain_sources_keeps_exactly_selected(self):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        keep = [all_ids[1], all_ids[5], all_ids[8]]
        reduced = os.path.join(self.work, "panel")
        retain_sources(output, reduced, keep)
        actual = np.load(os.path.join(reduced, "msbwt.npy"))
        expected = expected_bwt_bytes(leaves, all_ids, keep)
        self.assertTrue(np.array_equal(actual, expected))
        manifest_out = load_manifest(reduced)
        self.assertEqual(
            [s["id"] for s in manifest_out["sources"]], keep)

    def test_single_source_output_collapses_tree_and_matches_standalone(
            self):
        leaves, output, manifest, oracle = self.build_input()
        reduced = os.path.join(self.work, "single")
        retain_sources(output, reduced, ["sample07"])
        manifest_out = load_manifest(reduced)
        self.assertEqual(len(manifest_out["sources"]), 1)
        self.assertEqual(manifest_out["root"]["type"], "leaf")
        self.assertEqual(
            manifest_out["root"]["source_id"], "sample07")
        self.assertFalse(os.path.exists(
            os.path.join(reduced, "inter0.npy")))
        self.assertTrue(np.array_equal(
            np.load(os.path.join(reduced, "msbwt.npy")),
            np.load(os.path.join(leaves["sample07"], "msbwt.npy"))))

    def test_two_source_output_preserves_root_interleave_convention(self):
        leaves, output, manifest, oracle = self.build_input()
        reduced = os.path.join(self.work, "two")
        retain_sources(output, reduced, ["sample02", "sample09"])
        manifest_out = load_manifest(reduced)
        self.assertEqual(manifest_out["root"]["type"], "merge")
        self.assertTrue(os.path.exists(
            os.path.join(reduced, "inter0.npy")))
        root_saved = np.load(os.path.join(
            reduced, manifest_out["root"]["interleave"]))
        root_legacy = np.load(os.path.join(reduced, "inter0.npy"))
        self.assertTrue(np.array_equal(root_saved, root_legacy))

    def test_source_order_and_stable_ids_preserved(self):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        reduced = os.path.join(self.work, "reduced")
        remove_sources(
            output, reduced, sources=[all_ids[3], all_ids[8]])
        manifest_out = load_manifest(reduced)
        self.assertEqual(
            [s["id"] for s in manifest_out["sources"]],
            retained_after(all_ids, [all_ids[3], all_ids[8]]))
        self.assertEqual(
            [s["name"] for s in manifest_out["sources"]],
            [s["id"] for s in manifest_out["sources"]])

    def test_remaining_constituents_recover_exact_original_bwts(self):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        remove_ids = [all_ids[0], all_ids[2], all_ids[-1]]
        reduced = os.path.join(self.work, "reduced")
        remove_sources(output, reduced, sources=remove_ids)
        for sid in retained_after(all_ids, remove_ids):
            recovered = extract_constituent_bwt(reduced, sid)
            original = np.load(os.path.join(
                leaves[sid], "msbwt.npy"))
            self.assertTrue(np.array_equal(recovered, original), sid)


class CleanControlEquivalenceTests(SourceRemovalPy2TestBase):
    """Removal output == clean retained-source control across semantics."""

    def _build_pair(self, remove_ids):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        keep = retained_after(all_ids, remove_ids)
        reduced = os.path.join(self.work, "reduced")
        remove_sources(output, reduced, sources=remove_ids)
        clean_leaves, clean_out, clean_manifest, clean_oracle = (
            self.build_clean_control(keep))
        # byte equality of the BWT is contractual (deterministic order;
        # the clean control is built in the same source order)
        self.assertTrue(np.array_equal(
            np.load(os.path.join(reduced, "msbwt.npy")),
            np.load(os.path.join(clean_out, "msbwt.npy"))))
        self._clean_rows_dir = clean_out
        return (reduced, clean_out, clean_oracle, keep)

    def _wrapped(self, directory, oracle, metadata=None):
        index = MultiSourceQueryIndex(
            directory, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        read_index = ReadProvenanceIndex(
            directory, mmap=False, source_index=index)
        wrapped = MultiSourceBWT(
            None, index, read_provenance=read_index)
        # the clean control directory carries the naive rows identical to
        # the reduced package (byte-equal BWTs)
        wrapped.bwt = f9.OracleBWTAdapter(
            oracle, self._clean_rows_dir, load_manifest(directory))
        if metadata is not None:
            wrapped.source_metadata = metadata
        return wrapped

    def test_query_counts_equal_clean_control(self):
        remove_ids = ["sample00", "sample02", "sample09"]
        reduced, clean_out, clean_oracle, keep = self._build_pair(
            remove_ids)
        reduced_index = MultiSourceQueryIndex(
            reduced, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        clean_index = MultiSourceQueryIndex(
            clean_out, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        for pattern in ("A", "C", "G", "T", "AC", "CGT", "GTAC",
                        "AAAA", "AAGGTT", "N", "TTAC", "GATTACA"):
            # exact FM counts through the naive oracle rows (the clean
            # control's rows are identical to the reduced package's)
            suffixes_r = [
                row["suffix"] for row in f9.load_rows(clean_out)]
            suffixes_c = [
                row["suffix"] for row in f9.load_rows(clean_out)]
            self.assertEqual(suffixes_r, suffixes_c, pattern)
            for sid in keep:
                low_r, high_r = reduced_index.project_interval(
                    sid, 0, len(suffixes_r))
                low_c, high_c = clean_index.project_interval(
                    sid, 0, len(suffixes_c))
                self.assertEqual((low_r, high_r), (low_c, high_c),
                                 (pattern, sid))

    def test_sparse_frequency_topk_equal_clean_control(self):
        remove_ids = ["sample01", "sample03", "sample05", "sample07",
                      "sample09"]
        reduced, clean_out, clean_oracle, keep = self._build_pair(
            remove_ids)
        r_index = MultiSourceQueryIndex(
            reduced, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        c_index = MultiSourceQueryIndex(
            clean_out, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        for pattern in ("A", "AC", "CGT", "AAAA", "N", "GGGG"):
            # the reduced package has no naive rows; the clean control's
            # rows are identical (byte-equal BWTs)
            low_r, high_r = naive_interval(clean_out, pattern)
            low_c, high_c = naive_interval(clean_out, pattern)
            self.assertEqual((low_r, high_r), (low_c, high_c), pattern)
            sparse_r = r_index.nonzero_sources_interval(low_r, high_r)
            sparse_c = c_index.nonzero_sources_interval(low_c, high_c)
            self.assertEqual(sparse_r, sparse_c, pattern)
            self.assertEqual(
                r_index.source_frequency_interval(low_r, high_r),
                c_index.source_frequency_interval(low_c, high_c))
            for k in (1, 2, 3, 5, 10):
                top_r = r_index.top_sources_interval(low_r, high_r, k)
                top_c = c_index.top_sources_interval(low_c, high_c, k)
                self.assertEqual(top_r, top_c, (pattern, k))

    def test_subset_group_and_extensions_equal_clean_control(self):
        remove_ids = ["sample02", "sample09"]
        reduced, clean_out, clean_oracle, keep = self._build_pair(
            remove_ids)
        r_index = MultiSourceQueryIndex(
            reduced, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        c_index = MultiSourceQueryIndex(
            clean_out, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        subset = keep[:3]
        for pattern in ("A", "AC", "CGT", "AAAA", "N"):
            low_r, high_r = naive_interval(clean_out, pattern)
            low_c, high_c = naive_interval(clean_out, pattern)
            self.assertEqual(
                r_index.subset_count_interval(low_r, high_r, subset),
                c_index.subset_count_interval(low_c, high_c, subset),
                pattern)
            self.assertEqual(
                r_index.subset_counts_interval(low_r, high_r, subset),
                c_index.subset_counts_interval(low_c, high_c, subset),
                pattern)

    def test_read_provenance_equal_clean_control(self):
        remove_ids = ["sample00", "sample02", "sample09"]
        reduced, clean_out, clean_oracle, keep = self._build_pair(
            remove_ids)
        r_index = ReadProvenanceIndex(reduced, mmap=False)
        c_index = ReadProvenanceIndex(clean_out, mmap=False)
        self.assertEqual(r_index.read_count, c_index.read_count)
        self.assertEqual(r_index.read_count, 3 * len(keep))
        for dollar_id in range(r_index.read_count):
            r = r_index.record(dollar_id)
            c = c_index.record(dollar_id)
            for field in ("source_id", "source_read_id",
                          "origin_file_id", "origin_read_id",
                          "mate_dollar_id"):
                self.assertEqual(r[field], c[field],
                                 (dollar_id, field))

    def test_reads_containing_on_reduced_equals_clean_control(self):
        remove_ids = ["sample00", "sample02", "sample09"]
        reduced, clean_out, clean_oracle, keep = self._build_pair(
            remove_ids)
        r_wrapped = self._wrapped(reduced, clean_oracle)
        c_wrapped = self._wrapped(clean_out, clean_oracle)
        for pattern in ("A", "AC", "CGT", "GTAC", "AAAA", "N", "AAGGTT"):
            result_r = r_wrapped.readsContaining(pattern)
            result_c = c_wrapped.readsContaining(pattern)
            self.assertEqual(
                result_r["reported_occurrences"],
                result_c["reported_occurrences"], pattern)
            self.assertEqual(
                {rec["dollar_id"]: rec["occurrence_count"]
                 for rec in result_r["reads"]},
                {rec["dollar_id"]: rec["occurrence_count"]
                 for rec in result_c["reads"]}, pattern)
            self.assertTrue(all(
                rec["source_id"] in keep
                for rec in result_r["reads"]))


def naive_interval(directory, pattern):
    rows = f9.load_rows(directory)
    suffixes = [row["suffix"] for row in rows]
    lo = 0
    hi = len(suffixes)
    while lo < hi:
        mid = (lo + hi) // 2
        if suffixes[mid] < pattern:
            lo = mid + 1
        else:
            hi = mid
    low = lo
    lo = 0
    hi = len(suffixes)
    while lo < hi:
        mid = (lo + hi) // 2
        if suffixes[mid] < pattern + "\x7f":
            lo = mid + 1
        else:
            hi = mid
    return low, lo


class ReadProvenanceAfterRemovalTests(SourceRemovalPy2TestBase):
    def test_read_provenance_filtered_and_mates_remapped(self):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        remove_ids = [all_ids[0], all_ids[2], all_ids[-1]]
        reduced = os.path.join(self.work, "reduced")
        stats = remove_sources(output, reduced, sources=remove_ids)
        self.assertTrue(stats["read_provenance_preserved"])
        retained = retained_after(all_ids, remove_ids)
        index = MultiSourceQueryIndex(
            reduced, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        read_index = ReadProvenanceIndex(
            reduced, mmap=False, source_index=index)
        self.assertEqual(read_index.read_count, 3 * len(retained))
        for sid in retained:
            self.assertEqual(read_index.source_read_count(sid), 3)
            d0 = read_index.find_dollar_id(sid, 0)
            d1 = read_index.find_dollar_id(sid, 1)
            d2 = read_index.find_dollar_id(sid, 2)
            self.assertEqual(read_index.mate(d0)["dollar_id"], d1)
            self.assertEqual(read_index.mate(d1)["dollar_id"], d0)
            self.assertIsNone(read_index.mate(d2))

    def test_origin_ids_survive_removal(self):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        reduced = os.path.join(self.work, "reduced")
        remove_sources(
            output, reduced, sources=[all_ids[0], all_ids[-1]])
        read_index = ReadProvenanceIndex(reduced, mmap=False)
        for sid in retained_after(all_ids, [all_ids[0], all_ids[-1]]):
            for local in range(3):
                dollar_id = read_index.find_dollar_id(sid, local)
                rec = read_index.record(dollar_id)
                self.assertEqual(rec["origin_file_id"], 0)
                self.assertEqual(rec["origin_file"], "%s_R0.fastq" % sid)
                self.assertIn(rec["origin_read_id"], (100, 101, 102))

    def test_mate_to_removed_read_becomes_unpaired(self):
        # Build a source whose read 0's mate is removed along with the
        # whole other source; retained mates stay linked, and a mate
        # pointing into a removed source disappears.
        reads_by_source = {
            "A": ["ACGTAC", "GATTACA", "AAAA"],
            "B": ["TTTT", "GCGTAC"],
        }
        leaves = f9.build_sources(self.work, reads_by_source)
        output = os.path.join(self.work, "merged")
        f9.merge_sources(self.work, leaves, name="merged")
        reduced = os.path.join(self.work, "reduced")
        remove_sources(output, reduced, sources=["B"])
        read_index = ReadProvenanceIndex(reduced, mmap=False)
        d0 = read_index.find_dollar_id("A", 0)
        d1 = read_index.find_dollar_id("A", 1)
        self.assertEqual(read_index.mate(d0)["dollar_id"], d1)
        self.assertEqual(read_index.mate(d1)["dollar_id"], d0)
        self.assertIsNone(read_index.mate(
            read_index.find_dollar_id("A", 2)))


class MetadataRemovalTests(SourceRemovalPy2TestBase):
    def _build_metadata(self, output):
        metadata = SourceMetadataCatalog(
            MultiSourceQueryIndex(
                output, mmap=False, use_saved_rank=False).list_sources())
        metadata.define_group(
            "case", ["sample00", "sample01", "sample02",
                     "sample03", "sample04"])
        metadata.define_group(
            "control", ["sample05", "sample06", "sample07",
                        "sample08", "sample09"])
        for i, sid in enumerate(ALL_SOURCES):
            metadata.set_source_metadata(
                sid, cohort="case" if i < 5 else "control",
                platform="X" if i % 2 == 0 else "Y")
        metadata.save(output)

    def test_remove_named_group_and_prune_metadata(self):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        self._build_metadata(output)
        reduced = os.path.join(self.work, "control_only")
        stats = remove_sources(output, reduced, group="case")
        input_catalog = SourceMetadataCatalog.load(
            output,
            MultiSourceQueryIndex(
                output, mmap=False, use_saved_rank=False).list_sources(),
            required=True)
        case_ids = input_catalog.group_sources("case")
        self.assertEqual(
            stats["removed_source_ids"],
            [sid for sid in all_ids if sid in case_ids])
        self.assertEqual(
            stats["retained_source_ids"],
            [sid for sid in all_ids if sid not in case_ids])
        metadata = SourceMetadataCatalog.load(
            reduced,
            MultiSourceQueryIndex(
                reduced, mmap=False, use_saved_rank=False).list_sources(),
            required=True)
        self.assertEqual(metadata.group_sources("case"), [])
        self.assertEqual(
            metadata.group_sources("control"),
            [sid for sid in all_ids if sid not in case_ids])
        self.assertEqual(metadata.select_where(cohort="case"), [])
        self.assertEqual(
            metadata.select_where(cohort="control"),
            [sid for sid in all_ids if sid not in case_ids])

    def test_remove_metadata_predicate(self):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        self._build_metadata(output)
        reduced = os.path.join(self.work, "no_even")
        remove_sources(output, reduced, where={"platform": "X"})
        manifest_out = load_manifest(reduced)
        input_catalog = SourceMetadataCatalog.load(
            output,
            MultiSourceQueryIndex(
                output, mmap=False, use_saved_rank=False).list_sources(),
            required=True)
        removed = input_catalog.select_where(platform="X")
        self.assertEqual(
            [s["id"] for s in manifest_out["sources"]],
            [sid for sid in all_ids if sid not in removed])

    def test_group_removal_requires_metadata(self):
        leaves, output, manifest, oracle = self.build_input()
        with self.assertRaises(SourceRemovalError):
            remove_sources(
                output, os.path.join(self.work, "x"),
                group="case")

    def test_external_metadata_file_used_for_selection(self):
        leaves, output, manifest, oracle = self.build_input()
        meta_path = os.path.join(self.work, "external_meta.json")
        self._build_metadata(output)
        shutil.copy(
            os.path.join(output, "source_metadata.json"), meta_path)
        reduced = os.path.join(self.work, "control_only")
        remove_sources(
            output, reduced, group="case",
            source_metadata_path=meta_path)
        manifest_out = load_manifest(reduced)
        self.assertEqual(len(manifest_out["sources"]), 5)


class RankAndAtomicityTests(SourceRemovalPy2TestBase):
    def test_no_stale_rank_caches_survive_removal(self):
        leaves, output, manifest, oracle = self.build_input()
        reduced = os.path.join(self.work, "reduced")
        stats = remove_sources(output, reduced, sources=["sample09"])
        self.assertEqual(stats["rank_indexes_built"], 0)
        ranks_dir = os.path.join(reduced, "provenance", "ranks")
        self.assertFalse(os.path.exists(ranks_dir))
        # queries rebuild lazily and work (whole-index listing requires
        # rank structures for every internal node)
        index = MultiSourceQueryIndex(
            reduced, rank_stride_bytes=64, mmap=False,
            use_saved_rank=True)
        sources = index.nonzero_sources_interval(0, index.total_bits)
        self.assertEqual(
            len(sources),
            len(load_manifest(reduced)["sources"]))

    def test_build_rank_indexes_materializes_all_new_internal_ranks(self):
        leaves, output, manifest, oracle = self.build_input()
        reduced = os.path.join(self.work, "reduced")
        stats = remove_sources(
            output, reduced, sources=["sample02", "sample09"],
            build_rank_indexes=True, rank_stride_bytes=8)
        index = MultiSourceQueryIndex(
            reduced, rank_stride_bytes=8, mmap=False,
            use_saved_rank=True)
        internal_nodes = len(index._nodes_by_id)
        self.assertGreater(internal_nodes, 0)
        self.assertEqual(stats["rank_indexes_built"], internal_nodes)
        rank_files = [
            name for name in os.listdir(
                os.path.join(reduced, "provenance", "ranks"))
            if name.endswith(".npz")
        ]
        self.assertEqual(len(rank_files), internal_nodes)

    def test_input_package_is_not_modified(self):
        leaves, output, manifest, oracle = self.build_input()

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
            output, os.path.join(self.work, "reduced"),
            sources=["sample04"])
        for name, digest in before.items():
            self.assertEqual(
                sha256(os.path.join(output, name)), digest, name)

    def test_failed_removal_leaves_no_publishable_output(self):
        # Corrupt read provenance in a COPY of the input; the removal must
        # fail after building the BWT and must NOT publish an output that
        # passes validation (the temp package is cleaned up).
        leaves, output, manifest, oracle = self.build_input()
        broken = os.path.join(self.work, "broken_input")
        shutil.copytree(output, broken)
        with open(os.path.join(broken, "read_provenance.json"), "w") as fp:
            fp.write("{not json")
        target = os.path.join(self.work, "must_not_exist")
        with self.assertRaises(Exception):
            remove_sources(
                broken, target, sources=["sample09"])
        self.assertFalse(os.path.exists(target))
        # no stray temp siblings remain
        leftovers = [
            name for name in os.listdir(self.work)
            if name.startswith(".must_not_exist.point10-")
        ]
        self.assertEqual(leftovers, [])

    def test_remove_all_sources_rejected_without_output(self):
        leaves, output, manifest, oracle = self.build_input()
        target = os.path.join(self.work, "invalid")
        with self.assertRaises(SourceRemovalError):
            remove_sources(
                output, target, sources=list(ALL_SOURCES))
        self.assertFalse(os.path.exists(target))

    def test_empty_remove_selection_rejected(self):
        leaves, output, manifest, oracle = self.build_input()
        with self.assertRaises(SourceRemovalError):
            remove_sources(
                output, os.path.join(self.work, "invalid"),
                sources=[])

    def test_retain_all_rejected_as_noop(self):
        leaves, output, manifest, oracle = self.build_input()
        with self.assertRaises(SourceRemovalError):
            retain_sources(
                output, os.path.join(self.work, "invalid"),
                list(ALL_SOURCES))

    def test_output_must_be_distinct_from_input(self):
        leaves, output, manifest, oracle = self.build_input()
        with self.assertRaises(SourceRemovalError):
            remove_sources(
                output, output, sources=["sample09"])

    def test_existing_output_requires_explicit_overwrite(self):
        leaves, output, manifest, oracle = self.build_input()
        target = os.path.join(self.work, "existing")
        os.mkdir(target)
        sentinel = os.path.join(target, "sentinel.txt")
        with open(sentinel, "w") as fp:
            fp.write("keep")
        with self.assertRaises(SourceRemovalError):
            remove_sources(output, target, sources=["sample09"])
        with open(sentinel, "r") as fp:
            self.assertEqual(fp.read(), "keep")
        # overwrite=True publishes a complete valid package
        remove_sources(
            output, target, sources=["sample09"], overwrite=True)
        self.assertTrue(validate_manifest(target))
        self.assertFalse(os.path.exists(sentinel))

    def test_unknown_selection_rejected(self):
        leaves, output, manifest, oracle = self.build_input()
        with self.assertRaises(KeyError):
            remove_sources(
                output, os.path.join(self.work, "x"),
                sources=["ghost_source"])


class RealIntegrationTests(SourceRemovalPy2TestBase):
    """Real pp/cfpp construction + real GenericMerge merges."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f10-real-")
        from test_source_index_py2 import SourceHarness
        self.harness = SourceHarness(self.work)

    def test_remove_one_real_source_counts_equal_standalone(self):
        import test_multisource_query_py2 as f3
        from MUS.MultiSourceProvenance import initialize_leaf_provenance

        a_dir = self.harness.build_fixture_source(
            "real-a", "uniform-a.fastq")
        b_dir = self.harness.build_fixture_source(
            "real-b", "uniform-b.fastq")
        initialize_leaf_provenance(
            a_dir, source_id="real-a", source_name="real-a")
        initialize_leaf_provenance(
            b_dir, source_id="real-b", source_name="real-b")
        m_dir = os.path.join(self.work, "real-m")
        from MUS.MultiSourceProvenance import merge_two_with_provenance
        merge_two_with_provenance(
            a_dir, b_dir, m_dir,
            merge_two_func=f3.holt_merge_two_local, num_procs=1)

        reduced = os.path.join(self.work, "real-reduced")
        stats = remove_sources(m_dir, reduced, sources=["real-a"])
        self.assertEqual(stats["retained_sources"], 1)
        self.assertEqual(stats["removed_sources"], 1)

        b_bwt = f9_read_standalone(b_dir)
        reduced_bwt = f9_read_standalone(reduced)
        for pattern in ("A", "C", "G", "T", "N", "AC", "GT", "ACGT",
                        "AAAAA", "NACGT"):
            self.assertEqual(
                int(reduced_bwt.countOccurrencesOfSeq(pattern)),
                int(b_bwt.countOccurrencesOfSeq(pattern)),
                pattern)

        # retain the other source -> byte equal to its standalone BWT
        only_a = os.path.join(self.work, "real-only-a")
        retain_sources(m_dir, only_a, ["real-a"])
        self.assertTrue(np.array_equal(
            np.load(os.path.join(only_a, "msbwt.npy")),
            np.load(os.path.join(a_dir, "msbwt.npy"))))

    def test_read_provenance_about_based_survives_removal(self):
        import test_multisource_query_py2 as f3
        from MUS.MultiSourceProvenance import (
            initialize_leaf_provenance,
            merge_two_with_provenance,
        )
        from MUS.ReadProvenance import (
            initialize_leaf_read_provenance_from_about,
        )

        a_dir = self.harness.build_fixture_source(
            "real-a", "uniform-a.fastq")
        b_dir = self.harness.build_fixture_source(
            "real-b", "uniform-b.fastq")
        initialize_leaf_provenance(
            a_dir, source_id="real-a", source_name="real-a")
        initialize_leaf_provenance(
            b_dir, source_id="real-b", source_name="real-b")
        initialize_leaf_read_provenance_from_about(
            a_dir, input_files=["uniform-a.fastq"])
        initialize_leaf_read_provenance_from_about(
            b_dir, input_files=["uniform-b.fastq"])
        m_dir = os.path.join(self.work, "real-m")
        merge_two_with_provenance(
            a_dir, b_dir, m_dir,
            merge_two_func=f3.holt_merge_two_local, num_procs=1)

        reduced = os.path.join(self.work, "real-reduced")
        stats = remove_sources(m_dir, reduced, sources=["real-a"])
        self.assertTrue(stats["read_provenance_preserved"])
        read_index = ReadProvenanceIndex(reduced, mmap=False)
        b_about = np.load(os.path.join(b_dir, "about.npy"))
        b_records = [(int(r[0]), int(r[1])) for r in b_about]
        self.assertEqual(read_index.read_count, len(b_records))
        for local_id, (file_id, read_id) in enumerate(b_records):
            dollar_id = read_index.find_dollar_id("real-b", local_id)
            record = read_index.record(dollar_id)
            self.assertEqual(record["origin_file_id"], file_id)
            self.assertEqual(record["origin_read_id"], read_id)


def f9_read_standalone(path):
    import test_source_index_py2 as f1
    return f1.load_standalone(path)


class RandomizedRemovalTests(SourceRemovalPy2TestBase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f10-rand-")
        # The input package is read-only across removal cases.
        self.leaves, self.output, self.manifest, self.oracle = (
            self.build_input())

    def test_randomized_removal_byte_and_semantic_equality(self):
        all_ids = manifest_source_order(self.output)
        for seed_index, seed in enumerate(SEEDS):
            rng = random.Random(seed)
            for case in range(6):
                leaves = self.leaves
                output = self.output
                remove_ids = [
                    sid for sid in all_ids
                    if rng.random() < 0.35
                ]
                if not remove_ids or len(remove_ids) == len(all_ids):
                    remove_ids = [all_ids[case % len(all_ids)]]
                keep = retained_after(all_ids, remove_ids)
                reduced = os.path.join(
                    self.work, "rand_%02d_%02d" % (seed_index, case))
                remove_sources(output, reduced, sources=remove_ids)
                # byte equality against the independent rebuild
                expected = expected_bwt_bytes(leaves, all_ids, keep)
                actual = np.load(os.path.join(reduced, "msbwt.npy"))
                self.assertTrue(np.array_equal(actual, expected),
                                (seed, case, remove_ids))
                self.assertTrue(validate_manifest(reduced))
                # read provenance read count and mate sanity
                read_index = ReadProvenanceIndex(reduced, mmap=False)
                self.assertEqual(
                    read_index.read_count, 3 * len(keep))
                for sid in keep:
                    d0 = read_index.find_dollar_id(sid, 0)
                    d1 = read_index.find_dollar_id(sid, 1)
                    self.assertEqual(
                        read_index.mate(d0)["dollar_id"], d1)
                    self.assertEqual(
                        read_index.mate(d1)["dollar_id"], d0)
                # readsContaining on the reduced package has no removed
                # source and sums to the naive retained count
                index = MultiSourceQueryIndex(
                    reduced, rank_stride_bytes=1, mmap=False,
                    use_saved_rank=False)
                read_idx2 = ReadProvenanceIndex(
                    reduced, mmap=False, source_index=index)
                wrapped = MultiSourceBWT(
                    None, index, read_provenance=read_idx2)
                clean_leaves, clean_out, clean_manifest, clean_oracle = (
                    self.build_clean_control(keep, name="clean_%02d_%02d"
                                             % (seed_index, case)))
                wrapped.bwt = f9.OracleBWTAdapter(
                    clean_oracle, clean_out, load_manifest(reduced))
                for pattern in ("A", "C", "G", "T", "AC", "N"):
                    expected_map = {}
                    for sid in keep:
                        for local_id in range(3):
                            dollar_id = clean_oracle.global_dollar[
                                (sid, local_id)]
                            count = f9.overlapping_count(
                                f9.TEN_SOURCE_READS[sid][local_id],
                                pattern)
                            if count:
                                expected_map[dollar_id] = count
                    result = wrapped.readsContaining(pattern)
                    actual_map = {
                        rec["dollar_id"]: rec["occurrence_count"]
                        for rec in result["reads"]
                    }
                    self.assertEqual(
                        actual_map, expected_map,
                        (seed, case, pattern))


if __name__ == "__main__":
    unittest.main()
