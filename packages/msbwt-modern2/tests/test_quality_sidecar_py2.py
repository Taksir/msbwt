"""Q1 - exact lossless FASTQ quality sidecar (Python-2 suite, real merges).

This suite validates ``MUS.QualitySidecar`` (a strict Point-12
specialization: reserved tag ``fastq_quality_ascii``) plus the Q1
additions to ``MUS.MultiSourceProvenance``, ``MUS.MultiSourceQuery``, and
``MUS.SourceRemoval`` against independent oracles:

* suffix-start alignment: for the suffix row beginning at read position
  ``p``, ``quality[row] == Q[p]``; the terminal ``$`` row stores 255 --
  expected leaf arrays are computed DIRECTLY from the naive suffix rows
  and the original read/quality lists (no Q1 code);
* merged quality arrays by independent suffix-sort replay;
* exact read-quality recovery: ``recover_quality(dollar_id)`` equals the
  original FASTQ quality line byte-for-byte;
* independent Phred conversion for the analysis helper.

Coverage:

- leaf initialization from records (dollar-ordered qualities), with
  independent sequence verification and sequence-mismatch rejection;
- disk-backed FASTQ retrofit: small FASTQ files (plain and .gz, varied
  printable quality bytes), about.npy origin remapping where FASTQ order
  does NOT match dollar order, sequence mismatch rejection, reserved
  byte-255 rejection;
- exhaustive small-row quality alignment for unique/duplicate/identical/
  mixed-length/N-heavy/1-base reads;
- two-way and balanced 10-source merges preserve every quality row;
  one-sided quality merge rejected BEFORE the BWT merge; merge metadata
  (child_builders) written;
- merged retrofit from leaf arrays (quality_sidecar.json regenerated,
  BWT bytes unchanged);
- Feature-10 removal: ``quality_reduced == quality_original[keep_mask]``
  element-for-element; every surviving read's recovered quality equals
  its pre-removal expectation; removed sources absent;
  ``quality_sidecar_preserved`` stat;
- query APIs: ``hasQuality`` / ``qualityForRow`` (sentinel -> None) /
  ``readQuality`` / ``readSequenceAndQuality`` / ``readFastqData`` /
  ``qualityValues`` (merged + source/group/where) /
  ``readsContaining(include_quality=True)``;
- randomized differentials (seeds 20260811/20260812/20260813).
"""

from __future__ import print_function

import gzip
import os
import random
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_read_provenance_py2 as f9  # noqa: E402

