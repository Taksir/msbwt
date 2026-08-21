"""Host-side regression tests for enhanced-modern2 Feature 12: generic
BWT-aligned tag arrays (``MUS.BWTTags`` plus Feature-12 additions to
``MUS.MultiSourceProvenance``, ``MUS.MultiSourceQuery``, and
``MUS.SourceRemoval``).

These tests are read-only and run on any CPython 3 with NumPy; they do NOT
require the compiled MUSCython extensions (real-merge integration runs in
the pinned Python-2.7 suite and the Feature-12 validation driver).

Coverage:

- the strongest row-identity tag ``row_id``: initially
  ``tag[x] = independently known unique identity of BWT row x``, then
  independently tracked through two-way merges, balanced 10-source
  merges, and Feature-10 source removal using verified interleave tree
  walks (never derived from the BWTTags implementation);
- attach/list/schema/remove/overwrite; shape mismatch; dtype policy
  (object/structured rejected); unsafe names (``/``, ``\\``, ``..``,
  spaces, unicode, NUL) mapped to hash filenames; collision behavior;
- scalar and vector tags across multiple dtypes; mmap loading; direct
  interval slices; corrupt registry/array failures;
- one-sided tags: declared missing value fills only missing rows;
  without a missing value the merge fails BEFORE the BWT merge;
  incompatible schemas fail before the merge;
- retrofit from leaf arrays equals the merge-produced tag
  element-for-element (BWT bytes unchanged);
- removal: ``T_reduced == T_original[keep_mask]`` for every tag; single-
  source removal output equals the leaf array;
- query lifecycle: whole-index exact interval == ``T[l:r]``;
  source/subset/group/where selection == independently projected rows;
  ``tagValueCounts`` == naive counting; vector-tag counts rejected;
  missing tag layer errors; row bounds;
- randomized differentials (seeds 20260811/20260812/20260813);
- evidence-record and validation-driver consistency.
"""

import json
import os
import random
import shutil
import sys
import tempfile
import unittest

import numpy as np

PACKAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "..", "packages", "msbwt-modern2")
# sys.path injection is handled by conftest.py --msbwt-package option

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
from MUS.SourceMetadata import SourceMetadataCatalog  # noqa: E402
from MUS.SourceRemoval import remove_sources  # noqa: E402

import test_multisource_query as f3  # noqa: E402
import test_read_provenance as f9  # noqa: E402

SEEDS = (20260811, 20260812, 20260813)

EVIDENCE = os.path.join(PACKAGE, "evidence", "feature12-bwt-tags.json")
EVIDENCE_GENERATOR = os.path.join(
    PACKAGE, "validate", "feature12_bwt_tags_evidence.py")
VALIDATION_DRIVER = os.path.join(
    PACKAGE, "validate", "feature12-bwt-tags.sh")

MAX_LOCAL = 10000


def row_identity_tag(leaf_dir, all_order):
    rows = f3.load_rows(leaf_dir)
    sid = os.path.basename(leaf_dir)
    return np.asarray(
        [all_order[sid] * MAX_LOCAL + i for i in range(len(rows))],
        dtype=np.uint32,
    )


def unpack_bits(path, total):
    packed = np.load(path, mmap_mode="r")
    needed = (total + 7) // 8
    used = np.asarray(packed[:needed], dtype=np.uint8)
    shifts = np.arange(8, dtype=np.uint8)
    bits = ((used[:, None] >> shifts[None, :]) & np.uint8(1)).reshape(-1)
    return bits[:total]


def row_source(merged_dir, manifest, row_index):
    node = manifest["root"]
    local_index = int(row_index)
    while node["type"] == "merge":
        bits = unpack_bits(os.path.join(
            merged_dir, str(node["interleave"])), node["length"])
        bit = int(bits[local_index])
        if bit == 0:
            local_index = int(np.count_nonzero(bits[:local_index] == 0))
            node = node["left"]
        else:
            local_index = int(np.count_nonzero(bits[:local_index] == 1))
            node = node["right"]
    return str(node["source_id"])


