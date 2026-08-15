"""Host-side regression tests for enhanced-modern2 Feature 3: query one
constituent inside a multi-merged MSBWT (``MUS.MultiSourceQuery``).

These tests are read-only and run on any CPython 3 with NumPy; they do NOT
require the compiled MUSCython extensions (real-merge integration runs in
the pinned Python-2.7 suite and the Feature-3 validation driver).

Coverage:

- read-derived tiny fixture machinery (explicit terminated-suffix sorting
  and stable suffix merges) with a fully independent standalone-interval
  oracle: ten-source exhaustive projection (>=350 patterns x 10 sources),
  rich query fields, one merged FM search per query, lazy rank loading,
  projection traces, portable packages, '$' patterns;
- independent naive interval-projection oracle (direct bit-array counting
  through ``unpack_interleave``) vs the sampled rank projection for
  synthetic random provenance trees and random intervals (100+ cases,
  seeds 20260811/20260812/20260813), including full-interval leaf-length
  identity and sum-of-sources distributivity;
- rank-cache hardening: round trip, reload, same-length replaced internal
  interleave (stale cache must be ignored), corrupt/truncated cache, wrong
  stride, legacy cache without identity fields;
- edge fixtures: unbalanced chains, duplicate reads, identical reads across
  sources, all-identical reads, N-heavy/nonuniform reads, single-leaf
  packages, ambiguous/unknown source resolution, empty intervals, interval
  bounds errors, sequence-normalization contract, BWT-length mismatch
  rejection;
- evidence-record and validation-driver consistency.
"""

import gc
import hashlib
import itertools
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
sys.path.insert(0, PACKAGE)