from MUS.QualitySidecar import (  # noqa: E402
    NO_QUALITY,
    QUALITY_TAG_NAME,
    QualitySidecar,
    QualitySidecarError,
    attach_quality_from_row_values,
    initialize_leaf_quality_from_fastqs,
    initialize_leaf_quality_from_records,
    quality_ascii_to_phred,
    quality_sidecar_exists,
    retrofit_merged_quality_from_leaf_arrays,
    validate_quality_sidecar,
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

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

SEEDS = (20260811, 20260812, 20260813)

# Deterministic printable FASTQ quality byte generator (never 255).
QUALITY_BYTES = [
    ord(c) for c in "!\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ"
]


def quality_for_read(read, read_id, salt):
    """Deterministic printable quality line for a read (py2-safe bytes)."""
    chars = [
        QUALITY_BYTES[(read_id * 7 + p + salt) % len(QUALITY_BYTES)]
        for p in range(len(read))
    ]
    if sys.version_info[0] == 2:
        return "".join(chr(c) for c in chars)
    return bytes(chars)


def expected_leaf_quality(leaf_dir, reads, salt=0):
    """Independent expected suffix-first-base quality array.

    For the suffix row at read position ``p``: ``Q[p]``; the terminal
    ``$`` suffix row stores 255.  Computed directly from the naive suffix
    rows and the original reads (no Q1 code).
    """
    rows = f9.load_rows(leaf_dir)
    out = np.zeros(len(rows), dtype=np.uint8)
    for idx, row in enumerate(rows):
        read = reads[row["read_id"]]
        if row["pos"] >= len(read):
            out[idx] = int(NO_QUALITY)
        else:
            out[idx] = ord(quality_for_read(
                read, row["read_id"], salt)[row["pos"]])
    return out


def expected_merged_quality(merged_dir, leaves, reads_by_source, salt=0):
    """Independent merged quality array by suffix-sort replay."""
    all_order = {sid: i for i, sid in enumerate(reads_by_source)}
    rows = []
    for sid in reads_by_source:
        for idx, row in enumerate(f9.load_rows(leaves[sid])):
            rows.append((
                row["suffix"],
                all_order[sid],
                row["read_id"],
                row["pos"],
                expected_leaf_quality(
                    leaves[sid], reads_by_source[sid], salt)[idx],
            ))
    rows.sort()
    return np.asarray([r[4] for r in rows], dtype=np.uint8)


class NaiveQualityBWT(object):
    """Naive BWT adapter over the fixture suffix rows.

    Implements the real ``BasicBWT`` surface used by Q1:
    ``recoverString(dollar_id, withIndex=True)`` returns
    ``('$' + read, row_indices)`` with row indices in rotation order
    (terminal row first, then read positions 0..L-1).

    For a MERGED package an ``oracle`` (Feature-9 ``OracleReadIdentity``)
    must be supplied: per-source ``read_id`` values collide across sources,
    so the adapter resolves every read through the independent tree walk
    and returns merged row indices.
    """

    def __init__(self, directory, oracle=None):
        self.directory = str(directory)
        self.rows = f9.load_rows(self.directory)
        self.suffixes = [r["suffix"] for r in self.rows]
        self.lf_calls = 0
        self.oracle = oracle
        self.merged_index = None
        if oracle is not None:
            self.merged_index = {}
            manifest = load_manifest(self.directory, validate=True)
            for x in range(len(self.rows)):
                sid, local = f9._tree_walk_row(
                    self.directory, manifest, x)
                self.merged_index[(sid, int(local))] = x

    def getTotalSize(self):
        return len(self.rows)

    def findIndicesOfStr(self, seq, givenRange=None):
        if givenRange is not None:
            raise NotImplementedError("givenRange not used in Q1 tests")
        pattern = seq.decode("ascii") if isinstance(seq, bytes) else str(seq)
        low = bisect_left(self.suffixes, pattern)
        high = bisect_left(self.suffixes, pattern + "\x7f")
        return low, high

    def countOccurrencesOfSeq(self, seq, givenRange=None):
        low, high = self.findIndicesOfStr(seq, givenRange)
        return high - low

    def getSequenceDollarID(self, row_index, returnOffset=False):
        self.lf_calls += 1
        row_index = int(row_index)
        if self.oracle is not None:
            return self.oracle.getSequenceDollarID(
                row_index, returnOffset)
        read_id = self.rows[row_index]["read_id"]
        dollar_row = [
            i for i, r in enumerate(self.rows)
            if r["suffix"] == "$" and r["read_id"] == read_id
        ][0]
        local_dollar = sum(
            1 for i, r in enumerate(self.rows)
            if r["suffix"] == "$" and i < dollar_row
        )
        if returnOffset:
            return local_dollar, int(self.rows[row_index]["pos"])
        return local_dollar

    def recoverString(self, dollar_id, withIndex=False):
        if self.oracle is not None:
            return self._recover_merged(dollar_id, withIndex)
        dollar_rows = [
            (i, r) for i, r in enumerate(self.rows)
            if r["suffix"] == "$"
        ]
        row_index, dollar_row = dollar_rows[int(dollar_id)]
        read_id = dollar_row["read_id"]
        by_pos = {
            r["pos"]: i
            for i, r in enumerate(self.rows)
            if r["read_id"] == read_id
        }
        length = max(by_pos)
        order = [length] + list(range(length))
        indices = [by_pos[p] for p in order]
        sequence = "".join(self.rows[i]["suffix"][0] for i in indices)
        encoded = sequence.encode("ascii")
        if withIndex:
            return encoded, indices
        return encoded

    def _recover_merged(self, dollar_id, withIndex):
        oracle = self.oracle
        sid, local_dollar = oracle.dollar_to_identity[int(dollar_id)]
        inverse = {
            v: k for k, v in oracle.leaf_dollar_rows[sid].items()
        }
        read_id = inverse[local_dollar]
        leaf_rows = oracle.leaf_rows[sid]
        by_pos = {
            r["pos"]: i
            for i, r in enumerate(leaf_rows)
            if r["read_id"] == read_id
        }
        length = max(by_pos)
        order = [length] + list(range(length))
        indices = [
            self.merged_index[(sid, by_pos[p])] for p in order
        ]
        sequence = "".join(
            leaf_rows[by_pos[p]]["suffix"][0] for p in order)
        encoded = sequence.encode("ascii")
        if withIndex:
            return encoded, indices
        return encoded


def bisect_left(a, x):
    lo = 0
    hi = len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def write_fastq(path, records):
    """Write records [(name, seq, qual)]; ``.gz`` when the path ends so."""
    lines = []
    for name, seq, qual in records:
        lines.append("@" + name + "\n")
        lines.append(seq + "\n")
        lines.append("+\n")
        lines.append(qual + "\n")
    payload = "".join(lines)
    if path.endswith(".gz"):
        with gzip.open(path, "wb") as fp:
            fp.write(payload.encode("ascii"))
    else:
        with open(path, "wb") as fp:
            fp.write(payload.encode("ascii"))


class QualityPy2TestBase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="q1-py2-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def build_quality_leaves(self, reads_by_source=None, salt=0):
        reads_by_source = reads_by_source or f9.TEN_SOURCE_READS
        leaves = {}
        for sid, reads in reads_by_source.items():
            leaf = f9.make_read_derived_leaf(self.work, sid, reads)
            qualities = [
                quality_for_read(reads[i], i, salt)
                for i in range(len(reads))
            ]
            initialize_leaf_quality_from_records(
                leaf,
                NaiveQualityBWT(leaf),
                qualities,
                sequences_by_dollar_id=reads,
            )
            leaves[sid] = leaf
        return leaves, reads_by_source

    def tagged_merged(self, reads_by_source=None):
        leaves, reads_by_source = self.build_quality_leaves(
            reads_by_source)
        output = os.path.join(self.work, "merged10")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f9.read_derived_merge)
        return leaves, output, reads_by_source


