"""Host-side regression tests for enhanced-modern2 Q1: exact lossless
FASTQ quality sidecar (``MUS.QualitySidecar``, a strict Point-12
specialization).

These tests are read-only and run on any CPython 3 with NumPy; they do NOT
require the compiled MUSCython extensions (real-merge integration runs in
the pinned Python-2.7 suite and the Q1 validation driver).

Coverage:

- suffix-start alignment oracle: for the suffix row beginning at read
  position ``p``, ``quality[row] == Q[p]``; the terminal ``$`` row stores
  255; expected arrays computed directly from the naive suffix rows and
  the original reads (no Q1 code);
- exhaustive small datasets (unique/duplicate/identical/mixed-length/
  N-heavy/1-base reads);
- leaf initialization from records with independent sequence
  verification and mismatch rejection; reserved byte-255 rejection;
  Phred analysis helper;
- disk-backed FASTQ retrofit (plain and .gz, unsorted about.npy origin
  remapping, sequence-mismatch rejection, missing origin mapping);
- two-way and balanced 10-source merges preserve every quality row;
  one-sided quality merge rejected BEFORE the BWT merge;
- merged retrofit from leaf arrays (BWT bytes unchanged);
- Feature-10 removal: ``quality_reduced == quality_original[keep_mask]``;
  surviving reads recover their exact original quality lines;
- query APIs: ``hasQuality`` / ``qualityForRow`` (sentinel -> None) /
  ``readQuality`` / ``readSequenceAndQuality`` / ``readFastqData`` /
  ``qualityValues`` (merged + source/group/where) /
  ``readsContaining(include_quality=True)``;
- randomized differentials (seeds 20260811/20260812/20260813);
- evidence-record and validation-driver consistency.
"""

import gzip
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

