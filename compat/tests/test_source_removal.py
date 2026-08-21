"""Host-side regression tests for enhanced-modern2 Feature 10: source
removal / unmerge without FASTQ rebuild (``MUS.SourceRemoval``).

These tests are read-only and run on any CPython 3 with NumPy; they do NOT
require the compiled MUSCython extensions (real-merge integration runs in
the pinned Python-2.7 suite and the Feature-10 validation driver).

Coverage:

- reduced ``msbwt.npy`` BYTE-FOR-BYTE equal to an independent suffix sort
  of the retained reads for many removal shapes (first/last/middle,
  nonadjacent, contiguous group, odd sources, retain-one);
- single-source collapse to a leaf package byte-identical to the original
  standalone BWT; two-source output keeps the Feature-1 ``inter0.npy``
  convention;
- every retained constituent recovers byte-for-byte to its original
  standalone BWT; stable source order/IDs preserved;
- Feature-9 read provenance filtered with mate remapping, equal to a
  CLEAN retained-source control index record-for-record; readsContaining
  on the reduced package == naive retained counts; no removed sources;
- source-aware semantics on the reduced package equal the clean control:
  per-source counts, sparse listing, frequency, top-k, subset/group
  aggregates;
- Feature-7 metadata group/predicate removal with pruned groups and
  source records; external metadata files;
- rank policy: no stale caches survive (never copied); eager rank
  construction option materializes every new internal node;
- atomicity: failed removal leaves no publishable output and no temp
  leftovers; input package bytes unchanged; rejections (remove-all,
  empty, retain-all, input==output, existing output);
- randomized removal differentials (seeds 20260811/20260812/20260813);
- evidence-record and validation-driver consistency.
"""

import hashlib
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

import test_multisource_query as f3  # noqa: E402
import test_read_provenance as f9  # noqa: E402

SEEDS = (20260811, 20260812, 20260813)

EVIDENCE = os.path.join(PACKAGE, "evidence", "feature10-source-removal.json")
EVIDENCE_GENERATOR = os.path.join(
    PACKAGE, "validate", "feature10_source_removal_evidence.py")
VALIDATION_DRIVER = os.path.join(
    PACKAGE, "validate", "feature10-source-removal.sh")

ALL_SOURCES = sorted(f3.TEN_SOURCE_READS)


def manifest_source_order(output):
    return [s["id"] for s in load_manifest(output)["sources"]]


def retained_after(all_ids, remove_ids):
    removed = set(remove_ids)
    return [sid for sid in all_ids if sid not in removed]


def expected_bwt_bytes(leaves, all_ids, keep_ids):
    """Independent suffix sort of the retained reads (no Feature-10 code)."""
    all_order = {sid: i for i, sid in enumerate(all_ids)}
    rows = []
    for sid in keep_ids:
        for row in f3.load_rows(leaves[sid]):
            rows.append((
                row["suffix"],
                all_order[sid],
                int(row["read_id"]),
                int(row["pos"]),
                row["bwt"],
            ))
    rows.sort()
    return np.asarray(
        [f3.ALPHABET_CODE[r[4]] for r in rows], dtype=np.uint8)


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


class SourceRemovalHostTestBase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f10-host-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def build_input(self):
        return f9.build_fixture_with_reads(
            self.work, f3.TEN_SOURCE_READS, name="merged10")


class ByteEqualityHostTests(SourceRemovalHostTestBase):
    def test_removed_output_bwt_equals_independent_rebuild(self):
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

    def test_single_source_output_collapses_tree_and_matches_standalone(
            self):
        leaves, output, manifest, oracle = self.build_input()
        reduced = os.path.join(self.work, "single")
        retain_sources(output, reduced, ["sample07"])
        manifest_out = load_manifest(reduced)
        self.assertEqual(manifest_out["root"]["type"], "leaf")
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
        self.assertTrue(np.array_equal(
            np.load(os.path.join(
                reduced, manifest_out["root"]["interleave"])),
            np.load(os.path.join(reduced, "inter0.npy"))))

    def test_remaining_constituents_recover_exact_original_bwts(self):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        remove_ids = [all_ids[0], all_ids[2], all_ids[-1]]
        reduced = os.path.join(self.work, "reduced")
        remove_sources(output, reduced, sources=remove_ids)
        for sid in retained_after(all_ids, remove_ids):
            self.assertTrue(np.array_equal(
                extract_constituent_bwt(reduced, sid),
                np.load(os.path.join(leaves[sid], "msbwt.npy"))), sid)

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