class LeafQualityTests(QualityPy2TestBase):
    def test_suffix_start_alignment_every_row(self):
        reads_by_source = {
            "S1": ["ACGT", "AAAA", "NACGN"],
            "S2": ["T", "G", "NN"],
        }
        leaves, _ = self.build_quality_leaves(reads_by_source)
        for sid, leaf in leaves.items():
            sidecar = QualitySidecar(leaf)
            expected = expected_leaf_quality(
                leaf, reads_by_source[sid])
            self.assertTrue(np.array_equal(
                sidecar.values, expected), sid)
            # every row checked element-for-element
            for idx in range(expected.shape[0]):
                self.assertEqual(
                    int(sidecar.values[idx]), int(expected[idx]),
                    (sid, idx))

    def test_exhaustive_small_datasets(self):
        cases = [
            {"D": ["ACGTAC", "ACGTAC", "ACGTAC"]},
            {"I": ["AAAA", "AAAA"]},
            {"M": ["A", "AC", "ACG", "ACGT", "ACGTACGTACGT"]},
            {"N": ["N", "NN", "ACGTNNNN", "NACGT"]},
            {"one": ["A"]},
        ]
        for case_index, reads_by_source in enumerate(cases):
            leaves, _ = self.build_quality_leaves(reads_by_source)
            for sid, leaf in leaves.items():
                sidecar = QualitySidecar(leaf)
                expected = expected_leaf_quality(
                    leaf, reads_by_source[sid])
                self.assertTrue(np.array_equal(
                    sidecar.values, expected),
                    (case_index, sid))

    def test_quality_recovery_equals_original_line(self):
        reads_by_source = {
            "S1": ["ACGT", "AAAA", "NACGN"],
            "S2": ["TTTT", "GCGT"],
        }
        leaves, _ = self.build_quality_leaves(reads_by_source)
        for sid, leaf in leaves.items():
            sidecar = QualitySidecar(leaf)
            reads = reads_by_source[sid]
            for dollar_id in range(len(reads)):
                quality = sidecar.recover_quality(
                    NaiveQualityBWT(leaf), dollar_id)
                self.assertEqual(
                    quality, quality_for_read(reads[dollar_id], dollar_id, 0),
                    (sid, dollar_id))
                sequence, q2 = sidecar.recover_sequence_and_quality(
                    NaiveQualityBWT(leaf), dollar_id)
                self.assertEqual(sequence, reads[dollar_id].encode("ascii"))
                self.assertEqual(q2, quality)

    def test_sequence_mismatch_rejected(self):
        leaf = f9.make_read_derived_leaf(
            self.work, "src", ["ACGT", "AAAA"])
        with self.assertRaises(QualitySidecarError):
            initialize_leaf_quality_from_records(
                leaf,
                NaiveQualityBWT(leaf),
                [b"####", b"!!!!"],
                sequences_by_dollar_id=["ACGT", "CCCC"],
            )
        # wrong quality length rejected
        with self.assertRaises(QualitySidecarError):
            initialize_leaf_quality_from_records(
                leaf,
                NaiveQualityBWT(leaf),
                [b"###", b"!!!!"],
                sequences_by_dollar_id=["ACGT", "AAAA"],
            )
        # byte 255 in a quality line rejected
        with self.assertRaises(QualitySidecarError):
            initialize_leaf_quality_from_records(
                leaf,
                NaiveQualityBWT(leaf),
                [b"###\xff", b"!!!!"],
                sequences_by_dollar_id=["ACGT", "AAAA"],
            )

    def test_phred_helper(self):
        self.assertTrue(np.array_equal(
            quality_ascii_to_phred(np.asarray([33, 43, 63], dtype=np.uint8)),
            np.asarray([0, 10, 30])))
        with self.assertRaises(QualitySidecarError):
            quality_ascii_to_phred(np.asarray([30], dtype=np.uint8))