from MUS.QualitySidecar import (  # noqa: E402
    NO_QUALITY,
    QUALITY_TAG_NAME,
    QualitySidecar,
    QualitySidecarError,
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
from MUS.ReadProvenance import ReadProvenanceIndex  # noqa: E402
from MUS.SourceMetadata import SourceMetadataCatalog  # noqa: E402
from MUS.SourceRemoval import remove_sources  # noqa: E402

import test_multisource_query as f3  # noqa: E402
import test_read_provenance as f9  # noqa: E402

SEEDS = (20260811, 20260812, 20260813)

EVIDENCE = os.path.join(PACKAGE, "evidence", "q1-quality-sidecar.json")
EVIDENCE_GENERATOR = os.path.join(
    PACKAGE, "validate", "q1_quality_sidecar_evidence.py")
VALIDATION_DRIVER = os.path.join(
    PACKAGE, "validate", "q1-quality-sidecar.sh")

QUALITY_BYTES = [
    ord(c) for c in "!\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ"
]


def quality_for_read(read, read_id, salt=0):
    return bytes([
        QUALITY_BYTES[(read_id * 7 + p + salt) % len(QUALITY_BYTES)]
        for p in range(len(read))
    ])


def expected_leaf_quality(leaf_dir, reads, salt=0):
    rows = f3.load_rows(leaf_dir)
    out = np.zeros(len(rows), dtype=np.uint8)
    for idx, row in enumerate(rows):
        read = reads[row["read_id"]]
        if row["pos"] >= len(read):
            out[idx] = int(NO_QUALITY)
        else:
            out[idx] = quality_for_read(
                read, row["read_id"], salt)[row["pos"]]
    return out


def expected_merged_quality(merged_dir, leaves, reads_by_source, salt=0):
    all_order = {sid: i for i, sid in enumerate(reads_by_source)}
    rows = []
    for sid in reads_by_source:
        for idx, row in enumerate(f3.load_rows(leaves[sid])):
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


def walk_row(merged_dir, manifest, row_index):
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
    return str(node["source_id"]), local_index


def row_source(merged_dir, manifest, row_index):
    return walk_row(merged_dir, manifest, row_index)[0]


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


class NaiveQualityBWT(object):
    """Naive BWT adapter over the fixture suffix rows with withIndex."""

    def __init__(self, directory, oracle=None):
        self.directory = str(directory)
        self.rows = f3.load_rows(self.directory)
        self.suffixes = [r["suffix"] for r in self.rows]
        self.lf_calls = 0
        self.oracle = oracle
        self.merged_index = None
        if oracle is not None:
            self.merged_index = {}
            manifest = load_manifest(self.directory, validate=True)
            for x in range(len(self.rows)):
                sid, local = walk_row(self.directory, manifest, x)
                self.merged_index[(sid, int(local))] = x

    def getTotalSize(self):
        return len(self.rows)

    def findIndicesOfStr(self, seq, givenRange=None):
        if givenRange is not None:
            raise NotImplementedError("givenRange not used in Q1 tests")
        pattern = seq.decode("ascii") if isinstance(seq, bytes) else str(seq)
        lo = 0
        hi = len(self.suffixes)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.suffixes[mid] < pattern:
                lo = mid + 1
            else:
                hi = mid
        low = lo
        lo = 0
        hi = len(self.suffixes)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.suffixes[mid] < pattern + "\x7f":
                lo = mid + 1
            else:
                hi = mid
        return low, lo

    def countOccurrencesOfSeq(self, seq, givenRange=None):
        low, high = self.findIndicesOfStr(seq, givenRange)
        return high - low

    def getSequenceDollarID(self, row_index, returnOffset=False):
        self.lf_calls += 1
        if self.oracle is not None:
            return self.oracle.getSequenceDollarID(row_index, returnOffset)
        row_index = int(row_index)
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


def write_fastq(path, records):
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


class QualityHostTestBase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="q1-host-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def build_quality_leaves(self, reads_by_source=None, salt=0):
        reads_by_source = reads_by_source or f3.TEN_SOURCE_READS
        leaves = {}
        for sid, reads in reads_by_source.items():
            leaf = f3.make_read_derived_leaf(self.work, sid, reads)
            qualities = [
                quality_for_read(reads[i], i, salt)
                for i in range(len(reads))
            ]
            initialize_leaf_quality_from_records(
                leaf, NaiveQualityBWT(leaf), qualities,
                sequences_by_dollar_id=reads)
            leaves[sid] = leaf
        return leaves, reads_by_source


class LeafQualityHostTests(QualityHostTestBase):
    def test_suffix_start_alignment_every_row(self):
        cases = [
            {"S1": ["ACGT", "AAAA", "NACGN"], "S2": ["T", "G", "NN"]},
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
                    sidecar.values, expected), (case_index, sid))
                for idx in range(expected.shape[0]):
                    self.assertEqual(
                        int(sidecar.values[idx]), int(expected[idx]),
                        (case_index, sid, idx))

    def test_recovery_and_errors(self):
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
                    quality, quality_for_read(reads[dollar_id], dollar_id),
                    (sid, dollar_id))
                sequence, q2 = sidecar.recover_sequence_and_quality(
                    NaiveQualityBWT(leaf), dollar_id)
                self.assertEqual(
                    sequence, reads[dollar_id].encode("ascii"))
                self.assertEqual(q2, quality)
        leaf = f3.make_read_derived_leaf(self.work, "src", ["ACGT", "AAAA"])
        with self.assertRaises(QualitySidecarError):
            initialize_leaf_quality_from_records(
                leaf, NaiveQualityBWT(leaf), [b"####", b"!!!!"],
                sequences_by_dollar_id=["ACGT", "CCCC"])
        with self.assertRaises(QualitySidecarError):
            initialize_leaf_quality_from_records(
                leaf, NaiveQualityBWT(leaf), [b"###\xff", b"!!!!"],
                sequences_by_dollar_id=["ACGT", "AAAA"])
        self.assertTrue(np.array_equal(
            quality_ascii_to_phred(np.asarray([33, 43, 63], dtype=np.uint8)),
            np.asarray([0, 10, 30])))


