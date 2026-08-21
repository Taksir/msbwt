"""Host-side regression tests for enhanced-modern2 Feature 9: exact
read-level provenance (``MUS.ReadProvenance`` plus the Feature-9 additions
to ``MUS.MultiSourceProvenance`` and ``MUS.MultiSourceQuery``).

These tests are read-only and run on any CPython 3 with NumPy; they do NOT
require the compiled MUSCython extensions (real-merge integration runs in
the pinned Python-2.7 suite and the Feature-9 validation driver).

Coverage:

- read-derived tiny fixture machinery with a fully independent read
  identity oracle (naive suffix rows + direct interleave counting): every
  merged dollar ID resolves to the exact (source, local read, origin
  file/read ID) identity; every BWT row's read matches the provenance
  tree; mate links survive; duplicate/identical reads keep identities;
- leaf initialization from explicit records and from legacy ``about.npy``
  (structured and 2-D layouts) with optional input-file tables;
- 20-byte packed records, memory-mapped loading, exact-size verification;
- automatic two-way/balanced merges; one-sided read-provenance merge
  rejection before the BWT merge;
- retrofit of a stripped merged package reproduces the fresh-merge read
  provenance exactly and leaves BWT/provenance.json bytes unchanged;
- ``readsContaining`` == naive per-read overlapping counts for the full
  pattern set; source/subset/group/where filters == independently filtered
  global result; source-prefilter LF-walk reduction; include_sequence
  recovery; max_occurrences truncation; missing-read-provenance errors;
- persistence safety: wrong count, wrong dtype, truncated array, wrong
  format/version/ordering, replaced same-length BWT, copied foreign
  same-length array, unknown source metadata, missing metadata file;
- randomized differentials (seeds 20260811/20260812/20260813);
- evidence-record and validation-driver consistency.
"""

import gc
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
    ProvenanceError,
    initialize_leaf_provenance,
    load_manifest,
    merge_many_balanced,
    merge_two_with_provenance,
    unpack_interleave,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryError,
    MultiSourceQueryIndex,
)
from MUS.ReadProvenance import (  # noqa: E402
    ReadProvenanceError,
    ReadProvenanceIndex,
    initialize_leaf_read_provenance,
    initialize_leaf_read_provenance_from_about,
    read_provenance_exists,
    retrofit_read_provenance_from_leaf_dirs,
)
from MUS.SourceMetadata import SourceMetadataCatalog  # noqa: E402

import test_multisource_query as f3  # noqa: E402
import test_multisource_provenance as f2  # noqa: E402

SEEDS = (20260811, 20260812, 20260813)

EVIDENCE = os.path.join(PACKAGE, "evidence", "feature9-read-provenance.json")
EVIDENCE_GENERATOR = os.path.join(
    PACKAGE, "validate", "feature9_read_provenance_evidence.py")
VALIDATION_DRIVER = os.path.join(
    PACKAGE, "validate", "feature9-read-provenance.sh")