class FastqRetrofitTests(QualityPy2TestBase):
    def _build_leaf_with_about(self, reads, about_records, name="src"):
        leaf = f9.make_read_derived_leaf(self.work, name, reads)
        about = np.empty(
            len(about_records),
            dtype=np.dtype([("f0", "<u1"), ("f1", "<u8")]))
        for i, (fid, rid) in enumerate(about_records):
            about[i] = (fid, rid)
        np.save(os.path.join(leaf, "about.npy"), about)
        return leaf

    def test_fastq_retrofit_with_unsorted_origin_order(self):
        # about.npy order differs from FASTQ order and from read order
        reads = ["ACGT", "AAAA", "TTTT"]
        fastq_records = [
            ("read0", "TTTT", "IIII"),
            ("read1", "ACGT", "####"),
            ("read2", "AAAA", "!!!!"),
        ]
        fastq = os.path.join(self.work, "src.fastq")
        write_fastq(fastq, fastq_records)
        # leaf dollar k = read k; about maps each dollar to a DIFFERENT
        # FASTQ record position: dollar0(ACGT)->file read1,
        # dollar1(AAAA)->file read2, dollar2(TTTT)->file read0
        leaf = self._build_leaf_with_about(
            reads, [(0, 1), (0, 2), (0, 0)])
        bwt = NaiveQualityBWT(leaf)
        metadata = initialize_leaf_quality_from_fastqs(
            leaf, bwt, [fastq])
        self.assertTrue(quality_sidecar_exists(leaf))
        self.assertEqual(metadata["builder"], "leaf-fastq-retrofit")
        self.assertEqual(metadata["input_files"], [fastq])
        sidecar = QualitySidecar(leaf)
        # recovered qualities follow the ORIGINAL FASTQ records
        self.assertEqual(
            sidecar.recover_quality(bwt, 0), b"####")   # ACGT
        self.assertEqual(
            sidecar.recover_quality(bwt, 1), b"!!!!")   # AAAA
        self.assertEqual(
            sidecar.recover_quality(bwt, 2), b"IIII")   # TTTT
        # alignment matches the FASTQ-derived values directly (each leaf
        # read's rows carry the quality of its about-mapped file record)
        q = np.zeros(len(f9.load_rows(leaf)), dtype=np.uint8)
        rec_by_name = {r[0]: r for r in fastq_records}
        about_map = {0: 1, 1: 2, 2: 0}
        for idx, row in enumerate(f9.load_rows(leaf)):
            read = reads[row["read_id"]]
            if row["pos"] >= len(read):
                q[idx] = int(NO_QUALITY)
            else:
                file_read = about_map[row["read_id"]]
                q[idx] = ord(
                    rec_by_name["read%d" % file_read][2][row["pos"]])
        self.assertTrue(np.array_equal(sidecar.values, q))

    def test_fastq_retrofit_gz_and_multiple_files(self):
        reads = ["ACGT", "AAAA"]
        f1 = os.path.join(self.work, "lane1.fastq.gz")
        f2 = os.path.join(self.work, "lane2.fastq")
        write_fastq(f1, [("r0", "ACGT", "####")])
        write_fastq(f2, [("r1", "AAAA", "!!!!")])
        leaf = self._build_leaf_with_about(
            reads, [(0, 0), (1, 0)])
        bwt = NaiveQualityBWT(leaf)
        initialize_leaf_quality_from_fastqs(leaf, bwt, [f1, f2])
        sidecar = QualitySidecar(leaf)
        self.assertEqual(sidecar.recover_quality(bwt, 0), b"####")
        self.assertEqual(sidecar.recover_quality(bwt, 1), b"!!!!")

    def test_fastq_retrofit_sequence_mismatch_rejected(self):
        reads = ["ACGT", "AAAA"]
        fastq = os.path.join(self.work, "src.fastq")
        write_fastq(fastq, [("r0", "ACGT", "####"), ("r1", "CCCC", "!!!!")])
        leaf = self._build_leaf_with_about(
            reads, [(0, 0), (0, 1)])
        with self.assertRaises(QualitySidecarError):
            initialize_leaf_quality_from_fastqs(
                leaf, NaiveQualityBWT(leaf), [fastq])
        # disabling verification allows it (explicit opt-out)
        initialize_leaf_quality_from_fastqs(
            leaf, NaiveQualityBWT(leaf), [fastq],
            verify_sequences=False)
        self.assertTrue(quality_sidecar_exists(leaf))

    def test_fastq_retrofit_requires_origin_mapping(self):
        leaf = f9.make_read_derived_leaf(
            self.work, "src", ["ACGT", "AAAA"])
        fastq = os.path.join(self.work, "src.fastq")
        write_fastq(fastq, [("r0", "ACGT", "####"), ("r1", "AAAA", "!!!!")])
        with self.assertRaises(QualitySidecarError):
            initialize_leaf_quality_from_fastqs(
                leaf, NaiveQualityBWT(leaf), [fastq])