from MUS.MultiSourceProvenance import (  # noqa: E402
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

ROWS_FILENAME = "naive_suffix_rows.json"
ALPHABET_CODE = {"$": 0, "A": 1, "C": 2, "G": 3, "N": 4, "T": 5}

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


def pack_little_endian_bits(bits):
    bits = [int(b) for b in bits]
    nbytes = (len(bits) + 7) // 8
    arr = np.zeros(nbytes, dtype=np.uint8)
    for i, bit in enumerate(bits):
        if bit:
            arr[i >> 3] |= np.uint8(1 << (i & 7))
    return arr


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
    with open(os.path.join(directory, ROWS_FILENAME), "w") as fp:
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
    merged_rows, bits = stable_suffix_merge(load_rows(left_dir),
                                            load_rows(right_dir))
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    np.save(os.path.join(output_dir, "msbwt.npy"),
            np.asarray([ALPHABET_CODE[row["bwt"]] for row in merged_rows],
                       dtype=np.uint8))
    np.save(os.path.join(output_dir, "inter0.npy"),
            pack_little_endian_bits(bits))
    save_rows(output_dir, merged_rows)


def make_read_derived_leaf(work, source_name, reads):
    directory = os.path.join(work, source_name)
    os.mkdir(directory)
    rows = terminated_suffix_rows(reads)
    np.save(os.path.join(directory, "msbwt.npy"),
            np.asarray([ALPHABET_CODE[row["bwt"]] for row in rows],
                       dtype=np.uint8))
    save_rows(directory, rows)
    initialize_leaf_provenance(directory, source_id=source_name,
                               source_name=source_name)
    return directory


class NaiveSuffixBWT(object):
    """Independent tiny exact-search oracle over sorted suffix rows."""

    def __init__(self, directory):
        self.rows = load_rows(directory)
        self.suffixes = [row["suffix"] for row in self.rows]
        self.search_calls = 0

    def getTotalSize(self):
        return len(self.rows)

    def findIndicesOfStr(self, seq, givenRange=None):
        self.search_calls += 1
        pattern = seq.decode("ascii") if isinstance(seq, bytes) else str(seq)
        if givenRange is None:
            return self._bisect(pattern), self._bisect(pattern + "\x7f")
        if len(pattern) != 1:
            raise NotImplementedError(
                "naive fixture givenRange supports single symbols only")
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

    def _bisect(self, pattern):
        lo, hi = 0, len(self.suffixes)
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


def node_has_source(node, source_id):
    if node["type"] == "leaf":
        return node["source_id"] == source_id
    return (node_has_source(node["left"], source_id) or
            node_has_source(node["right"], source_id))


def naive_project_interval(merged_dir, manifest, source_id, start, end):
    """Independent interval projection by direct bit-array counting."""
    node = manifest["root"]
    l = int(start)
    r = int(end)
    while node["type"] == "merge":
        bits = unpack_interleave(
            os.path.join(merged_dir, str(node["interleave"])),
            node["length"])
        if node_has_source(node["left"], source_id):
            selected = bits == 0
            node = node["left"]
        else:
            selected = bits == 1
            node = node["right"]
        l = int(np.count_nonzero(selected[:l]))
        r = int(np.count_nonzero(selected[:r]))
    return (l, r)


def build_fixture(work, source_reads, name="merged10"):
    leaves = []
    standalone = {}
    for source_name, reads in source_reads.items():
        leaf = make_read_derived_leaf(work, source_name, reads)
        leaves.append(leaf)
        standalone[source_name] = NaiveSuffixBWT(leaf)
    output = os.path.join(work, name)
    work_dir = os.path.join(work, name + "_work")
    manifest = merge_many_balanced(
        leaves, output, merge_two_func=read_derived_merge,
        work_dir=work_dir, keep_work=True)
    merged = NaiveSuffixBWT(output)
    return output, manifest, merged, standalone, leaves


def all_test_patterns():
    patterns = set()
    for reads in TEN_SOURCE_READS.values():
        for read in reads:
            for start in range(len(read)):
                for length in range(1, min(5, len(read) - start) + 1):
                    patterns.add(read[start:start + length])
    for length in range(1, 5):
        for chars in itertools.product("ACGT", repeat=length):
            patterns.add("".join(chars))
    patterns.update(["N", "NA", "ACN", "NG", "NN", "NNNN"])
    patterns.update(["$", "A$", "T$", "N$", "C$", "G$"])
    return sorted(patterns)


def max_depth(node):
    if node["type"] == "leaf":
        return 0
    return 1 + max(max_depth(node["left"]), max_depth(node["right"]))


def array_sha256_hex(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


class TenSourceQueryHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f3-host-ten-")
        cls.output, cls.manifest, cls.merged, cls.standalone, cls.leaves = (
            build_fixture(cls.work, TEN_SOURCE_READS))
        cls.index = MultiSourceQueryIndex(
            cls.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        cls.wrapped = MultiSourceBWT(cls.merged, cls.index)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_fixture_and_depth(self):
        self.assertEqual(len(self.leaves), 10)
        self.assertEqual(self.index.source_count, 10)
        self.assertLessEqual(max_depth(self.manifest["root"]), 4)

    def test_exhaustive_projection_matches_standalone_intervals(self):
        patterns = all_test_patterns()
        self.assertGreaterEqual(len(patterns), 350)
        comparisons = 0
        for pattern in patterns:
            merged_interval = self.merged.findIndicesOfStr(pattern)
            for source_name, standalone in self.standalone.items():
                expected = standalone.findIndicesOfStr(pattern)
                actual = self.index.project_interval(
                    source_name, merged_interval[0], merged_interval[1])
                self.assertEqual(actual, expected,
                                 (pattern, source_name))
                comparisons += 1
        self.assertGreaterEqual(comparisons, 3500)

    def test_naive_oracle_matches_rank_projection_and_standalone(self):
        for pattern in ("AC", "CGT", "AAAA", "N", "TTTTT", "GGGGG", "$"):
            merged_interval = self.merged.findIndicesOfStr(pattern)
            for source_name in TEN_SOURCE_READS:
                expected = self.standalone[source_name].findIndicesOfStr(
                    pattern)
                projected = self.index.project_interval(
                    source_name, merged_interval[0], merged_interval[1])
                naive = naive_project_interval(
                    self.output, self.manifest, source_name,
                    merged_interval[0], merged_interval[1])
                self.assertEqual(naive, expected)
                self.assertEqual(projected, naive)

    def test_rich_query_fields(self):
        for source_name in TEN_SOURCE_READS:
            for pattern in ("AC", "CGT", "AAAA", "N", "TTTTT", "GGGGG"):
                expected_interval = self.standalone[source_name].findIndicesOfStr(
                    pattern)
                expected_count = expected_interval[1] - expected_interval[0]
                merged_interval = self.merged.findIndicesOfStr(pattern)
                merged_count = merged_interval[1] - merged_interval[0]
                result = self.wrapped.querySource(pattern, source_name)
                self.assertEqual(result["source_id"], source_name)
                self.assertEqual(result["source_interval"], expected_interval)
                self.assertEqual(result["count"], expected_count)
                self.assertEqual(result["present"], expected_count > 0)
                self.assertEqual(result["merged_interval"], merged_interval)
                self.assertEqual(result["merged_count"], merged_count)
                if merged_count:
                    self.assertAlmostEqual(
                        result["fraction_of_merged_occurrences"],
                        expected_count / merged_count, places=12)
                else:
                    self.assertEqual(
                        result["fraction_of_merged_occurrences"], 0.0)

    def test_one_merged_search_per_query(self):
        fresh = MultiSourceBWT(
            self.merged,
            MultiSourceQueryIndex(self.output, mmap=False,
                                  use_saved_rank=False))
        before = self.merged.search_calls
        result = fresh.querySource("ACGT", "sample07")
        self.assertEqual(self.merged.search_calls, before + 1)
        self.assertEqual(
            result["source_interval"],
            self.standalone["sample07"].findIndicesOfStr("ACGT"))

    def test_lazy_rank_loading(self):
        fresh = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        self.assertEqual(fresh.loaded_rank_node_count, 0)
        source = "sample09"
        depth = len(fresh.source_path(source))
        fresh.project_interval(source,
                               *self.merged.findIndicesOfStr("CGT"))
        self.assertEqual(fresh.loaded_rank_node_count, depth)
        self.assertLess(fresh.loaded_rank_node_count, 9)

    def test_rank_cache_round_trip_and_reload(self):
        index = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=2, mmap=False,
            use_saved_rank=False)
        interval = self.merged.findIndicesOfStr("AC")
        expected = index.project_interval("sample04", *interval)
        paths = index.save_loaded_rank_indexes()
        self.assertEqual(len(paths), index.loaded_rank_node_count)
        reloaded = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=2, mmap=False,
            use_saved_rank=True)
        self.assertEqual(
            reloaded.project_interval("sample04", *interval), expected)

    def test_stale_rank_cache_ignored_after_same_length_replacement(self):
        work = tempfile.mkdtemp(prefix="f3-host-stale-")
        try:
            reads = {"s0": ["ACGTAC"], "s1": ["ACGTAC"],
                     "s2": ["ACGTAC"], "s3": ["ACGTAC"]}
            output, manifest, merged, _, _ = build_fixture(
                work, reads, name="equal4")
            index = MultiSourceQueryIndex(
                output, rank_stride_bytes=1, mmap=False,
                use_saved_rank=False)
            probe_patterns = ("A", "C", "G", "T", "AC", "CG", "GT", "AA",
                              "ACGT", "ACGTAC")
            old_proj = {}
            for pattern in probe_patterns:
                interval = merged.findIndicesOfStr(pattern)
                for sid in ("s0", "s3"):
                    old_proj[(pattern, sid)] = (
                        interval,
                        naive_project_interval(
                            output, manifest, sid,
                            interval[0], interval[1]))
            index.project_interval("s0", *merged.findIndicesOfStr("ACGT"))
            self.assertGreater(index.loaded_rank_node_count, 0)
            index.save_loaded_rank_indexes()

            # replace one internal node's interleave with a different valid
            # same-length interleave (seeded shuffle preserves counts) and
            # update the manifest digest (valid but changed package)
            node = manifest["root"]
            inter_path = os.path.join(output, str(node["interleave"]))
            bits = list(unpack_interleave(inter_path, node["length"]))
            rng = random.Random(20260811)
            rng.shuffle(bits)
            replaced = pack_little_endian_bits(bits)
            np.save(inter_path, replaced)
            new_manifest = json.loads(json.dumps(manifest))
            new_manifest["root"]["interleave_sha256"] = array_sha256_hex(
                replaced)
            with open(os.path.join(output, "provenance.json"), "w") as fp:
                json.dump(new_manifest, fp, indent=2, sort_keys=True)
                fp.write("\n")
            load_manifest(output)

            # find a pattern+source where the old and new interleaves give
            # different projections so the staleness test is meaningful
            differing = None
            for pattern, sid in old_proj:
                interval, old = old_proj[(pattern, sid)]
                new = naive_project_interval(
                    output, load_manifest(output), sid,
                    interval[0], interval[1])
                if old != new:
                    differing = (pattern, sid, interval, old, new)
                    break
            self.assertIsNotNone(differing)
            pattern, sid, interval, old, new = differing

            # a reloading index must NOT reuse the stale cache: results must
            # match the new interleave, not the old projections
            reloaded = MultiSourceQueryIndex(
                output, rank_stride_bytes=1, mmap=False,
                use_saved_rank=True)
            got = reloaded.project_interval(sid, *interval)
            self.assertNotEqual(got, old)
            self.assertEqual(got, new)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_corrupt_and_legacy_caches_ignored(self):
        index = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        interval = self.merged.findIndicesOfStr("AC")
        expected = index.project_interval("sample01", *interval)
        index.save_loaded_rank_indexes()
        rank_dir = os.path.join(self.output, "provenance", "ranks")
        full = os.path.join(rank_dir, os.listdir(rank_dir)[0])

        with open(full, "wb") as fp:
            fp.write(b"not a zip")
        reloaded = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=True)
        self.assertEqual(
            reloaded.project_interval("sample01", *interval), expected)

        index2 = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        index2.project_interval("sample01", *interval)
        index2.save_loaded_rank_indexes()
        saved = np.load(full)
        np.savez(full,
                 rank_prefix=saved["rank_prefix"],
                 total_bits=saved["total_bits"],
                 rank_stride_bytes=np.asarray([999], dtype=np.uint64),
                 interleave_sha256=saved["interleave_sha256"],
                 interleave_total_ones=saved["interleave_total_ones"])
        reloaded2 = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=True)
        self.assertEqual(
            reloaded2.project_interval("sample01", *interval), expected)

        index3 = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        index3.project_interval("sample01", *interval)
        index3.save_loaded_rank_indexes()
        saved2 = np.load(full)
        np.savez(full,
                 rank_prefix=saved2["rank_prefix"],
                 total_bits=saved2["total_bits"],
                 rank_stride_bytes=saved2["rank_stride_bytes"])
        reloaded3 = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=True)
        self.assertEqual(
            reloaded3.project_interval("sample01", *interval), expected)

    def test_projection_trace(self):
        interval = self.merged.findIndicesOfStr("ACG")
        source = "sample06"
        projected, trace = self.index.project_interval(
            source, *interval, trace=True)
        self.assertEqual(len(trace), len(self.index.source_path(source)))
        self.assertEqual(trace[0]["before"], interval)
        if trace:
            self.assertEqual(trace[-1]["after"], projected)

    def test_empty_intervals_and_bounds(self):
        total = self.index.total_bits
        # an empty merged interval projects to an empty local interval
        # (equal bounds); only [0,0) is guaranteed to map to (0,0)
        self.assertEqual(self.index.project_interval("sample00", 0, 0),
                         (0, 0))
        for start, end in ((5, 5), (total, total)):
            proj = self.index.project_interval("sample00", start, end)
            self.assertEqual(proj[0], proj[1])
        for args in ((-1, 5), (5, 3), (0, total + 1)):
            with self.assertRaises(IndexError):
                self.index.project_interval("sample00", *args)

    def test_unknown_and_ambiguous_sources(self):
        with self.assertRaises(KeyError):
            self.index.resolve_source("does-not-exist")
        with self.assertRaises(KeyError):
            self.wrapped.querySource("AC", "not-here")

    def test_sequence_normalization(self):
        for seq in ("AC", "GT", "N"):
            b = seq.encode("ascii")
            self.assertEqual(
                self.wrapped.countOccurrencesForSource(seq, "sample00"),
                self.wrapped.countOccurrencesForSource(b, "sample00"))
        for bad in (42, None, ["AC"]):
            with self.assertRaises(TypeError):
                self.wrapped.countOccurrencesForSource(bad, "sample00")
        with self.assertRaises(UnicodeEncodeError):
            self.wrapped.countOccurrencesForSource("\u00e9", "sample00")


