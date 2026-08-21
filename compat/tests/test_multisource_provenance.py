"""Host-side regression tests for enhanced-modern2 Feature 2:
persistent multi-source provenance (``MUS.MultiSourceProvenance``).

These tests are read-only and run on any CPython 3 with NumPy; they do NOT
require the compiled MUSCython extensions (real-merge integration runs in the
pinned Python-2.7 suite and the Feature-2 validation driver).

Coverage:

- little-endian pack/unpack convention and padding isolation;
- leaf manifest identity: stable explicit IDs, auto UUID, overwrite
  semantics, save/reload stability, leaf BWT digest verification;
- two-way packaging: root ``inter0.npy`` retained (Feature-1 compatible),
  interleave copies, duplicate-ID rejection BEFORE the merge runs,
  output-dir safety, merged-length check;
- multi-source merges with a deterministic fake two-way merger: 4-way
  balanced, 8-way balanced, 5-leaf uneven, 3-source chain (unbalanced),
  alternate 4-source merge order, portability after deleting
  originals/intermediates;
- persistence/corruption matrix: reload, ID stability, truncated/non-JSON
  manifest, wrong format/version, missing digest fields, same-length
  replaced BWT, manifest copied from another index, same-length same-count
  replaced interleave (digest must catch it), wrong-dtype interleave,
  missing interleave, BWT-length mismatch;
- atomic manifest writes (no ``.tmp`` left behind, deterministic bytes);
- deterministic randomized fake-merge differential: 40 datasets with 3-8
  sources plus 4 explicit 10-source datasets (seed 20260811): exact
  constituent recovery, per-source totals, BWT-length invariant;
- public surface and Python-2 safety of the production module;
- Feature-2 evidence-record and validation-driver consistency.
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

from MUS.MultiSourceProvenance import (  # noqa: E402
    BWT_FILENAME,
    FORMAT_NAME,
    FORMAT_VERSION,
    INTERLEAVE_FILENAME,
    MANIFEST_FILENAME,
    ProvenanceError,
    ensure_provenance,
    extract_all_constituent_bwts,
    extract_constituent_bwt,
    initialize_leaf_provenance,
    list_sources,
    load_manifest,
    merge_many_balanced,
    merge_two_with_provenance,
    save_manifest,
    source_ids,
    unpack_interleave,
    validate_manifest,
)

SEED = 20260811


def pack_little_endian_bits(bits):
    """Pack bits exactly like GenericMerge.pyx: bit i is 1 << (i & 7)."""
    bits = [int(b) for b in bits]
    nbytes = (len(bits) + 7) // 8
    arr = np.zeros(nbytes, dtype=np.uint8)
    for i, bit in enumerate(bits):
        if bit:
            arr[i >> 3] |= np.uint8(1 << (i & 7))
    return arr


def deterministic_bits(n_left, n_right):
    """Stable, nontrivial 0/1 interleave with exact child counts."""
    bits = []
    left = right = 0
    while left < n_left or right < n_right:
        if left < n_left and (right >= n_right or left <= right):
            bits.append(0)
            left += 1
        elif right < n_right:
            bits.append(1)
            right += 1
    return bits


def fake_holt_merge(left_dir, right_dir, output_dir, num_procs=1,
                    logger=None):
    """Stable two-stream merger with the same inter0 semantics as Holt."""
    left = np.load(os.path.join(left_dir, "msbwt.npy"))
    right = np.load(os.path.join(right_dir, "msbwt.npy"))
    bits = deterministic_bits(len(left), len(right))

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    merged = np.empty(len(bits), dtype=np.uint8)
    li = ri = 0
    for i, bit in enumerate(bits):
        if bit:
            merged[i] = right[ri]
            ri += 1
        else:
            merged[i] = left[li]
            li += 1

    np.save(os.path.join(output_dir, "msbwt.npy"), merged)
    np.save(os.path.join(output_dir, "inter0.npy"),
            pack_little_endian_bits(bits))


def make_leaf(work, name, values, source_id=None):
    path = os.path.join(work, name)
    os.mkdir(path)
    np.save(os.path.join(path, "msbwt.npy"),
            np.asarray(values, dtype=np.uint8))
    initialize_leaf_provenance(path, source_id=source_id or name,
                               source_name=name)
    return path


def max_depth(node):
    if node["type"] == "leaf":
        return 0
    return 1 + max(max_depth(node["left"]), max_depth(node["right"]))


class UnpackConventionTests(unittest.TestCase):
    def test_little_endian_unpack_matches_generic_merge(self):
        path = os.path.join(tempfile.mkdtemp(prefix="f2-host-"), "bits.npy")
        try:
            np.save(path, np.asarray([0b10000101, 0xFF], dtype=np.uint8))
            bits = unpack_interleave(path, 10)
            self.assertEqual(bits.tolist(), [1, 0, 1, 0, 0, 0, 0, 1, 1, 1])
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_module_packer_round_trip(self):
        from MUS.MultiSourceProvenance import _pack_little_endian_bits
        for length in (0, 1, 7, 8, 9, 63, 64, 65, 130):
            bits = [int(i * 7 % 3 == 0) for i in range(length)]
            path = os.path.join(tempfile.mkdtemp(prefix="f2-host-"),
                                "bits.npy")
            try:
                np.save(path, _pack_little_endian_bits(bits))
                self.assertEqual(unpack_interleave(path, length).tolist(),
                                 bits)
            finally:
                shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_zero_bits(self):
        path = os.path.join(tempfile.mkdtemp(prefix="f2-host-"), "bits.npy")
        try:
            np.save(path, np.zeros(0, dtype=np.uint8))
            self.assertEqual(unpack_interleave(path, 0).tolist(), [])
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_wrong_dtype_and_dimensions_rejected(self):
        work = tempfile.mkdtemp(prefix="f2-host-")
        try:
            bad_dtype = os.path.join(work, "u16.npy")
            np.save(bad_dtype, np.zeros(2, dtype=np.uint16))
            with self.assertRaises(ProvenanceError):
                unpack_interleave(bad_dtype, 8)
            bad_shape = os.path.join(work, "2d.npy")
            np.save(bad_shape, np.zeros((2, 2), dtype=np.uint8))
            with self.assertRaises(ProvenanceError):
                unpack_interleave(bad_shape, 8)
            short = os.path.join(work, "short.npy")
            np.save(short, np.zeros(1, dtype=np.uint8))
            with self.assertRaises(ProvenanceError):
                unpack_interleave(short, 16)
        finally:
            shutil.rmtree(work, ignore_errors=True)


class LeafManifestTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f2-host-leaf-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_stable_explicit_identity_and_reload(self):
        leaf = make_leaf(self.work, "sample-A", [1, 2, 3, 4])
        manifest = load_manifest(leaf)
        self.assertEqual(manifest["root"]["type"], "leaf")
        self.assertEqual(manifest["root"]["source_id"], "sample-A")
        self.assertEqual(manifest["bwt_length"], 4)
        self.assertEqual(manifest["format"], FORMAT_NAME)
        self.assertEqual(manifest["version"], FORMAT_VERSION)
        self.assertIn("msbwt_sha256", manifest)
        self.assertEqual(source_ids(leaf), ["sample-A"])
        self.assertEqual(list_sources(leaf)[0]["name"], "sample-A")
        self.assertEqual(len(list_sources(leaf)[0]["bwt_sha256"]), 64)
        self.assertTrue(validate_manifest(leaf))
        self.assertEqual(source_ids(leaf), ["sample-A"])

    def test_auto_uuid_and_overwrite_semantics(self):
        leaf = os.path.join(self.work, "auto")
        os.mkdir(leaf)
        np.save(os.path.join(leaf, "msbwt.npy"), np.asarray([9], dtype=np.uint8))
        manifest = initialize_leaf_provenance(leaf)
        sid = source_ids(leaf)[0]
        self.assertEqual(len(sid), 36)
        self.assertEqual(manifest["root"]["source_id"], sid)
        # existing manifest is authoritative without overwrite
        initialize_leaf_provenance(leaf, source_id="other")
        self.assertEqual(source_ids(leaf), [sid])
        initialize_leaf_provenance(leaf, source_id="other", overwrite=True)
        self.assertEqual(source_ids(leaf), ["other"])

    def test_same_length_replaced_leaf_bwt_is_detected(self):
        leaf = make_leaf(self.work, "guarded", [1, 2, 3])
        original = np.load(os.path.join(leaf, "msbwt.npy"))
        changed = original.copy()
        changed[0] = changed[0] ^ np.uint8(1)
        np.save(os.path.join(leaf, "msbwt.npy"), changed)
        with self.assertRaises(ProvenanceError):
            load_manifest(leaf)

    def test_ensure_provenance_creates_or_loads(self):
        leaf = make_leaf(self.work, "ens", [1, 2])
        manifest = ensure_provenance(leaf, source_id="ens", source_name="ens")
        self.assertEqual(source_ids(leaf), ["ens"])
        self.assertEqual(ensure_provenance(leaf), manifest)


class TwoWayMergeTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f2-host-twoway-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_two_way_merge_copies_root_interleave_into_portable_store(self):
        left = make_leaf(self.work, "A", [10, 11, 12])
        right = make_leaf(self.work, "B", [20, 21])
        merged = os.path.join(self.work, "AB")

        manifest = merge_two_with_provenance(
            left, right, merged, merge_two_func=fake_holt_merge)

        self.assertTrue(os.path.exists(
            os.path.join(merged, INTERLEAVE_FILENAME)))  # Feature-1 compat
        saved = os.path.join(merged, manifest["root"]["interleave"])
        self.assertTrue(os.path.exists(saved))
        self.assertTrue(np.array_equal(
            np.load(saved), np.load(os.path.join(merged, INTERLEAVE_FILENAME))))
        self.assertEqual(source_ids(merged), ["A", "B"])
        self.assertEqual(manifest["root"]["length"], 5)
        self.assertTrue(validate_manifest(merged))

    def test_duplicate_constituent_id_rejected_before_merge(self):
        left = make_leaf(self.work, "left", [1, 2])
        right = make_leaf(self.work, "right", [3, 4])
        initialize_leaf_provenance(right, source_id="left",
                                   source_name="dup", overwrite=True)

        called = {"value": False}

        def should_not_run(*args, **kwargs):
            called["value"] = True

        with self.assertRaises(ProvenanceError):
            merge_two_with_provenance(
                left, right, os.path.join(self.work, "bad"),
                merge_two_func=should_not_run)
        self.assertFalse(called["value"])

    def test_merged_length_mismatch_rejected(self):
        left = make_leaf(self.work, "A", [1, 2])
        right = make_leaf(self.work, "B", [3, 4])

        def wrong_merge(left_dir, right_dir, output_dir, num_procs=1,
                        logger=None):
            if not os.path.isdir(output_dir):
                os.makedirs(output_dir)
            np.save(os.path.join(output_dir, "msbwt.npy"),
                    np.zeros(5, dtype=np.uint8))
            np.save(os.path.join(output_dir, "inter0.npy"),
                    np.zeros(1, dtype=np.uint8))

        with self.assertRaises(ProvenanceError):
            merge_two_with_provenance(
                left, right, os.path.join(self.work, "bad"),
                merge_two_func=wrong_merge)

    def test_nonempty_output_directory_rejected(self):
        left = make_leaf(self.work, "A", [1])
        right = make_leaf(self.work, "B", [2])
        output = os.path.join(self.work, "occupied")
        os.mkdir(output)
        with open(os.path.join(output, "junk.txt"), "w") as handle:
            handle.write("x")
        with self.assertRaises(ProvenanceError):
            merge_two_with_provenance(
                left, right, output, merge_two_func=fake_holt_merge)


class MultiSourceFakeMergeTests(unittest.TestCase):
    """Mirrors the candidate's unit tests against the production module."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f2-host-multi-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _leaves_and_originals(self, names, values_by_name):
        leaves = []
        originals = {}
        for name in names:
            leaf = make_leaf(self.work, name, values_by_name[name])
            leaves.append(leaf)
            originals[name] = np.asarray(values_by_name[name],
                                         dtype=np.uint8).copy()
        return leaves, originals

    def test_four_way_balanced_merge_recovers_every_constituent_exactly(self):
        leaves, originals = self._leaves_and_originals(
            "ABCD", {"A": [10, 11, 12, 13], "B": [20, 21, 22],
                     "C": [30, 31, 32, 33, 34], "D": [40, 41]})
        output = os.path.join(self.work, "ABCD")
        manifest = merge_many_balanced(
            leaves, output, merge_two_func=fake_holt_merge)

        self.assertEqual(source_ids(output), ["A", "B", "C", "D"])
        self.assertEqual(max_depth(manifest["root"]), 2)
        for sid, expected in originals.items():
            np.testing.assert_array_equal(
                extract_constituent_bwt(output, sid), expected)

    def test_eight_way_balanced_merge_recovers_every_constituent_exactly(self):
        leaves = []
        originals = {}
        for i, name in enumerate("ABCDEFGH"):
            values = np.arange(3 + (i % 4), dtype=np.uint8) + (i + 1) * 20
            leaf = make_leaf(self.work, name, values)
            leaves.append(leaf)
            originals[name] = values.copy()

        output = os.path.join(self.work, "ALL8")
        manifest = merge_many_balanced(
            leaves, output, merge_two_func=fake_holt_merge)

        self.assertEqual(max_depth(manifest["root"]), 3)
        self.assertEqual(source_ids(output), list("ABCDEFGH"))
        self.assertTrue(validate_manifest(output))
        for sid, expected in originals.items():
            np.testing.assert_array_equal(
                extract_constituent_bwt(output, sid), expected)

    def test_uneven_input_count_stays_shallow_and_recovers_all(self):
        leaves = []
        originals = {}
        for i, name in enumerate("ABCDE"):
            values = np.asarray([i * 10 + 1, i * 10 + 2], dtype=np.uint8)
            leaf = make_leaf(self.work, name, values)
            leaves.append(leaf)
            originals[name] = values.copy()

        output = os.path.join(self.work, "ALL5")
        manifest = merge_many_balanced(
            leaves, output, merge_two_func=fake_holt_merge)

        self.assertEqual(max_depth(manifest["root"]), 3)
        for sid, expected in originals.items():
            np.testing.assert_array_equal(
                extract_constituent_bwt(output, sid), expected)

    def test_three_source_unbalanced_chain(self):
        a = make_leaf(self.work, "A", [1, 2, 3])
        b = make_leaf(self.work, "B", [4, 5])
        c = make_leaf(self.work, "C", [6, 7, 8, 9])
        ab = os.path.join(self.work, "AB")
        merge_two_with_provenance(a, b, ab, merge_two_func=fake_holt_merge)
        abc = os.path.join(self.work, "ABC")
        manifest = merge_two_with_provenance(
            ab, c, abc, merge_two_func=fake_holt_merge)
        self.assertEqual(source_ids(abc), ["A", "B", "C"])
        for name, expected in (("A", [1, 2, 3]), ("B", [4, 5]),
                               ("C", [6, 7, 8, 9])):
            np.testing.assert_array_equal(
                extract_constituent_bwt(abc, name),
                np.asarray(expected, dtype=np.uint8))

    def test_alternate_four_source_merge_order(self):
        leaves, originals = self._leaves_and_originals(
            "ABCD", {"A": [1, 2], "B": [3, 4], "C": [5, 6], "D": [7, 8]})
        abc = os.path.join(self.work, "ABC")
        merge_two_with_provenance(leaves[0], leaves[1], abc,
                                  merge_two_func=fake_holt_merge)
        abc2 = os.path.join(self.work, "ABC2")
        merge_two_with_provenance(abc, leaves[2], abc2,
                                  merge_two_func=fake_holt_merge)
        abcd = os.path.join(self.work, "ABCD")
        manifest = merge_two_with_provenance(abc2, leaves[3], abcd,
                                             merge_two_func=fake_holt_merge)
        self.assertEqual(source_ids(abcd), ["A", "B", "C", "D"])
        self.assertEqual(max_depth(manifest["root"]), 3)
        for sid, expected in originals.items():
            np.testing.assert_array_equal(
                extract_constituent_bwt(abcd, sid), expected)

    def test_final_package_is_portable_after_intermediates_removed(self):
        leaves, originals = self._leaves_and_originals(
            "ABCD", {"A": [1, 2, 3], "B": [11, 12, 13],
                     "C": [21, 22, 23], "D": [31, 32, 33]})
        work = os.path.join(self.work, "work")
        output = os.path.join(self.work, "portable")

        merge_many_balanced(
            leaves, output, merge_two_func=fake_holt_merge, work_dir=work)

        for leaf in leaves:
            shutil.rmtree(leaf)
        shutil.rmtree(work)

        for sid, expected in originals.items():
            np.testing.assert_array_equal(
                extract_constituent_bwt(output, sid), expected)

    def test_single_input_copies_package(self):
        leaf = make_leaf(self.work, "only", [1, 2, 3])
        output = os.path.join(self.work, "copy")
        merge_many_balanced([leaf], output, merge_two_func=fake_holt_merge)
        self.assertEqual(source_ids(output), ["only"])
        np.testing.assert_array_equal(
            extract_constituent_bwt(output, "only"),
            np.asarray([1, 2, 3], dtype=np.uint8))

    def test_duplicate_ids_across_many_inputs_rejected_early(self):
        leaves = [
            make_leaf(self.work, "A", [1]),
            make_leaf(self.work, "B", [2]),
            make_leaf(self.work, "C", [3]),
        ]
        initialize_leaf_provenance(leaves[2], source_id="A",
                                   source_name="dup", overwrite=True)
        with self.assertRaises(ProvenanceError):
            merge_many_balanced(
                leaves, os.path.join(self.work, "bad"),
                merge_two_func=fake_holt_merge)
        self.assertFalse(os.path.exists(os.path.join(self.work, "bad")))


class CorruptionMatrixTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f2-host-corrupt-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        left = make_leaf(self.work, "A", [1, 2, 3])
        right = make_leaf(self.work, "B", [4, 5])
        self.merged = os.path.join(self.work, "AB")
        self.manifest = merge_two_with_provenance(
            left, right, self.merged, merge_two_func=fake_holt_merge)

    def test_reload_preserves_everything(self):
        self.assertEqual(load_manifest(self.merged), self.manifest)
        self.assertEqual(source_ids(self.merged), ["A", "B"])
        self.assertTrue(validate_manifest(self.merged))

    def test_truncated_and_non_json_manifests_rejected(self):
        path = os.path.join(self.merged, MANIFEST_FILENAME)
        with open(path, "ab") as handle:
            handle.write(b'{"truncated":')
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)
        with open(path, "wb") as handle:
            handle.write(b"this is not json")
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_wrong_format_and_version_rejected(self):
        bad = json.loads(json.dumps(self.manifest))
        bad["format"] = "not-msbwt-provenance"
        save_manifest(self.merged, bad)
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)
        bad2 = json.loads(json.dumps(self.manifest))
        bad2["version"] = FORMAT_VERSION + 1
        save_manifest(self.merged, bad2)
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_missing_identity_fields_rejected(self):
        bad = json.loads(json.dumps(self.manifest))
        del bad["msbwt_sha256"]
        save_manifest(self.merged, bad)
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)
        bad2 = json.loads(json.dumps(self.manifest))
        del bad2["sources"][0]["bwt_sha256"]
        save_manifest(self.merged, bad2)
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_same_length_replaced_bwt_rejected(self):
        bwt_path = os.path.join(self.merged, BWT_FILENAME)
        original = np.load(bwt_path)
        changed = original.copy()
        changed[0] = changed[0] ^ np.uint8(1)
        np.save(bwt_path, changed)
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_manifest_copied_from_other_index_rejected(self):
        other_left = make_leaf(self.work, "X", [9, 8, 7])
        other_right = make_leaf(self.work, "Y", [6, 5])
        other = os.path.join(self.work, "XY")
        merge_two_with_provenance(other_left, other_right, other,
                                  merge_two_func=fake_holt_merge)
        shutil.copyfile(
            os.path.join(self.merged, MANIFEST_FILENAME),
            os.path.join(other, MANIFEST_FILENAME))
        with self.assertRaises(ProvenanceError):
            load_manifest(other)

    def test_same_length_same_count_replaced_interleave_rejected(self):
        # reversed bits keep length AND zero/one counts (2 vs 2 here); only
        # the digest identity can catch this
        left = make_leaf(self.work, "A2", [1, 2])
        right = make_leaf(self.work, "B2", [3, 4])
        merged = os.path.join(self.work, "AB2")
        manifest = merge_two_with_provenance(
            left, right, merged, merge_two_func=fake_holt_merge)
        node = manifest["root"]
        inter_path = os.path.join(merged, node["interleave"])
        bits = unpack_interleave(inter_path, node["length"])
        self.assertNotEqual(bits.tolist(), list(reversed(bits)))
        replaced = pack_little_endian_bits(list(reversed(bits)))
        np.save(inter_path, replaced)
        with self.assertRaises(ProvenanceError):
            load_manifest(merged)

    def test_wrong_dtype_interleave_rejected(self):
        node = self.manifest["root"]
        inter_path = os.path.join(self.merged, node["interleave"])
        packed = np.load(inter_path)
        np.save(inter_path, packed.astype(np.uint16))
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_missing_interleave_rejected(self):
        node = self.manifest["root"]
        os.remove(os.path.join(self.merged, node["interleave"]))
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_bwt_length_mismatch_rejected(self):
        bad = json.loads(json.dumps(self.manifest))
        bad["bwt_length"] = bad["bwt_length"] + 1
        save_manifest(self.merged, bad)
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_unknown_source_extraction_raises(self):
        with self.assertRaises(KeyError):
            extract_constituent_bwt(self.merged, "nope")
        with self.assertRaises(ProvenanceError):
            extract_all_constituent_bwts(os.path.join(self.work, "missing"))


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f2-host-atomic-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_save_manifest_is_atomic_and_deterministic(self):
        leaf = make_leaf(self.work, "A", [1, 2])
        self.assertEqual(
            [n for n in os.listdir(leaf) if n.endswith(".tmp")], [])
        manifest = load_manifest(leaf)
        save_manifest(leaf, manifest)
        save_manifest(leaf, manifest)
        with open(os.path.join(leaf, MANIFEST_FILENAME), "rb") as handle:
            first = handle.read()
        save_manifest(leaf, manifest)
        with open(os.path.join(leaf, MANIFEST_FILENAME), "rb") as handle:
            second = handle.read()
        self.assertEqual(first, second)
        self.assertEqual(
            [n for n in os.listdir(leaf) if n.endswith(".tmp")], [])