class MergeQualityTests(QualityPy2TestBase):
    def test_two_way_merge_preserves_quality_exactly(self):
        reads_by_source = {
            "A": ["ACGTAC", "GATTACA", "AAAA"],
            "B": ["TTTT", "GCGTAC"],
        }
        leaves, output, rbs = self.tagged_merged(reads_by_source)
        self.assertTrue(quality_sidecar_exists(output))
        sidecar = QualitySidecar(output)
        expected = expected_merged_quality(
            output, leaves, rbs)
        self.assertTrue(np.array_equal(sidecar.values, expected))
        metadata = validate_quality_sidecar(output, full=True)
        self.assertEqual(metadata["builder"], "automatic-merge")
        self.assertIn("child_builders", metadata)

    def test_balanced_ten_source_merge_preserves_quality(self):
        leaves, output, rbs = self.tagged_merged()
        sidecar = QualitySidecar(output)
        expected = expected_merged_quality(output, leaves, rbs)
        self.assertTrue(np.array_equal(sidecar.values, expected))
        self.assertEqual(sidecar.bwt_rows, 191)

    def test_one_sided_quality_merge_rejected_before_merge(self):
        leaf_a = f9.make_read_derived_leaf(
            self.work, "A", ["ACGTAC", "AAAA"])
        leaf_b = f9.make_read_derived_leaf(
            self.work, "B", ["TTTT", "CCCC"])
        initialize_leaf_quality_from_records(
            leaf_a,
            NaiveQualityBWT(leaf_a),
            [b"######", b"####"],
            sequences_by_dollar_id=["ACGTAC", "AAAA"],
        )
        called = [False]

        def should_not_run(*args, **kwargs):
            called[0] = True

        with self.assertRaises(QualitySidecarError):
            merge_two_with_provenance(
                leaf_a, leaf_b, os.path.join(self.work, "bad"),
                merge_two_func=should_not_run)
        self.assertFalse(called[0])

    def test_merge_without_quality_still_works(self):
        leaf_a = f9.make_read_derived_leaf(
            self.work, "A", ["ACGTAC", "AAAA"])
        leaf_b = f9.make_read_derived_leaf(
            self.work, "B", ["TTTT", "CCCC"])
        output = os.path.join(self.work, "merged")
        merge_two_with_provenance(
            leaf_a, leaf_b, output,
            merge_two_func=f9.read_derived_merge)
        self.assertFalse(quality_sidecar_exists(output))

    def test_merged_retrofit_from_leaf_arrays(self):
        leaves, output, rbs = self.tagged_merged()
        # strip quality from the merged package
        from MUS.BWTTags import remove_tag
        remove_tag(output, QUALITY_TAG_NAME)
        os.remove(os.path.join(output, "quality_sidecar.json"))
        self.assertFalse(quality_sidecar_exists(output))
        arrays_by_source = {
            sid: QualitySidecar(leaf).values
            for sid, leaf in leaves.items()
        }
        retrofit_merged_quality_from_leaf_arrays(
            output, arrays_by_source)
        sidecar = QualitySidecar(output)
        expected = expected_merged_quality(output, leaves, rbs)
        self.assertTrue(np.array_equal(sidecar.values, expected))