class FastqRetrofitHostTests(QualityHostTestBase):
    def test_unsorted_origin_order_and_gz(self):
        reads = ["ACGT", "AAAA", "TTTT"]
        f1 = os.path.join(self.work, "lane1.fastq.gz")
        f2 = os.path.join(self.work, "lane2.fastq")
        write_fastq(f1, [("r0", "TTTT", "IIII"), ("r1", "ACGT", "####")])
        write_fastq(f2, [("r0", "AAAA", "!!!!")])
        leaf = f3.make_read_derived_leaf(self.work, "src", reads)
        about = np.empty(
            3, dtype=np.dtype([("f0", "<u1"), ("f1", "<u8")]))
        about[0] = (0, 1)   # ACGT -> file0 read1
        about[1] = (1, 0)   # AAAA -> file1 read0
        about[2] = (0, 0)   # TTTT -> file0 read0
        np.save(os.path.join(leaf, "about.npy"), about)
        bwt = NaiveQualityBWT(leaf)
        metadata = initialize_leaf_quality_from_fastqs(
            leaf, bwt, [f1, f2])
        self.assertEqual(metadata["builder"], "leaf-fastq-retrofit")
        sidecar = QualitySidecar(leaf)
        self.assertEqual(sidecar.recover_quality(bwt, 0), b"####")
        self.assertEqual(sidecar.recover_quality(bwt, 1), b"!!!!")
        self.assertEqual(sidecar.recover_quality(bwt, 2), b"IIII")

    def test_sequence_mismatch_rejected_and_opt_out(self):
        reads = ["ACGT", "AAAA"]
        fastq = os.path.join(self.work, "src.fastq")
        write_fastq(fastq, [("r0", "ACGT", "####"), ("r1", "CCCC", "!!!!")])
        leaf = f3.make_read_derived_leaf(self.work, "src", reads)
        about = np.empty(
            2, dtype=np.dtype([("f0", "<u1"), ("f1", "<u8")]))
        about[0] = (0, 0)
        about[1] = (0, 1)
        np.save(os.path.join(leaf, "about.npy"), about)
        with self.assertRaises(QualitySidecarError):
            initialize_leaf_quality_from_fastqs(
                leaf, NaiveQualityBWT(leaf), [fastq])
        initialize_leaf_quality_from_fastqs(
            leaf, NaiveQualityBWT(leaf), [fastq],
            verify_sequences=False)
        self.assertTrue(quality_sidecar_exists(leaf))
        # no origin mapping -> rejected
        leaf2 = f3.make_read_derived_leaf(
            self.work, "noorigin", ["ACGT", "AAAA"])
        with self.assertRaises(QualitySidecarError):
            initialize_leaf_quality_from_fastqs(
                leaf2, NaiveQualityBWT(leaf2), [fastq])


class MergeQualityHostTests(QualityHostTestBase):
    def test_merges_preserve_quality_exactly(self):
        leaves, rbs = self.build_quality_leaves()
        output = os.path.join(self.work, "merged10")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f3.read_derived_merge)
        self.assertTrue(quality_sidecar_exists(output))
        sidecar = QualitySidecar(output)
        expected = expected_merged_quality(output, leaves, rbs)
        self.assertTrue(np.array_equal(sidecar.values, expected))
        self.assertEqual(sidecar.bwt_rows, 191)
        metadata = validate_quality_sidecar(output, full=True)
        self.assertEqual(metadata["builder"], "automatic-merge")
        # two-way
        two = {}
        for sid, reads in (("A", ["ACGTAC", "GATTACA", "AAAA"]),
                           ("B", ["TTTT", "GCGTAC"])):
            leaf = f3.make_read_derived_leaf(self.work, sid, reads)
            two[sid] = leaf
        for sid, leaf in two.items():
            reads = {"A": ["ACGTAC", "GATTACA", "AAAA"],
                     "B": ["TTTT", "GCGTAC"]}[sid]
            initialize_leaf_quality_from_records(
                leaf, NaiveQualityBWT(leaf),
                [quality_for_read(reads[i], i) for i in range(len(reads))],
                sequences_by_dollar_id=reads)
        out2 = os.path.join(self.work, "two")
        merge_two_with_provenance(
            two["A"], two["B"], out2,
            merge_two_func=f3.read_derived_merge)
        self.assertTrue(np.array_equal(
            QualitySidecar(out2).values,
            expected_merged_quality(out2, two,
                                    {"A": ["ACGTAC", "GATTACA", "AAAA"],
                                     "B": ["TTTT", "GCGTAC"]})))

    def test_one_sided_quality_merge_rejected_before_merge(self):
        leaf_a = f3.make_read_derived_leaf(
            self.work, "A", ["ACGTAC", "AAAA"])
        leaf_b = f3.make_read_derived_leaf(
            self.work, "B", ["TTTT", "CCCC"])
        initialize_leaf_quality_from_records(
            leaf_a, NaiveQualityBWT(leaf_a),
            [b"######", b"####"],
            sequences_by_dollar_id=["ACGTAC", "AAAA"])
        called = [False]

        def should_not_run(*args, **kwargs):
            called[0] = True

        with self.assertRaises(QualitySidecarError):
            merge_two_with_provenance(
                leaf_a, leaf_b, os.path.join(self.work, "bad"),
                merge_two_func=should_not_run)
        self.assertFalse(called[0])
        self.assertFalse(os.path.exists(
            os.path.join(self.work, "bad", "msbwt.npy")))

    def test_merged_retrofit_from_leaf_arrays(self):
        from MUS.BWTTags import remove_tag

        leaves, rbs = self.build_quality_leaves()
        output = os.path.join(self.work, "merged10")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f3.read_derived_merge)
        remove_tag(output, QUALITY_TAG_NAME)
        os.remove(os.path.join(output, "quality_sidecar.json"))
        self.assertFalse(quality_sidecar_exists(output))
        arrays_by_source = {
            sid: QualitySidecar(leaf).values
            for sid, leaf in leaves.items()
        }
        retrofit_merged_quality_from_leaf_arrays(
            output, arrays_by_source)
        self.assertTrue(np.array_equal(
            QualitySidecar(output).values,
            expected_merged_quality(output, leaves, rbs)))