class RandomizedFakeMergeDifferentialTests(unittest.TestCase):
    """40 datasets with 3-8 sources + 4 explicit 10-source datasets
    (seed 20260811): exact constituent recovery, totals, BWT length."""

    DATASETS = 40
    TEN_SOURCE_DATASETS = 4

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f2-host-random-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_randomized_datasets(self):
        rng = random.Random(SEED)
        checked = 0
        for case_index in range(self.DATASETS):
            source_count = rng.randint(3, 8)
            leaves = []
            originals = {}
            for i in range(source_count):
                length = rng.randint(1, 12)
                values = np.asarray(
                    [rng.randint(0, 5) for _ in range(length)],
                    dtype=np.uint8)
                leaf = make_leaf(self.work, "d%02d-s%d" % (case_index, i),
                                 values, source_id="s%d" % i)
                leaves.append(leaf)
                originals["s%d" % i] = values.copy()

            output = os.path.join(self.work, "d%02d-out" % case_index)
            manifest = merge_many_balanced(
                leaves, output, merge_two_func=fake_holt_merge,
                source_ids=["s%d" % i for i in range(source_count)],
                source_names=["s%d" % i for i in range(source_count)])
            expected_total = sum(int(values.shape[0])
                                 for values in originals.values())
            self.assertEqual(manifest["bwt_length"], expected_total)
            self.assertEqual(manifest["root"]["length"], expected_total)
            self.assertEqual(
                source_ids(output),
                ["s%d" % i for i in range(source_count)])
            for sid, expected in originals.items():
                np.testing.assert_array_equal(
                    extract_constituent_bwt(output, sid), expected)
                checked += 1
            self.assertTrue(validate_manifest(output))
        self.assertGreater(checked, 40 * 3)

    def test_explicit_ten_source_datasets(self):
        rng = random.Random(SEED + 1000)
        for case_index in range(self.TEN_SOURCE_DATASETS):
            leaves = []
            originals = {}
            for i in range(10):
                values = np.asarray(
                    [v % 6 for v in
                     np.arange(3 + (i + case_index) % 5, dtype=np.uint8)],
                    dtype=np.uint8)
                leaf = make_leaf(self.work, "t%02d-s%d" % (case_index, i),
                                 values, source_id="s%d" % i)
                leaves.append(leaf)
                originals["s%d" % i] = values.copy()
            output = os.path.join(self.work, "t%02d-out" % case_index)
            manifest = merge_many_balanced(
                leaves, output, merge_two_func=fake_holt_merge,
                source_ids=["s%d" % i for i in range(10)])
            self.assertEqual(max_depth(manifest["root"]), 4)
            for sid, expected in originals.items():
                np.testing.assert_array_equal(
                    extract_constituent_bwt(output, sid), expected)
            self.assertEqual(
                manifest["bwt_length"],
                sum(int(v.shape[0]) for v in originals.values()))