class SyntheticTreeDifferentialHostTests(unittest.TestCase):
    """Random provenance trees + random intervals: sampled rank projection
    vs independent direct bit-array projection (100+ cases)."""

    def random_bits_merge(self, rng):
        def merge_two(left_dir, right_dir, output_dir, num_procs=1,
                      logger=None):
            left = np.load(os.path.join(left_dir, "msbwt.npy"))
            right = np.load(os.path.join(right_dir, "msbwt.npy"))
            nl, nr = len(left), len(right)
            bits = [0] * nl + [1] * nr
            rng.shuffle(bits)
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
        return merge_two

    def test_random_tree_projection_differential(self):
        mismatches = []
        comparisons = 0
        for seed in SEEDS:
            rng = random.Random(seed)
            for case in range(40):
                source_count = rng.randint(1, 8)
                work = tempfile.mkdtemp(prefix="f3-host-synth-")
                try:
                    leaves = []
                    lengths = {}
                    for i in range(source_count):
                        length = rng.randint(1, 40)
                        leaf = os.path.join(work, "s%d" % i)
                        os.mkdir(leaf)
                        np.save(os.path.join(leaf, "msbwt.npy"),
                                np.zeros(length, dtype=np.uint8))
                        initialize_leaf_provenance(
                            leaf, source_id="s%d" % i, source_name="s%d" % i)
                        leaves.append(leaf)
                        lengths["s%d" % i] = length
                    output = os.path.join(work, "merged")
                    work_dir = os.path.join(work, "w")
                    manifest = merge_many_balanced(
                        leaves, output,
                        merge_two_func=self.random_bits_merge(rng),
                        work_dir=work_dir, keep_work=True)
                    total = int(manifest["bwt_length"])
                    index = MultiSourceQueryIndex(
                        output, rank_stride_bytes=1, mmap=False,
                        use_saved_rank=False)

                    # full-interval projection must give each leaf's length
                    for sid, length in lengths.items():
                        self.assertEqual(
                            index.project_interval(sid, 0, total),
                            (0, length))
                        comparisons += 1

                    for _ in range(12):
                        start = rng.randint(0, total)
                        end = rng.randint(start, total)
                        for sid in lengths:
                            expected = naive_project_interval(
                                output, manifest, sid, start, end)
                            got = index.project_interval(sid, start, end)
                            comparisons += 1
                            if got != expected:
                                mismatches.append(
                                    (seed, case, sid, start, end, got,
                                     expected, lengths))
                    # distributivity: per-source interval lengths sum to the
                    # merged interval length
                    for _ in range(4):
                        start = rng.randint(0, total)
                        end = rng.randint(start, total)
                        total_len = sum(
                            index.count_interval(sid, start, end)
                            for sid in lengths)
                        comparisons += 1
                        if total_len != end - start:
                            mismatches.append(
                                ("sum", seed, case, start, end, total_len))
                finally:
                    shutil.rmtree(work, ignore_errors=True)
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 1200)