class RemovalQualityTests(QualityPy2TestBase):
    def test_removal_filters_quality_with_exact_mask(self):
        leaves, output, rbs = self.tagged_merged()
        sidecar = QualitySidecar(output)
        keep_set = set(s for s in f9.TEN_SOURCE_READS
                       if s not in ("sample00", "sample02", "sample09"))
        manifest = load_manifest(output)
        mask = np.asarray(
            [f9_row_source(output, manifest, x) in keep_set
             for x in range(sidecar.bwt_rows)],
            dtype=np.bool_)
        reduced = os.path.join(self.work, "reduced")
        stats = remove_sources(
            output, reduced,
            sources=["sample00", "sample02", "sample09"])
        self.assertTrue(stats["quality_sidecar_preserved"])
        rsidecar = QualitySidecar(reduced)
        self.assertTrue(np.array_equal(
            rsidecar.values, sidecar.values[mask]))
        # every surviving read recovers its exact original quality
        # (the reduced package gets test-side naive rows from the
        # independent suffix sort of the retained leaves, byte-equal to
        # the reduced BWT by the Feature-10 invariant)
        save_expected_rows(reduced, leaves, keep_set)
        reduced_oracle = f9.OracleReadIdentity(
            reduced,
            {sid: leaves[sid] for sid in keep_set},
            {sid: f9.TEN_SOURCE_READS[sid] for sid in keep_set})
        reduced_bwt = NaiveQualityBWT(reduced, oracle=reduced_oracle)
        for sid in keep_set:
            reads = f9.TEN_SOURCE_READS[sid]
            for local_id in range(len(reads)):
                dollar_id = reduced_oracle.global_dollar[(sid, local_id)]
                quality = rsidecar.recover_quality(
                    reduced_bwt, dollar_id)
                self.assertEqual(
                    quality, quality_for_read(reads[local_id], local_id, 0),
                    (sid, local_id))


def save_expected_rows(directory, leaves, keep_ids):
    """Write naive suffix rows for a reduced package (test-side oracle).

    The reduced BWT is byte-equal to the independent suffix sort of the
    retained leaves (verified Feature-10 invariant), so these rows are a
    faithful fixture for row-level oracles.
    """
    all_order = {sid: i for i, sid in enumerate(leaves)}
    rows = []
    for sid in keep_ids:
        for r in f9.load_rows(leaves[sid]):
            rows.append((
                r["suffix"],
                all_order[sid],
                r["read_id"],
                r["pos"],
                r["bwt"],
            ))
    rows.sort()
    out = [
        {"suffix": a, "read_id": c, "pos": d, "bwt": e}
        for a, b, c, d, e in rows
    ]
    f9.save_rows(directory, out)