class PublicSurfaceTests(unittest.TestCase):
    def test_public_symbols_exist(self):
        import MUS.MultiSourceProvenance as module
        for name in (
            "ProvenanceError",
            "MANIFEST_FILENAME",
            "FORMAT_NAME",
            "FORMAT_VERSION",
            "initialize_leaf_provenance",
            "ensure_provenance",
            "save_manifest",
            "load_manifest",
            "validate_manifest",
            "list_sources",
            "source_ids",
            "source_ids_from_manifest",
            "merge_two_with_provenance",
            "merge_many_balanced",
            "holt_merge_two",
            "unpack_interleave",
            "extract_constituent_bwt",
            "extract_all_constituent_bwts",
        ):
            self.assertTrue(hasattr(module, name), name)

    def test_module_is_pure_python_no_module_level_musc_cython(self):
        text = open(os.path.join(PACKAGE, "MUS",
                                 "MultiSourceProvenance.py"), "rb").read()
        self.assertNotIn(b"\nimport MUSCython", text)
        self.assertNotIn(b"\nfrom MUSCython", text)
        self.assertIn(b"from MUSCython import GenericMerge", text)

    def test_module_source_is_python2_safe(self):
        text = open(os.path.join(PACKAGE, "MUS",
                                 "MultiSourceProvenance.py"), "rb").read()
        self.assertIn(b"from __future__ import absolute_import", text)
        self.assertNotIn(b"import pathlib", text)
        self.assertNotIn(b"from pathlib", text)
        # the whole file must clear the baseline py3-syntax scan: no
        # open(..., encoding=...) and no bare os.replace / os.fsencode
        self.assertNotIn(b"encoding=", text)
        self.assertIn(b"json.dumps(", text)
        # os.replace / os.fsencode are used only behind Python-2-safe guards
        self.assertIn(b'hasattr(os, "replace")', text)
        self.assertIn(b'hasattr(os, "fsencode")', text)
        self.assertNotIn(b"f'{", text)
        self.assertNotIn(b"f\"{", text)
        self.assertNotIn(b"from __future__ import annotations", text)
        self.assertNotIn(b"def validate_manifest(bwt_dir, manifest=None) ->", text)

    def test_feature1_module_unchanged(self):
        text = open(os.path.join(PACKAGE, "MUS", "SourceIndex.py"), "rb").read()
        self.assertIn(b"class TwoSourceInterleaveIndex", text)
        self.assertIn(b"class TwoSourceBWT", text)
        self.assertIn(b"def countOccurrencesBySource", text)


