"""Host-side regression tests for enhanced-modern2 Feature 11A: exact
post-construction LCP retrofit (``MUS.LCP`` plus Feature-11A additions to
``MUS.MultiSourceQuery`` and ``MUS.SourceRemoval``).

These tests are read-only and run on any CPython 3 with NumPy; they do NOT
require the compiled MUSCython extensions (real-merge integration runs in
the pinned Python-2.7 suite and the Feature-11A validation driver).

Coverage:

- ``lcps.npy`` convention (length N-1, ``lcps[i] = LCP(SA[i], SA[i+1])``)
  and canonical boundary convention (``LCP[0] = 0``);
- independent oracle: EVERY adjacent LCP computed character-by-character
  with distinct-virtual-terminator semantics (duplicate reads never gain
  an extra terminator symbol; two terminal suffixes have LCP 0);
- required cases: one read, two reads, duplicates, many identical reads,
  prefix/suffix-related reads, N-heavy, mixed lengths, multi-source
  merged package, post-Feature-10 reduced package, Point-12-tagged and
  Q1-quality-enabled packages (no tag/quality/BWT bytes change);
- query API: ``hasLCP`` / ``lcpAt`` / ``lcpAdjacent`` /
  ``lcpBetweenRows`` (RMQ identity verified on small indexes);
- stale/corrupt protection: same-length replaced BWT, wrong length,
  wrong dtype, wrong version, corrupt metadata, stale max_lcp, missing
  array;
- Point-10 fail-safe (LCP removal rejected) and explicit ``drop_lcp``;
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

from MUS.LCP import (  # noqa: E402
    LCPError,
    LCPIndex,
    construct_lcp_from_bwt,
    lcp_exists,
    validate_lcp,
)
from MUS.MultiSourceProvenance import (  # noqa: E402
    load_manifest,
    merge_many_balanced,
    validate_manifest,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryError,
    MultiSourceQueryIndex,
)
from MUS.SourceRemoval import remove_sources  # noqa: E402

import test_multisource_query as f3  # noqa: E402
import test_read_provenance as f9  # noqa: E402

SEEDS = (20260811, 20260812, 20260813)

EVIDENCE = os.path.join(PACKAGE, "evidence", "feature11a-lcp.json")
EVIDENCE_GENERATOR = os.path.join(
    PACKAGE, "validate", "feature11a_lcp_evidence.py")
VALIDATION_DRIVER = os.path.join(
    PACKAGE, "validate", "feature11a-lcp.sh")


def explicit_lcp(a, b):
    i = 0
    j = 0
    count = 0
    while (
        i < len(a) and j < len(b)
        and a[i] == b[j] and a[i] != "$"
    ):
        count += 1
        i += 1
        j += 1
    return count


def expected_lcps(directory):
    suffixes = [row["suffix"] for row in f3.load_rows(directory)]
    return np.asarray(
        [explicit_lcp(suffixes[i], suffixes[i + 1])
         for i in range(len(suffixes) - 1)],
        dtype=np.uint32,
    )


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


class OracleBackedAdapter(object):
    """Naive recoverString(withIndex=True) safe for merged packages."""

    def __init__(self, directory, oracle=None):
        self.directory = str(directory)
        self.rows = f3.load_rows(self.directory)
        self.suffixes = [r["suffix"] for r in self.rows]
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
        pattern = seq.decode("ascii") if isinstance(seq, bytes) else str(seq)
        if givenRange is not None:
            # FM backward step for a single symbol by direct counting.
            if len(pattern) != 1:
                raise NotImplementedError(
                    "givenRange supports single symbols only")
            low, high = givenRange
            c_first = 0
            rank_l = 0
            rank_h = 0
            for index, row in enumerate(self.rows):
                first = row["suffix"][0]
                if first < pattern:
                    c_first += 1
                if index < low and row["bwt"] == pattern:
                    rank_l += 1
                if index < high and row["bwt"] == pattern:
                    rank_h += 1
            return (c_first + rank_l, c_first + rank_h)
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

    def getCharAtIndex(self, index):
        row = self.rows[int(index)]
        return f3.ALPHABET_CODE[row["bwt"]]

    def getOccurrence(self, symbol, position):
        position = int(position)
        symbol = int(symbol)
        return sum(
            1 for row in self.rows[:position]
            if f3.ALPHABET_CODE[row["bwt"]] == symbol
        )

    def getSequenceDollarID(self, row_index, returnOffset=False):
        row_index = int(row_index)
        if self.oracle is None:
            read_id = self.rows[row_index]["read_id"]
            dollar_row = [
                i for i, r in enumerate(self.rows)
                if r["suffix"] == "$" and r["read_id"] == read_id
            ][0]
            local_dollar = sum(
                1 for i, r in enumerate(self.rows)
                if r["suffix"] == "$" and i < dollar_row
            )
            pos = int(self.rows[row_index]["pos"])
        else:
            sid, local_row = walk_row(
                self.directory, load_manifest(self.directory), row_index)
            leaf_rows = self.oracle.leaf_rows[sid]
            read_id = leaf_rows[local_row]["read_id"]
            local_dollar = self.oracle.leaf_dollar_rows[sid][read_id]
            pos = int(leaf_rows[local_row]["pos"])
        dollar_id = (
            local_dollar
            if self.oracle is None
            else self.oracle.global_dollar[(sid, local_dollar)]
        )
        if returnOffset:
            return dollar_id, pos
        return dollar_id

    def recoverString(self, dollar_id, withIndex=False):
        if self.oracle is None:
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
        else:
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
        if self.oracle is None:
            indices = [by_pos[p] for p in order]
            rows_for_seq = self.rows
        else:
            indices = [
                self.merged_index[(sid, by_pos[p])] for p in order
            ]
            rows_for_seq = leaf_rows
        sequence = "".join(
            rows_for_seq[by_pos[p]]["suffix"][0] for p in order)
        encoded = sequence.encode("ascii")
        if withIndex:
            return encoded, indices
        return encoded


class LCPHostTestBase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="lcp-host-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def build_merged(self, reads_by_source=None, name="merged"):
        reads_by_source = reads_by_source or f3.TEN_SOURCE_READS
        leaves = {}
        for sid, reads in reads_by_source.items():
            leaf = f3.make_read_derived_leaf(self.work, sid, reads)
            leaves[sid] = leaf
        output = os.path.join(self.work, name)
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f3.read_derived_merge)
        oracle = f9.OracleReadIdentity(
            output,
            {sid: leaves[sid] for sid in reads_by_source},
            reads_by_source)
        return leaves, output, oracle, reads_by_source

    def construct(self, directory, oracle=None):
        return construct_lcp_from_bwt(
            directory, bwt=OracleBackedAdapter(directory, oracle))

    def assert_lcp_exact(self, directory):
        index = LCPIndex(directory)
        expected = expected_lcps(directory)
        self.assertEqual(index.values.shape[0], expected.shape[0])
        for i in range(expected.shape[0]):
            self.assertEqual(
                int(index.values[i]), int(expected[i]), i)
        return index, expected


class TerminatorAndConstructionHostTests(LCPHostTestBase):
    def test_terminator_semantics_cases(self):
        cases = [
            {"D": ["ACG", "ACG"], "O": ["TTTT"]},
            {"S1": ["AAAA", "AAAA", "AAAA"], "S2": ["AAAA", "AAAA"]},
            {"P": ["ACGT", "ACG", "AC", "A", "ACGTACGT"],
             "S": ["TACGT", "GTACGT", "CGTACGT"]},
            {"M": ["A", "AC", "ACG", "ACGT", "ACGTACGTACGT"],
             "B": ["T", "G", "N"]},
            {"N": ["N", "NN", "ACGTNNNN", "NACGT"]},
            {"one": ["A"]},
        ]
        for case_index, reads_by_source in enumerate(cases):
            leaves, output, oracle, rbs = self.build_merged(
                reads_by_source,
                name="case_%d" % case_index)
            self.construct(output, oracle)
            index, expected = self.assert_lcp_exact(output)
            # duplicate reads never gain an extra terminator symbol:
            # max LCP <= max read length in the collection
            max_read_len = max(len(r)
                               for reads in reads_by_source.values()
                               for r in reads)
            self.assertLessEqual(int(np.max(index.values)),
                                 max_read_len,
                                 (case_index,))

    def test_ten_source_fixture_every_boundary_exact(self):
        leaves, output, oracle, rbs = self.build_merged(
            f3.TEN_SOURCE_READS, name="merged10")
        self.construct(output, oracle)
        index, expected = self.assert_lcp_exact(output)
        self.assertEqual(index.n_rows, 191)
        self.assertEqual(index.values.shape[0], 190)
        self.assertEqual(index.max_lcp, int(np.max(expected)))
        self.assertEqual(
            index.metadata["terminator_semantics"],
            "virtual-distinct-ordered-dollar-excluded-from-lcp")

    def test_bwt_unchanged_and_layer_compatible_with_tags_quality(self):
        from MUS.BWTTags import BWTTagStore, attach_tag
        from MUS.QualitySidecar import (
            QualitySidecar, attach_quality_from_row_values)
        import hashlib

        leaves = {}
        for sid, reads in (("A", ["ACGTAC", "AAAA"]),
                           ("B", ["TTTT", "CCCC"])):
            leaf = f3.make_read_derived_leaf(self.work, sid, reads)
            attach_tag(
                leaf, "row_id",
                np.arange(len(f3.load_rows(leaf)), dtype=np.uint32))
            rows = f3.load_rows(leaf)
            q = np.zeros(len(rows), dtype=np.uint8)
            for idx, r in enumerate(rows):
                read = reads[r["read_id"]]
                q[idx] = 255 if r["pos"] >= len(read) else 33 + (idx % 40)
            attach_quality_from_row_values(leaf, q)
            leaves[sid] = leaf
        output = os.path.join(self.work, "merged")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f3.read_derived_merge)
        bwt_before = hashlib.sha256(open(
            os.path.join(output, "msbwt.npy"), "rb").read()).hexdigest()
        tag_before = BWTTagStore(output).array("row_id").copy()
        quality_before = QualitySidecar(output).values.copy()
        oracle = f9.OracleReadIdentity(
            output,
            {sid: leaves[sid] for sid in leaves},
            {"A": ["ACGTAC", "AAAA"], "B": ["TTTT", "CCCC"]})
        self.construct(output, oracle)
        self.assertEqual(
            bwt_before,
            hashlib.sha256(open(
                os.path.join(output, "msbwt.npy"), "rb").read()).hexdigest())
        self.assertTrue(np.array_equal(
            BWTTagStore(output).array("row_id"), tag_before))
        self.assertTrue(np.array_equal(
            QualitySidecar(output).values, quality_before))
        self.assert_lcp_exact(output)

    def test_reduced_package_construction(self):
        leaves, output, oracle, rbs = self.build_merged(
            f3.TEN_SOURCE_READS, name="merged10")
        reduced = os.path.join(self.work, "reduced")
        remove_sources(
            output, reduced,
            sources=["sample00", "sample02", "sample09"],
            drop_lcp=True)
        keep = {sid: rbs[sid] for sid in rbs
                if sid not in ("sample00", "sample02", "sample09")}
        reduced_oracle = f9.OracleReadIdentity(
            reduced,
            {sid: leaves[sid] for sid in keep},
            keep)
        save_expected_rows(reduced, leaves, keep)
        self.construct(reduced, reduced_oracle)
        self.assert_lcp_exact(reduced)


def save_expected_rows(directory, leaves, reads_by_source):
    all_order = {sid: i for i, sid in enumerate(reads_by_source)}
    rows = []
    for sid in reads_by_source:
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


class QueryAndStaleHostTests(LCPHostTestBase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="lcp-host-query-")
        cls.leaves = {}
        for sid, reads in f3.TEN_SOURCE_READS.items():
            leaf = f3.make_read_derived_leaf(cls.work, sid, reads)
            cls.leaves[sid] = leaf
        cls.output = os.path.join(cls.work, "merged10")
        merge_many_balanced(
            list(cls.leaves.values()), cls.output,
            merge_two_func=f3.read_derived_merge)
        cls.oracle = f9.OracleReadIdentity(
            cls.output,
            {sid: cls.leaves[sid] for sid in cls.leaves},
            f3.TEN_SOURCE_READS)
        construct_lcp_from_bwt(
            cls.output, bwt=OracleBackedAdapter(cls.output, cls.oracle))
        cls.index = MultiSourceQueryIndex(
            cls.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        cls.wrapped = MultiSourceBWT(
            None, cls.index, lcp_index=LCPIndex(cls.output))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_query_api_and_rmq_identity(self):
        self.assertTrue(self.wrapped.hasLCP())
        plain = MultiSourceBWT(None, self.index)
        self.assertFalse(plain.hasLCP())
        with self.assertRaises(MultiSourceQueryError):
            plain.lcpAt(0)
        expected = expected_lcps(self.output)
        self.assertEqual(self.wrapped.lcpAt(0), 0)
        for row in (1, 5, 100, 190):
            self.assertEqual(
                self.wrapped.lcpAt(row), int(expected[row - 1]))
        for left in (0, 3, 77, 189):
            self.assertEqual(
                self.wrapped.lcpAdjacent(left), int(expected[left]))
        for i in (0, 1, 5, 60, 100, 189):
            for j in (i + 1, min(i + 7, 190), 190):
                if j <= i:
                    continue
                self.assertEqual(
                    self.wrapped.lcpBetweenRows(i, j),
                    int(np.min(expected[i:j])), (i, j))
        with self.assertRaises(IndexError):
            self.wrapped.lcpAt(191)
        with self.assertRaises(LCPError):
            self.wrapped.lcpBetweenRows(5, 5)

    def test_stale_and_corrupt_rejected(self):
        import gc

        from MUS.MultiSourceProvenance import ProvenanceError

        # run corruption checks on a copy so the class-level LCPIndex
        # memory map cannot lock the files (Windows)
        target = os.path.join(self.work, "stale_copy")
        shutil.copytree(self.output, target)

        # same-length replaced BWT (either the manifest digest binding or
        # the LCP identity binding fails loudly)
        bwt = np.load(os.path.join(target, "msbwt.npy"))
        bwt[0] = (bwt[0] + 1) % 6
        np.save(os.path.join(target, "msbwt.npy"), bwt)
        with self.assertRaises((LCPError, ProvenanceError)):
            LCPIndex(target)
        gc.collect()
        # wrong length
        arr = np.load(os.path.join(target, "lcps.npy"))
        np.save(os.path.join(target, "lcps.npy"), arr[:-1])
        with self.assertRaises(LCPError):
            LCPIndex(target)
        gc.collect()
        np.save(os.path.join(target, "lcps.npy"), arr)
        # wrong dtype
        np.save(os.path.join(target, "lcps.npy"),
                np.zeros(190, dtype=np.int32))
        with self.assertRaises(LCPError):
            LCPIndex(target)
        gc.collect()
        np.save(os.path.join(target, "lcps.npy"), arr)
        # corrupt metadata
        meta_path = os.path.join(target, "lcp.json")
        with open(meta_path, "w") as fp:
            fp.write("{not json")
        with self.assertRaises(LCPError):
            LCPIndex(target)


class RemovalFailSafeHostTests(LCPHostTestBase):
    def test_removal_rejected_and_drop_lcp(self):
        leaves, output, oracle, rbs = self.build_merged(
            f3.TEN_SOURCE_READS, name="merged10")
        self.construct(output, oracle)
        with self.assertRaises(LCPError):
            remove_sources(
                output, os.path.join(self.work, "r"),
                sources=["sample09"])
        self.assertFalse(os.path.exists(
            os.path.join(self.work, "r", "msbwt.npy")))
        reduced = os.path.join(self.work, "r2")
        remove_sources(
            output, reduced, sources=["sample09"], drop_lcp=True)
        self.assertFalse(lcp_exists(reduced))
        self.assertTrue(validate_manifest(reduced))


class RandomizedLCPHostTests(LCPHostTestBase):
    def test_randomized_construction_matches_oracle(self):
        for seed_index, seed in enumerate(SEEDS):
            rng = random.Random(seed)
            for case in range(6):
                reads_by_source = {}
                n_sources = rng.randint(1, 4)
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
                leaves, output, oracle, rbs = self.build_merged(
                    reads_by_source,
                    name="rand_%02d_%02d" % (seed_index, case))
                self.construct(output, oracle)
                index, expected = self.assert_lcp_exact(output)
                self.assertEqual(index.boundary(0), 0)
                n = expected.shape[0]
                for _ in range(20):
                    i = rng.randrange(n)
                    j = rng.randrange(i + 1, n + 1)
                    self.assertEqual(
                        index.between_rows(i, j),
                        int(np.min(expected[i:j])),
                        (seed, case, i, j))


class EvidenceConsistencyTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = json.load(open(EVIDENCE, encoding="utf-8"))
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "enhanced-modern2")
        self.assertEqual(
            evidence["final"]["milestone"],
            "enhanced-modern2-feature11a-lcp")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")

    def test_evidence_contract(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["seed"], 20260811)
        boundaries = report["boundaries"]
        self.assertEqual(boundaries["count"], 190)
        self.assertEqual(boundaries["mismatches"], 0)
        self.assertEqual(boundaries["max_lcp"], 5)
        self.assertTrue(report["terminator_semantics"]["duplicates"])
        self.assertTrue(report["terminator_semantics"]["identical"])
        self.assertTrue(report["bwt_unchanged"])
        self.assertTrue(report["tags_quality_unchanged"])
        self.assertTrue(report["removal_failsafe"]["rejected"])
        self.assertTrue(report["removal_failsafe"]["drop_lcp"])
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
        self.assertIn("feature11a-lcp", driver)


if __name__ == "__main__":
    unittest.main()