class OracleReadIdentity(object):
    """Fully independent read-identity oracle over naive suffix rows.

    ``getSequenceDollarID`` / ``recoverString`` are reimplemented here from
    the fixture ground truth (leaf suffix rows and the provenance tree).
    No Feature-9 code is used to build expectations.
    """

    def __init__(self, merged_dir, leaf_dirs_by_source, reads_by_source):
        self.merged_dir = str(merged_dir)
        self.manifest = load_manifest(self.merged_dir, validate=True)
        self.leaf_rows = {}
        self.reads = {}
        self.leaf_dollar_rows = {}
        for sid, leaf_dir in leaf_dirs_by_source.items():
            rows = f3.load_rows(leaf_dir)
            self.leaf_rows[sid] = rows
            self.reads[sid] = reads_by_source[sid]
            dollar_rows = [r for r in rows if r["suffix"] == "$"]
            local_dollar = {}
            for index, row in enumerate(dollar_rows):
                local_dollar[int(row["read_id"])] = index
            self.leaf_dollar_rows[sid] = local_dollar

        total_reads = sum(len(reads) for reads in reads_by_source.values())
        self.global_dollar = {}
        self.dollar_to_identity = {}
        for dollar_id in range(total_reads):
            sid, local_row = tree_walk_row(
                self.merged_dir, self.manifest, dollar_id)
            read_id = int(self.leaf_rows[sid][local_row]["read_id"])
            local_dollar = self.leaf_dollar_rows[sid][read_id]
            self.global_dollar[(sid, local_dollar)] = dollar_id
            self.dollar_to_identity[dollar_id] = (sid, local_dollar)
        self.read_count = total_reads

    def getSequenceDollarID(self, row_index, returnOffset=False):
        sid, local_row = tree_walk_row(
            self.merged_dir, self.manifest, int(row_index))
        leaf_row = self.leaf_rows[sid][local_row]
        read_id = int(leaf_row["read_id"])
        local_dollar = self.leaf_dollar_rows[sid][read_id]
        dollar_id = self.global_dollar[(sid, local_dollar)]
        if returnOffset:
            return dollar_id, int(leaf_row["pos"])
        return dollar_id

    def recoverString(self, dollar_id):
        sid, local_dollar = self.dollar_to_identity[int(dollar_id)]
        inverse = {v: k for k, v in self.leaf_dollar_rows[sid].items()}
        read_id = inverse[local_dollar]
        # Real Holt/McMillan contract: full rotation starting at '$'.
        return ("$" + self.reads[sid][read_id]).encode("ascii")


def tree_walk_row(merged_dir, manifest, row_index):
    """(source_id, local_row) by direct bit-array counting."""
    node = manifest["root"]
    local_index = int(row_index)
    while node["type"] == "merge":
        bits = unpack_interleave(
            os.path.join(merged_dir, str(node["interleave"])),
            node["length"])
        bit = int(bits[local_index])
        if bit == 0:
            child_index = int(np.count_nonzero(bits[:local_index] == 0))
            node = node["left"]
        else:
            child_index = int(np.count_nonzero(bits[:local_index] == 1))
            node = node["right"]
        local_index = child_index
    return str(node["source_id"]), local_index


class OracleBWTAdapter(object):
    """Thin BWT view over the independent read-identity oracle."""

    def __init__(self, oracle, merged_dir, manifest):
        self.oracle = oracle
        self.merged_dir = str(merged_dir)
        self.manifest = manifest
        self.lf_calls = 0
        self.search_calls = 0
        self.rows = f3.load_rows(self.merged_dir)
        self.suffixes = [row["suffix"] for row in self.rows]

    def getTotalSize(self):
        return len(self.rows)

    def findIndicesOfStr(self, seq, givenRange=None):
        self.search_calls += 1
        pattern = seq.decode("ascii") if isinstance(seq, bytes) else str(seq)
        if givenRange is not None:
            raise NotImplementedError(
                "givenRange not used in Feature-9 host tests")
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
        return self.oracle.getSequenceDollarID(row_index, returnOffset)

    def recoverString(self, dollar_id):
        return self.oracle.recoverString(dollar_id)


def default_leaf_records(reads, origin_base=100, file_count=1):
    records = []
    for i in range(len(reads)):
        record = {
            "origin_file_id": i % file_count,
            "origin_read_id": origin_base + i,
        }
        if len(reads) >= 2 and i < 2:
            record["mate_source_read_id"] = 1 - i
        records.append(record)
    return records


def attach_leaf_read_provenance(leaf_dir, reads, origin_base=100,
                                file_count=1):
    input_files = ["%s_R%d.fastq" % (os.path.basename(leaf_dir), fid)
                   for fid in range(file_count)]
    return initialize_leaf_read_provenance(
        leaf_dir,
        default_leaf_records(reads, origin_base=origin_base,
                             file_count=file_count),
        source_metadata={"input_files": input_files},
    )


def overlapping_count(text, pattern):
    count = 0
    start = 0
    while True:
        pos = text.find(pattern, start)
        if pos < 0:
            return count
        count += 1
        start = pos + 1