class RandomReadDifferentialHostTests(unittest.TestCase):
    """Deterministic randomized read-derived differential: Feature-3
    projection vs independent standalone suffix-order oracles."""

    def test_random_reads_against_standalone_oracles(self):
        mismatches = []
        comparisons = 0
        for seed in SEEDS:
            rng = random.Random(seed)
            for case in range(10):
                source_count = rng.randint(2, 6)
                source_reads = {}
                for i in range(source_count):
                    read_count = rng.randint(1, 5)
                    reads = []
                    for _ in range(read_count):
                        length = rng.randint(1, 10)
                        chars = []
                        for _ in range(length):
                            chars.append(
                                "N" if rng.random() < 0.15 else
                                "ACGT"[rng.randint(0, 3)])
                        reads.append("".join(chars))
                    source_reads["s%d" % i] = reads
                work = tempfile.mkdtemp(prefix="f3-host-rand-")
                try:
                    output, manifest, merged, standalone, _ = build_fixture(
                        work, source_reads, name="m%d" % case)
                    index = MultiSourceQueryIndex(
                        output, mmap=False, use_saved_rank=False)
                    wrapped = MultiSourceBWT(merged, index)

                    patterns = set(["A", "C", "G", "T", "N", "$", "AA",
                                    "AC", "NN", "A$", "T$"])
                    for reads in source_reads.values():
                        for read in reads:
                            for start in range(len(read)):
                                for end in range(start + 1, len(read) + 1):
                                    patterns.add(read[start:end])
                    for pattern in patterns:
                        merged_interval = merged.findIndicesOfStr(pattern)
                        for sid in source_reads:
                            expected = standalone[sid].findIndicesOfStr(
                                pattern)
                            got = wrapped.findIndicesForSource(pattern, sid)
                            comparisons += 1
                            if got != expected:
                                mismatches.append(
                                    (seed, case, pattern, sid, got, expected,
                                     source_reads))
                            naive = naive_project_interval(
                                output, manifest, sid,
                                merged_interval[0], merged_interval[1])
                            comparisons += 1
                            if naive != expected:
                                mismatches.append(
                                    ("naive", seed, case, pattern, sid, naive,
                                     expected, source_reads))
                finally:
                    shutil.rmtree(work, ignore_errors=True)
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 5000)


