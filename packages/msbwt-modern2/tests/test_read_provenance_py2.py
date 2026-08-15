"""Feature 9 - exact read-level provenance through multi-merged MSBWTs
(Python-2 suite, real merges).

This suite validates ``MUS.ReadProvenance`` plus the Feature-9 additions to
``MUS.MultiSourceProvenance`` (automatic read-provenance merge and
one-sided rejection) and ``MUS.MultiSourceQuery`` (``locate_row_source`` /
``readProvenance`` / ``rowReadProvenance`` / ``readMate`` /
``readsContaining``) against an INDEPENDENT oracle:

* read-derived leaf fixtures: every BWT row's owning read is known exactly
  from ``naive_suffix_rows.json`` (explicit terminated-suffix sorting);
* merged row -> (source, local row) mapping by direct bit-array counting
  through the verified ``unpack_interleave`` (no sampled rank index, no
  Feature-9 code);
* the merged ``$`` rows are rows [0, R) of the merged order, so every
  global dollar ID maps to an exact (source, original read) identity;
* ``getSequenceDollarID`` / ``recoverString`` are reimplemented
  independently from those naive rows.

Coverage:

- leaf initialization from explicit records (origin file/read IDs, mate
  links) and from legacy ``about.npy`` with optional input-file tables;
- 20-byte packed record format and memory-mapped loading;
- two-way and balanced 10-source merges automatically preserve read
  provenance; every dollar ID matches the oracle; mate links survive;
- one-sided read provenance merge rejection BEFORE the BWT merge;
- retrofit of an already-merged package (no BWT re-merge, BWT bytes
  unchanged, hashes equal) from leaf read provenance and from leaf
  ``about.npy``;
- ``readsContaining`` == naive per-read overlapping counts for duplicate,
  identical, mixed-length, N-heavy, multi-file-origin and multi-source
  datasets; source/group/where filters equal the filtered global result;
  source-prefilter LF-walk reduction;
- randomized differentials (seeds 20260811/20260812/20260813);
- stale/corrupt persistence protection (wrong count, wrong dtype, wrong
  format/version, truncated array, replaced BWT, copied foreign array,
  unknown source metadata).
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
import test_source_index_py2 as f1  # noqa: E402

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
    READ_DTYPE,
    ReadProvenanceError,
    ReadProvenanceIndex,
    build_read_provenance_from_leaf_records,
    initialize_leaf_read_provenance,
    initialize_leaf_read_provenance_from_about,
    read_provenance_exists,
    retrofit_read_provenance_from_leaf_dirs,
)
from MUS.SourceMetadata import SourceMetadataCatalog  # noqa: E402

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

ALPHABET_CODE = {"$": 0, "A": 1, "C": 2, "G": 3, "N": 4, "T": 5}
ROWS_FILENAME = "naive_suffix_rows.json"

SEEDS = (20260811, 20260812, 20260813)

TEN_SOURCE_READS = {
    "sample00": ["ACGTAC", "GATTACA", "AAAA"],
    "sample01": ["ACGTTC", "CCCC", "TACGTA"],
    "sample02": ["GGGG", "ACACAC", "TTAC"],
    "sample03": ["TGCATG", "CATCAT", "AGGG"],
    "sample04": ["AAAAAC", "CGCG", "GTGTGT"],
    "sample05": ["TTTT", "GCGTAC", "AACCAA"],
    "sample06": ["CAGTCA", "AGAGAG", "CTTT"],
    "sample07": ["GTACGT", "CCGGA", "ATATAT"],
    "sample08": ["NACGT", "ACNGT", "GGNCC"],
    "sample09": ["TTAACC", "CGTACG", "AAGGTT"],
}


# ---------------------------------------------------------------------------
# read-derived fixture machinery (independent suffix-row oracle)
# ---------------------------------------------------------------------------


def terminated_suffix_rows(reads):
    rows = []
    for read_id, read in enumerate(reads):
        text = read + "$"
        for pos in range(len(text)):
            rows.append({
                "suffix": text[pos:],
                "bwt": text[pos - 1] if pos > 0 else "$",
                "read_id": read_id,
                "pos": pos,
            })
    rows.sort(key=lambda row: (row["suffix"], row["read_id"], row["pos"]))
    return rows


def save_rows(directory, rows):
    path = os.path.join(directory, ROWS_FILENAME)
    with open(path, "w") as fp:
        json.dump(rows, fp, separators=(",", ":"))


def load_rows(directory):
    with open(os.path.join(directory, ROWS_FILENAME), "r") as fp:
        return json.load(fp)


def stable_suffix_merge(left_rows, right_rows):
    merged = []
    bits = []
    li = 0
    ri = 0
    while li < len(left_rows) or ri < len(right_rows):
        if ri >= len(right_rows):
            choose_right = False
        elif li >= len(left_rows):
            choose_right = True
        else:
            choose_right = right_rows[ri]["suffix"] < left_rows[li]["suffix"]
        if choose_right:
            merged.append(right_rows[ri])
            bits.append(1)
            ri += 1
        else:
            merged.append(left_rows[li])
            bits.append(0)
            li += 1
    return merged, bits


def read_derived_merge(left_dir, right_dir, output_dir, num_procs=1,
                       logger=None):
    merged_rows, bits = stable_suffix_merge(
        load_rows(left_dir), load_rows(right_dir))
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    np.save(os.path.join(output_dir, "msbwt.npy"),
            np.asarray([ALPHABET_CODE[row["bwt"]] for row in merged_rows],
                       dtype=np.uint8))
    np.save(os.path.join(output_dir, "inter0.npy"),
            f1.pack_little_endian_bits(bits))
    save_rows(output_dir, merged_rows)


def make_read_derived_leaf(work, source_name, reads):
    directory = os.path.join(work, source_name)
    os.mkdir(directory)
    rows = terminated_suffix_rows(reads)
    np.save(os.path.join(directory, "msbwt.npy"),
            np.asarray([ALPHABET_CODE[row["bwt"]] for row in rows],
                       dtype=np.uint8))
    save_rows(directory, rows)
    initialize_leaf_provenance(
        directory, source_id=source_name, source_name=source_name)
    return directory


def default_leaf_records(reads, origin_base=100, file_count=1):
    """Explicit Feature-9 leaf records with mates on the first two reads.

    Mates are only assigned when the source has at least two reads (a
    one-read source cannot hold a valid mate link).
    """
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


# ---------------------------------------------------------------------------
# independent oracle: naive rows + tree walk (no Feature-9 code)
# ---------------------------------------------------------------------------


def _tree_walk_row(merged_dir, manifest, row_index):
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


class OracleReadIdentity(object):
    """Fully independent read-identity oracle over naive suffix rows.

    ``getSequenceDollarID(row)`` and ``recoverString(dollar_id)`` are
    reimplemented here from the fixture ground truth (leaf suffix rows and
    the provenance tree).  No Feature-9 code is used to build expectations.
    """

    def __init__(self, merged_dir, leaf_dirs_by_source, reads_by_source):
        self.merged_dir = str(merged_dir)
        self.manifest = load_manifest(self.merged_dir, validate=True)
        self.leaf_rows = {}
        self.reads = {}
        self.leaf_dollar_rows = {}
        for sid, leaf_dir in leaf_dirs_by_source.items():
            rows = load_rows(leaf_dir)
            self.leaf_rows[sid] = rows
            self.reads[sid] = reads_by_source[sid]
            dollar_rows = [r for r in rows if r["suffix"] == "$"]
            # dollar rows sort by read_id within a leaf, so the local dollar
            # ID of a read is its index among the '$' rows.
            local_dollar = {}
            for index, row in enumerate(dollar_rows):
                local_dollar[int(row["read_id"])] = index
            self.leaf_dollar_rows[sid] = local_dollar

        total_reads = sum(len(reads) for reads in reads_by_source.values())
        self.global_dollar = {}
        self.dollar_to_identity = {}
        for dollar_id in range(total_reads):
            sid, local_row = _tree_walk_row(
                self.merged_dir, self.manifest, dollar_id)
            read_id = int(self.leaf_rows[sid][local_row]["read_id"])
            local_dollar = self.leaf_dollar_rows[sid][read_id]
            self.global_dollar[(sid, local_dollar)] = dollar_id
            self.dollar_to_identity[dollar_id] = (sid, local_dollar)
        self.read_count = total_reads

    def getSequenceDollarID(self, row_index, returnOffset=False):
        sid, local_row = _tree_walk_row(
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
        # Real Holt/McMillan contract: recoverString returns the full
        # rotation starting at '$', i.e. '$' + original read.
        return ("$" + self.reads[sid][read_id]).encode("ascii")


def overlapping_count(text, pattern):
    count = 0
    start = 0
    while True:
        pos = text.find(pattern, start)
        if pos < 0:
            return count
        count += 1
        start = pos + 1


def build_sources(work, reads_by_source, origin_base=100, file_count=1):
    leaves = {}
    for source_name, reads in reads_by_source.items():
        leaf = make_read_derived_leaf(work, source_name, reads)
        attach_leaf_read_provenance(
            leaf, reads, origin_base=origin_base,
            file_count=file_count)
        leaves[source_name] = leaf
    return leaves


def merge_sources(work, leaves, name="merged"):
    output = os.path.join(work, name)
    work_dir = os.path.join(work, name + "_work")
    manifest = merge_many_balanced(
        leaves.values(), output,
        merge_two_func=read_derived_merge,
        work_dir=work_dir, keep_work=True)
    return output, manifest


def build_merged(work, reads_by_source, origin_base=100, file_count=1,
                 name="merged"):
    leaves = build_sources(
        work, reads_by_source, origin_base=origin_base,
        file_count=file_count)
    output, manifest = merge_sources(work, leaves, name=name)
    oracle = OracleReadIdentity(
        output,
        {sid: leaves[sid] for sid in reads_by_source},
        reads_by_source)
    return leaves, output, manifest, oracle


def pattern_set(reads_by_source):
    patterns = set()
    for reads in reads_by_source.values():
        for read in reads:
            for start in range(len(read)):
                for length in range(1, len(read) - start + 1):
                    patterns.add(read[start:start + length])
    patterns.update(["A", "C", "G", "T", "N", "AC", "GT", "NN", "AAAA"])
    return sorted(patterns)


class ReadProvenancePy2TestBase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f9-py2-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def build_sources(self, reads_by_source, origin_base=100,
                      file_count=1):
        return build_sources(
            self.work, reads_by_source, origin_base=origin_base,
            file_count=file_count)

    def merge_sources(self, leaves, name="merged"):
        return merge_sources(self.work, leaves, name=name)

    def build_merged(self, reads_by_source, origin_base=100, file_count=1,
                     name="merged"):
        return build_merged(
            self.work, reads_by_source, origin_base=origin_base,
            file_count=file_count, name=name)

    def _check_reads_containing(self, wrapped, oracle, reads_by_source,
                                patterns, origin_base=100, file_count=1):
        for pattern in patterns:
            result = wrapped.readsContaining(pattern)
            expected = {}
            for sid, reads in reads_by_source.items():
                for local_id in range(len(reads)):
                    dollar_id = oracle.global_dollar[(sid, local_id)]
                    count = overlapping_count(reads[local_id], pattern)
                    if count:
                        expected[dollar_id] = count
            actual = {
                rec["dollar_id"]: rec["occurrence_count"]
                for rec in result["reads"]
            }
            self.assertEqual(actual, expected, pattern)
            self.assertEqual(result["unique_read_count"], len(expected))
            self.assertEqual(
                result["reported_occurrences"], sum(expected.values()))
            self.assertEqual(
                result["reported_occurrences"],
                result["merged_occurrences"])
        return wrapped, oracle

    def assert_identity_exact(self, output, oracle, reads_by_source,
                              origin_base=100, file_count=1):
        index = ReadProvenanceIndex(output)
        self.assertEqual(index.read_count, oracle.read_count)
        self.assertEqual(index.record_bytes(), 20)
        for dollar_id in range(oracle.read_count):
            sid, local_dollar = oracle.dollar_to_identity[dollar_id]
            record = index.record(dollar_id)
            self.assertEqual(record["source_id"], sid)
            self.assertEqual(record["source_read_id"], local_dollar)
            self.assertEqual(
                record["origin_read_id"],
                origin_base + local_dollar)
            self.assertEqual(
                record["origin_file_id"],
                local_dollar % file_count)
            # input-file table resolves the origin file name
            expected_file = "%s_R%d.fastq" % (sid, local_dollar % file_count)
            self.assertEqual(record["origin_file"], expected_file)
            if len(reads_by_source[sid]) >= 2 and local_dollar < 2:
                mate = index.mate(dollar_id)
                self.assertIsNotNone(mate)
                self.assertEqual(
                    mate["dollar_id"],
                    oracle.global_dollar[(sid, 1 - local_dollar)])
            else:
                self.assertIsNone(index.mate(dollar_id))


class LeafReadProvenanceTests(ReadProvenancePy2TestBase):
    def test_leaf_initialization_exact_fields(self):
        reads = ["ACGTAC", "GATTACA", "AAAA"]
        leaf = make_read_derived_leaf(self.work, "single", reads)
        index = attach_leaf_read_provenance(leaf, reads)
        self.assertEqual(index.read_count, 3)
        self.assertEqual(index.record_bytes(), 20)
        self.assertTrue(read_provenance_exists(leaf))
        for i in range(3):
            record = index.record(i)
            self.assertEqual(record["source_id"], "single")
            self.assertEqual(record["source_read_id"], i)
            self.assertEqual(record["origin_read_id"], 100 + i)
            self.assertEqual(record["origin_file"], "single_R0.fastq")
        self.assertEqual(index.mate(0)["dollar_id"], 1)
        self.assertEqual(index.mate(1)["dollar_id"], 0)
        self.assertIsNone(index.mate(2))

    def test_leaf_initialization_rejects_out_of_order_records(self):
        reads = ["AAAA", "CCCC"]
        leaf = make_read_derived_leaf(self.work, "ord", reads)
        with self.assertRaises(ReadProvenanceError):
            initialize_leaf_read_provenance(
                leaf,
                [{"source_read_id": 1, "origin_read_id": 0},
                 {"source_read_id": 0, "origin_read_id": 1}])

    def test_leaf_initialization_rejects_bad_mate(self):
        reads = ["AAAA"]
        leaf = make_read_derived_leaf(self.work, "mate", reads)
        with self.assertRaises(ReadProvenanceError):
            initialize_leaf_read_provenance(
                leaf,
                [{"origin_read_id": 0, "mate_source_read_id": 5}])

    def test_legacy_about_import_preserves_file_and_read_ids(self):
        reads = ["ACGT", "TTTT", "AAAA"]
        leaf = make_read_derived_leaf(self.work, "legacy", reads)
        about = np.empty(
            3, dtype=np.dtype([("f0", "<u1"), ("f1", "<u8")]))
        about[0] = (1, 100)
        about[1] = (0, 7)
        about[2] = (1, 101)
        np.save(os.path.join(leaf, "about.npy"), about)
        imported = initialize_leaf_read_provenance_from_about(
            leaf, input_files=["R1.fastq", "R2.fastq"])
        self.assertEqual(imported.read_count, 3)
        self.assertEqual(imported.record(0)["origin_file"], "R2.fastq")
        self.assertEqual(imported.record(0)["origin_read_id"], 100)
        self.assertEqual(imported.record(1)["origin_file"], "R1.fastq")
        self.assertEqual(imported.record(1)["origin_read_id"], 7)
        self.assertEqual(imported.record(2)["origin_file"], "R2.fastq")
        # no mate information in legacy about.npy
        self.assertIsNone(imported.mate(0))

    def test_legacy_about_import_missing_file_fails(self):
        leaf = make_read_derived_leaf(self.work, "nofile", ["AAAA"])
        with self.assertRaises(ReadProvenanceError):
            initialize_leaf_read_provenance_from_about(leaf)

    def test_leaf_memmap_loading(self):
        reads = ["ACGTAC", "GATTACA", "AAAA"]
        leaf = make_read_derived_leaf(self.work, "mmap", reads)
        attach_leaf_read_provenance(leaf, reads)
        index = ReadProvenanceIndex(leaf, mmap=True)
        self.assertIsInstance(index.table.records, np.memmap)
        self.assertEqual(index.read_count, 3)


class MergeReadProvenanceTests(ReadProvenancePy2TestBase):
    def test_two_way_merge_preserves_identity_and_mates(self):
        reads_by_source = {
            "A": ["ACGTAC", "GATTACA", "AAAA"],
            "B": ["TTTT", "GCGTAC"],
        }
        leaves, output, manifest, oracle = self.build_merged(reads_by_source)
        self.assertTrue(read_provenance_exists(output))
        self.assert_identity_exact(output, oracle, reads_by_source)

    def test_balanced_ten_source_merge_preserves_identity(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        self.assertTrue(read_provenance_exists(output))
        self.assertEqual(oracle.read_count, 30)
        self.assert_identity_exact(output, oracle, TEN_SOURCE_READS)
        index = ReadProvenanceIndex(output)
        for source in index.source_index.list_sources():
            self.assertEqual(
                index.source_read_count(source["id"]), 3)

    def test_merge_rejects_one_sided_read_provenance_before_merge(self):
        reads_by_source = {
            "A": ["ACGTAC", "GATTACA", "AAAA"],
            "B": ["TTTT", "GCGTAC"],
        }
        leaves = self.build_sources(reads_by_source)
        os.remove(os.path.join(leaves["B"], "read_provenance.npy"))
        os.remove(os.path.join(leaves["B"], "read_provenance.json"))
        called = [False]

        def should_not_run(*args, **kwargs):
            called[0] = True

        with self.assertRaises(Exception) as ctx:
            merge_two_with_provenance(
                leaves["A"], leaves["B"],
                os.path.join(self.work, "bad"),
                merge_two_func=should_not_run)
        self.assertIn("only one merge input", str(ctx.exception))
        self.assertFalse(called[0])
        self.assertFalse(os.path.exists(os.path.join(
            self.work, "bad", "msbwt.npy")))

    def test_merge_without_read_provenance_still_works(self):
        # both sides lacking provenance must merge normally
        leaves = {}
        for name, reads in (("A", ["ACGTAC", "AAAA"]),
                            ("B", ["TTTT"])):
            leaf = make_read_derived_leaf(self.work, name, reads)
            leaves[name] = leaf
        output, manifest = self.merge_sources(leaves)
        self.assertFalse(read_provenance_exists(output))

    def test_duplicate_reads_inside_source_keep_identities(self):
        reads_by_source = {
            "dup": ["ACGTAC", "ACGTAC", "ACGTAC", "TTTT"],
            "other": ["GGGG", "ACGTAC"],
        }
        leaves, output, manifest, oracle = self.build_merged(reads_by_source)
        index = ReadProvenanceIndex(output)
        self.assertEqual(oracle.read_count, 6)
        # identical sequences must not collapse identities: the
        # (source, origin_read_id) pair is unique per dollar ID
        identities = set()
        for dollar_id in range(index.read_count):
            record = index.record(dollar_id)
            identities.add((record["source_id"],
                            record["origin_read_id"]))
        self.assertEqual(len(identities), 6)

    def test_same_read_in_multiple_sources_keeps_source_identity(self):
        reads_by_source = {
            "S1": ["ACGTAC", "TTTT"],
            "S2": ["ACGTAC", "CCCC"],
        }
        leaves, output, manifest, oracle = self.build_merged(reads_by_source)
        index = ReadProvenanceIndex(output)
        records = {index.record(d)["source_id"]
                   for d in range(index.read_count)}
        self.assertEqual(records, set(["S1", "S2"]))
        self.assert_identity_exact(output, oracle, reads_by_source)

    def test_all_identical_reads(self):
        reads_by_source = {
            "S1": ["AAAA", "AAAA"],
            "S2": ["AAAA"],
            "S3": ["AAAA", "AAAA", "AAAA"],
        }
        leaves, output, manifest, oracle = self.build_merged(reads_by_source)
        self.assertEqual(oracle.read_count, 6)
        index = ReadProvenanceIndex(output)
        counts = {}
        for d in range(index.read_count):
            sid = index.record(d)["source_id"]
            counts[sid] = counts.get(sid, 0) + 1
        self.assertEqual(counts, {"S1": 2, "S2": 1, "S3": 3})

    def test_mixed_lengths_and_n_heavy(self):
        reads_by_source = {
            "N": ["N", "NN", "ACGTNNNN", "NACGT"],
            "M": ["A", "AC", "ACG", "ACGT", "ACGTACGTACGT"],
        }
        leaves, output, manifest, oracle = self.build_merged(reads_by_source)
        self.assert_identity_exact(output, oracle, reads_by_source)

    def test_multiple_fastq_files_per_source(self):
        reads_by_source = {
            "multi": ["ACGTAC", "GATTACA", "AAAA", "TTTT", "CCCC"],
        }
        leaves, output, manifest, oracle = self.build_merged(
            reads_by_source, file_count=3)
        index = ReadProvenanceIndex(output)
        for d in range(index.read_count):
            record = index.record(d)
            expected_file = "multi_R%d.fastq" % (
                record["source_read_id"] % 3)
            self.assertEqual(record["origin_file"], expected_file)

    def test_unbalanced_chain_merge(self):
        reads_by_source = {
            "S0": ["AAAA"],
            "S1": ["CCCC"],
            "S2": ["GGGG"],
            "S3": ["TTTT"],
        }
        leaves = self.build_sources(reads_by_source)
        order = ["S0", "S1", "S2", "S3"]
        current = leaves[order[0]]
        for name in order[1:]:
            out = os.path.join(self.work, "chain_" + name)
            merge_two_with_provenance(
                current, leaves[name], out,
                merge_two_func=read_derived_merge)
            current = out
        oracle = OracleReadIdentity(
            current,
            {sid: leaves[sid] for sid in order},
            reads_by_source)
        self.assert_identity_exact(current, oracle, reads_by_source)


class RetrofitReadProvenanceTests(ReadProvenancePy2TestBase):
    def _build_and_strip(self, reads_by_source):
        leaves, output, manifest, oracle = self.build_merged(reads_by_source)
        merged2 = os.path.join(self.work, "merged_stripped")
        shutil.copytree(output, merged2)
        os.remove(os.path.join(merged2, "read_provenance.npy"))
        os.remove(os.path.join(merged2, "read_provenance.json"))
        bwt_before = hashlib.sha256(open(
            os.path.join(merged2, "msbwt.npy"), "rb").read()).hexdigest()
        manifest_before = hashlib.sha256(open(
            os.path.join(merged2, "provenance.json"), "rb").read()).hexdigest()
        return leaves, output, merged2, oracle, bwt_before, manifest_before

    def test_retrofit_from_leaf_read_provenance(self):
        leaves, output, merged2, oracle, bwt_before, manifest_before = (
            self._build_and_strip(TEN_SOURCE_READS))
        retrofit_read_provenance_from_leaf_dirs(
            merged2,
            {sid: leaves[sid] for sid in TEN_SOURCE_READS})
        # BWT and manifest bytes unchanged by retrofit
        self.assertEqual(
            bwt_before,
            hashlib.sha256(open(
                os.path.join(merged2, "msbwt.npy"), "rb").read()).hexdigest())
        self.assertEqual(
            manifest_before,
            hashlib.sha256(open(
                os.path.join(merged2, "provenance.json"), "rb").read())
            .hexdigest())
        # retrofit output equals fresh-merge output exactly
        i1 = ReadProvenanceIndex(output)
        i2 = ReadProvenanceIndex(merged2)
        self.assertEqual(i1.read_count, i2.read_count)
        for d in range(i1.read_count):
            r1 = i1.record(d)
            r2 = i2.record(d)
            self.assertEqual(r1["source_id"], r2["source_id"])
            self.assertEqual(r1["origin_file_id"], r2["origin_file_id"])
            self.assertEqual(r1["origin_read_id"], r2["origin_read_id"])
            self.assertEqual(r1["mate_dollar_id"], r2["mate_dollar_id"])

    def test_retrofit_from_legacy_about(self):
        reads_by_source = {
            "A": ["ACGTAC", "GATTACA", "AAAA"],
            "B": ["TTTT", "GCGTAC"],
        }
        leaves, output, merged2, oracle, _, _ = self._build_and_strip(
            reads_by_source)
        for sid, leaf in leaves.items():
            os.remove(os.path.join(leaf, "read_provenance.npy"))
            os.remove(os.path.join(leaf, "read_provenance.json"))
            about = np.empty(
                len(reads_by_source[sid]),
                dtype=np.dtype([("f0", "<u1"), ("f1", "<u8")]))
            for i in range(len(reads_by_source[sid])):
                about[i] = (i % 2, 1000 + i)
            np.save(os.path.join(leaf, "about.npy"), about)
        retrofit_read_provenance_from_leaf_dirs(
            merged2,
            {sid: leaves[sid] for sid in reads_by_source})
        index = ReadProvenanceIndex(merged2)
        for d in range(index.read_count):
            record = index.record(d)
            self.assertEqual(
                record["origin_read_id"],
                1000 + record["source_read_id"])
            self.assertEqual(
                record["origin_file_id"],
                record["source_read_id"] % 2)
            self.assertIsNone(record["mate_dollar_id"])

    def test_retrofit_requires_exact_leaf_read_counts(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        merged2 = os.path.join(self.work, "merged_counts")
        shutil.copytree(output, merged2)
        os.remove(os.path.join(merged2, "read_provenance.npy"))
        os.remove(os.path.join(merged2, "read_provenance.json"))
        records = {}
        for sid in TEN_SOURCE_READS:
            records[sid] = [
                {"origin_file_id": 0, "origin_read_id": 0},
                {"origin_file_id": 0, "origin_read_id": 1},
            ]
        with self.assertRaises(ReadProvenanceError):
            build_read_provenance_from_leaf_records(
                merged2, records, overwrite=True)

    def test_retrofit_missing_leaf_dir_fails(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        merged2 = os.path.join(self.work, "merged_missing")
        shutil.copytree(output, merged2)
        os.remove(os.path.join(merged2, "read_provenance.npy"))
        os.remove(os.path.join(merged2, "read_provenance.json"))
        leaf_dirs = {sid: leaves[sid] for sid in TEN_SOURCE_READS}
        del leaf_dirs["sample05"]
        with self.assertRaises(ReadProvenanceError):
            retrofit_read_provenance_from_leaf_dirs(merged2, leaf_dirs)

    def test_retrofit_without_overwrite_keeps_existing(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        # call with overwrite=False must not clobber the fresh-merge table
        retrofit_read_provenance_from_leaf_dirs(
            output,
            {sid: leaves[sid] for sid in TEN_SOURCE_READS})
        self.assert_identity_exact(output, oracle, TEN_SOURCE_READS)


class ReadIdentityOracleTests(ReadProvenancePy2TestBase):
    def test_every_dollar_id_matches_independent_oracle(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        index = ReadProvenanceIndex(output)
        for dollar_id in range(index.read_count):
            expected_source, expected_local = (
                oracle.dollar_to_identity[dollar_id])
            record = index.record(dollar_id)
            self.assertEqual(record["source_id"], expected_source)
            self.assertEqual(record["source_read_id"], expected_local)
            # provenance-tree row identity agrees too
            sid, local = index.source_index.locate_row_source(dollar_id)
            self.assertEqual(sid, expected_source)
            self.assertEqual(local, expected_local)

    def test_every_bwt_row_read_identity_agrees_with_row_source(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        index = ReadProvenanceIndex(output)
        for row_index in range(manifest["root"]["length"]):
            source_id, _ = index.source_index.locate_row_source(row_index)
            dollar_id = oracle.getSequenceDollarID(row_index)
            record = index.record(dollar_id)
            self.assertEqual(record["source_id"], source_id)

    def test_find_dollar_id_roundtrip(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        index = ReadProvenanceIndex(output)
        for sid in TEN_SOURCE_READS:
            for local in range(len(TEN_SOURCE_READS[sid])):
                self.assertEqual(
                    index.find_dollar_id(sid, local),
                    oracle.global_dollar[(sid, local)])

    def test_read_mate_and_read_provenance_methods(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        index = ReadProvenanceIndex(output)
        d0 = index.find_dollar_id("sample03", 0)
        mate = index.mate(d0)
        self.assertEqual(mate["dollar_id"],
                         index.find_dollar_id("sample03", 1))
        self.assertIsNone(index.mate(index.find_dollar_id("sample03", 2)))
        with self.assertRaises(KeyError):
            index.find_dollar_id("sample03", 99)

    def test_unknown_source_and_ambiguous_name(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        index = ReadProvenanceIndex(output)
        with self.assertRaises(IndexError):
            index.record(999)
        with self.assertRaises(KeyError):
            index.find_dollar_id("missing_source", 0)


class ReadsContainingTests(ReadProvenancePy2TestBase):
    def _check_patterns(self, reads_by_source, patterns, origin_base=100,
                        file_count=1):
        leaves, output, manifest, oracle = self.build_merged(
            reads_by_source, origin_base=origin_base, file_count=file_count)
        index = ReadProvenanceIndex(output)
        wrapped = MultiSourceBWT(
            None, index.source_index, read_provenance=index)
        bwt = OracleBWTAdapter(oracle, output, manifest)
        wrapped.bwt = bwt
        return self._check_reads_containing(
            wrapped, oracle, reads_by_source, patterns,
            origin_base=origin_base, file_count=file_count)

    def test_ten_source_patterns_match_naive_counts(self):
        self._check_patterns(TEN_SOURCE_READS, pattern_set(TEN_SOURCE_READS))

    def test_duplicate_and_identical_reads_retain_identities(self):
        reads_by_source = {
            "D": ["ACGTAC", "ACGTAC", "ACGTAC"],
            "I": ["AAAA", "AAAA"],
            "O": ["ACGTAC"],
        }
        patterns = ["ACGTAC", "A", "AAAA", "AC", "TT", "N"]
        self._check_patterns(reads_by_source, patterns)

    def test_all_identical_reads(self):
        reads_by_source = {
            "S1": ["AAAA", "AAAA"],
            "S2": ["AAAA", "AAAA"],
        }
        patterns = ["A", "AA", "AAA", "AAAA", "AAAAA", "G"]
        wrapped, oracle = self._check_patterns(reads_by_source, patterns)
        result = wrapped.readsContaining("AAAA")
        self.assertEqual(result["unique_read_count"], 4)
        # one overlapping occurrence per identical read
        self.assertEqual(result["reported_occurrences"], 4)

    def test_n_heavy_and_mixed_lengths(self):
        reads_by_source = {
            "N": ["N", "NN", "ACGTNNNN", "NACGT", "NNNNNNNNNN"],
            "M": ["A", "AC", "ACG", "ACGT", "ACGTACGTACGT"],
        }
        patterns = ["N", "NN", "AC", "ACG", "ACGT", "A", "C", "G", "T",
                    "NNNN", "ACGTACGT", "G"]
        self._check_patterns(reads_by_source, patterns)

    def test_one_base_reads(self):
        reads_by_source = {
            "S1": ["A", "C"],
            "S2": ["G", "T"],
        }
        self._check_patterns(reads_by_source, ["A", "C", "G", "T", "AA"])

    def test_source_filter_prefilters_before_lf_walk(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        index = ReadProvenanceIndex(output)
        wrapped = MultiSourceBWT(
            None, index.source_index, read_provenance=index)
        bwt = OracleBWTAdapter(oracle, output, manifest)
        wrapped.bwt = bwt

        pattern = "A"
        merged_low, merged_high = bwt.findIndicesOfStr(pattern)
        total_occurrences = merged_high - merged_low
        before = bwt.lf_calls
        result = wrapped.readsContaining(pattern, source="sample09")
        lf_calls = bwt.lf_calls - before
        self.assertEqual(lf_calls, result["stats"]["lf_walks"])
        self.assertEqual(lf_calls, result["reported_occurrences"])
        self.assertLess(lf_calls, total_occurrences)
        self.assertTrue(all(
            rec["source_id"] == "sample09" for rec in result["reads"]))

    def test_source_and_subset_filters_match_independent_filtering(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        index = ReadProvenanceIndex(output)
        wrapped = MultiSourceBWT(
            None, index.source_index, read_provenance=index)
        wrapped.bwt = OracleBWTAdapter(oracle, output, manifest)

        for pattern in ("A", "AC", "CGT", "AAAA", "N", "AAGGTT"):
            global_result = wrapped.readsContaining(pattern)
            global_map = {
                rec["dollar_id"]: rec["occurrence_count"]
                for rec in global_result["reads"]
            }
            subset = ["sample00", "sample02", "sample09"]
            filtered = {
                d: c for d, c in global_map.items()
                if index.record(d)["source_id"] in subset
            }
            result = wrapped.readsContaining(
                pattern, sources=subset)
            actual = {
                rec["dollar_id"]: rec["occurrence_count"]
                for rec in result["reads"]
            }
            self.assertEqual(actual, filtered, pattern)
            self.assertEqual(
                result["reported_occurrences"], sum(filtered.values()))
            self.assertEqual(
                result["stats"]["source_prefilter_skips"]
                + result["reported_occurrences"],
                global_result["merged_occurrences"])

    def test_group_and_where_filters_match(self):
        reads_by_source = {
            "case1": ["ACGTAC", "GATTACA", "AAAA"],
            "case2": ["ACGTTC", "CCCC", "TACGTA"],
            "ctrl1": ["GGGG", "ACACAC", "TTAC"],
        }
        leaves, output, manifest, oracle = self.build_merged(
            reads_by_source)
        index = ReadProvenanceIndex(output)
        metadata = SourceMetadataCatalog(index.source_index.list_sources())
        metadata.define_group("case", ["case1", "case2"])
        metadata.define_group("ctrl", ["ctrl1"])
        metadata.set_source_metadata("case1", cohort="case")
        metadata.set_source_metadata("case2", cohort="case")
        metadata.set_source_metadata("ctrl1", cohort="ctrl")
        wrapped = MultiSourceBWT(
            None, index.source_index, source_metadata=metadata,
            read_provenance=index)
        wrapped.bwt = OracleBWTAdapter(oracle, output, manifest)

        for pattern in ("A", "AC", "CGT", "AAAA"):
            group_result = wrapped.readsContaining(
                pattern, group="case")
            where_result = wrapped.readsContaining(
                pattern, where={"cohort": "case"})
            self.assertEqual(
                [r["dollar_id"] for r in group_result["reads"]],
                [r["dollar_id"] for r in where_result["reads"]])
            self.assertTrue(all(
                rec["source_id"] in ("case1", "case2")
                for rec in group_result["reads"]))
            self.assertEqual(
                group_result["reported_occurrences"],
                where_result["reported_occurrences"])

    def test_include_sequence_recovers_exact_read(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        index = ReadProvenanceIndex(output)
        wrapped = MultiSourceBWT(
            None, index.source_index, read_provenance=index)
        wrapped.bwt = OracleBWTAdapter(oracle, output, manifest)
        result = wrapped.readsContaining(
            "AAGGTT", include_sequence=True)
        self.assertEqual(len(result["reads"]), 1)
        record = result["reads"][0]
        self.assertEqual(record["source_id"], "sample09")
        # real Holt/McMillan recoverString returns the rotation starting
        # at '$', i.e. '$' + original read
        self.assertEqual(record["sequence"], b"$AAGGTT")

    def test_row_read_provenance_with_offset(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        index = ReadProvenanceIndex(output)
        wrapped = MultiSourceBWT(
            None, index.source_index, read_provenance=index)
        wrapped.bwt = OracleBWTAdapter(oracle, output, manifest)
        result = wrapped.rowReadProvenance(60, include_offset=True)
        self.assertEqual(result["row_index"], 60)
        self.assertGreaterEqual(result["lf_offset"], 0)

    def test_missing_read_provenance_reports_cleanly(self):
        reads_by_source = {
            "A": ["ACGTAC", "AAAA"],
            "B": ["TTTT", "CCCC"],
        }
        leaves, output, manifest, oracle = self.build_merged(reads_by_source)
        index = ReadProvenanceIndex(output)
        wrapped = MultiSourceBWT(
            None, index.source_index, read_provenance=None)
        wrapped.bwt = OracleBWTAdapter(oracle, output, manifest)
        with self.assertRaises(MultiSourceQueryError):
            wrapped.readProvenance(0)
        with self.assertRaises(MultiSourceQueryError):
            wrapped.readsContaining("A")

    def test_max_occurrences_truncation_stats(self):
        leaves, output, manifest, oracle = self.build_merged(
            TEN_SOURCE_READS)
        index = ReadProvenanceIndex(output)
        wrapped = MultiSourceBWT(
            None, index.source_index, read_provenance=index)
        wrapped.bwt = OracleBWTAdapter(oracle, output, manifest)
        result = wrapped.readsContaining("A", max_occurrences=3)
        self.assertTrue(result["stats"]["truncated"])
        self.assertEqual(result["stats"]["interval_rows_scanned"], 3)


class OracleBWTAdapter(object):
    """Thin BWT view over the independent read-identity oracle."""

    def __init__(self, oracle, merged_dir, manifest):
        self.oracle = oracle
        self.merged_dir = str(merged_dir)
        self.manifest = manifest
        self.lf_calls = 0
        self.search_calls = 0
        self.rows = load_rows(self.merged_dir)
        self.suffixes = [row["suffix"] for row in self.rows]

    def getTotalSize(self):
        return len(self.rows)

    def findIndicesOfStr(self, seq, givenRange=None):
        self.search_calls += 1
        if isinstance(seq, bytes):
            pattern = seq.decode("ascii")
        else:
            pattern = str(seq)
        if givenRange is None:
            low = self._bisect(pattern)
            high = self._bisect(pattern + "\x7f")
            return low, high
        raise NotImplementedError("givenRange not used in Feature-9 tests")

    def _bisect(self, pattern):
        lo = 0
        hi = len(self.suffixes)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.suffixes[mid] < pattern:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def countOccurrencesOfSeq(self, seq, givenRange=None):
        low, high = self.findIndicesOfStr(seq, givenRange)
        return high - low

    def getSequenceDollarID(self, row_index, returnOffset=False):
        self.lf_calls += 1
        return self.oracle.getSequenceDollarID(row_index, returnOffset)

    def recoverString(self, dollar_id):
        return self.oracle.recoverString(dollar_id)


class PersistenceSafetyTests(ReadProvenancePy2TestBase):
    def _make_fixture(self):
        reads_by_source = TEN_SOURCE_READS
        leaves, output, manifest, oracle = self.build_merged(reads_by_source)
        return output, oracle

    def test_wrong_read_count_rejected(self):
        output, oracle = self._make_fixture()
        merged2 = os.path.join(self.work, "wrong_count")
        shutil.copytree(output, merged2)
        os.remove(os.path.join(merged2, "read_provenance.npy"))
        # truncate the table by one record
        table = np.load(os.path.join(output, "read_provenance.npy"))
        np.save(os.path.join(merged2, "read_provenance.npy"),
                table[:-1])
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(merged2)

    def test_wrong_dtype_rejected(self):
        output, oracle = self._make_fixture()
        merged2 = os.path.join(self.work, "wrong_dtype")
        shutil.copytree(output, merged2)
        np.save(os.path.join(merged2, "read_provenance.npy"),
                np.zeros(30, dtype=np.uint64))
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(merged2)

    def test_truncated_npy_rejected(self):
        output, oracle = self._make_fixture()
        merged2 = os.path.join(self.work, "truncated")
        shutil.copytree(output, merged2)
        path = os.path.join(merged2, "read_provenance.npy")
        size = os.path.getsize(path)
        with open(path, "r+b") as fp:
            fp.truncate(size - 40)
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(merged2)

    def test_wrong_format_and_version_rejected(self):
        output, oracle = self._make_fixture()
        for field, value in (("format", "other-format"),
                             ("version", 99)):
            merged2 = os.path.join(self.work, "wrong_" + str(field))
            shutil.copytree(output, merged2)
            meta_path = os.path.join(
                merged2, "read_provenance.json")
            with open(meta_path, "r") as fp:
                meta = json.load(fp)
            meta[field] = value
            with open(meta_path, "w") as fp:
                json.dump(meta, fp)
            with self.assertRaises(ReadProvenanceError):
                ReadProvenanceIndex(merged2)

    def test_wrong_ordering_rejected(self):
        output, oracle = self._make_fixture()
        merged2 = os.path.join(self.work, "wrong_order")
        shutil.copytree(output, merged2)
        meta_path = os.path.join(merged2, "read_provenance.json")
        with open(meta_path, "r") as fp:
            meta = json.load(fp)
        meta["ordering"] = "by-source"
        with open(meta_path, "w") as fp:
            json.dump(meta, fp)
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(merged2)

    def test_replaced_same_length_bwt_rejected(self):
        output, oracle = self._make_fixture()
        merged2 = os.path.join(self.work, "replaced_bwt")
        shutil.copytree(output, merged2)
        bwt = np.load(os.path.join(merged2, "msbwt.npy"))
        bwt[0] = (bwt[0] + 1) % 6
        np.save(os.path.join(merged2, "msbwt.npy"), bwt)
        with self.assertRaises((ReadProvenanceError, ProvenanceError)):
            ReadProvenanceIndex(merged2)

    def test_copied_foreign_same_length_array_rejected(self):
        # read provenance from index A copied into index B of the same
        # read count must be rejected by the BWT identity binding.
        reads_a = {
            "A1": ["ACGTAC", "GATTACA", "AAAA"],
            "A2": ["TTTT", "GCGTAC", "AACCAA"],
        }
        leaves_a, output_a, manifest_a, oracle_a = self.build_merged(
            reads_a)
        leaves_b, output_b, manifest_b, oracle_b = self.build_merged(
            TEN_SOURCE_READS, name="merged_b")
        shutil.copy(
            os.path.join(output_a, "read_provenance.npy"),
            os.path.join(output_b, "read_provenance.npy"))
        shutil.copy(
            os.path.join(output_a, "read_provenance.json"),
            os.path.join(output_b, "read_provenance.json"))
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(output_b)

    def test_unknown_source_metadata_rejected(self):
        output, oracle = self._make_fixture()
        merged2 = os.path.join(self.work, "unknown_source")
        shutil.copytree(output, merged2)
        meta_path = os.path.join(merged2, "read_provenance.json")
        with open(meta_path, "r") as fp:
            meta = json.load(fp)
        meta["source_metadata"]["ghost_source"] = {}
        with open(meta_path, "w") as fp:
            json.dump(meta, fp)
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(merged2)

    def test_missing_metadata_file_reported(self):
        output, oracle = self._make_fixture()
        merged2 = os.path.join(self.work, "missing_meta")
        shutil.copytree(output, merged2)
        os.remove(os.path.join(merged2, "read_provenance.json"))
        self.assertFalse(read_provenance_exists(merged2))
        with self.assertRaises(ReadProvenanceError):
            ReadProvenanceIndex(merged2)


class RandomizedDifferentialTests(ReadProvenancePy2TestBase):
    def _random_dataset(self, rng, seed_index, case):
        sources = {}
        n_sources = rng.randint(1, 5)
        alphabet = "ACGTN"
        for i in range(n_sources):
            n_reads = rng.randint(1, 5)
            reads = []
            for _ in range(n_reads):
                length = rng.randint(1, 10)
                if rng.random() < 0.3:
                    # force duplicates
                    if reads:
                        reads.append(reads[rng.randrange(len(reads))])
                        continue
                reads.append("".join(
                    rng.choice(alphabet) for _ in range(length)))
            sources["S%02d_C%02d_S%d" % (seed_index, case, i)] = reads
        return sources

    def _patterns(self, reads_by_source, rng):
        patterns = ["A", "C", "G", "T", "N", "AC", "GT", "AA"]
        pool = []
        for reads in reads_by_source.values():
            for read in reads:
                pool.append(read)
                if len(read) >= 3:
                    pool.append(read[:3])
                    pool.append(read[-3:])
        for _ in range(6):
            if pool:
                patterns.append(rng.choice(pool))
        return sorted(set(patterns))

    def _check_dataset(self, reads_by_source, origin_base, file_count,
                       case):
        leaves, output, manifest, oracle = self.build_merged(
            reads_by_source, origin_base=origin_base, file_count=file_count,
            name="merged_c%02d" % case)
        self.assert_identity_exact(
            output, oracle, reads_by_source,
            origin_base=origin_base, file_count=file_count)
        index = ReadProvenanceIndex(output)
        wrapped = MultiSourceBWT(
            None, index.source_index, read_provenance=index)
        wrapped.bwt = OracleBWTAdapter(oracle, output, manifest)
        patterns = self._patterns(reads_by_source, random.Random(1))
        self._check_reads_containing(
            wrapped, oracle, reads_by_source, patterns,
            origin_base=origin_base, file_count=file_count)

    def test_randomized_differentials(self):
        for seed_index, seed in enumerate(SEEDS):
            rng = random.Random(seed)
            for case in range(12):
                self._check_dataset(
                    self._random_dataset(rng, seed_index, case),
                    origin_base=1000 * case,
                    file_count=rng.randint(1, 3),
                    case=seed_index * 100 + case)


if __name__ == "__main__":
    unittest.main()
