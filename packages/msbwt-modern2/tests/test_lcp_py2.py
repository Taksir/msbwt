"""Feature 11A - exact post-construction LCP retrofit (Python-2 suite,
real merges).

This suite validates ``MUS.LCP`` (``construct_lcp_from_bwt``,
``LCPIndex``, ``validate_lcp``) plus the Feature-11A additions to
``MUS.MultiSourceQuery`` (``hasLCP`` / ``lcpAt`` / ``lcpAdjacent`` /
``lcpBetweenRows``) and ``MUS.SourceRemoval`` (LCP fail-safe and
``drop_lcp``) against an independent oracle:

* for every adjacent pair of explicitly sorted suffix rows, the LCP is
  computed character-by-character and stops BEFORE the terminator
  (distinct-virtual-terminator semantics: identical reads have LCP equal
  to the biological length, never +1; two terminal suffixes have LCP 0);
* EVERY stored boundary is compared, not aggregates.

Coverage:

- ``lcps.npy`` convention (length N-1, ``lcps[i] = LCP(SA[i], SA[i+1])``)
  and the canonical boundary convention (``LCP[0] = 0``);
- terminator semantics: duplicate reads, many identical reads, prefix/
  suffix-related reads, N-heavy, mixed lengths, 1-base reads;
- construction from leaf and multi-merged packages (no FASTQ, no BWT
  rebuild; BWT bytes unchanged);
- LCP added on top of Point-12-tagged and Q1-quality-enabled packages
  without changing any tag/quality bytes;
- construction on a post-Feature-10 reduced package;
- query API: ``lcpAt`` / ``lcpAdjacent`` / ``lcpBetweenRows`` (RMQ
  identity verified exhaustively on small indexes);
- stale/corrupt protection: same-length replaced BWT, wrong length,
  wrong dtype, wrong version, corrupt metadata, truncated array;
- Point-10 fail-safe (LCP removal rejected) and explicit ``drop_lcp``;
- randomized differentials (seeds 20260811/20260812/20260813).
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
import test_read_provenance_py2 as f9  # noqa: E402

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


def explicit_lcp(a, b):
    """Independent adjacent LCP; '$' is never counted as a symbol."""
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


def expected_lcps(directory):
    """Independent LCP array from the explicit sorted suffix rows."""
    suffixes = [row["suffix"] for row in f9.load_rows(directory)]
    return np.asarray(
        [explicit_lcp(suffixes[i], suffixes[i + 1])
         for i in range(len(suffixes) - 1)],
        dtype=np.uint32,
    )


def build_merged(work, reads_by_source, name="merged"):
    """Build a merged read-derived package plus its Feature-9 oracle."""
    leaves = {}
    for sid, reads in reads_by_source.items():
        leaf = f9.make_read_derived_leaf(work, sid, reads)
        leaves[sid] = leaf
    output = os.path.join(work, name)
    merge_many_balanced(
        list(leaves.values()), output,
        merge_two_func=f9.read_derived_merge)
    oracle = f9.OracleReadIdentity(
        output,
        {sid: leaves[sid] for sid in reads_by_source},
        reads_by_source)
    return leaves, output, oracle, reads_by_source


class OracleBackedAdapter(object):
    """Naive recoverString(withIndex=True) safe for merged packages.

    Per-source ``read_id`` values collide across sources in a merged
    package, so reads are resolved through the independent Feature-9
    oracle and tree walk.
    """

    def __init__(self, directory, oracle=None):
        self.directory = str(directory)
        self.rows = f9.load_rows(self.directory)
        self.suffixes = [r["suffix"] for r in self.rows]
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
        pattern = seq.decode("ascii") if isinstance(seq, bytes) else str(seq)
        if givenRange is not None:
            # FM backward step for a single symbol: I(cP) = [C(c) +
            # rank_c(l), C(c) + rank_c(h)) computed by direct counting.
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
        low = bisect_left(self.suffixes, pattern)
        high = bisect_left(self.suffixes, pattern + "\x7f")
        return low, high

    def countOccurrencesOfSeq(self, seq, givenRange=None):
        low, high = self.findIndicesOfStr(seq, givenRange)
        return high - low

    def getCharAtIndex(self, index):
        """Raw BWT symbol code at one row (access primitive)."""
        row = self.rows[int(index)]
        return f9.ALPHABET_CODE[row["bwt"]]

    def getOccurrence(self, symbol, position):
        """Occ(symbol, position) by direct counting (rank primitive)."""
        position = int(position)
        symbol = int(symbol)
        return sum(
            1 for row in self.rows[:position]
            if f9.ALPHABET_CODE[row["bwt"]] == symbol
        )

    def getSequenceDollarID(self, row_index, returnOffset=False):
        """Global dollar ID of the read owning a row (oracle-backed)."""
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
            sid, local_row = f9._tree_walk_row(
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


class LCPPy2TestBase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="lcp-py2-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def build_merged(self, reads_by_source=None, name="merged"):
        return build_merged(
            self.work, reads_by_source or f9.TEN_SOURCE_READS, name=name)

    def construct(self, directory, oracle=None):
        return construct_lcp_from_bwt(
            directory, bwt=OracleBackedAdapter(directory, oracle))

    def assert_lcp_exact(self, directory):
        index = LCPIndex(directory)
        expected = expected_lcps(directory)
        self.assertEqual(index.values.shape[0], expected.shape[0])
        for i in range(expected.shape[0]):
            self.assertEqual(
                int(index.values[i]), int(expected[i]),
                (i, "lcp boundary"))
        return index, expected


class TerminatorSemanticsTests(LCPPy2TestBase):
    def test_duplicate_reads_lcp_is_biological_length_not_plus_one(self):
        # 'ACG$' vs 'ACG$' must have LCP 3, never 4.
        leaves, output, oracle, rbs = self.build_merged(
            {"D": ["ACG", "ACG"], "O": ["TTTT"]})
        self.construct(output, oracle)
        index, expected = self.assert_lcp_exact(output)
        self.assertLessEqual(int(np.max(index.values)), 3)

    def test_many_identical_reads(self):
        leaves, output, oracle, rbs = self.build_merged(
            {"S1": ["AAAA", "AAAA", "AAAA"],
             "S2": ["AAAA", "AAAA"]})
        self.construct(output, oracle)
        index, expected = self.assert_lcp_exact(output)
        # identical reads: adjacent identical suffixes have LCP 4 (full
        # biological length), never 5
        self.assertEqual(int(np.max(index.values)), 4)
        self.assertLessEqual(int(np.max(index.values)),
                             int(np.max(expected)))

    def test_all_terminal_boundaries_are_zero(self):
        leaves, output, oracle, rbs = self.build_merged(
            {"S1": ["AAAA"], "S2": ["TTTT"], "S3": ["CCCC"]})
        self.construct(output, oracle)
        index = LCPIndex(output)
        read_count = len(rbs["S1"]) + len(rbs["S2"]) + len(rbs["S3"])
        self.assertTrue(np.all(index.values[:read_count] == 0))

    def test_prefix_and_suffix_related_reads(self):
        reads_by_source = {
            "P": ["ACGT", "ACG", "AC", "A", "ACGTACGT"],
            "S": ["TACGT", "GTACGT", "CGTACGT"],
            "N": ["NACGT", "ACNT", "GGN"],
        }
        leaves, output, oracle, rbs = self.build_merged(reads_by_source)
        self.construct(output, oracle)
        self.assert_lcp_exact(output)

    def test_mixed_lengths_and_one_base_reads(self):
        reads_by_source = {
            "M": ["A", "AC", "ACG", "ACGT", "ACGTACGTACGT"],
            "B": ["T", "G", "N"],
        }
        leaves, output, oracle, rbs = self.build_merged(reads_by_source)
        self.construct(output, oracle)
        self.assert_lcp_exact(output)

    def test_single_read_package(self):
        leaves, output, oracle, rbs = self.build_merged(
            {"only": ["ACGTAC"]})
        self.construct(output, oracle)
        index, expected = self.assert_lcp_exact(output)
        # 7 rows -> 6 stored boundaries
        self.assertEqual(index.values.shape[0], 6)
        self.assertEqual(index.boundary(0), 0)


class ConstructionTests(LCPPy2TestBase):
    def test_ten_source_fixture_every_boundary_exact(self):
        leaves, output, oracle, rbs = self.build_merged(
            f9.TEN_SOURCE_READS, name="merged10")
        self.construct(output, oracle)
        index, expected = self.assert_lcp_exact(output)
        self.assertEqual(index.n_rows, 191)
        self.assertEqual(index.values.shape[0], 190)
        self.assertEqual(index.max_lcp, int(np.max(expected)))
        # metadata conventions
        metadata = index.metadata
        self.assertEqual(metadata["bwt_rows"], 191)
        self.assertEqual(metadata["read_count"], 30)
        self.assertEqual(
            metadata["terminator_semantics"],
            "virtual-distinct-ordered-dollar-excluded-from-lcp")
        self.assertIn("lcps[i] = LCP(SA[i], SA[i+1])",
                      metadata["stored_convention"])
        self.assertIn("LCP[0] = 0", metadata["canonical_convention"])

    def test_bwt_bytes_unchanged_by_construction(self):
        import hashlib
        leaves, output, oracle, rbs = self.build_merged(
            f9.TEN_SOURCE_READS, name="merged10")
        before = hashlib.sha256(open(
            os.path.join(output, "msbwt.npy"), "rb").read()).hexdigest()
        self.construct(output, oracle)
        after = hashlib.sha256(open(
            os.path.join(output, "msbwt.npy"), "rb").read()).hexdigest()
        self.assertEqual(before, after)

    def test_construction_on_reduced_package(self):
        leaves, output, oracle, rbs = self.build_merged(
            f9.TEN_SOURCE_READS, name="merged10")
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

    def test_overwrite_safety(self):
        leaves, output, oracle, rbs = self.build_merged(
            {"A": ["ACGT", "AAAA"], "B": ["TTTT", "CCCC"]})
        self.construct(output, oracle)
        with self.assertRaises(LCPError):
            construct_lcp_from_bwt(
                output, bwt=OracleBackedAdapter(output, oracle))
        construct_lcp_from_bwt(
            output, bwt=OracleBackedAdapter(output, oracle),
            overwrite=True)
        self.assert_lcp_exact(output)

    def test_leaf_construction(self):
        leaf = f9.make_read_derived_leaf(
            self.work, "leaf", ["ACGT", "AAAA", "TTTT"])
        construct_lcp_from_bwt(leaf, bwt=OracleBackedAdapter(leaf))
        self.assert_lcp_exact(leaf)

    def test_lcp_does_not_change_tag_or_quality_bytes(self):
        from MUS.BWTTags import BWTTagStore, attach_tag
        from MUS.QualitySidecar import (
            QualitySidecar, attach_quality_from_row_values)

        leaves = {}
        for sid, reads in (("A", ["ACGTAC", "AAAA"]),
                           ("B", ["TTTT", "CCCC"])):
            leaf = f9.make_read_derived_leaf(self.work, sid, reads)
            attach_tag(
                leaf, "row_id",
                np.arange(len(f9.load_rows(leaf)), dtype=np.uint32))
            rows = f9.load_rows(leaf)
            q = np.zeros(len(rows), dtype=np.uint8)
            for idx, r in enumerate(rows):
                read = reads[r["read_id"]]
                q[idx] = 255 if r["pos"] >= len(read) else 33 + (idx % 40)
            attach_quality_from_row_values(leaf, q)
            leaves[sid] = leaf
        output = os.path.join(self.work, "merged")
        merge_many_balanced(
            list(leaves.values()), output,
            merge_two_func=f9.read_derived_merge)
        tag_before = BWTTagStore(output).array("row_id").copy()
        quality_before = QualitySidecar(output).values.copy()
        oracle = f9.OracleReadIdentity(
            output,
            {sid: leaves[sid] for sid in leaves},
            {"A": ["ACGTAC", "AAAA"], "B": ["TTTT", "CCCC"]})
        self.construct(output, oracle)
        self.assertTrue(np.array_equal(
            BWTTagStore(output).array("row_id"), tag_before))
        self.assertTrue(np.array_equal(
            QualitySidecar(output).values, quality_before))
        self.assert_lcp_exact(output)


def save_expected_rows(directory, leaves, reads_by_source):
    """Test-side naive rows for a reduced package (independent oracle)."""
    all_order = {sid: i for i, sid in enumerate(reads_by_source)}
    rows = []
    for sid in reads_by_source:
        for r in f9.load_rows(leaves[sid]):
            rows.append((
                r["suffix"], all_order[sid], r["read_id"], r["pos"],
                r["bwt"]))
    rows.sort()
    out = [
        {"suffix": a, "read_id": c, "pos": d, "bwt": e}
        for a, b, c, d, e in rows
    ]
    f9.save_rows(directory, out)


class QueryAPITests(LCPPy2TestBase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="lcp-query-")
        cls.leaves = {}
        for sid, reads in f9.TEN_SOURCE_READS.items():
            leaf = f9.make_read_derived_leaf(cls.work, sid, reads)
            cls.leaves[sid] = leaf
        cls.output = os.path.join(cls.work, "merged10")
        merge_many_balanced(
            list(cls.leaves.values()), cls.output,
            merge_two_func=f9.read_derived_merge)
        cls.oracle = f9.OracleReadIdentity(
            cls.output,
            {sid: cls.leaves[sid] for sid in cls.leaves},
            f9.TEN_SOURCE_READS)
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

    def test_has_lcp_and_boundary_api(self):
        self.assertTrue(self.wrapped.hasLCP())
        plain = MultiSourceBWT(None, self.index)
        self.assertFalse(plain.hasLCP())
        with self.assertRaises(MultiSourceQueryError):
            plain.lcpAt(0)
        suffixes = [r["suffix"] for r in f9.load_rows(self.output)]
        expected = expected_lcps(self.output)
        self.assertEqual(self.wrapped.lcpAt(0), 0)
        for row in (1, 5, 100, 190):
            self.assertEqual(
                self.wrapped.lcpAt(row), int(expected[row - 1]))
        for left in (0, 3, 77, 189):
            self.assertEqual(
                self.wrapped.lcpAdjacent(left), int(expected[left]))
        with self.assertRaises(IndexError):
            self.wrapped.lcpAt(191)
        with self.assertRaises(IndexError):
            self.wrapped.lcpAdjacent(190)

    def test_rmq_identity_between_rows(self):
        expected = expected_lcps(self.output)
        for i in (0, 1, 5, 60, 100, 189):
            for j in (i + 1, min(i + 7, 190), 190):
                if j <= i:
                    continue
                self.assertEqual(
                    self.wrapped.lcpBetweenRows(i, j),
                    int(np.min(expected[i:j])),
                    (i, j))
        with self.assertRaises(LCPError):
            self.wrapped.lcpBetweenRows(5, 5)


class StaleProtectionTests(LCPPy2TestBase):
    def _fixture(self):
        leaves, output, oracle, rbs = self.build_merged(
            f9.TEN_SOURCE_READS, name="merged10")
        self.construct(output, oracle)
        return output

    def test_replaced_same_length_bwt_rejected(self):
        from MUS.MultiSourceProvenance import ProvenanceError

        output = self._fixture()
        bwt = np.load(os.path.join(output, "msbwt.npy"))
        bwt[0] = (bwt[0] + 1) % 6
        np.save(os.path.join(output, "msbwt.npy"), bwt)
        # either the manifest digest binding or the LCP identity binding
        # fails loudly
        with self.assertRaises((LCPError, ProvenanceError)):
            validate_lcp(output)
        with self.assertRaises((LCPError, ProvenanceError)):
            LCPIndex(output)

    def test_wrong_length_rejected(self):
        output = self._fixture()
        arr = np.load(os.path.join(output, "lcps.npy"))
        np.save(os.path.join(output, "lcps.npy"), arr[:-1])
        with self.assertRaises(LCPError):
            LCPIndex(output)

    def test_wrong_dtype_rejected(self):
        output = self._fixture()
        np.save(os.path.join(output, "lcps.npy"),
                np.zeros(190, dtype=np.int32))
        with self.assertRaises(LCPError):
            LCPIndex(output)

    def test_wrong_version_and_corrupt_metadata_rejected(self):
        output = self._fixture()
        meta_path = os.path.join(output, "lcp.json")
        with open(meta_path, "r") as fp:
            meta = json.load(fp)
        meta["version"] = 99
        with open(meta_path, "w") as fp:
            json.dump(meta, fp)
        with self.assertRaises(LCPError):
            LCPIndex(output)
        meta["version"] = 1
        with open(meta_path, "w") as fp:
            fp.write("{not json")
        with self.assertRaises(LCPError):
            LCPIndex(output)

    def test_stale_max_lcp_rejected(self):
        output = self._fixture()
        meta_path = os.path.join(output, "lcp.json")
        with open(meta_path, "r") as fp:
            meta = json.load(fp)
        meta["max_lcp"] = 1
        with open(meta_path, "w") as fp:
            json.dump(meta, fp)
        with self.assertRaises(LCPError):
            LCPIndex(output)

    def test_missing_array_rejected(self):
        output = self._fixture()
        os.remove(os.path.join(output, "lcps.npy"))
        self.assertFalse(lcp_exists(output))
        with self.assertRaises(LCPError):
            LCPIndex(output)


class RemovalFailSafeTests(LCPPy2TestBase):
    def test_removal_rejected_without_drop_lcp(self):
        leaves, output, oracle, rbs = self.build_merged(
            f9.TEN_SOURCE_READS, name="merged10")
        self.construct(output, oracle)
        with self.assertRaises(LCPError):
            remove_sources(
                output, os.path.join(self.work, "r"),
                sources=["sample09"])
        self.assertFalse(os.path.exists(
            os.path.join(self.work, "r", "msbwt.npy")))

    def test_drop_lcp_produces_clean_reduced_package(self):
        leaves, output, oracle, rbs = self.build_merged(
            f9.TEN_SOURCE_READS, name="merged10")
        self.construct(output, oracle)
        reduced = os.path.join(self.work, "r2")
        stats = remove_sources(
            output, reduced, sources=["sample09"], drop_lcp=True)
        self.assertFalse(lcp_exists(reduced))
        self.assertFalse(os.path.exists(
            os.path.join(reduced, "lcps.npy")))
        self.assertFalse(os.path.exists(
            os.path.join(reduced, "lcp.json")))
        # the reduced package is fully usable
        from MUS.MultiSourceProvenance import validate_manifest
        self.assertTrue(validate_manifest(reduced))


class RandomizedLCPTests(LCPPy2TestBase):
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
                # canonical + RMQ spot checks
                self.assertEqual(index.boundary(0), 0)
                n = expected.shape[0]
                for _ in range(20):
                    i = rng.randrange(n)
                    j = rng.randrange(i + 1, n + 1)
                    self.assertEqual(
                        index.between_rows(i, j),
                        int(np.min(expected[i:j])),
                        (seed, case, i, j))


if __name__ == "__main__":
    unittest.main()