def f9_row_source(merged_dir, manifest, row_index):
    node = manifest["root"]
    local_index = int(row_index)
    while node["type"] == "merge":
        packed = np.load(os.path.join(
            merged_dir, str(node["interleave"])), mmap_mode="r")
        needed = (node["length"] + 7) // 8
        used = np.asarray(packed[:needed], dtype=np.uint8)
        shifts = np.arange(8, dtype=np.uint8)
        bits = ((used[:, None] >> shifts[None, :]) & np.uint8(1))
        bits = bits.reshape(-1)[:node["length"]]
        bit = int(bits[local_index])
        if bit == 0:
            local_index = int(np.count_nonzero(bits[:local_index] == 0))
            node = node["left"]
        else:
            local_index = int(np.count_nonzero(bits[:local_index] == 1))
            node = node["right"]
    return str(node["source_id"])


def f9_dollar_for(merged_dir, manifest, sid, local_id):
    """Independent global dollar id of (source, local read)."""
    node = manifest["root"]
    # dollar rows are rows [0, R); walk row `local_id`-th dollar row of sid
    total_reads = sum(1 for r in f9.load_rows(merged_dir)
                      if r["suffix"] == "$")
    for dollar_id in range(total_reads):
        source = f9_row_source(merged_dir, manifest, dollar_id)
        if source == sid:
            if local_id == 0:
                return dollar_id
            local_id -= 1
    raise AssertionError("dollar not found")


class QueryQualityTests(QualityPy2TestBase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="q1-query-")
        cls.leaves, cls.output, cls.rbs = cls._build(cls.work)
        cls.sidecar = QualitySidecar(cls.output)
        cls.index = MultiSourceQueryIndex(
            cls.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        cls.oracle = f9.OracleReadIdentity(
            cls.output,
            {sid: cls.leaves[sid] for sid in cls.leaves},
            cls.rbs)
        from MUS.ReadProvenance import ReadProvenanceIndex
        from MUS.BWTTags import BWTTagStore
        cls.wrapped = MultiSourceBWT(
            None, cls.index, quality_sidecar=cls.sidecar,
            bwt_tags=BWTTagStore(cls.output),
            read_provenance=ReadProvenanceIndex(
                cls.output, mmap=False, source_index=cls.index))
        cls.wrapped.bwt = NaiveQualityBWT(cls.output, oracle=cls.oracle)

    @classmethod
    def _build(cls, work):
        from MUS.ReadProvenance import ReadProvenanceIndex

        leaves = {}
        for sid, reads in f9.TEN_SOURCE_READS.items():
            leaf = f9.make_read_derived_leaf(work, sid, reads)
            f9.attach_leaf_read_provenance(leaf, reads)
            qualities = [
                quality_for_read(reads[i], i, 0)
                for i in range(len(reads))
            ]
            initialize_leaf_quality_from_records(
                leaf, NaiveQualityBWT(leaf), qualities,
                sequences_by_dollar_id=reads)
            leaves[sid] = leaf
        output = os.path.join(work, "merged10")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f9.read_derived_merge)
        return leaves, output, f9.TEN_SOURCE_READS

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_has_quality_and_row_api(self):
        self.assertTrue(self.wrapped.hasQuality())
        plain = MultiSourceBWT(None, self.index)
        self.assertFalse(plain.hasQuality())
        with self.assertRaises(MultiSourceQueryError):
            plain.readQuality(0)
        # sentinel row -> None; base row -> exact byte
        self.assertIsNone(self.wrapped.qualityForRow(0))
        value = int(self.sidecar.values[30])
        self.assertEqual(
            self.wrapped.qualityForRow(30),
            chr(value) if sys.version_info[0] == 2 else bytes([value]))

    def test_read_quality_and_fastq_data_exact(self):
        for sid in ("sample00", "sample03", "sample09"):
            reads = f9.TEN_SOURCE_READS[sid]
            for local_id in range(len(reads)):
                dollar_id = self.oracle.global_dollar[(sid, local_id)]
                quality = self.wrapped.readQuality(dollar_id)
                self.assertEqual(
                    quality, quality_for_read(reads[local_id], local_id, 0),
                    (sid, local_id))
                sequence, q2 = self.wrapped.readSequenceAndQuality(dollar_id)
                self.assertEqual(
                    sequence, reads[local_id].encode("ascii"))
                self.assertEqual(q2, quality)

    def test_quality_values_merged_and_selected(self):
        manifest = load_manifest(self.output)
        for pattern in ("A", "AC", "CGT", "AAAA", "N"):
            low, high = naive_interval_q(self.output, pattern)
            result = self.wrapped.qualityValues(pattern)
            self.assertEqual(
                result["value_count"], high - low, pattern)
            self.assertTrue(np.array_equal(
                result["values"],
                self.sidecar.values[low:high]), pattern)
            for sid in ("sample00", "sample09"):
                sresult = self.wrapped.qualityValues(
                    pattern, source=sid)
                expected_rows = [
                    x for x in range(low, high)
                    if f9_row_source(self.output, manifest, x) == sid
                ]
                self.assertEqual(
                    sresult["value_count"], len(expected_rows),
                    (pattern, sid))
                self.assertTrue(np.array_equal(
                    sresult["values"],
                    self.sidecar.values[expected_rows]),
                    (pattern, sid))

    def test_reads_containing_include_quality(self):
        result = self.wrapped.readsContaining(
            "AAGGTT", include_quality=True)
        self.assertEqual(len(result["reads"]), 1)
        record = result["reads"][0]
        self.assertEqual(record["source_id"], "sample09")
        self.assertEqual(
            record["quality"],
            quality_for_read("AAGGTT", 2, 0))
        # without the sidecar, include_quality raises
        plain = MultiSourceBWT(None, self.index)
        plain.bwt = self.wrapped.bwt
        with self.assertRaises(MultiSourceQueryError):
            plain.readsContaining("A", include_quality=True)