class RemovalQualityHostTests(QualityHostTestBase):
    def test_removal_filters_quality_and_recovers_reads(self):
        leaves, rbs = self.build_quality_leaves()
        output = os.path.join(self.work, "merged10")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f3.read_derived_merge)
        sidecar = QualitySidecar(output)
        keep_set = set(s for s in f3.TEN_SOURCE_READS
                       if s not in ("sample00", "sample02", "sample09"))
        manifest = load_manifest(output)
        mask = np.asarray(
            [row_source(output, manifest, x) in keep_set
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
        # surviving reads recover exact original quality lines
        save_expected_rows(reduced, leaves, keep_set)
        oracle = f9.OracleReadIdentity(
            reduced,
            {sid: leaves[sid] for sid in keep_set},
            {sid: f3.TEN_SOURCE_READS[sid] for sid in keep_set})
        rbwt = NaiveQualityBWT(reduced, oracle=oracle)
        for sid in keep_set:
            reads = f3.TEN_SOURCE_READS[sid]
            for local_id in range(len(reads)):
                dollar_id = oracle.global_dollar[(sid, local_id)]
                self.assertEqual(
                    rsidecar.recover_quality(rbwt, dollar_id),
                    quality_for_read(reads[local_id], local_id),
                    (sid, local_id))


def save_expected_rows(directory, leaves, keep_ids):
    all_order = {sid: i for i, sid in enumerate(leaves)}
    rows = []
    for sid in keep_ids:
        for r in f3.load_rows(leaves[sid]):
            rows.append((
                r["suffix"], all_order[sid], r["read_id"], r["pos"],
                r["bwt"]))
    rows.sort()
    out = [
        {"suffix": a, "read_id": c, "pos": d, "bwt": e}
        for a, b, c, d, e in rows
    ]
    with open(os.path.join(directory, f3.ROWS_FILENAME), "w") as fp:
        json.dump(out, fp, separators=(",", ":"))


class QueryQualityHostTests(QualityHostTestBase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="q1-host-query-")
        cls.leaves = {}
        for sid, reads in f3.TEN_SOURCE_READS.items():
            leaf = f3.make_read_derived_leaf(cls.work, sid, reads)
            f9.attach_leaf_read_provenance(leaf, reads)
            initialize_leaf_quality_from_records(
                leaf, NaiveQualityBWT(leaf),
                [quality_for_read(reads[i], i) for i in range(len(reads))],
                sequences_by_dollar_id=reads)
            cls.leaves[sid] = leaf
        cls.output = os.path.join(cls.work, "merged10")
        merge_many_balanced(
            list(cls.leaves.values()), cls.output,
            merge_two_func=f3.read_derived_merge)
        cls.sidecar = QualitySidecar(cls.output)
        cls.index = MultiSourceQueryIndex(
            cls.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        cls.oracle = f9.OracleReadIdentity(
            cls.output,
            {sid: cls.leaves[sid] for sid in cls.leaves},
            f3.TEN_SOURCE_READS)
        cls.wrapped = MultiSourceBWT(
            None, cls.index, quality_sidecar=cls.sidecar,
            bwt_tags=cls.sidecar.store,
            read_provenance=ReadProvenanceIndex(
                cls.output, mmap=False, source_index=cls.index))
        cls.wrapped.bwt = NaiveQualityBWT(cls.output, oracle=cls.oracle)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_quality_api(self):
        self.assertTrue(self.wrapped.hasQuality())
        plain = MultiSourceBWT(None, self.index)
        self.assertFalse(plain.hasQuality())
        with self.assertRaises(MultiSourceQueryError):
            plain.readQuality(0)
        self.assertIsNone(self.wrapped.qualityForRow(0))
        self.assertEqual(
            self.wrapped.qualityForRow(30),
            bytes([int(self.sidecar.values[30])]))
        for sid in ("sample00", "sample03", "sample09"):
            reads = f3.TEN_SOURCE_READS[sid]
            for local_id in range(len(reads)):
                dollar_id = self.oracle.global_dollar[(sid, local_id)]
                quality = self.wrapped.readQuality(dollar_id)
                self.assertEqual(
                    quality, quality_for_read(reads[local_id], local_id),
                    (sid, local_id))
                sequence, q2 = self.wrapped.readSequenceAndQuality(dollar_id)
                self.assertEqual(
                    sequence, reads[local_id].encode("ascii"))
                self.assertEqual(q2, quality)
                record = self.wrapped.readFastqData(dollar_id)
                self.assertEqual(record["quality"], quality)
                self.assertEqual(
                    record["provenance"]["source_id"], sid)

    def test_quality_values_and_reads_containing(self):
        manifest = load_manifest(self.output)
        for pattern in ("A", "AC", "CGT", "AAAA", "N"):
            low, high = naive_interval(self.output, pattern)
            result = self.wrapped.qualityValues(pattern)
            self.assertEqual(result["value_count"], high - low, pattern)
            self.assertTrue(np.array_equal(
                result["values"],
                self.sidecar.values[low:high]), pattern)
            for sid in ("sample00", "sample09"):
                sresult = self.wrapped.qualityValues(
                    pattern, source=sid)
                expected_rows = [
                    x for x in range(low, high)
                    if row_source(self.output, manifest, x) == sid
                ]
                self.assertEqual(
                    sresult["value_count"], len(expected_rows),
                    (pattern, sid))
                self.assertTrue(np.array_equal(
                    sresult["values"],
                    self.sidecar.values[expected_rows]),
                    (pattern, sid))
        result = self.wrapped.readsContaining(
            "AAGGTT", include_quality=True)
        self.assertEqual(len(result["reads"]), 1)
        self.assertEqual(
            result["reads"][0]["quality"],
            quality_for_read("AAGGTT", 2))


class RandomizedQualityHostTests(QualityHostTestBase):
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
                    leaf = f3.make_read_derived_leaf(self.work, sid, reads)
                    initialize_leaf_quality_from_records(
                        leaf, NaiveQualityBWT(leaf),
                        [quality_for_read(reads[j], j, seed_index)
                         for j in range(len(reads))],
                        sequences_by_dollar_id=reads)
                    leaves[sid] = leaf
                output = os.path.join(
                    self.work, "rand_%02d_%02d" % (seed_index, case))
                merge_many_balanced(
                    list(leaves.values()), output,
                    merge_two_func=f3.read_derived_merge)
                sidecar = QualitySidecar(output)
                expected = expected_merged_quality(
                    output, leaves, reads_by_source, salt=seed_index)
                self.assertTrue(np.array_equal(
                    sidecar.values, expected), (seed, case))
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
                    [row_source(output, manifest, x) in keep
                     for x in range(sidecar.bwt_rows)],
                    dtype=np.bool_)
                self.assertTrue(np.array_equal(
                    rsidecar.values, sidecar.values[mask]),
                    (seed, case))


class EvidenceConsistencyTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = json.load(open(EVIDENCE, encoding="utf-8"))
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "enhanced-modern2")
        self.assertEqual(
            evidence["final"]["milestone"],
            "enhanced-modern2-q1-quality-sidecar")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")

    def test_evidence_contract(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["seed"], 20260811)
        alignment = report["alignment"]
        self.assertEqual(alignment["rows"], 191)
        self.assertEqual(alignment["mismatches"], 0)
        self.assertTrue(report["fastq_retrofit"]["unsorted_origin"])
        merged = report["merge_lifecycle"]
        self.assertEqual(merged["mismatches"], 0)
        self.assertTrue(report["merge_lifecycle"]["one_sided_rejected"])
        removal = report["removal"]
        self.assertEqual(removal["mismatches"], 0)
        self.assertTrue(removal["read_quality_recovered"])
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
        self.assertIn("q1-quality-sidecar", driver)


if __name__ == "__main__":
    unittest.main()