def build_fixture_with_reads(work, reads_by_source, origin_base=100,
                             file_count=1, name="merged10"):
    leaves = {}
    for source_name, reads in reads_by_source.items():
        leaf = f3.make_read_derived_leaf(work, source_name, reads)
        attach_leaf_read_provenance(
            leaf, reads, origin_base=origin_base, file_count=file_count)
        leaves[source_name] = leaf
    output = os.path.join(work, name)
    work_dir = os.path.join(work, name + "_work")
    manifest = merge_many_balanced(
        list(leaves.values()), output,
        merge_two_func=f3.read_derived_merge,
        work_dir=work_dir, keep_work=True)
    oracle = OracleReadIdentity(
        output,
        {sid: leaves[sid] for sid in reads_by_source},
        reads_by_source)
    return leaves, output, manifest, oracle


class ReadProvenanceHostTestBase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f9-host-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)


class TenSourceReadProvenanceHostTests(ReadProvenanceHostTestBase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f9-host-ten-")
        cls.leaves, cls.output, cls.manifest, cls.oracle = (
            build_fixture_with_reads(cls.work, f3.TEN_SOURCE_READS))
        cls.index = ReadProvenanceIndex(cls.output, mmap=False)
        cls.wrapped = MultiSourceBWT(
            None, cls.index.source_index, read_provenance=cls.index)
        cls.wrapped.bwt = OracleBWTAdapter(cls.oracle, cls.output,
                                           cls.manifest)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_fixture_counts_and_record_size(self):
        self.assertEqual(self.index.read_count, 30)
        self.assertEqual(self.index.record_bytes(), 20)
        self.assertEqual(self.index.source_index.source_count, 10)
        self.assertTrue(read_provenance_exists(self.output))

    def test_every_dollar_id_matches_independent_oracle(self):
        for dollar_id in range(self.oracle.read_count):
            expected_source, expected_local = (
                self.oracle.dollar_to_identity[dollar_id])
            record = self.index.record(dollar_id)
            self.assertEqual(record["source_id"], expected_source)
            self.assertEqual(record["source_read_id"], expected_local)
            self.assertEqual(
                record["origin_read_id"], 100 + expected_local)
            self.assertEqual(record["origin_file"],
                             "%s_R0.fastq" % expected_source)
            sid, local = self.index.source_index.locate_row_source(
                dollar_id)
            self.assertEqual(sid, expected_source)
            self.assertEqual(local, expected_local)

    def test_every_bwt_row_read_identity_agrees_with_row_source(self):
        for row_index in range(self.manifest["root"]["length"]):
            source_id, _ = self.index.source_index.locate_row_source(
                row_index)
            dollar_id = self.oracle.getSequenceDollarID(row_index)
            record = self.index.record(dollar_id)
            self.assertEqual(record["source_id"], source_id)

    def test_mate_links_survive_merged_dollar_order(self):
        for source in self.index.source_index.list_sources():
            sid = str(source["id"])
            d0 = self.index.find_dollar_id(sid, 0)
            d1 = self.index.find_dollar_id(sid, 1)
            d2 = self.index.find_dollar_id(sid, 2)
            self.assertEqual(self.index.mate(d0)["dollar_id"], d1)
            self.assertEqual(self.index.mate(d1)["dollar_id"], d0)
            self.assertIsNone(self.index.mate(d2))

    def test_reads_containing_matches_naive_per_read_counts(self):
        for pattern in ("A", "AC", "CGT", "GTAC", "AAAA", "AAGGTT", "N",
                        "TT", "GATTACA", "ACGTAC"):
            expected = {}
            for sid, reads in f3.TEN_SOURCE_READS.items():
                for local_id in range(len(reads)):
                    dollar_id = self.oracle.global_dollar[(sid, local_id)]
                    count = overlapping_count(reads[local_id], pattern)
                    if count:
                        expected[dollar_id] = count
            result = self.wrapped.readsContaining(pattern)
            actual = {
                rec["dollar_id"]: rec["occurrence_count"]
                for rec in result["reads"]
            }
            self.assertEqual(actual, expected, pattern)
            self.assertEqual(result["unique_read_count"], len(expected))
            self.assertEqual(result["reported_occurrences"],
                             sum(expected.values()))
            self.assertEqual(result["reported_occurrences"],
                             result["merged_occurrences"])

    def test_source_filter_prefilters_before_lf_walk(self):
        pattern = "A"
        merged_low, merged_high = self.wrapped.bwt.findIndicesOfStr(pattern)
        total_occurrences = merged_high - merged_low
        before = self.wrapped.bwt.lf_calls
        result = self.wrapped.readsContaining(pattern, source="sample09")
        lf_calls = self.wrapped.bwt.lf_calls - before
        self.assertEqual(lf_calls, result["stats"]["lf_walks"])
        self.assertEqual(lf_calls, result["reported_occurrences"])
        self.assertLess(lf_calls, total_occurrences)
        self.assertTrue(all(
            rec["source_id"] == "sample09" for rec in result["reads"]))

    def test_subset_group_where_filters_match_filtered_global(self):
        global_result = self.wrapped.readsContaining("A")
        global_map = {
            rec["dollar_id"]: rec["occurrence_count"]
            for rec in global_result["reads"]
        }
        subset = ["sample00", "sample02", "sample09"]
        filtered = {
            d: c for d, c in global_map.items()
            if self.index.record(d)["source_id"] in subset
        }
        result = self.wrapped.readsContaining("A", sources=subset)
        actual = {
            rec["dollar_id"]: rec["occurrence_count"]
            for rec in result["reads"]
        }
        self.assertEqual(actual, filtered)
        self.assertEqual(
            result["stats"]["source_prefilter_skips"]
            + result["reported_occurrences"],
            global_result["merged_occurrences"])

        metadata = SourceMetadataCatalog(
            self.index.source_index.list_sources())
        metadata.define_group("case", subset)
        for sid in subset:
            metadata.set_source_metadata(sid, cohort="case")
        wrapped2 = MultiSourceBWT(
            None, self.index.source_index, source_metadata=metadata,
            read_provenance=self.index)
        wrapped2.bwt = self.wrapped.bwt
        group_result = wrapped2.readsContaining("AC", group="case")
        where_result = wrapped2.readsContaining(
            "AC", where={"cohort": "case"})
        self.assertEqual(
            [r["dollar_id"] for r in group_result["reads"]],
            [r["dollar_id"] for r in where_result["reads"]])
        self.assertEqual(
            group_result["reported_occurrences"],
            where_result["reported_occurrences"])

    def test_include_sequence_and_row_provenance(self):
        result = self.wrapped.readsContaining(
            "AAGGTT", include_sequence=True)
        self.assertEqual(len(result["reads"]), 1)
        record = result["reads"][0]
        self.assertEqual(record["source_id"], "sample09")
        self.assertEqual(record["sequence"], b"$AAGGTT")
        row_record = self.wrapped.rowReadProvenance(60, include_offset=True)
        self.assertEqual(row_record["row_index"], 60)
        self.assertGreaterEqual(row_record["lf_offset"], 0)

    def test_read_mate_and_missing_provenance_error(self):
        d0 = self.index.find_dollar_id("sample03", 0)
        mate = self.wrapped.readMate(d0)
        self.assertEqual(mate["dollar_id"],
                         self.index.find_dollar_id("sample03", 1))
        self.assertIsNone(self.wrapped.readMate(
            self.index.find_dollar_id("sample03", 2)))
        wrapped = MultiSourceBWT(
            None, self.index.source_index, read_provenance=None)
        wrapped.bwt = self.wrapped.bwt
        with self.assertRaises(MultiSourceQueryError):
            wrapped.readProvenance(0)
        with self.assertRaises(MultiSourceQueryError):
            wrapped.readsContaining("A")

    def test_max_occurrences_truncation(self):
        result = self.wrapped.readsContaining("A", max_occurrences=3)
        self.assertTrue(result["stats"]["truncated"])
        self.assertEqual(result["stats"]["interval_rows_scanned"], 3)


class LeafAndRetrofitHostTests(ReadProvenanceHostTestBase):
    def test_leaf_initialization_and_about_import(self):
        reads = ["ACGTAC", "GATTACA", "AAAA"]
        leaf = f3.make_read_derived_leaf(self.work, "single", reads)
        index = attach_leaf_read_provenance(leaf, reads)
        self.assertEqual(index.read_count, 3)
        self.assertEqual(index.record_bytes(), 20)
        self.assertEqual(index.record(1)["origin_file"], "single_R0.fastq")
        self.assertEqual(index.mate(0)["dollar_id"], 1)

        # legacy about.npy import (structured layout)
        leaf2 = f3.make_read_derived_leaf(self.work, "legacy", reads)
        about = np.empty(
            3, dtype=np.dtype([("f0", "<u1"), ("f1", "<u8")]))
        about[0] = (1, 100)
        about[1] = (0, 7)
        about[2] = (1, 101)
        np.save(os.path.join(leaf2, "about.npy"), about)
        imported = initialize_leaf_read_provenance_from_about(
            leaf2, input_files=["R1.fastq", "R2.fastq"])
        self.assertEqual(imported.record(0)["origin_file"], "R2.fastq")
        self.assertEqual(imported.record(1)["origin_file"], "R1.fastq")
        self.assertEqual(imported.record(2)["origin_read_id"], 101)
        self.assertIsNone(imported.mate(0))

        # legacy about.npy import (plain 2-D layout)
        leaf3 = f3.make_read_derived_leaf(self.work, "legacy2", reads)
        np.save(os.path.join(leaf3, "about.npy"),
                np.asarray([[0, 5], [0, 6], [1, 7]], dtype=np.uint64))
        imported3 = initialize_leaf_read_provenance_from_about(leaf3)
        self.assertEqual(
            [imported3.record(i)["origin_read_id"] for i in range(3)],
            [5, 6, 7])

    def test_retrofit_reproduces_fresh_merge_and_leaves_bwt_unchanged(self):
        leaves, output, manifest, oracle = build_fixture_with_reads(
            self.work, f3.TEN_SOURCE_READS)
        merged2 = os.path.join(self.work, "merged_stripped")
        shutil.copytree(output, merged2)
        os.remove(os.path.join(merged2, "read_provenance.npy"))
        os.remove(os.path.join(merged2, "read_provenance.json"))
        bwt_before = hashlib.sha256(open(
            os.path.join(merged2, "msbwt.npy"), "rb").read()).hexdigest()
        manifest_before = hashlib.sha256(open(
            os.path.join(merged2, "provenance.json"), "rb").read()).hexdigest()
        retrofit_read_provenance_from_leaf_dirs(
            merged2, {sid: leaves[sid] for sid in f3.TEN_SOURCE_READS})
        self.assertEqual(
            bwt_before,
            hashlib.sha256(open(
                os.path.join(merged2, "msbwt.npy"), "rb").read()).hexdigest())
        self.assertEqual(
            manifest_before,
            hashlib.sha256(open(
                os.path.join(merged2, "provenance.json"), "rb").read())
            .hexdigest())
        i1 = ReadProvenanceIndex(output)
        i2 = ReadProvenanceIndex(merged2)
        self.assertEqual(i1.read_count, i2.read_count)
        for d in range(i1.read_count):
            r1 = i1.record(d)
            r2 = i2.record(d)
            for field in ("source_id", "source_read_id", "origin_file_id",
                          "origin_read_id", "mate_dollar_id"):
                self.assertEqual(r1[field], r2[field], (d, field))

    def test_retrofit_requires_exact_leaf_read_counts(self):
        from MUS.ReadProvenance import build_read_provenance_from_leaf_records

        leaves, output, manifest, oracle = build_fixture_with_reads(
            self.work, f3.TEN_SOURCE_READS)
        merged2 = os.path.join(self.work, "merged_counts")
        shutil.copytree(output, merged2)
        os.remove(os.path.join(merged2, "read_provenance.npy"))
        os.remove(os.path.join(merged2, "read_provenance.json"))
        records = {
            sid: [{"origin_file_id": 0, "origin_read_id": 0},
                  {"origin_file_id": 0, "origin_read_id": 1}]
            for sid in f3.TEN_SOURCE_READS
        }
        with self.assertRaises(ReadProvenanceError):
            build_read_provenance_from_leaf_records(
                merged2, records, overwrite=True)

    def test_one_sided_merge_rejected_before_merge(self):
        reads_by_source = {
            "A": ["ACGTAC", "GATTACA", "AAAA"],
            "B": ["TTTT", "GCGTAC"],
        }
        leaves, output, manifest, oracle = build_fixture_with_reads(
            self.work, reads_by_source)
        os.remove(os.path.join(leaves["B"], "read_provenance.npy"))
        os.remove(os.path.join(leaves["B"], "read_provenance.json"))
        called = [False]

        def should_not_run(*args, **kwargs):
            called[0] = True

        with self.assertRaises(ProvenanceError) as ctx:
            merge_two_with_provenance(
                leaves["A"], leaves["B"],
                os.path.join(self.work, "bad"),
                merge_two_func=should_not_run)
        self.assertIn("only one merge input", str(ctx.exception))
        self.assertFalse(called[0])

    def test_edge_datasets_keep_identities(self):
        cases = [
            {"D": ["ACGTAC", "ACGTAC", "ACGTAC"], "O": ["ACGTAC"]},
            {"S1": ["AAAA", "AAAA"], "S2": ["AAAA", "AAAA"]},
            {"N": ["N", "NN", "ACGTNNNN", "NACGT"],
             "M": ["A", "AC", "ACG", "ACGT", "ACGTACGTACGT"]},
        ]
        for case_index, reads_by_source in enumerate(cases):
            leaves, output, manifest, oracle = build_fixture_with_reads(
                self.work, reads_by_source,
                name="edge_%d" % case_index)
            index = ReadProvenanceIndex(output)
            self.assertEqual(index.read_count, oracle.read_count)
            identities = set()
            for d in range(index.read_count):
                record = index.record(d)
                identities.add((record["source_id"],
                                record["origin_read_id"]))
            self.assertEqual(len(identities), oracle.read_count)
            patterns = ["A", "C", "G", "T", "N", "AC", "AAAA", "NN"]
            for pattern in patterns:
                wrapped = MultiSourceBWT(
                    None, index.source_index, read_provenance=index)
                wrapped.bwt = OracleBWTAdapter(oracle, output, manifest)
                rc = wrapped.readsContaining(pattern)
                expected = {}
                for sid, reads in reads_by_source.items():
                    for local_id in range(len(reads)):
                        dollar_id = oracle.global_dollar[(sid, local_id)]
                        count = overlapping_count(reads[local_id], pattern)
                        if count:
                            expected[dollar_id] = count
                actual = {
                    rec["dollar_id"]: rec["occurrence_count"]
                    for rec in rc["reads"]
                }
                self.assertEqual(actual, expected, (case_index, pattern))


class PersistenceSafetyHostTests(ReadProvenanceHostTestBase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f9-host-safe-")
        cls.leaves, cls.output, cls.manifest, cls.oracle = (
            build_fixture_with_reads(cls.work, f3.TEN_SOURCE_READS))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def _copy(self, label):
        target = os.path.join(self.work, label)
        shutil.copytree(self.output, target)
        return target

    def test_wrong_read_count_rejected(self):
        merged2 = self._copy("wrong_count")
        os.remove(os.path.join(merged2, "read_provenance.npy"))
        table = np.load(os.path.join(self.output, "read_provenance.npy"))
        np.save(os.path.join(merged2, "read_provenance.npy"), table[:-1])
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(merged2)

    def test_wrong_dtype_rejected(self):
        merged2 = self._copy("wrong_dtype")
        np.save(os.path.join(merged2, "read_provenance.npy"),
                np.zeros(30, dtype=np.uint64))
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(merged2)

    def test_truncated_npy_rejected(self):
        merged2 = self._copy("truncated")
        path = os.path.join(merged2, "read_provenance.npy")
        size = os.path.getsize(path)
        with open(path, "r+b") as fp:
            fp.truncate(size - 40)
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(merged2)

    def test_appended_bytes_rejected(self):
        merged2 = self._copy("appended")
        path = os.path.join(merged2, "read_provenance.npy")
        with open(path, "ab") as fp:
            fp.write(b"\x00" * 20)
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(merged2)

    def test_wrong_format_version_ordering_rejected(self):
        for field, value in (("format", "other-format"),
                             ("version", 99),
                             ("ordering", "by-source")):
            merged2 = self._copy("wrong_" + field)
            meta_path = os.path.join(merged2, "read_provenance.json")
            with open(meta_path, "r") as fp:
                meta = json.load(fp)
            meta[field] = value
            with open(meta_path, "w") as fp:
                json.dump(meta, fp)
            with self.assertRaises(ReadProvenanceError):
                ReadProvenanceIndex(merged2)

    def test_replaced_same_length_bwt_rejected(self):
        merged2 = self._copy("replaced_bwt")
        bwt = np.load(os.path.join(merged2, "msbwt.npy"))
        bwt[0] = (bwt[0] + 1) % 6
        np.save(os.path.join(merged2, "msbwt.npy"), bwt)
        with self.assertRaises((ReadProvenanceError, ProvenanceError)):
            ReadProvenanceIndex(merged2)

    def test_copied_foreign_same_length_array_rejected(self):
        # A second index with the same read count (30) but a different BWT
        # cannot donate its read provenance to this index: the BWT identity
        # binding in read_provenance.json rejects the copy.
        foreign_work = tempfile.mkdtemp(prefix="f9-host-foreign-")
        try:
            foreign_reads = {
                "X%02d" % i: ["CGTAC", "TTTAA", "GGCC"]
                for i in range(10)
            }
            _, foreign_out, _, _ = build_fixture_with_reads(
                foreign_work, foreign_reads, name="foreign")
            target = self._copy("foreign_copy")
            shutil.copy(
                os.path.join(foreign_out, "read_provenance.npy"),
                os.path.join(target, "read_provenance.npy"))
            shutil.copy(
                os.path.join(foreign_out, "read_provenance.json"),
                os.path.join(target, "read_provenance.json"))
            with self.assertRaises(ReadProvenanceError):
                ReadProvenanceIndex(target)
        finally:
            shutil.rmtree(foreign_work, ignore_errors=True)

    def test_unknown_source_metadata_rejected(self):
        merged2 = self._copy("unknown_source")
        meta_path = os.path.join(merged2, "read_provenance.json")
        with open(meta_path, "r") as fp:
            meta = json.load(fp)
        meta["source_metadata"]["ghost_source"] = {}
        with open(meta_path, "w") as fp:
            json.dump(meta, fp)
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(merged2)

    def test_missing_metadata_file_reported(self):
        merged2 = self._copy("missing_meta")
        os.remove(os.path.join(merged2, "read_provenance.json"))
        self.assertFalse(read_provenance_exists(merged2))
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(merged2)

    def test_corrupt_json_metadata_rejected(self):
        merged2 = self._copy("corrupt_json")
        with open(os.path.join(merged2, "read_provenance.json"), "w") as fp:
            fp.write("{not json")
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(merged2)


class RandomizedDifferentialHostTests(ReadProvenanceHostTestBase):
    def test_randomized_differentials(self):
        for seed_index, seed in enumerate(SEEDS):
            rng = random.Random(seed)
            for case in range(12):
                reads_by_source = {}
                n_sources = rng.randint(1, 5)
                alphabet = "ACGTN"
                for i in range(n_sources):
                    n_reads = rng.randint(1, 5)
                    reads = []
                    for _ in range(n_reads):
                        length = rng.randint(1, 10)
                        if rng.random() < 0.3 and reads:
                            reads.append(reads[rng.randrange(len(reads))])
                            continue
                        reads.append("".join(
                            rng.choice(alphabet) for _ in range(length)))
                    reads_by_source["S%02d_C%02d_S%d" % (
                        seed_index, case, i)] = reads
                origin_base = 1000 * case
                file_count = rng.randint(1, 3)
                leaves, output, manifest, oracle = build_fixture_with_reads(
                    self.work, reads_by_source,
                    origin_base=origin_base, file_count=file_count,
                    name="rand_%02d_%02d" % (seed_index, case))
                index = ReadProvenanceIndex(output, mmap=False)
                self.assertEqual(index.read_count, oracle.read_count)
                self.assertEqual(index.record_bytes(), 20)
                for d in range(oracle.read_count):
                    sid, local = oracle.dollar_to_identity[d]
                    record = index.record(d)
                    self.assertEqual(record["source_id"], sid)
                    self.assertEqual(record["source_read_id"], local)
                    self.assertEqual(
                        record["origin_read_id"], origin_base + local)
                    self.assertEqual(
                        record["origin_file_id"], local % file_count)
                wrapped = MultiSourceBWT(
                    None, index.source_index, read_provenance=index)
                wrapped.bwt = OracleBWTAdapter(oracle, output, manifest)
                patterns = ["A", "C", "G", "T", "N", "AC", "GT", "AA"]
                pool = []
                for reads in reads_by_source.values():
                    for read in reads:
                        pool.append(read)
                for _ in range(6):
                    if pool:
                        patterns.append(rng.choice(pool))
                for pattern in sorted(set(patterns)):
                    expected = {}
                    for sid, reads in reads_by_source.items():
                        for local_id in range(len(reads)):
                            dollar_id = oracle.global_dollar[(sid, local_id)]
                            count = overlapping_count(
                                reads[local_id], pattern)
                            if count:
                                expected[dollar_id] = count
                    result = wrapped.readsContaining(pattern)
                    actual = {
                        rec["dollar_id"]: rec["occurrence_count"]
                        for rec in result["reads"]
                    }
                    self.assertEqual(actual, expected,
                                     (seed, case, pattern))
                    self.assertEqual(
                        result["reported_occurrences"],
                        result["merged_occurrences"])


class EvidenceConsistencyTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = json.load(open(EVIDENCE, encoding="utf-8"))
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "enhanced-modern2")
        self.assertEqual(
            evidence["final"]["milestone"],
            "enhanced-modern2-feature9-read-provenance")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")

    def test_evidence_contract(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["seed"], 20260811)
        ten = report["ten_source_fixture"]
        self.assertEqual(ten["reads"], 30)
        self.assertEqual(ten["sources"], 10)
        self.assertEqual(ten["record_bytes"], 20)
        self.assertGreaterEqual(ten["patterns"], 100)
        self.assertGreaterEqual(ten["comparisons"], 1000)
        self.assertEqual(ten["mismatches"], 0)
        self.assertTrue(ten["one_sided_rejection"])
        real = report["real_integration"]
        self.assertEqual(real["record_bytes"], 20)
        self.assertEqual(real["mismatches"], 0)
        self.assertGreater(real["comparisons"], 500)
        rand = report["randomized"]
        self.assertEqual(rand["seed"], 20260811)
        self.assertEqual(rand["datasets"], 3)
        self.assertEqual(rand["mismatches"], 0)
        perf = report["performance"]
        self.assertLess(perf["lf_walks_with_filter"],
                        perf["lf_walks_without_filter"])

    def test_evidence_generator_is_python2_and_driver_checks(self):
        with open(EVIDENCE_GENERATOR, "rb") as fp:
            text = fp.read().decode("utf-8")
        self.assertIn("Python 2.7 only", text)
        self.assertIn("def run_evidence", text)
        with open(VALIDATION_DRIVER, "rb") as fp:
            driver = fp.read().decode("utf-8")
        self.assertIn("--evidence", driver)
        self.assertIn("run_evidence", driver)
        self.assertIn("feature9-read-provenance", driver)


if __name__ == "__main__":
    unittest.main()