def naive_interval_q(directory, pattern):
    suffixes = [row["suffix"] for row in f9.load_rows(directory)]
    low = bisect_left(suffixes, pattern)
    high = bisect_left(suffixes, pattern + "\x7f")
    return low, high


class RandomizedQualityTests(QualityPy2TestBase):
    def test_randomized_quality_through_merges_and_removals(self):
        for seed_index, seed in enumerate(SEEDS):
            rng = random.Random(seed)
            for case in range(6):
                reads_by_source = {}
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
                    reads_by_source[sid] = reads
                    leaf = f9.make_read_derived_leaf(self.work, sid, reads)
                    qualities = [
                        quality_for_read(reads[j], j, seed_index)
                        for j in range(len(reads))
                    ]
                    initialize_leaf_quality_from_records(
                        leaf, NaiveQualityBWT(leaf), qualities,
                        sequences_by_dollar_id=reads)
                    leaves[sid] = leaf
                output = os.path.join(
                    self.work, "rand_%02d_%02d" % (seed_index, case))
                merge_many_balanced(
                    list(leaves.values()), output,
                    merge_two_func=f9.read_derived_merge)
                sidecar = QualitySidecar(output)
                expected = expected_merged_quality(
                    output, leaves, reads_by_source, salt=seed_index)
                self.assertTrue(np.array_equal(
                    sidecar.values, expected),
                    (seed, case, "merge"))
                remove_ids = [
                    sid for sid in leaves if rng.random() < 0.4
                ]
                if not remove_ids or len(remove_ids) == len(leaves):
                    remove_ids = [list(leaves)[0]]
                reduced = os.path.join(
                    self.work, "randred_%02d_%02d" % (seed_index, case))
                stats = remove_sources(
                    output, reduced, sources=remove_ids)
                self.assertTrue(stats["quality_sidecar_preserved"])
                rsidecar = QualitySidecar(reduced)
                keep = set(reads_by_source) - set(remove_ids)
                manifest = load_manifest(output)
                mask = np.asarray(
                    [f9_row_source(output, manifest, x) in keep
                     for x in range(sidecar.bwt_rows)],
                    dtype=np.bool_)
                self.assertTrue(np.array_equal(
                    rsidecar.values, sidecar.values[mask]),
                    (seed, case, "remove"))


if __name__ == "__main__":
    unittest.main()