class EdgeHostTests(unittest.TestCase):
    def check_all_sources(self, source_reads, tree="balanced", label="edge",
                          queries=None):
        work = tempfile.mkdtemp(prefix="f3-host-edge-")
        try:
            if tree == "chain":
                leaves = []
                standalone = {}
                for name in sorted(source_reads):
                    leaf = make_read_derived_leaf(work, name,
                                                  source_reads[name])
                    leaves.append(leaf)
                    standalone[name] = NaiveSuffixBWT(leaf)
                current = leaves[0]
                for i, leaf in enumerate(leaves[1:], start=1):
                    out = os.path.join(work, "chain-%d" % i)
                    merge_two_with_provenance(
                        current, leaf, out, merge_two_func=read_derived_merge)
                    current = out
                output = current
                manifest = load_manifest(output)
            else:
                output, manifest, _, standalone, _ = build_fixture(
                    work, source_reads, name=label)
            merged = NaiveSuffixBWT(output)
            index = MultiSourceQueryIndex(output, mmap=False,
                                          use_saved_rank=False)
            wrapped = MultiSourceBWT(merged, index)
            if queries is None:
                queries = ["A", "C", "G", "T", "N", "$", "AA", "AC", "CG",
                           "GT", "NN", "AAAA", "AAAAA", "ACGT", "ACGTAC",
                           "A$", "T$", "GGGGG", "TTTTT", "N$"]
            for pattern in queries:
                merged_interval = merged.findIndicesOfStr(pattern)
                for name in source_reads:
                    expected = standalone[name].findIndicesOfStr(pattern)
                    self.assertEqual(
                        wrapped.findIndicesForSource(pattern, name),
                        expected, (label, pattern, name))
                    naive = naive_project_interval(
                        output, manifest, name, merged_interval[0],
                        merged_interval[1])
                    self.assertEqual(naive, expected)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_unbalanced_three_source_chain(self):
        self.check_all_sources(
            {"s0": ["ACGT", "ACGT"], "s1": ["ACGT", "TGCA"],
             "s2": ["GATTACA", "ACGT"]}, tree="chain", label="chain3")

    def test_duplicate_reads_within_sources(self):
        self.check_all_sources(
            {"s0": ["ACGT", "ACGT", "ACGT"], "s1": ["ACGT", "ACGT"],
             "s2": ["TTTT", "ACGT"]})

    def test_identical_reads_across_all_sources(self):
        self.check_all_sources(
            {"s0": ["ACGTAC"], "s1": ["ACGTAC"], "s2": ["ACGTAC"],
             "s3": ["ACGTAC"]})

    def test_all_identical_reads_heavy(self):
        self.check_all_sources(
            {"s0": ["AAA", "AAA"], "s1": ["AAA"],
             "s2": ["AAA", "AAA", "AAA"]})

    def test_n_heavy_and_nonuniform_reads(self):
        self.check_all_sources(
            {"s0": ["N", "NN", "NACGT", "NNNNN", "ACNNT"],
             "s1": ["NACGT", "GGNCC", "TTAACC"],
             "s2": ["NA", "ANG", "NNNA"]})

    def test_single_leaf_package_projection_is_identity(self):
        work = tempfile.mkdtemp(prefix="f3-host-leaf-")
        try:
            leaf = make_read_derived_leaf(work, "solo", ["ACGTAC",
                                                         "GATTACA"])
            index = MultiSourceQueryIndex(leaf, mmap=False)
            self.assertEqual(index.source_count, 1)
            self.assertEqual(index.source_path("solo"), [])
            merged = NaiveSuffixBWT(leaf)
            wrapped = MultiSourceBWT(merged, index)
            for pattern in ("A", "AC", "ACGT", "GATTACA", "TT"):
                self.assertEqual(
                    wrapped.findIndicesForSource(pattern, "solo"),
                    merged.findIndicesOfStr(pattern))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_duplicate_display_names_require_stable_ids(self):
        work = tempfile.mkdtemp(prefix="f3-host-names-")
        try:
            left = make_read_derived_leaf(work, "left", ["ACGT"])
            right = make_read_derived_leaf(work, "right", ["TGCA"])
            for directory in (left, right):
                manifest_path = os.path.join(directory, "provenance.json")
                with open(manifest_path, "r") as fp:
                    manifest = json.load(fp)
                manifest["sources"][0]["name"] = "duplicate-name"
                with open(manifest_path, "w") as fp:
                    json.dump(manifest, fp)
            output = os.path.join(work, "pair")
            merge_many_balanced([left, right], output,
                                merge_two_func=read_derived_merge)
            index = MultiSourceQueryIndex(output, mmap=False)
            with self.assertRaises(MultiSourceQueryError):
                index.resolve_source("duplicate-name")
            with self.assertRaises(KeyError):
                index.resolve_source("does-not-exist")
            self.assertEqual(index.resolve_source("left"), "left")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_bwt_length_mismatch_is_rejected(self):
        work = tempfile.mkdtemp(prefix="f3-host-mismatch-")
        try:
            output, _, merged, _, _ = build_fixture(
                work, {"s0": ["ACGT"], "s1": ["TGCA"]}, name="pair")

            class WrongSize(object):
                def getTotalSize(self):
                    return merged.getTotalSize() + 1

            with self.assertRaises(MultiSourceQueryError):
                MultiSourceBWT(WrongSize(),
                               MultiSourceQueryIndex(output, mmap=False))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_given_range_delegation_with_fake_bwt(self):
        class FakeBWT(object):
            def __init__(self):
                self.calls = []

            def getTotalSize(self):
                return 10

            def findIndicesOfStr(self, seq, givenRange=None):
                self.calls.append((seq, givenRange))
                return (2, 7)

        work = tempfile.mkdtemp(prefix="f3-host-range-")
        try:
            output, manifest, _, _, _ = build_fixture(
                work, {"s0": ["ACGT"], "s1": ["TGCA"]}, name="pair")
            fake = FakeBWT()
            wrapped = MultiSourceBWT(
                fake, MultiSourceQueryIndex(output, mmap=False))
            wrapped.findIndicesForSource(b"AC", "s0")
            wrapped.countOccurrencesForSource(b"AC", "s1",
                                              givenRange=(1, 9))
            self.assertEqual(fake.calls[0], (b"AC", None))
            self.assertEqual(fake.calls[1], (b"AC", (1, 9)))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_portable_package_after_deleting_leaves(self):
        work = tempfile.mkdtemp(prefix="f3-host-portable-")
        try:
            leaves = []
            original_intervals = {}
            for source_name, reads in TEN_SOURCE_READS.items():
                leaf = make_read_derived_leaf(work, source_name, reads)
                leaves.append(leaf)
                oracle = NaiveSuffixBWT(leaf)
                original_intervals[source_name] = {
                    p: oracle.findIndicesOfStr(p)
                    for p in ("A", "AC", "CGT", "N", "GGGG")}
            output = os.path.join(work, "portable10")
            work_dir = os.path.join(work, "work10")
            merge_many_balanced(
                leaves, output, merge_two_func=read_derived_merge,
                work_dir=work_dir, keep_work=True)
            for leaf in leaves:
                shutil.rmtree(leaf)
            shutil.rmtree(work_dir)
            merged = NaiveSuffixBWT(output)
            wrapped = MultiSourceBWT(
                merged,
                MultiSourceQueryIndex(output, mmap=False,
                                      use_saved_rank=False))
            for source_name, expected_by_pattern in (
                    original_intervals.items()):
                for pattern, expected in expected_by_pattern.items():
                    self.assertEqual(
                        wrapped.findIndicesForSource(pattern, source_name),
                        expected)
        finally:
            shutil.rmtree(work, ignore_errors=True)


