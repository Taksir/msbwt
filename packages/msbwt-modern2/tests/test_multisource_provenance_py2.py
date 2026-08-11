"""msbwt-modern2 enhanced Feature 2 tests: persistent multi-source provenance
(``MUS.MultiSourceProvenance``), runnable inside the pinned Python-2.7
environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO.
Fast structural tests use a deterministic fake two-way merger with the same
``inter0.npy`` semantics as GenericMerge; integration tests execute REAL
modern2 construction (``pp`` + ``cfpp``) and REAL ``GenericMerge`` merges
through the Feature-2 adapter.

Coverage:

- leaf manifest identity: stable explicit IDs, auto UUID, overwrite
  semantics, save/reload stability, leaf BWT digest verification;
- two-way packaging: root ``inter0.npy`` retained (Feature-1 compatible),
  interleave copied into ``provenance/interleaves``, duplicate-ID rejection
  BEFORE the merge runs, output-dir safety, merged-length check;
- multi-source merges: 4-way balanced, 8-way balanced, 5-leaf uneven,
  3-source chain (unbalanced), alternate 4-source merge order, portability
  after deleting originals/intermediates, 10-source REAL merge with exact
  constituent recovery of all ten sources;
- persistence/corruption matrix: reload, ID stability, truncated/non-JSON
  manifest, wrong format/version, missing digest fields, same-length replaced
  BWT, manifest copied from another index, same-length replaced interleave
  (same counts, digest must catch it), wrong-dtype interleave, missing
  interleave, BWT-length mismatch;
- atomic manifest writes (no ``.tmp`` left behind, deterministic bytes);
- Feature-1 compatibility: for a real two-source merge, the Feature-2
  provenance tree agrees with ``MUS.SourceIndex`` ``inter0.npy``
  interpretation at EVERY row and for every per-query source count;
- deterministic randomized real-merge subset (seed 20260811, 3-5 sources);
- Python-2 compatibility of the production module (no pathlib / os.replace /
  f-strings; positional-call retry for the Cython signature).

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import json
import os
import random
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_source_index_py2 as f1  # noqa: E402

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
    holt_merge_two,
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

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

SEED = f1.SEED


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


def fake_holt_merge(left_dir, right_dir, output_dir, num_procs=1, logger=None):
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
            f1.pack_little_endian_bits(bits))


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


class LeafManifestPy2Tests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f2-py2-leaf-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_stable_explicit_identity_and_reload(self):
        leaf = make_leaf(self.work, "sample-A", [1, 2, 3, 4])
        manifest = load_manifest(leaf)
        self.assertEqual(manifest["root"]["type"], "leaf")
        self.assertEqual(manifest["root"]["source_id"], "sample-A")
        self.assertEqual(manifest["bwt_length"], 4)
        self.assertEqual(source_ids(leaf), ["sample-A"])
        self.assertEqual(list_sources(leaf)[0]["name"], "sample-A")
        self.assertIn("bwt_sha256", list_sources(leaf)[0])
        self.assertEqual(len(list_sources(leaf)[0]["bwt_sha256"]), 64)
        # save/reload does not permute or change the ID
        self.assertEqual(source_ids(leaf), ["sample-A"])

    def test_auto_uuid_when_no_id_given(self):
        leaf = os.path.join(self.work, "auto")
        os.mkdir(leaf)
        np.save(os.path.join(leaf, "msbwt.npy"), np.asarray([9], dtype=np.uint8))
        manifest = initialize_leaf_provenance(leaf)
        sid = source_ids(leaf)[0]
        self.assertTrue(isinstance(sid, basestring))
        self.assertEqual(len(sid), 36)  # uuid4
        self.assertEqual(list_sources(leaf)[0]["name"], sid)
        # stable across reload
        self.assertEqual(source_ids(leaf), [sid])

    def test_existing_manifest_is_authoritative_without_overwrite(self):
        leaf = make_leaf(self.work, "keep", [1, 2])
        initialize_leaf_provenance(leaf, source_id="other", source_name="x")
        self.assertEqual(source_ids(leaf), ["keep"])

    def test_overwrite_replaces_identity(self):
        leaf = make_leaf(self.work, "old", [1, 2])
        initialize_leaf_provenance(leaf, source_id="new", source_name="new",
                                   overwrite=True)
        self.assertEqual(source_ids(leaf), ["new"])

    def test_same_length_replaced_leaf_bwt_is_detected(self):
        leaf = make_leaf(self.work, "guarded", [1, 2, 3])
        original = np.load(os.path.join(leaf, "msbwt.npy"))
        changed = original.copy()
        changed[0] = changed[0] ^ np.uint8(1)
        np.save(os.path.join(leaf, "msbwt.npy"), changed)
        with self.assertRaises(ProvenanceError):
            load_manifest(leaf)


class TwoWayMergePy2Tests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f2-py2-twoway-")
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
        self.assertEqual(source_ids(merged), ["A", "B"])
        self.assertTrue(validate_manifest(merged))
        self.assertEqual(manifest["root"]["length"], 5)
        self.assertEqual(manifest["bwt_length"], 5)
        # the stored copy is byte-identical to the root inter0.npy
        self.assertTrue(np.array_equal(
            np.load(saved), np.load(os.path.join(merged, INTERLEAVE_FILENAME))))

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
        self.assertFalse(os.path.exists(os.path.join(self.work, "bad")))

    def test_merged_length_mismatch_is_rejected(self):
        left = make_leaf(self.work, "A", [1, 2])
        right = make_leaf(self.work, "B", [3, 4])

        def wrong_merge(left_dir, right_dir, output_dir, num_procs=1,
                        logger=None):
            if not os.path.isdir(output_dir):
                os.makedirs(output_dir)
            np.save(os.path.join(output_dir, "msbwt.npy"),
                    np.zeros(5, dtype=np.uint8))  # 5 != 2 + 2
            np.save(os.path.join(output_dir, "inter0.npy"),
                    np.zeros(1, dtype=np.uint8))

        with self.assertRaises(ProvenanceError):
            merge_two_with_provenance(
                left, right, os.path.join(self.work, "bad"),
                merge_two_func=wrong_merge)

    def test_nonempty_output_directory_is_rejected(self):
        left = make_leaf(self.work, "A", [1])
        right = make_leaf(self.work, "B", [2])
        output = os.path.join(self.work, "occupied")
        os.mkdir(output)
        with open(os.path.join(output, "junk.txt"), "w") as handle:
            handle.write("x")
        with self.assertRaises(ProvenanceError):
            merge_two_with_provenance(
                left, right, output, merge_two_func=fake_holt_merge)


class MultiSourceMergePy2Tests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f2-py2-multi-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_four_way_balanced_merge_recovers_every_constituent_exactly(self):
        leaves = [
            make_leaf(self.work, "A", [10, 11, 12, 13]),
            make_leaf(self.work, "B", [20, 21, 22]),
            make_leaf(self.work, "C", [30, 31, 32, 33, 34]),
            make_leaf(self.work, "D", [40, 41]),
        ]
        originals = {
            os.path.basename(leaf): np.load(os.path.join(leaf, "msbwt.npy")).copy()
            for leaf in leaves
        }

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
        # ((A+B)+C)+D is a valid unbalanced tree; original identities must
        # survive regardless of tree shape
        leaves = [make_leaf(self.work, n, [i * 7 + 1, i * 7 + 2, i * 7 + 3])
                  for i, n in enumerate("ABCD")]
        originals = {
            os.path.basename(leaf): np.load(os.path.join(leaf, "msbwt.npy")).copy()
            for leaf in leaves
        }
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
        leaves = [
            make_leaf(self.work, name, [i * 10 + 1, i * 10 + 2, i * 10 + 3])
            for i, name in enumerate("ABCD")
        ]
        originals = {
            os.path.basename(leaf): np.load(os.path.join(leaf, "msbwt.npy")).copy()
            for leaf in leaves
        }
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

    def test_ten_source_real_merge_recovers_every_constituent_exactly(self):
        harness = f1.SourceHarness(self.work)
        leaves = []
        originals = {}
        rng = random.Random(SEED)
        for i in range(10):
            reads = f1.make_random_case(rng)[0]
            leaf = harness.build_fastq_source("ten-%d" % i, reads)
            leaves.append(leaf)
            originals["sample-%d" % i] = np.load(
                os.path.join(leaf, "msbwt.npy")).copy()

        output = os.path.join(self.work, "TEN")
        manifest = merge_many_balanced(
            leaves, output,
            merge_two_func=holt_merge_two,
            source_ids=["sample-%d" % i for i in range(10)],
            source_names=["sample-%d" % i for i in range(10)],
            num_procs=1,
        )
        self.assertEqual(max_depth(manifest["root"]), 4)
        self.assertEqual(
            source_ids(output), ["sample-%d" % i for i in range(10)])
        for sid, expected in originals.items():
            np.testing.assert_array_equal(
                extract_constituent_bwt(output, sid), expected)

    def test_unbalanced_four_source_real_merge(self):
        harness = f1.SourceHarness(self.work)
        leaves = []
        originals = {}
        rng = random.Random(SEED + 1)
        for i in range(4):
            reads = f1.make_random_case(rng)[0]
            leaf = harness.build_fastq_source("ub-%d" % i, reads)
            initialize_leaf_provenance(leaf, source_id="u%d" % i,
                                       source_name="u%d" % i)
            leaves.append(leaf)
            originals["u%d" % i] = np.load(
                os.path.join(leaf, "msbwt.npy")).copy()

        ab = os.path.join(self.work, "ub-AB")
        merge_two_with_provenance(leaves[0], leaves[1], ab,
                                  merge_two_func=holt_merge_two, num_procs=1)
        abc = os.path.join(self.work, "ub-ABC")
        merge_two_with_provenance(ab, leaves[2], abc,
                                  merge_two_func=holt_merge_two, num_procs=1)
        abcd = os.path.join(self.work, "ub-ABCD")
        merge_two_with_provenance(abc, leaves[3], abcd,
                                  merge_two_func=holt_merge_two, num_procs=1)
        self.assertEqual(source_ids(abcd), ["u0", "u1", "u2", "u3"])
        for sid, expected in originals.items():
            np.testing.assert_array_equal(
                extract_constituent_bwt(abcd, sid), expected)


class PersistenceAndCorruptionPy2Tests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f2-py2-persist-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        left = make_leaf(self.work, "A", [1, 2, 3])
        right = make_leaf(self.work, "B", [4, 5])
        self.merged = os.path.join(self.work, "AB")
        self.manifest = merge_two_with_provenance(
            left, right, self.merged, merge_two_func=fake_holt_merge)

    def test_reload_preserves_ids_lengths_and_tree(self):
        reloaded = load_manifest(self.merged)
        self.assertEqual(reloaded, self.manifest)
        self.assertEqual(source_ids(self.merged), ["A", "B"])
        self.assertTrue(validate_manifest(self.merged))
        np.testing.assert_array_equal(
            extract_constituent_bwt(self.merged, "A"),
            np.asarray([1, 2, 3], dtype=np.uint8))

    def test_truncated_manifest_is_rejected(self):
        path = os.path.join(self.merged, MANIFEST_FILENAME)
        with open(path, "ab") as handle:
            handle.write(b"{\"truncated\":")
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_non_json_manifest_is_rejected(self):
        path = os.path.join(self.merged, MANIFEST_FILENAME)
        with open(path, "wb") as handle:
            handle.write(b"this is not json")
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_wrong_format_and_version_are_rejected(self):
        bad = json.loads(json.dumps(self.manifest))
        bad["format"] = "some-other-format"
        save_manifest(self.merged, bad)
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)
        bad2 = json.loads(json.dumps(self.manifest))
        bad2["version"] = FORMAT_VERSION + 1
        save_manifest(self.merged, bad2)
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_missing_identity_fields_are_rejected(self):
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

    def test_same_length_replaced_merged_bwt_is_detected(self):
        bwt_path = os.path.join(self.merged, BWT_FILENAME)
        original = np.load(bwt_path)
        changed = original.copy()
        changed[0] = changed[0] ^ np.uint8(1)
        np.save(bwt_path, changed)
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_manifest_copied_from_another_index_is_detected(self):
        # a second same-sized merge with different content
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

    def test_same_length_same_count_replaced_interleave_is_detected(self):
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
        replaced = f1.pack_little_endian_bits(list(reversed(bits)))
        np.save(inter_path, replaced)
        with self.assertRaises(ProvenanceError):
            load_manifest(merged)

    def test_wrong_dtype_interleave_is_detected(self):
        node = self.manifest["root"]
        inter_path = os.path.join(self.merged, node["interleave"])
        packed = np.load(inter_path)
        np.save(inter_path, packed.astype(np.uint16))
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_missing_interleave_is_detected(self):
        node = self.manifest["root"]
        os.remove(os.path.join(self.merged, node["interleave"]))
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_bwt_length_mismatch_is_detected(self):
        bad = json.loads(json.dumps(self.manifest))
        bad["bwt_length"] = bad["bwt_length"] + 1
        save_manifest(self.merged, bad)
        with self.assertRaises(ProvenanceError):
            load_manifest(self.merged)

    def test_unknown_source_id_extraction_raises_key_error(self):
        with self.assertRaises(KeyError):
            extract_constituent_bwt(self.merged, "not-a-source")


class AtomicWritePy2Tests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f2-py2-atomic-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_save_manifest_is_atomic_and_leaves_no_tmp(self):
        leaf = make_leaf(self.work, "A", [1, 2])
        leftovers = [name for name in os.listdir(leaf)
                     if name.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        manifest = load_manifest(leaf)
        # repeated save is deterministic and replaces cleanly
        save_manifest(leaf, manifest)
        save_manifest(leaf, manifest)
        with open(os.path.join(leaf, MANIFEST_FILENAME), "rb") as handle:
            first = handle.read()
        save_manifest(leaf, manifest)
        with open(os.path.join(leaf, MANIFEST_FILENAME), "rb") as handle:
            second = handle.read()
        self.assertEqual(first, second)
        self.assertEqual(
            [name for name in os.listdir(leaf) if name.endswith(".tmp")], [])


class Feature1CompatibilityPy2Tests(unittest.TestCase):
    """Feature-2 provenance must agree with Feature-1's ``inter0.npy``
    interpretation for exactly two sources, at every row and in every
    per-query source count."""

    @classmethod
    def setUpClass(cls):
        from MUS.MultiSourceProvenance import holt_merge_two
        cls.work = tempfile.mkdtemp(prefix="f2-py2-f1compat-")
        cls.harness = f1.SourceHarness(cls.work)
        cls.a_dir = cls.harness.build_fixture_source(
            "in_a", "uniform-a.fastq")
        cls.b_dir = cls.harness.build_fixture_source(
            "in_b", "uniform-b.fastq")
        cls.m_dir = os.path.join(cls.work, "merged")
        cls.manifest = merge_two_with_provenance(
            cls.a_dir, cls.b_dir, cls.m_dir,
            merge_two_func=holt_merge_two,
            left_source_id="A", left_source_name="A",
            right_source_id="B", right_source_name="B",
            num_procs=1,
        )
        from MUS.SourceIndex import TwoSourceBWT
        cls.merged = TwoSourceBWT.load(cls.m_dir, source_names=("A", "B"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_root_interleave_copy_is_byte_identical_to_inter0(self):
        node = self.manifest["root"]
        self.assertTrue(np.array_equal(
            np.load(os.path.join(self.m_dir, node["interleave"])),
            np.load(os.path.join(self.m_dir, INTERLEAVE_FILENAME))))

    def test_row_level_provenance_agrees_at_every_row(self):
        total = int(self.merged.bwt.getTotalSize())
        self.assertEqual(self.manifest["bwt_length"], total)
        bits = unpack_interleave(
            os.path.join(self.m_dir, self.manifest["root"]["interleave"]),
            total)
        for row in range(total):
            feature1 = self.merged.source_index.source_at(row)
            feature2 = int(bits[row])
            self.assertEqual(feature2, feature1,
                             "row %d provenance disagrees" % row)

    def test_per_query_source_counts_agree(self):
        queries = (list(f1.COMMITTED_QUERIES.keys())
                   + [str(q) for q in f1.CANONICAL_EXTRA_QUERIES])
        total = int(self.merged.bwt.getTotalSize())
        bits = unpack_interleave(
            os.path.join(self.m_dir, self.manifest["root"]["interleave"]),
            total)
        for query in queries:
            result = self.merged.countOccurrencesBySource(query)
            low, high = result["interval"]
            interval_bits = bits[low:high]
            tree_a = int(interval_bits.size - interval_bits.sum(dtype=np.uint64))
            tree_b = int(interval_bits.sum(dtype=np.uint64))
            self.assertEqual(tree_a, result["A"], query)
            self.assertEqual(tree_b, result["B"], query)
            self.assertEqual(tree_a + tree_b, result["total"], query)

    def test_source_ids_match_requested_identities(self):
        self.assertEqual(source_ids(self.m_dir), ["A", "B"])


class RandomizedRealMergePy2Tests(unittest.TestCase):
    """Deterministic randomized Feature-2 subset with REAL merges."""

    CASES = 5

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f2-py2-random-")
        cls.harness = f1.SourceHarness(cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_randomized_multi_source_extraction(self):
        rng = random.Random(SEED)
        for case_index in range(self.CASES):
            source_count = rng.randint(3, 5)
            leaves = []
            originals = {}
            for i in range(source_count):
                reads = f1.make_random_case(rng)[0]
                leaf = self.harness.build_fastq_source(
                    "r%d-s%d" % (case_index, i), reads)
                leaves.append(leaf)
                originals["s%d" % i] = np.load(
                    os.path.join(leaf, "msbwt.npy")).copy()
            output = os.path.join(self.work, "r%d-out" % case_index)
            manifest = merge_many_balanced(
                leaves, output, merge_two_func=holt_merge_two,
                source_ids=["s%d" % i for i in range(source_count)],
                source_names=["s%d" % i for i in range(source_count)],
                num_procs=1)
            expected_total = sum(int(originals[sid].shape[0])
                                 for sid in originals)
            self.assertEqual(manifest["bwt_length"], expected_total)
            self.assertEqual(
                source_ids(output),
                ["s%d" % i for i in range(source_count)])
            for sid, expected in originals.items():
                np.testing.assert_array_equal(
                    extract_constituent_bwt(output, sid), expected)
            # persistence round trip
            self.assertTrue(validate_manifest(output))
            for sid, expected in originals.items():
                np.testing.assert_array_equal(
                    extract_constituent_bwt(output, sid), expected)


class Python2CompatibilityTests(unittest.TestCase):
    def test_python_is_cpython_27_and_numpy_pinned(self):
        self.assertEqual(sys.version_info[:2], (2, 7))
        self.assertEqual(np.__version__, "1.16.6")

    def test_module_source_has_no_python3_only_constructs(self):
        module_path = os.path.join(os.path.dirname(__file__), "..", "MUS",
                                   "MultiSourceProvenance.py")
        with open(module_path, "rb") as handle:
            text = handle.read()
        self.assertNotIn(b"import pathlib", text)
        self.assertNotIn(b"from pathlib", text)
        # the whole file must clear the baseline py3-syntax scan: no
        # open(..., encoding=...) and no bare os.replace / os.fsencode
        self.assertNotIn(b"encoding=", text)
        self.assertIn(b"json.dumps(", text)
        # os.replace is used only behind the Python-2-safe hasattr guard
        self.assertIn(b'hasattr(os, "replace")', text)
        self.assertIn(b'hasattr(os, "fsencode")', text)
        # MUSCython is imported lazily inside holt_merge_two only
        self.assertNotIn(b"\nimport MUSCython", text)
        self.assertNotIn(b"\nfrom MUSCython", text)

    def test_positional_retry_reaches_merge(self):
        # compiled Cython def functions under Python 2 reject keyword
        # arguments; the adapter must retry positionally on an
        # argument-signature TypeError only.  Simulate the keyword rejection
        # with a function whose parameter names do not match the keywords.
        calls = []

        def py2_cython_style(left_dir, right_dir, output_dir, procs, log):
            calls.append((left_dir, right_dir, output_dir, procs, log))
            return "done"

        from MUS.MultiSourceProvenance import _call_merge
        result = _call_merge(py2_cython_style, "L", "R", "O", 3, "log")
        self.assertEqual(calls, [("L", "R", "O", 3, "log")])
        self.assertEqual(result, "done")

    def test_non_signature_type_error_propagates_without_retry(self):
        calls = []

        def internal_error(left_dir, right_dir, output_dir, num_procs=None,
                           logger=None):
            calls.append("called")
            raise TypeError("boom: something failed inside")

        from MUS.MultiSourceProvenance import _call_merge
        with self.assertRaises(TypeError):
            _call_merge(internal_error, "L", "R", "O", 1, None)
        self.assertEqual(calls, ["called"])


if __name__ == "__main__":
    unittest.main()