def expected_merged_row_identity(merged_dir, leaves, all_order):
    manifest = load_manifest(merged_dir, validate=True)
    total = int(manifest["root"]["length"])
    expected = np.empty(total, dtype=np.uint32)
    for x in range(total):
        sid, local_row = walk_row(merged_dir, manifest, x)
        expected[x] = all_order[sid] * MAX_LOCAL + local_row
    return expected


def walk_row(merged_dir, manifest, row_index):
    node = manifest["root"]
    local_index = int(row_index)
    while node["type"] == "merge":
        bits = unpack_bits(os.path.join(
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


def naive_interval(directory, pattern):
    suffixes = [row["suffix"] for row in f3.load_rows(directory)]
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


class BWTTagsHostTestBase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f12-host-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def build_tagged_merged(self):
        leaves = {}
        for sid, reads in f3.TEN_SOURCE_READS.items():
            leaf = f3.make_read_derived_leaf(self.work, sid, reads)
            leaves[sid] = leaf
        all_order = {sid: i for i, sid in enumerate(leaves)}
        for sid, leaf in leaves.items():
            attach_tag(
                leaf, "row_id", row_identity_tag(leaf, all_order),
                description="independent row identity")
        output = os.path.join(self.work, "merged10")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f3.read_derived_merge)
        return leaves, output, all_order


class SchemaAndAttachHostTests(BWTTagsHostTestBase):
    def test_attach_list_remove_and_shape_errors(self):
        leaf = f3.make_read_derived_leaf(
            self.work, "src", ["ACGTAC", "GATTACA", "AAAA"])
        rows = len(f3.load_rows(leaf))
        schema = attach_tag(
            leaf, "read_pos", np.arange(rows, dtype=np.uint16),
            description="position inside original read")
        self.assertTrue(tags_exist(leaf))
        store = BWTTagStore(leaf)
        self.assertEqual(store.list_tags(), ["read_pos"])
        self.assertEqual(store.schema("read_pos")["dtype"], "<u2")
        self.assertEqual(store.array("read_pos").shape[0], rows)
        with self.assertRaises(BWTTagError):
            attach_tag(leaf, "bad", np.zeros(3, dtype=np.uint8))
        with self.assertRaises(BWTTagError):
            attach_tag(leaf, "obj", np.zeros(rows, dtype=object))
        structured = np.zeros(rows, dtype=np.dtype([("a", "u1")]))
        with self.assertRaises(BWTTagError):
            attach_tag(leaf, "struct", structured)
        store.release()
        remove_tag(leaf, "read_pos")
        self.assertFalse(tags_exist(leaf))

    def test_unsafe_names_hash_to_safe_filenames(self):
        leaf = f3.make_read_derived_leaf(
            self.work, "src", ["ACGTAC", "AAAA"])
        rows = len(f3.load_rows(leaf))
        for name in ("a/b", "a\\b", "..", "has space", "uni\u00e9"):
            attach_tag(leaf, name, np.zeros(rows, dtype=np.uint8))
        store = BWTTagStore(leaf)
        self.assertEqual(len(store.list_tags()), 5)
        for name in store.list_tags():
            filename = store.schema(name)["filename"]
            self.assertTrue(filename.startswith("bwt_tags/tag_"))
            self.assertNotIn("/", filename[len("bwt_tags/"):])
        with self.assertRaises(BWTTagError):
            attach_tag(leaf, "a/b", np.zeros(rows, dtype=np.uint8))
        attach_tag(leaf, "a/b", np.zeros(rows, dtype=np.uint8),
                   overwrite=True)
        with self.assertRaises(BWTTagError):
            attach_tag(leaf, "bad\x00name", np.zeros(1, dtype=np.uint8))

    def test_vector_and_dtypes_and_mmap(self):
        leaf = f3.make_read_derived_leaf(
            self.work, "src", ["ACGTAC", "AAAA"])
        rows = len(f3.load_rows(leaf))
        attach_tag(leaf, "pair", np.zeros((rows, 2), dtype=np.uint16))
        attach_tag(leaf, "flag", np.ones(rows, dtype=np.bool_))
        attach_tag(leaf, "score", np.full(rows, 1.5, dtype=np.float32))
        store = BWTTagStore(leaf, mmap=True)
        self.assertIsInstance(store.array("pair"), np.memmap)
        self.assertEqual(store.array("pair").shape, (rows, 2))
        self.assertEqual(store.schema("pair")["tail_shape"], [2])
        with self.assertRaises(BWTTagError):
            store.value_counts("pair")
        self.assertEqual(store.array("flag").dtype, np.dtype(np.bool_))

    def test_corrupt_registry_and_array_fail_loudly(self):
        leaf = f3.make_read_derived_leaf(
            self.work, "src", ["ACGTAC", "AAAA"])
        rows = len(f3.load_rows(leaf))
        attach_tag(leaf, "t", np.zeros(rows, dtype=np.uint8))
        reg = os.path.join(leaf, "bwt_tags.json")
        with open(reg, "w") as fp:
            fp.write("{not json")
        with self.assertRaises(BWTTagError):
            BWTTagStore(leaf)
        os.remove(reg)
        attach_tag(leaf, "t", np.zeros(rows, dtype=np.uint8))
        wrong = os.path.join(
            leaf, "bwt_tags",
            os.path.basename(BWTTagStore(leaf).schema("t")["filename"]))
        np.save(wrong, np.zeros(rows + 5, dtype=np.uint8))
        with self.assertRaises(BWTTagError):
            BWTTagStore(leaf)


class MergeLifecycleHostTests(BWTTagsHostTestBase):
    def test_two_way_and_balanced_merges_preserve_row_identity(self):
        leaves, output, all_order = self.build_tagged_merged()
        store = BWTTagStore(output)
        expected = expected_merged_row_identity(
            output, leaves, all_order)
        self.assertTrue(np.array_equal(store.array("row_id"), expected))
        self.assertEqual(store.bwt_length, 191)
        # two-way
        two_leaves = {}
        for sid, reads in (("A", ["ACGTAC", "GATTACA", "AAAA"]),
                           ("B", ["TTTT", "GCGTAC"])):
            leaf = f3.make_read_derived_leaf(self.work, sid, reads)
            two_leaves[sid] = leaf
        two_order = {sid: i for i, sid in enumerate(two_leaves)}
        for sid, leaf in two_leaves.items():
            attach_tag(leaf, "row_id", row_identity_tag(leaf, two_order))
        out2 = os.path.join(self.work, "two")
        merge_two_with_provenance(
            two_leaves["A"], two_leaves["B"], out2,
            merge_two_func=f3.read_derived_merge)
        store2 = BWTTagStore(out2)
        self.assertTrue(np.array_equal(
            store2.array("row_id"),
            expected_merged_row_identity(out2, two_leaves, two_order)))

    def test_one_sided_tag_policies(self):
        leaf_a = f3.make_read_derived_leaf(
            self.work, "A", ["ACGTAC", "AAAA"])
        leaf_b = f3.make_read_derived_leaf(
            self.work, "B", ["TTTT", "CCCC"])
        rows_a = len(f3.load_rows(leaf_a))
        attach_tag(leaf_a, "code", np.zeros(rows_a, dtype=np.uint8))
        called = [False]

        def should_not_run(*args, **kwargs):
            called[0] = True

        with self.assertRaises(BWTTagError):
            merge_two_with_provenance(
                leaf_a, leaf_b, os.path.join(self.work, "bad"),
                merge_two_func=should_not_run)
        self.assertFalse(called[0])
        # with a declared missing value the merge proceeds and fills
        remove_tag(leaf_a, "code")
        attach_tag(leaf_a, "opt",
                   np.asarray(list(range(rows_a)), dtype=np.uint8),
                   missing_value=0)
        output = os.path.join(self.work, "merged")
        merge_two_with_provenance(
            leaf_a, leaf_b, output,
            merge_two_func=f3.read_derived_merge)
        store = BWTTagStore(output)
        values = store.array("opt")
        manifest = load_manifest(output)
        b_rows = [x for x in range(values.shape[0])
                  if row_source(output, manifest, x) == "B"]
        a_rows = [x for x in range(values.shape[0])
                  if row_source(output, manifest, x) == "A"]
        self.assertEqual(sorted(values[a_rows].tolist()),
                         list(range(rows_a)))
        self.assertEqual(set(values[b_rows].tolist()), set([0]))
        # incompatible schema fails before the merge
        rows_b = len(f3.load_rows(leaf_b))
        attach_tag(leaf_b, "code", np.zeros(rows_b, dtype=np.uint16))
        with self.assertRaises(BWTTagError):
            merge_two_with_provenance(
                leaf_a, leaf_b, os.path.join(self.work, "bad2"),
                merge_two_func=should_not_run)


class RetrofitAndRemovalHostTests(BWTTagsHostTestBase):
    def test_retrofit_equals_merge_produced_tag_exactly(self):
        leaves, output, all_order = self.build_tagged_merged()
        remove_tag(output, "row_id")
        self.assertFalse(tags_exist(output))
        arrays_by_source = {
            sid: os.path.join(leaf, "bwt_tags",
                              os.path.basename(
                                  BWTTagStore(leaf).schema(
                                      "row_id")["filename"]))
            for sid, leaf in leaves.items()
        }
        build_tag_from_leaf_arrays(output, "row_id", arrays_by_source)
        store = BWTTagStore(output)
        self.assertTrue(np.array_equal(
            store.array("row_id"),
            expected_merged_row_identity(output, leaves, all_order)))

    def test_removal_filters_every_tag_with_bwt_mask(self):
        leaves, output, all_order = self.build_tagged_merged()
        store = BWTTagStore(output)
        keep_set = set(s for s in f3.TEN_SOURCE_READS
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
        self.assertTrue(np.array_equal(
            rstore.array("row_id"),
            expected_merged_row_identity(reduced, leaves, all_order)))
        # single-source removal equals the leaf array
        single = os.path.join(self.work, "single")
        remove_sources(output, single, sources=[
            sid for sid in f3.TEN_SOURCE_READS if sid != "sample07"])
        self.assertTrue(np.array_equal(
            BWTTagStore(single).array("row_id"),
            row_identity_tag(leaves["sample07"], all_order)))


class QueryLifecycleHostTests(BWTTagsHostTestBase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f12-host-query-")
        cls.leaves = {}
        for sid, reads in f3.TEN_SOURCE_READS.items():
            leaf = f3.make_read_derived_leaf(cls.work, sid, reads)
            cls.leaves[sid] = leaf
        cls.all_order = {sid: i for i, sid in enumerate(cls.leaves)}
        for sid, leaf in cls.leaves.items():
            attach_tag(
                leaf, "row_id", row_identity_tag(leaf, cls.all_order))
        cls.output = os.path.join(cls.work, "merged10")
        merge_many_balanced(
            list(cls.leaves.values()), cls.output,
            merge_two_func=f3.read_derived_merge)
        cls.store = BWTTagStore(cls.output)
        cls.index = MultiSourceQueryIndex(
            cls.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        cls.wrapped = MultiSourceBWT(None, cls.index, bwt_tags=cls.store)
        cls.wrapped.bwt = f9.OracleBWTAdapter(
            f9.OracleReadIdentity(
                cls.output,
                {sid: cls.leaves[sid] for sid in cls.leaves},
                f3.TEN_SOURCE_READS),
            cls.output, load_manifest(cls.output))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_whole_interval_and_source_filtered_values(self):
        manifest = load_manifest(self.output)
        for pattern in ("A", "AC", "CGT", "AAAA", "N", "AAGGTT"):
            low, high = naive_interval(self.output, pattern)
            result = self.wrapped.tagValues(pattern, "row_id")
            self.assertEqual(result["value_count"], high - low, pattern)
            self.assertTrue(np.array_equal(
                result["values"],
                self.store.array("row_id")[low:high]), pattern)
            self.assertTrue(np.array_equal(
                self.wrapped.tagInterval("row_id", low, high),
                self.store.array("row_id")[low:high]))
            for sid in ("sample00", "sample03", "sample09"):
                sresult = self.wrapped.tagValues(
                    pattern, "row_id", source=sid)
                expected_rows = [
                    x for x in range(low, high)
                    if row_source(self.output, manifest, x) == sid
                ]
                self.assertEqual(
                    sresult["value_count"], len(expected_rows),
                    (pattern, sid))
                self.assertTrue(np.array_equal(
                    sresult["values"],
                    self.store.array("row_id")[expected_rows]),
                    (pattern, sid))

    def test_group_where_and_counts(self):
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
        group_rows = [
            x for x in range(low, high)
            if row_source(self.output, manifest, x)
            in ("sample00", "sample01", "sample02")
        ]
        group_result = wrapped.tagValues(
            pattern, "row_id", group="case")
        self.assertEqual(group_result["value_count"], len(group_rows))
        self.assertTrue(np.array_equal(
            group_result["values"],
            self.store.array("row_id")[group_rows]))
        where_result = wrapped.tagValues(
            pattern, "row_id", where={"cohort": "case"})
        self.assertEqual(where_result["value_count"], len(group_rows))
        # exact counts vs naive counting
        values = self.store.array("row_id")[low:high]
        unique, counts = np.unique(values, return_counts=True)
        counts_result = wrapped.tagValueCounts(pattern, "row_id")
        table = {item["value"]: item["count"]
                 for item in counts_result["counts"]}
        self.assertEqual(
            table, {int(u): int(c) for u, c in zip(unique, counts)})

    def test_errors(self):
        plain = MultiSourceBWT(None, self.index)
        plain.bwt = self.wrapped.bwt
        with self.assertRaises(MultiSourceQueryError):
            plain.listTags()
        with self.assertRaises(KeyError):
            self.wrapped.tagValues("A", "ghost_tag")
        with self.assertRaises(IndexError):
            self.wrapped.rowTag(self.store.bwt_length, "row_id")


class RandomizedTagHostTests(BWTTagsHostTestBase):
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
                    leaf = f3.make_read_derived_leaf(self.work, sid, reads)
                    leaves[sid] = leaf
                all_order = {sid: i for i, sid in enumerate(leaves)}
                for sid, leaf in leaves.items():
                    attach_tag(
                        leaf, "row_id", row_identity_tag(leaf, all_order))
                output = os.path.join(
                    self.work, "rand_%02d_%02d" % (seed_index, case))
                merge_many_balanced(
                    list(leaves.values()), output,
                    merge_two_func=f3.read_derived_merge)
                store = BWTTagStore(output)
                self.assertTrue(np.array_equal(
                    store.array("row_id"),
                    expected_merged_row_identity(
                        output, leaves, all_order)),
                    (seed, case))
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
                self.assertTrue(np.array_equal(
                    rstore.array("row_id"),
                    expected_merged_row_identity(
                        reduced, leaves, all_order)),
                    (seed, case))


class EvidenceConsistencyTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = json.load(open(EVIDENCE, encoding="utf-8"))
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "enhanced-modern2")
        self.assertEqual(
            evidence["final"]["milestone"],
            "enhanced-modern2-feature12-bwt-tags")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")

    def test_evidence_contract(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["seed"], 20260811)
        merged = report["merge_lifecycle"]
        self.assertEqual(merged["rows"], 191)
        self.assertEqual(merged["mismatches"], 0)
        self.assertTrue(report["one_sided_policies"]["without_missing"])
        retrofit = report["retrofit"]
        self.assertEqual(retrofit["mismatches"], 0)
        removal = report["removal"]
        self.assertEqual(removal["mismatches"], 0)
        self.assertTrue(removal["single_source_equals_leaf"])
        rand = report["randomized"]
        self.assertEqual(rand["seed"], 20260811)
        self.assertEqual(rand["mismatches"], 0)
        self.assertGreaterEqual(rand["cases"], 18)

    def test_evidence_generator_is_python2_and_driver_checks(self):
        with open(EVIDENCE_GENERATOR, "rb") as fp:
            text = fp.read().decode("utf-8")
        self.assertIn("Python 2.7 only", text)
        self.assertIn("def run_evidence", text)
        with open(VALIDATION_DRIVER, "rb") as fp:
            driver = fp.read().decode("utf-8")
        self.assertIn("--evidence", driver)
        self.assertIn("run_evidence", driver)
        self.assertIn("feature12-bwt-tags", driver)


if __name__ == "__main__":
    unittest.main()