class EvidenceRecordHostTests(unittest.TestCase):
    EVIDENCE = os.path.join(PACKAGE, "evidence",
                            "feature3-query-one-constituent.json")
    EVIDENCE_GENERATOR = os.path.join(
        PACKAGE, "validate", "feature3_query_one_constituent_evidence.py")

    def test_evidence_record_consistent(self):
        evidence = json.load(open(self.EVIDENCE, encoding="utf-8"))
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "enhanced-modern2")
        self.assertEqual(
            evidence["final"]["milestone"],
            "enhanced-modern2-feature3-query-one-constituent")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")

    def test_evidence_oracle_and_mismatch_contract(self):
        report = json.load(open(self.EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["mismatch_count"], 0)
        ten = report["ten_source_fixture"]
        self.assertGreaterEqual(ten["patterns"], 350)
        self.assertGreaterEqual(ten["interval_comparisons"], 3500)
        self.assertGreaterEqual(report["real_queries"], 100)
        self.assertEqual(report["seed"], 20260811)
        self.assertIn("naive_project_interval", report["oracles"])
        self.assertIn("standalone_bwt", report["oracles"])

    def test_evidence_cache_hardening(self):
        report = json.load(open(self.EVIDENCE, encoding="utf-8"))["evidence"]
        probes = report["cache_hardening_probes"]
        for probe, detected in probes.items():
            self.assertTrue(detected, probe)

    def test_evidence_performance_sanity(self):
        report = json.load(open(self.EVIDENCE, encoding="utf-8"))["evidence"]
        perf = report["performance"]
        self.assertGreater(perf["projection_steps_total"], 0)
        self.assertGreater(perf["rank_nodes_touched"], 0)

    def test_evidence_generator_is_python2_and_driver_checks(self):
        text = open(self.EVIDENCE_GENERATOR, encoding="utf-8").read()
        self.assertIn("from __future__ import print_function", text)
        self.assertNotIn("f'{", text)
        self.assertNotIn("pathlib", text)
        self.assertIn("def run_evidence", text)
        driver = open(os.path.join(PACKAGE, "validate",
                                   "feature3-query-one-constituent.sh"),
                      encoding="utf-8").read()
        self.assertIn("--evidence", driver)
        self.assertIn("run_evidence", driver)


if __name__ == "__main__":
    unittest.main()
