"""Feature 12 - generic BWT-aligned tag arrays (Python-2 suite, real
merges).

This suite validates ``MUS.BWTTags`` plus the Feature-12 additions to
``MUS.MultiSourceProvenance`` (merge-time tag preflight + automatic tag
merge), ``MUS.MultiSourceQuery`` (``listTags`` / ``tagSchema`` / ``rowTag``
/ ``tagInterval`` / ``tagValues`` / ``tagValueCounts``), and
``MUS.SourceRemoval`` (tag filtering with the exact BWT survival mask)
against independent oracles:

* the strongest possible row-identity tag ``row_id``: initially
  ``tag[x] = independently known unique identity of BWT row x`` (source
  order index + leaf-local row), then independently tracked through
  two-source merges, multi-stage merges, and source removal using the
  verified ``unpack_interleave`` tree walks (never derived from the
  BWTTags implementation);
* expected merged tag arrays computed by replaying the independent
  suffix sort of all reads;
* naive per-row counting for value frequencies.

Coverage:

- attach/validate/list/schema/remove/overwrite; shape-mismatch, dtype
  policy (object/structured rejected), unsafe tag names (``/``, ``\\``,
  ``..``, spaces, NUL, unicode), hash-based safe filenames;
- scalar and vector tags across multiple fixed-width dtypes; mmap
  loading; direct interval slices;
- two-way and balanced 10-source merges automatically preserve every tag
  (``T_final[x]`` travels exactly with ``BWT_final[x]``);
- one-sided tag with declared missing value fills only the missing
  source rows; one-sided tag without missing value fails BEFORE the BWT
  merge; incompatible schemas fail before the merge;
- retrofit via ``build_tag_from_leaf_arrays`` equals the merge-produced
  tag element-for-element (BWT bytes unchanged);
- Feature-10 removal: ``T_reduced == T_original[keep_mask]``
  element-for-element for every tag;
- query lifecycle: whole-index exact interval tags == ``T[l:r]``;
  source/subset/group/where tag selection == independently projected
  rows; ``tagValueCounts`` == naive counting; vector-tag counts rejected;
- randomized differentials (seeds 20260811/20260812/20260813): random
  merges and removals with row-identity tags.
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

from MUS.BWTTags import (  # noqa: E402
    BWTTagError,
    BWTTagStore,
    attach_tag,
    build_tag_from_leaf_arrays,
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
    MultiSourceQueryError,
    MultiSourceQueryIndex,
)
from MUS.SourceRemoval import remove_sources  # noqa: E402

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

SEEDS = (20260811, 20260812, 20260813)

MAX_LOCAL = 10000


def row_identity_tag(leaf_dir, all_order):
    """Independent row-identity tag for one leaf.

    ``tag[x] = all_order[source] * MAX_LOCAL + local_row`` for leaf BWT
    row ``x``; the identity is known independently from the naive suffix
    rows (no BWTTags code involved).
    """
    rows = f9.load_rows(leaf_dir)
    sid = os.path.basename(leaf_dir)
    return np.asarray(
        [all_order[sid] * MAX_LOCAL + i for i in range(len(rows))],
        dtype=np.uint32,
    )


def expected_merged_row_identity(merged_dir, leaves, all_order):
    """Independent expected row-identity tag for a merged package.

    Row ``x`` of the merged BWT maps to ``(source, local_row)`` by direct
    bit-array counting through ``unpack_interleave``; the expected tag
    value is ``all_order[source] * MAX_LOCAL + local_row``.
    """
    manifest = load_manifest(merged_dir, validate=True)

    def walk(row_index):
        node = manifest["root"]
        local_index = int(row_index)
        while node["type"] == "merge":
            bits = f9_unpack(os.path.join(
                merged_dir, str(node["interleave"])), node["length"])
            bit = int(bits[local_index])
            if bit == 0:
                child_index = int(np.count_nonzero(bits[:local_index] == 0))
                node = node["left"]
            else:
                child_index = int(np.count_nonzero(bits[:local_index] == 1))
                node = node["right"]
            local_index = child_index
        return str(node["source_id"]), local_index

    total = int(manifest["root"]["length"])
    expected = np.empty(total, dtype=np.uint32)
    for x in range(total):
        sid, local_row = walk(x)
        expected[x] = all_order[sid] * MAX_LOCAL + local_row
    return expected


def f9_unpack(path, total):
    packed = np.load(path, mmap_mode="r")
    needed = (total + 7) // 8
    used = np.asarray(packed[:needed], dtype=np.uint8)
    shifts = np.arange(8, dtype=np.uint8)
    bits = ((used[:, None] >> shifts[None, :]) & np.uint8(1)).reshape(-1)
    return bits[:total]


def attach_row_id_tags(leaves):
    all_order = {sid: i for i, sid in enumerate(leaves)}
    for sid, leaf in leaves.items():
        attach_tag(
            leaf,
            "row_id",
            row_identity_tag(leaf, all_order),
            description="independent row identity",
        )
    return all_order


def naive_interval(directory, pattern):
    suffixes = [row["suffix"] for row in f9.load_rows(directory)]
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


class BWTTagsPy2TestBase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f12-py2-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)


class AttachAndSchemaTests(BWTTagsPy2TestBase):
    def _leaf(self, name="src"):
        leaf = f9.make_read_derived_leaf(
            self.work, name, ["ACGTAC", "GATTACA", "AAAA"])
        return leaf

    def test_attach_list_schema_remove(self):
        leaf = self._leaf()
        rows = len(f9.load_rows(leaf))
        schema = attach_tag(
            leaf, "read_pos",
            np.arange(rows, dtype=np.uint16),
            description="position inside original read")
        self.assertTrue(tags_exist(leaf))
        store = BWTTagStore(leaf)
        self.assertEqual(store.list_tags(), ["read_pos"])
        self.assertEqual(store.schema("read_pos")["dtype"], "<u2")
        self.assertEqual(store.schema("read_pos")["tail_shape"], [])
        self.assertEqual(store.schema("read_pos")["description"],
                         "position inside original read")
        self.assertEqual(store.array("read_pos").shape[0], rows)
        # remove
        remove_tag(leaf, "read_pos")
        self.assertFalse(tags_exist(leaf))
        store2 = BWTTagStore(leaf)
        self.assertEqual(store2.list_tags(), [])

    def test_shape_mismatch_rejected(self):
        leaf = self._leaf()
        with self.assertRaises(BWTTagError):
            attach_tag(leaf, "bad", np.zeros(3, dtype=np.uint8))

    def test_dtype_policy_rejects_object_and_structured(self):
        leaf = self._leaf()
        rows = len(f9.load_rows(leaf))
        with self.assertRaises(BWTTagError):
            attach_tag(leaf, "obj", np.zeros(rows, dtype=object))
        structured = np.zeros(rows, dtype=np.dtype([("a", "u1")]))
        with self.assertRaises(BWTTagError):
            attach_tag(leaf, "struct", structured)

    def test_unsafe_names_are_hash_filenames(self):
        leaf = self._leaf()
        rows = len(f9.load_rows(leaf))
        for name in ("a/b", "a\\b", "..", "has space", "uni\u00e9",
                     "colon:name"):
            attach_tag(leaf, name, np.zeros(rows, dtype=np.uint8))
        store = BWTTagStore(leaf)
        self.assertEqual(len(store.list_tags()), 6)
        # filenames are safe hashes, never derived paths
        for name in store.list_tags():
            filename = store.schema(name)["filename"]
            self.assertTrue(filename.startswith("bwt_tags/tag_"))
            self.assertTrue(filename.endswith(".npy"))
            self.assertNotIn("/", filename[len("bwt_tags/"):])
        # collision behavior: same name -> same hash, overwrite required
        with self.assertRaises(BWTTagError):
            attach_tag(leaf, "a/b", np.zeros(rows, dtype=np.uint8))
        attach_tag(leaf, "a/b", np.zeros(rows, dtype=np.uint8),
                   overwrite=True)

    def test_nul_name_rejected(self):
        leaf = self._leaf()
        with self.assertRaises(BWTTagError):
            attach_tag(leaf, "bad\x00name", np.zeros(1, dtype=np.uint8))

    def test_vector_and_multiple_dtypes(self):
        leaf = self._leaf()
        rows = len(f9.load_rows(leaf))
        pair = np.zeros((rows, 2), dtype=np.uint16)
        attach_tag(leaf, "pair", pair)
        attach_tag(leaf, "flag", np.ones(rows, dtype=np.bool_))
        attach_tag(leaf, "score", np.full(rows, 1.5, dtype=np.float32))
        attach_tag(leaf, "label", np.asarray(
            [b"x" * 4] * rows, dtype="S4"))
        store = BWTTagStore(leaf)
        self.assertEqual(store.array("pair").shape, (rows, 2))
        self.assertEqual(store.schema("pair")["tail_shape"], [2])
        self.assertEqual(store.array("flag").dtype, np.dtype(np.bool_))
        self.assertEqual(store.array("score").dtype, np.dtype(np.float32))
        self.assertEqual(store.array("label").dtype, np.dtype("S4"))
        with self.assertRaises(BWTTagError):
            store.value_counts("pair")

    def test_mmap_loading(self):
        leaf = self._leaf()
        rows = len(f9.load_rows(leaf))
        attach_tag(leaf, "t", np.arange(rows, dtype=np.uint32))
        store = BWTTagStore(leaf, mmap=True)
        self.assertIsInstance(store.array("t"), np.memmap)
        self.assertTrue(np.array_equal(
            store.array("t"), np.arange(rows, dtype=np.uint32)))

    def test_corrupt_registry_fails_loudly(self):
        leaf = self._leaf()
        rows = len(f9.load_rows(leaf))
        attach_tag(leaf, "t", np.zeros(rows, dtype=np.uint8))
        reg = os.path.join(leaf, "bwt_tags.json")
        with open(reg, "w") as fp:
            fp.write("{not json")
        with self.assertRaises(BWTTagError):
            BWTTagStore(leaf)
        # restore a valid registry, then corrupt the ARRAY with a wrong
        # row count; loading must fail loudly
        os.remove(reg)
        attach_tag(leaf, "t", np.zeros(rows, dtype=np.uint8))
        wrong = os.path.join(
            leaf, "bwt_tags",
            os.path.basename(BWTTagStore(leaf).schema("t")["filename"]))
        np.save(wrong, np.zeros(rows + 5, dtype=np.uint8))
        with self.assertRaises(BWTTagError):
            BWTTagStore(leaf)

    def test_missing_value_roundtrip_nan_inf_bytes(self):
        leaf = self._leaf()
        rows = len(f9.load_rows(leaf))
        attach_tag(leaf, "f", np.zeros(rows, dtype=np.float64),
                   missing_value=np.nan)
        store = BWTTagStore(leaf)
        self.assertEqual(
            store.schema("f")["missing"],
            {"enabled": True, "value": {"kind": "float", "value": "nan"}})
        attach_tag(leaf, "inf", np.zeros(rows, dtype=np.float64),
                   missing_value=np.inf)
        store = BWTTagStore(leaf)
        self.assertEqual(
            store.schema("inf")["missing"]["value"],
            {"kind": "float", "value": "inf"})
        attach_tag(leaf, "b", np.zeros(rows, dtype="S2"),
                   missing_value=b"xy")
        store = BWTTagStore(leaf)
        self.assertEqual(
            store.schema("b")["missing"]["value"]["kind"], "bytes")
        # the decoded missing scalar round-trips to the same value
        attach_tag(leaf, "neg", np.zeros(rows, dtype=np.float64),
                   missing_value=-np.inf)
        store = BWTTagStore(leaf)
        self.assertEqual(
            store.schema("neg")["missing"]["value"],
            {"kind": "float", "value": "-inf"})


class MergeLifecycleTests(BWTTagsPy2TestBase):
    def _tagged_two_way(self, reads_a, reads_b):
        leaves = {}
        for sid, reads in (("A", reads_a), ("B", reads_b)):
            leaf = f9.make_read_derived_leaf(self.work, sid, reads)
            leaves[sid] = leaf
        all_order = attach_row_id_tags(leaves)
        output = os.path.join(self.work, "merged")
        merge_two_with_provenance(
            leaves["A"], leaves["B"], output,
            merge_two_func=f9.read_derived_merge)
        return leaves, output, all_order

    def test_two_way_merge_preserves_row_identity_tag_exactly(self):
        leaves, output, all_order = self._tagged_two_way(
            ["ACGTAC", "GATTACA", "AAAA"], ["TTTT", "GCGTAC"])
        self.assertTrue(tags_exist(output))
        store = BWTTagStore(output)
        expected = expected_merged_row_identity(
            output, leaves, all_order)
        self.assertTrue(np.array_equal(
            store.array("row_id"), expected))

    def test_balanced_ten_source_merge_preserves_tags(self):
        leaves = {}
        for sid, reads in f9.TEN_SOURCE_READS.items():
            leaf = f9.make_read_derived_leaf(self.work, sid, reads)
            leaves[sid] = leaf
        all_order = attach_row_id_tags(leaves)
        output = os.path.join(self.work, "merged10")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f9.read_derived_merge)
        store = BWTTagStore(output)
        expected = expected_merged_row_identity(
            output, leaves, all_order)
        self.assertTrue(np.array_equal(
            store.array("row_id"), expected))
        self.assertEqual(store.bwt_length, 191)

    def test_unbalanced_chain_merge_preserves_tags(self):
        reads_by_source = {
            "S0": ["AAAA"], "S1": ["CCCC"],
            "S2": ["GGGG"], "S3": ["TTTT"],
        }
        leaves = {}
        for sid, reads in reads_by_source.items():
            leaf = f9.make_read_derived_leaf(self.work, sid, reads)
            leaves[sid] = leaf
        all_order = attach_row_id_tags(leaves)
        order = ["S0", "S1", "S2", "S3"]
        current = leaves[order[0]]
        for name in order[1:]:
            out = os.path.join(self.work, "chain_" + name)
            merge_two_with_provenance(
                current, leaves[name], out,
                merge_two_func=f9.read_derived_merge)
            current = out
        store = BWTTagStore(current)
        expected = expected_merged_row_identity(
            current, leaves, all_order)
        self.assertTrue(np.array_equal(
            store.array("row_id"), expected))

    def test_one_sided_tag_without_missing_value_fails_before_merge(self):
        leaf_a = f9.make_read_derived_leaf(
            self.work, "A", ["ACGTAC", "AAAA"])
        leaf_b = f9.make_read_derived_leaf(
            self.work, "B", ["TTTT", "CCCC"])
        rows_a = len(f9.load_rows(leaf_a))
        attach_tag(leaf_a, "code", np.zeros(rows_a, dtype=np.uint8))
        called = [False]

        def should_not_run(*args, **kwargs):
            called[0] = True

        with self.assertRaises(BWTTagError):
            merge_two_with_provenance(
                leaf_a, leaf_b, os.path.join(self.work, "bad"),
                merge_two_func=should_not_run)
        self.assertFalse(called[0])
        self.assertFalse(os.path.exists(
            os.path.join(self.work, "bad", "msbwt.npy")))

    def test_one_sided_tag_with_missing_value_fills_missing_rows(self):
        leaf_a = f9.make_read_derived_leaf(
            self.work, "A", ["ACGTAC", "AAAA"])
        leaf_b = f9.make_read_derived_leaf(
            self.work, "B", ["TTTT", "CCCC"])
        rows_a = len(f9.load_rows(leaf_a))
        attach_tag(leaf_a, "code",
                   np.asarray(
                       list(range(rows_a)), dtype=np.uint8),
                   missing_value=0)
        output = os.path.join(self.work, "merged")
        merge_two_with_provenance(
            leaf_a, leaf_b, output,
            merge_two_func=f9.read_derived_merge)
        store = BWTTagStore(output)
        values = store.array("code")
        # A rows keep 0..rows_a-1; B rows are filled with the missing value
        manifest = load_manifest(output)
        b_rows = [x for x in range(values.shape[0])
                  if row_source(output, manifest, x) == "B"]
        a_rows = [x for x in range(values.shape[0])
                  if row_source(output, manifest, x) == "A"]
        self.assertEqual(
            sorted(values[a_rows].tolist()),
            list(range(rows_a)))
        self.assertEqual(set(values[b_rows].tolist()), set([0]))

    def test_incompatible_schemas_fail_before_merge(self):
        leaf_a = f9.make_read_derived_leaf(
            self.work, "A", ["ACGTAC", "AAAA"])
        leaf_b = f9.make_read_derived_leaf(
            self.work, "B", ["TTTT", "CCCC"])
        rows_a = len(f9.load_rows(leaf_a))
        rows_b = len(f9.load_rows(leaf_b))
        attach_tag(leaf_a, "code", np.zeros(rows_a, dtype=np.uint8))
        attach_tag(leaf_b, "code", np.zeros(rows_b, dtype=np.uint16))
        called = [False]

        def should_not_run(*args, **kwargs):
            called[0] = True

        with self.assertRaises(BWTTagError):
            merge_two_with_provenance(
                leaf_a, leaf_b, os.path.join(self.work, "bad"),
                merge_two_func=should_not_run)
        self.assertFalse(called[0])

    def test_merge_without_tags_still_works(self):
        leaf_a = f9.make_read_derived_leaf(
            self.work, "A", ["ACGTAC", "AAAA"])
        leaf_b = f9.make_read_derived_leaf(
            self.work, "B", ["TTTT", "CCCC"])
        output = os.path.join(self.work, "merged")
        merge_two_with_provenance(
            leaf_a, leaf_b, output,
            merge_two_func=f9.read_derived_merge)
        self.assertFalse(tags_exist(output))


def row_source(merged_dir, manifest, row_index):
    node = manifest["root"]
    local_index = int(row_index)
    while node["type"] == "merge":
        bits = f9_unpack(os.path.join(
            merged_dir, str(node["interleave"])), node["length"])
        bit = int(bits[local_index])
        if bit == 0:
            local_index = int(np.count_nonzero(bits[:local_index] == 0))
            node = node["left"]
        else:
            local_index = int(np.count_nonzero(bits[:local_index] == 1))
            node = node["right"]
    return str(node["source_id"])


class RetrofitAndRemovalTests(BWTTagsPy2TestBase):
    def _tagged_merged(self):
        leaves = {}
        for sid, reads in f9.TEN_SOURCE_READS.items():
            leaf = f9.make_read_derived_leaf(self.work, sid, reads)
            leaves[sid] = leaf
        all_order = attach_row_id_tags(leaves)
        output = os.path.join(self.work, "merged10")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f9.read_derived_merge)
        return leaves, output, all_order

    def test_retrofit_equals_merge_produced_tag_exactly(self):
        leaves, output, all_order = self._tagged_merged()
        # strip the tag from the merged package
        remove_tag(output, "row_id")
        self.assertFalse(tags_exist(output))
        # retrofit from the leaf arrays (paths)
        arrays_by_source = {
            sid: os.path.join(leaf, "bwt_tags",
                              os.path.basename(BWTTagStore(
                                  leaf).schema("row_id")["filename"]))
            for sid, leaf in leaves.items()
        }
        build_tag_from_leaf_arrays(output, "row_id", arrays_by_source)
        # BWT bytes unchanged by retrofit
        store = BWTTagStore(output)
        expected = expected_merged_row_identity(
            output, leaves, all_order)
        self.assertTrue(np.array_equal(
            store.array("row_id"), expected))

    def test_retrofit_missing_source_without_missing_value_fails(self):
        leaves, output, all_order = self._tagged_merged()
        arrays_by_source = {
            sid: row_identity_tag(leaf, all_order)
            for sid, leaf in leaves.items()
        }
        del arrays_by_source["sample05"]
        with self.assertRaises(BWTTagError):
            build_tag_from_leaf_arrays(
                output, "row_id", arrays_by_source)

    def test_removal_filters_every_tag_with_bwt_mask(self):
        leaves, output, all_order = self._tagged_merged()
        store = BWTTagStore(output)
        keep_set = set(s for s in f9.TEN_SOURCE_READS
                       if s not in ("sample00", "sample02", "sample09"))
        manifest = load_manifest(output)
        mask = np.asarray(
            [row_source(output, manifest, x) in keep_set
             for x in range(store.bwt_length)],
            dtype=np.bool_)
        reduced = os.path.join(self.work, "reduced")
        stats = remove_sources(
            output, reduced,
            sources=["sample00", "sample02", "sample09"])
        self.assertTrue(stats["bwt_tags_preserved"])
        self.assertEqual(stats["bwt_tag_count"], 1)
        rstore = BWTTagStore(reduced)
        self.assertTrue(np.array_equal(
            rstore.array("row_id"), store.array("row_id")[mask]))
        # reduced tag still equals the independent reduced row identity
        self.assertTrue(np.array_equal(
            rstore.array("row_id"),
            expected_merged_row_identity(reduced, leaves, all_order)))

    def test_removal_single_source_tag_equals_leaf_array(self):
        leaves, output, all_order = self._tagged_merged()
        reduced = os.path.join(self.work, "single")
        remove_sources(output, reduced, sources=[
            sid for sid in f9.TEN_SOURCE_READS if sid != "sample07"])
        store = BWTTagStore(reduced)
        expected = row_identity_tag(leaves["sample07"], all_order)
        self.assertTrue(np.array_equal(
            store.array("row_id"), expected))

    def test_removal_without_tags_reports_zero(self):
        leaves = {}
        for sid, reads in f9.TEN_SOURCE_READS.items():
            leaf = f9.make_read_derived_leaf(self.work, sid, reads)
            leaves[sid] = leaf
        output = os.path.join(self.work, "merged10")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f9.read_derived_merge)
        reduced = os.path.join(self.work, "reduced")
        stats = remove_sources(
            output, reduced, sources=["sample09"])
        self.assertFalse(stats["bwt_tags_preserved"])
        self.assertEqual(stats["bwt_tag_count"], 0)


class QueryLifecycleTests(BWTTagsPy2TestBase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f12-query-")
        cls.leaves = {}
        for sid, reads in f9.TEN_SOURCE_READS.items():
            leaf = f9.make_read_derived_leaf(cls.work, sid, reads)
            cls.leaves[sid] = leaf
        cls.all_order = attach_row_id_tags(cls.leaves)
        cls.output = os.path.join(cls.work, "merged10")
        merge_many_balanced(
            list(cls.leaves.values()), cls.output,
            merge_two_func=f9.read_derived_merge)
        cls.store = BWTTagStore(cls.output)
        cls.index = MultiSourceQueryIndex(
            cls.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        cls.wrapped = MultiSourceBWT(
            None, cls.index, bwt_tags=cls.store)
        cls.wrapped.bwt = f9.OracleBWTAdapter(
            f9.OracleReadIdentity(
                cls.output,
                {sid: cls.leaves[sid] for sid in cls.leaves},
                f9.TEN_SOURCE_READS),
            cls.output, load_manifest(cls.output))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_whole_index_interval_tags_equal_direct_slice(self):
        for pattern in ("A", "AC", "CGT", "AAAA", "N", "AAGGTT"):
            low, high = naive_interval(self.output, pattern)
            result = self.wrapped.tagValues(pattern, "row_id")
            self.assertEqual(
                result["value_count"], high - low, pattern)
            self.assertTrue(np.array_equal(
                result["values"],
                self.store.array("row_id")[low:high]), pattern)
            # direct API equality
            self.assertTrue(np.array_equal(
                self.wrapped.tagInterval("row_id", low, high),
                self.store.array("row_id")[low:high]))

    def test_source_filtered_tag_values_match_projected_rows(self):
        for pattern in ("A", "AC", "CGT", "AAAA", "N"):
            low, high = naive_interval(self.output, pattern)
            for sid in ("sample00", "sample03", "sample09"):
                result = self.wrapped.tagValues(
                    pattern, "row_id", source=sid)
                expected_rows = [
                    x for x in range(low, high)
                    if row_source(self.output,
                                  load_manifest(self.output), x) == sid
                ]
                self.assertEqual(
                    result["value_count"], len(expected_rows), (pattern, sid))
                self.assertTrue(np.array_equal(
                    result["values"],
                    self.store.array("row_id")[expected_rows]),
                    (pattern, sid))

    def test_subset_group_where_tag_values_match_independent_filter(self):
        from MUS.SourceMetadata import SourceMetadataCatalog
        metadata = SourceMetadataCatalog(self.index.list_sources())
        metadata.define_group(
            "case", ["sample00", "sample01", "sample02"])
        for sid in ("sample00", "sample01", "sample02"):
            metadata.set_source_metadata(sid, cohort="case")
        wrapped = MultiSourceBWT(
            None, self.index, source_metadata=metadata,
            bwt_tags=self.store)
        wrapped.bwt = self.wrapped.bwt
        pattern = "AC"
        low, high = naive_interval(self.output, pattern)
        manifest = load_manifest(self.output)
        for kind, selector in (
            ("subset", {"sources": ["sample00", "sample02"]}),
            ("group", {"group": "case"}),
            ("where", {"where": {"cohort": "case"}}),
        ):
            result = wrapped.tagValues(pattern, "row_id", **selector)
            if kind == "subset":
                selected_ids = set(selector["sources"])
            else:
                selected_ids = set(["sample00", "sample01", "sample02"])
            expected_rows = [
                x for x in range(low, high)
                if row_source(self.output, manifest, x) in selected_ids
            ]
            self.assertEqual(
                result["value_count"], len(expected_rows), kind)
            self.assertTrue(np.array_equal(
                result["values"],
                self.store.array("row_id")[expected_rows]), kind)

    def test_tag_value_counts_equal_naive_counting(self):
        for pattern in ("A", "AC", "CGT", "AAAA", "N"):
            low, high = naive_interval(self.output, pattern)
            values = self.store.array("row_id")[low:high]
            unique, counts = np.unique(values, return_counts=True)
            result = self.wrapped.tagValueCounts(pattern, "row_id")
            table = {item["value"]: item["count"]
                     for item in result["counts"]}
            self.assertEqual(
                table,
                {int(u): int(c) for u, c in zip(unique, counts)},
                pattern)

    def test_missing_tag_layer_reports_cleanly(self):
        wrapped = MultiSourceBWT(None, self.index)
        wrapped.bwt = self.wrapped.bwt
        with self.assertRaises(MultiSourceQueryError):
            wrapped.listTags()
        with self.assertRaises(MultiSourceQueryError):
            wrapped.tagValues("A", "row_id")

    def test_unknown_tag_rejected(self):
        with self.assertRaises(KeyError):
            self.wrapped.tagValues("A", "ghost_tag")
        with self.assertRaises(KeyError):
            self.wrapped.tagSchema("ghost_tag")

    def test_row_tag_bounds(self):
        with self.assertRaises(IndexError):
            self.wrapped.rowTag(self.store.bwt_length, "row_id")
        value = self.wrapped.rowTag(0, "row_id")
        self.assertEqual(
            int(value), int(self.store.array("row_id")[0]))

    def test_vector_tag_counts_rejected(self):
        leaves = {}
        for sid, reads in (("A", ["ACGTAC", "AAAA"]),
                           ("B", ["TTTT", "CCCC"])):
            leaf = f9.make_read_derived_leaf(self.work, sid, reads)
            leaves[sid] = leaf
        rows_a = len(f9.load_rows(leaves["A"]))
        rows_b = len(f9.load_rows(leaves["B"]))
        attach_tag(leaves["A"], "pair",
                   np.zeros((rows_a, 2), dtype=np.uint16))
        attach_tag(leaves["B"], "pair",
                   np.zeros((rows_b, 2), dtype=np.uint16))
        output = os.path.join(self.work, "merged")
        merge_two_with_provenance(
            leaves["A"], leaves["B"], output,
            merge_two_func=f9.read_derived_merge)
        index = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        wrapped = MultiSourceBWT(None, index, bwt_tags=BWTTagStore(output))
        reads_by_source = {"A": ["ACGTAC", "AAAA"], "B": ["TTTT", "CCCC"]}
        oracle = f9.OracleReadIdentity(
            output,
            {sid: leaves[sid] for sid in leaves},
            reads_by_source)
        wrapped.bwt = f9.OracleBWTAdapter(oracle, output,
                                          load_manifest(output))
        with self.assertRaises(BWTTagError):
            wrapped.tagValueCounts("A", "pair")


class RandomizedTagTests(BWTTagsPy2TestBase):
    def test_randomized_merges_and_removals_keep_row_alignment(self):
        for seed_index, seed in enumerate(SEEDS):
            rng = random.Random(seed)
            for case in range(6):
                leaves = {}
                n_sources = rng.randint(2, 5)
                for i in range(n_sources):
                    sid = "S%02d_C%02d_R%d" % (seed_index, case, i)
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
                    leaf = f9.make_read_derived_leaf(
                        self.work, sid, reads)
                    leaves[sid] = leaf
                all_order = attach_row_id_tags(leaves)
                output = os.path.join(
                    self.work, "rand_%02d_%02d" % (seed_index, case))
                merge_many_balanced(
                    list(leaves.values()), output,
                    merge_two_func=f9.read_derived_merge)
                store = BWTTagStore(output)
                expected = expected_merged_row_identity(
                    output, leaves, all_order)
                self.assertTrue(np.array_equal(
                    store.array("row_id"), expected),
                    (seed, case, "merge"))
                # removal keeps alignment
                remove_ids = [
                    sid for sid in leaves if rng.random() < 0.4
                ]
                if not remove_ids or len(remove_ids) == len(leaves):
                    remove_ids = [list(leaves)[0]]
                reduced = os.path.join(
                    self.work, "randred_%02d_%02d" % (seed_index, case))
                stats = remove_sources(
                    output, reduced, sources=remove_ids)
                self.assertTrue(stats["bwt_tags_preserved"])
                rstore = BWTTagStore(reduced)
                expected_reduced = expected_merged_row_identity(
                    reduced, leaves, all_order)
                self.assertTrue(np.array_equal(
                    rstore.array("row_id"), expected_reduced),
                    (seed, case, "remove"))


if __name__ == "__main__":
    unittest.main()