EVIDENCE = os.path.join(PACKAGE, "evidence",
                        "feature2-multi-source-provenance.json")
DRIVER = os.path.join(PACKAGE, "validate",
                      "feature2-multi-source-provenance.sh")
EVIDENCE_GENERATOR = os.path.join(
    PACKAGE, "validate", "feature2_multi_source_evidence.py")


class EvidenceRecordTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = json.load(open(EVIDENCE, encoding="utf-8"))
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "enhanced-modern2")
        self.assertEqual(evidence["final"]["milestone"],
                         "enhanced-modern2-feature2-multi-source-provenance")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")

    def test_evidence_randomized_suite_parameters(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["seed"], 20260811)
        self.assertEqual(report["randomized_datasets"], 40)
        self.assertEqual(report["explicit_ten_source_datasets"], 4)
        self.assertEqual(report["mismatch_count"], 0)

    def test_evidence_ten_source_fixture(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        fixture = report["ten_source_fixture"]
        self.assertEqual(fixture["source_count"], 10)
        self.assertEqual(fixture["extraction_mismatches"], 0)
        self.assertTrue(fixture["reload_ok"])
        self.assertEqual(fixture["depth"], 4)
        self.assertGreater(fixture["exact_rows_checked"], 0)

    def test_evidence_feature1_compatibility(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        compat = report["feature1_compatibility"]
        self.assertEqual(compat["row_mismatches"], 0)
        self.assertEqual(compat["query_mismatches"], 0)
        self.assertGreater(compat["rows_compared"], 0)
        self.assertGreater(compat["queries_compared"], 0)

    def test_evidence_corruption_probes_all_detected(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        probes = report["corruption_probes"]
        self.assertTrue(probes["same_length_replaced_bwt_detected"])
        self.assertTrue(probes["copied_manifest_detected"])
        self.assertTrue(probes["same_length_same_count_replaced_interleave_detected"])
        self.assertTrue(probes["truncated_manifest_detected"])
        self.assertTrue(probes["wrong_version_detected"])
        self.assertTrue(probes["wrong_dtype_interleave_detected"])
        self.assertTrue(probes["missing_interleave_detected"])
        self.assertTrue(probes["bwt_length_mismatch_detected"])

    def test_evidence_multi_stage_provenance_cases(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        cases = {case["case"]: case for case in report["deterministic_cases"]}
        for name in ("canonical-two-source", "three-source-chain",
                     "four-source-balanced", "four-source-unbalanced",
                     "five-source-balanced", "ten-source-balanced"):
            self.assertIn(name, cases)
            self.assertEqual(cases[name]["extraction_mismatches"], 0, name)


class ValidationDriverTests(unittest.TestCase):
    def test_driver_present_and_uses_independent_tooling(self):
        text = open(DRIVER, encoding="utf-8").read()
        self.assertIn("feature2-multi-source-provenance", text)
        self.assertIn("feature2_multi_source_evidence.py", text)
        self.assertIn("--evidence", text)
        self.assertIn("20260811", text)
        self.assertIn("run_evidence", text)

    def test_evidence_generator_is_python2(self):
        text = open(EVIDENCE_GENERATOR, encoding="utf-8").read()
        self.assertIn("from __future__ import print_function", text)
        self.assertNotIn("f'{", text)


if __name__ == "__main__":
    unittest.main()