class SemanticEquivalenceHostTests(SourceRemovalHostTestBase):
    def _build_pair(self, remove_ids):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        keep = retained_after(all_ids, remove_ids)
        reduced = os.path.join(self.work, "reduced")
        remove_sources(output, reduced, sources=remove_ids)
        # clean retained-source control in the same source order
        clean_work = os.path.join(self.work, "clean_work")
        os.mkdir(clean_work)
        clean_leaves = []
        for sid in keep:
            leaf = f3.make_read_derived_leaf(
                clean_work, sid, f3.TEN_SOURCE_READS[sid])
            f9.attach_leaf_read_provenance(
                leaf, f3.TEN_SOURCE_READS[sid])
            clean_leaves.append(leaf)
        clean_out = os.path.join(self.work, "clean")
        clean_manifest = f3.merge_many_balanced(
            clean_leaves, clean_out,
            merge_two_func=f3.read_derived_merge,
            work_dir=os.path.join(self.work, "clean_work_dir"),
            keep_work=True)
        clean_oracle = f9.OracleReadIdentity(
            clean_out,
            {sid: os.path.join(clean_work, sid) for sid in keep},
            {sid: f3.TEN_SOURCE_READS[sid] for sid in keep})
        self.assertTrue(np.array_equal(
            np.load(os.path.join(reduced, "msbwt.npy")),
            np.load(os.path.join(clean_out, "msbwt.npy"))))
        return reduced, clean_out, clean_oracle, keep

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
            low, high = naive_interval(clean_out, pattern)
            self.assertEqual(
                r_index.nonzero_sources_interval(low, high),
                c_index.nonzero_sources_interval(low, high), pattern)
            self.assertEqual(
                r_index.source_frequency_interval(low, high),
                c_index.source_frequency_interval(low, high), pattern)
            for k in (1, 2, 3, 5, 10):
                self.assertEqual(
                    r_index.top_sources_interval(low, high, k),
                    c_index.top_sources_interval(low, high, k),
                    (pattern, k))

    def test_subset_aggregates_equal_clean_control(self):
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
            low, high = naive_interval(clean_out, pattern)
            self.assertEqual(
                r_index.subset_count_interval(low, high, subset),
                c_index.subset_count_interval(low, high, subset), pattern)
            self.assertEqual(
                r_index.subset_counts_interval(low, high, subset),
                c_index.subset_counts_interval(low, high, subset), pattern)

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

    def test_reads_containing_on_reduced_matches_naive_counts(self):
        remove_ids = ["sample00", "sample02", "sample09"]
        reduced, clean_out, clean_oracle, keep = self._build_pair(
            remove_ids)
        index = MultiSourceQueryIndex(
            reduced, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        read_index = ReadProvenanceIndex(
            reduced, mmap=False, source_index=index)
        wrapped = MultiSourceBWT(
            None, index, read_provenance=read_index)
        wrapped.bwt = f9.OracleBWTAdapter(
            clean_oracle, clean_out, load_manifest(reduced))
        for pattern in ("A", "AC", "CGT", "GTAC", "AAAA", "N", "AAGGTT"):
            expected = {}
            for sid in keep:
                for local_id in range(3):
                    dollar_id = clean_oracle.global_dollar[(sid, local_id)]
                    count = f9.overlapping_count(
                        f3.TEN_SOURCE_READS[sid][local_id], pattern)
                    if count:
                        expected[dollar_id] = count
            result = wrapped.readsContaining(pattern)
            actual = {
                rec["dollar_id"]: rec["occurrence_count"]
                for rec in result["reads"]
            }
            self.assertEqual(actual, expected, pattern)
            self.assertEqual(
                result["reported_occurrences"],
                result["merged_occurrences"], pattern)
            self.assertTrue(all(
                rec["source_id"] in keep for rec in result["reads"]))


class MetadataRemovalHostTests(SourceRemovalHostTestBase):
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

    def test_remove_metadata_predicate(self):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        self._build_metadata(output)
        reduced = os.path.join(self.work, "no_even")
        remove_sources(output, reduced, where={"platform": "X"})
        input_catalog = SourceMetadataCatalog.load(
            output,
            MultiSourceQueryIndex(
                output, mmap=False, use_saved_rank=False).list_sources(),
            required=True)
        removed = input_catalog.select_where(platform="X")
        self.assertEqual(
            [s["id"] for s in load_manifest(reduced)["sources"]],
            [sid for sid in all_ids if sid not in removed])

    def test_group_removal_requires_metadata(self):
        leaves, output, manifest, oracle = self.build_input()
        with self.assertRaises(SourceRemovalError):
            remove_sources(
                output, os.path.join(self.work, "x"), group="case")


class SafetyHostTests(SourceRemovalHostTestBase):
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
        leaves, output, manifest, oracle = self.build_input()
        broken = os.path.join(self.work, "broken_input")
        shutil.copytree(output, broken)
        with open(os.path.join(broken, "read_provenance.json"), "w") as fp:
            fp.write("{not json")
        target = os.path.join(self.work, "must_not_exist")
        with self.assertRaises(Exception):
            remove_sources(broken, target, sources=["sample09"])
        self.assertFalse(os.path.exists(target))
        leftovers = [
            name for name in os.listdir(self.work)
            if name.startswith(".must_not_exist.point10-")
        ]
        self.assertEqual(leftovers, [])

    def test_no_stale_rank_caches_survive_removal(self):
        leaves, output, manifest, oracle = self.build_input()
        reduced = os.path.join(self.work, "reduced")
        stats = remove_sources(output, reduced, sources=["sample09"])
        self.assertEqual(stats["rank_indexes_built"], 0)
        self.assertFalse(os.path.exists(
            os.path.join(reduced, "provenance", "ranks")))
        index = MultiSourceQueryIndex(
            reduced, rank_stride_bytes=64, mmap=False,
            use_saved_rank=True)
        sources = index.nonzero_sources_interval(0, index.total_bits)
        self.assertEqual(
            len(sources), len(load_manifest(reduced)["sources"]))

    def test_build_rank_indexes_option(self):
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

    def test_rejections(self):
        leaves, output, manifest, oracle = self.build_input()
        with self.assertRaises(SourceRemovalError):
            remove_sources(
                output, os.path.join(self.work, "x"),
                sources=list(ALL_SOURCES))
        with self.assertRaises(SourceRemovalError):
            remove_sources(
                output, os.path.join(self.work, "x"), sources=[])
        with self.assertRaises(SourceRemovalError):
            retain_sources(
                output, os.path.join(self.work, "x"),
                list(ALL_SOURCES))
        with self.assertRaises(SourceRemovalError):
            remove_sources(
                output, output, sources=["sample09"])
        target = os.path.join(self.work, "existing")
        os.mkdir(target)
        with open(os.path.join(target, "sentinel.txt"), "w") as fp:
            fp.write("keep")
        with self.assertRaises(SourceRemovalError):
            remove_sources(output, target, sources=["sample09"])
        self.assertTrue(os.path.exists(
            os.path.join(target, "sentinel.txt")))
        remove_sources(
            output, target, sources=["sample09"], overwrite=True)
        self.assertTrue(validate_manifest(target))
        self.assertFalse(os.path.exists(
            os.path.join(target, "sentinel.txt")))


class RandomizedRemovalHostTests(SourceRemovalHostTestBase):
    def test_randomized_removal(self):
        leaves, output, manifest, oracle = self.build_input()
        all_ids = manifest_source_order(output)
        for seed_index, seed in enumerate(SEEDS):
            rng = random.Random(seed)
            for case in range(6):
                remove_ids = [
                    sid for sid in all_ids if rng.random() < 0.35
                ]
                if not remove_ids or len(remove_ids) == len(all_ids):
                    remove_ids = [all_ids[case % len(all_ids)]]
                keep = retained_after(all_ids, remove_ids)
                reduced = os.path.join(
                    self.work, "rand_%02d_%02d" % (seed_index, case))
                remove_sources(output, reduced, sources=remove_ids)
                self.assertTrue(np.array_equal(
                    np.load(os.path.join(reduced, "msbwt.npy")),
                    expected_bwt_bytes(leaves, all_ids, keep)),
                    (seed, case, remove_ids))
                self.assertTrue(validate_manifest(reduced))
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


class EvidenceConsistencyTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = json.load(open(EVIDENCE, encoding="utf-8"))
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "enhanced-modern2")
        self.assertEqual(
            evidence["final"]["milestone"],
            "enhanced-modern2-feature10-source-removal")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")

    def test_evidence_contract(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["seed"], 20260811)
        shapes = report["byte_equality"]
        self.assertGreaterEqual(shapes["shapes"], 6)
        self.assertEqual(shapes["mismatches"], 0)
        self.assertTrue(report["single_source_leaf"])
        real = report["real_integration"]
        self.assertEqual(real["mismatches"], 0)
        self.assertGreater(real["comparisons"], 100)
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
        self.assertIn("feature10-source-removal", driver)


if __name__ == "__main__":
    unittest.main()
