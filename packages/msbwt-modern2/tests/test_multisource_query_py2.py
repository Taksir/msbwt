"""msbwt-modern2 enhanced Feature 3 tests: query one constituent inside a
multi-merged MSBWT (``MUS.MultiSourceQuery``), runnable inside the pinned
Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO.

Coverage:

- read-derived tiny fixture machinery (explicit terminated-suffix sorting +
  stable suffix merges with Holt's 0=left/1=right interleave convention)
  giving a fully independent interval oracle per source;
- TEN-source balanced package: >=350 patterns x 10 sources with EXACT
  standalone interval identity, counts, rich query fields, projection
  traces, one merged FM search per query, lazy rank-node loading, portable
  package after deleting leaves/intermediates;
- independent naive interval-projection oracle (direct bit-array counting
  through ``unpack_interleave``) agreeing with the sampled rank projection
  and with standalone intervals;
- rank-cache hardening: round trip, reload, same-length replaced internal
  interleave (stale cache must be ignored and rebuilt), corrupt/truncated
  cache, wrong stride, legacy cache without identity fields;
- edge fixtures: unbalanced 3-source chain, duplicate reads, identical reads
  across sources, all-identical reads, N-heavy reads, nonuniform read
  lengths, single-leaf (no merge), '$' patterns, ambiguous/unknown source
  resolution, empty intervals, interval bounds errors, sequence
  normalization;
- REAL modern2 integration: canonical uniform-a + uniform-b merge (every
  committed query per source), real 5-source balanced merge, real 4-source
  unbalanced chain merge, ``givenRange`` legacy delegation, one-search
  instrumentation on the real BWT, deterministic randomized differential
  subset (seed 20260811).

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import itertools
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

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")
SEED = f1.SEED

ROWS_FILENAME = "naive_suffix_rows.json"
ALPHABET_CODE = {"$": 0, "A": 1, "C": 2, "G": 3, "N": 4, "T": 5}

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


def _terminated_suffix_rows(reads):
    rows = []
    for read_id, read in enumerate(reads):
        text = read + "$"
        for pos in range(len(text)):
            suffix = text[pos:]
            preceding = text[pos - 1] if pos > 0 else "$"
            rows.append({
                "suffix": suffix,
                "bwt": preceding,
                "read_id": read_id,
                "pos": pos,
            })
    # deterministic tie order within a source; stable merges preserve it
    rows.sort(key=lambda row: (row["suffix"], row["read_id"], row["pos"]))
    return rows


def _save_rows(directory, rows):
    path = os.path.join(directory, ROWS_FILENAME)
    with open(path, "w") as fp:
        json.dump(rows, fp, separators=(",", ":"))


def _load_rows(directory):
    with open(os.path.join(directory, ROWS_FILENAME), "r") as fp:
        return json.load(fp)


def make_read_derived_leaf(work, source_name, reads):
    directory = os.path.join(work, source_name)
    os.mkdir(directory)
    rows = _terminated_suffix_rows(reads)
    bwt = np.asarray(
        [ALPHABET_CODE[row["bwt"]] for row in rows], dtype=np.uint8)
    np.save(os.path.join(directory, "msbwt.npy"), bwt)
    _save_rows(directory, rows)
    initialize_leaf_provenance(
        directory, source_id=source_name, source_name=source_name)
    return directory


def stable_suffix_merge(left_rows, right_rows):
    """Stable merge of sorted suffix orders; ties select left first."""
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
    left_rows = _load_rows(left_dir)
    right_rows = _load_rows(right_dir)
    merged_rows, bits = stable_suffix_merge(left_rows, right_rows)

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    bwt = np.asarray(
        [ALPHABET_CODE[row["bwt"]] for row in merged_rows], dtype=np.uint8)
    np.save(os.path.join(output_dir, "msbwt.npy"), bwt)
    np.save(os.path.join(output_dir, "inter0.npy"),
            f1.pack_little_endian_bits(bits))
    _save_rows(output_dir, merged_rows)


class NaiveSuffixBWT(object):
    """Independent tiny exact-search oracle over sorted suffix rows."""

    def __init__(self, directory):
        self.rows = _load_rows(directory)
        self.suffixes = [row["suffix"] for row in self.rows]
        self.search_calls = 0

    def getTotalSize(self):
        return len(self.rows)

    def findIndicesOfStr(self, seq, givenRange=None):
        self.search_calls += 1
        if isinstance(seq, bytes):
            pattern = seq.decode("ascii")
        else:
            pattern = str(seq)
        if givenRange is None:
            low = self._bisect_left(pattern)
            # All observed suffix characters (DNA/N/$) are ASCII < 0x7F, so
            # any continuation of the pattern sorts below pattern + DEL on
            # both Python 2 and Python 3.
            high = self._bisect_left(pattern + "\x7f")
            return low, high
        return self._backward_step(pattern, givenRange)

    def _backward_step(self, symbol, given_range):
        """FM backward step: interval(cP) = [C(c) + rank_c(l),
        C(c) + rank_c(h)) where ``given_range = [l, h)`` is the interval
        of P.  Computed with plain counting over the naive rows (single-
        symbol extension only, like the real BasicBWT usage in the
        extension API)."""
        if len(symbol) != 1:
            raise NotImplementedError(
                "naive fixture givenRange supports single symbols only")
        low, high = given_range
        # C(c) = number of rows whose first character sorts below c
        c_first = 0
        rank_l = 0
        rank_h = 0
        for index, row in enumerate(self.rows):
            first = row["suffix"][0]
            if first < symbol:
                c_first += 1
            if index < low and row["bwt"] == symbol:
                rank_l += 1
            if index < high and row["bwt"] == symbol:
                rank_h += 1
        return (c_first + rank_l, c_first + rank_h)

    def _bisect_left(self, pattern):
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


def node_has_source(node, source_id):
    if node["type"] == "leaf":
        return node["source_id"] == source_id
    return node_has_source(node["left"], source_id) or node_has_source(
        node["right"], source_id)


def naive_project_interval(merged_dir, manifest, source_id, start, end):
    """Independent interval projection by direct bit-array counting.

    Walks the provenance tree with ``unpack_interleave`` (Feature 2's
    verified unpacker) and counts selected rows with plain NumPy prefix
    sums.  This shares no code with the sampled rank-index machinery.
    """
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
    if node["source_id"] != source_id:
        raise ValueError("source traversal ended at wrong leaf")
    return (l, r)


def max_depth(node):
    if node["type"] == "leaf":
        return 0
    return 1 + max(max_depth(node["left"]), max_depth(node["right"]))


def _array_sha256_hex(array):
    import hashlib
    return hashlib.sha256(
        np.ascontiguousarray(array).tobytes()).hexdigest()


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


def build_merged_fixture(work, source_reads, name="merged10",
                         merge_two_func=read_derived_merge):
    leaves = []
    standalone = {}
    for source_name, reads in source_reads.items():
        leaf = make_read_derived_leaf(work, source_name, reads)
        leaves.append(leaf)
        standalone[source_name] = NaiveSuffixBWT(leaf)

    output = os.path.join(work, name)
    work_dir = os.path.join(work, name + "_work")
    manifest = merge_many_balanced(
        leaves, output, merge_two_func=merge_two_func,
        work_dir=work_dir, keep_work=True)
    merged = NaiveSuffixBWT(output)
    return output, manifest, merged, standalone, leaves


# ---------------------------------------------------------------------------
# ten-source read-derived fixture tests
# ---------------------------------------------------------------------------


class TenSourceQueryTests(unittest.TestCase):
    """The main Point-3 suite: 10 independent tiny read-derived BWTs."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f3-py2-ten-")
        cls.output, cls.manifest, cls.merged, cls.standalone, cls.leaves = (
            build_merged_fixture(cls.work, TEN_SOURCE_READS))
        cls.index = MultiSourceQueryIndex(
            cls.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        cls.wrapped = MultiSourceBWT(cls.merged, cls.index)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_fixture_really_contains_ten_independent_sources(self):
        self.assertEqual(len(self.leaves), 10)
        self.assertEqual(len(self.manifest["sources"]), 10)
        self.assertEqual(self.index.source_count, 10)
        self.assertEqual(
            [src["id"] for src in self.manifest["sources"]],
            list(TEN_SOURCE_READS))
        self.assertLessEqual(max_depth(self.manifest["root"]), 4)

    def test_every_source_path_ends_in_correct_leaf_and_is_logarithmic(self):
        for sid in TEN_SOURCE_READS:
            path = self.index.source_path(sid)
            self.assertLessEqual(len(path), 4)
            self.assertTrue(all(branch in (0, 1) for _, branch in path))

    def test_projection_matches_all_ten_standalone_intervals(self):
        """Main Point-3 invariant: >=350 patterns x 10 sources with exact
        interval identity against independent standalone suffix orders."""
        patterns = all_test_patterns()
        self.assertGreaterEqual(len(patterns), 350)

        comparisons = 0
        for pattern in patterns:
            merged_interval = self.merged.findIndicesOfStr(pattern)
            for source_name, standalone in self.standalone.items():
                expected = standalone.findIndicesOfStr(pattern)
                actual = self.index.project_interval(
                    source_name, merged_interval[0], merged_interval[1])
                self.assertEqual(
                    actual, expected,
                    (pattern, source_name, merged_interval, expected,
                     actual))
                comparisons += 1
        self.assertGreaterEqual(comparisons, 3500)

    def test_naive_oracle_agrees_with_rank_projection(self):
        """The direct bit-array oracle must equal the sampled rank index and
        the standalone interval for a representative pattern set."""
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

    def test_rich_query_returns_exact_count_presence_fraction_intervals(self):
        for source_name in TEN_SOURCE_READS:
            for pattern in ("AC", "CGT", "AAAA", "N", "TTTTT", "GGGGG"):
                expected_interval = self.standalone[source_name].findIndicesOfStr(
                    pattern)
                expected_count = expected_interval[1] - expected_interval[0]
                merged_interval = self.merged.findIndicesOfStr(pattern)
                merged_count = merged_interval[1] - merged_interval[0]

                result = self.wrapped.querySource(pattern, source_name)

                self.assertEqual(result["source_id"], source_name)
                self.assertEqual(result["source_name"], source_name)
                self.assertEqual(result["source_interval"], expected_interval)
                self.assertEqual(result["count"], expected_count)
                self.assertEqual(result["present"], expected_count > 0)
                self.assertEqual(result["merged_interval"], merged_interval)
                self.assertEqual(result["merged_count"], merged_count)
                self.assertLessEqual(result["path_depth"], 4)
                if merged_count:
                    self.assertAlmostEqual(
                        result["fraction_of_merged_occurrences"],
                        float(expected_count) / merged_count, places=12)
                else:
                    self.assertEqual(
                        result["fraction_of_merged_occurrences"], 0.0)

    def test_one_constituent_query_searches_merged_bwt_only_once(self):
        fresh = MultiSourceBWT(
            self.merged,
            MultiSourceQueryIndex(self.output, mmap=False,
                                  use_saved_rank=False))
        before = self.merged.search_calls
        result = fresh.querySource("ACGT", "sample07")
        self.assertEqual(self.merged.search_calls, before + 1)
        expected = self.standalone["sample07"].findIndicesOfStr("ACGT")
        self.assertEqual(result["source_interval"], expected)

    def test_lazy_rank_nodes_loaded_only_along_query_path(self):
        fresh = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        self.assertEqual(fresh.loaded_rank_node_count, 0)

        source = "sample09"
        depth = len(fresh.source_path(source))
        merged_interval = self.merged.findIndicesOfStr("CGT")
        fresh.project_interval(source, *merged_interval)

        self.assertEqual(fresh.loaded_rank_node_count, depth)
        self.assertLessEqual(fresh.loaded_rank_node_count, 4)
        self.assertLess(fresh.loaded_rank_node_count, 9)

    def test_rank_cache_round_trip_for_only_touched_nodes(self):
        index = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=2, mmap=False,
            use_saved_rank=False)

        interval = self.merged.findIndicesOfStr("AC")
        expected = index.project_interval("sample04", *interval)
        touched = index.loaded_rank_node_count
        paths = index.save_loaded_rank_indexes()

        self.assertEqual(len(paths), touched)
        self.assertLessEqual(touched, 4)
        for path in paths:
            self.assertTrue(os.path.exists(path))

        reloaded = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=2, mmap=False,
            use_saved_rank=True)
        self.assertEqual(
            reloaded.project_interval("sample04", *interval), expected)

    def test_same_length_replaced_interleave_ignores_stale_rank_cache(self):
        """Candidate-defect hardening: a rank cache saved for node X must
        never be used after X's interleave content is replaced at the same
        length.  Only the content-digest identity can catch this (a
        same-length, same-child-count replacement stays valid for the
        manifest)."""
        work = tempfile.mkdtemp(prefix="f3-py2-stale-")
        try:
            # every leaf has the same row count, so complementing any node's
            # interleave preserves the zero/one counts (children are equal)
            reads = {"s0": ["ACGTAC"], "s1": ["ACGTAC"],
                     "s2": ["ACGTAC"], "s3": ["ACGTAC"]}
            output, manifest, merged, _, _ = build_merged_fixture(
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
            # touch the sampled rank machinery so caches exist to save
            index.project_interval("s0", *merged.findIndicesOfStr("ACGT"))
            self.assertGreater(index.loaded_rank_node_count, 0)
            index.save_loaded_rank_indexes()

            # replace one internal node's interleave with a different valid
            # same-length interleave (seeded shuffle preserves the zero/one
            # counts) and update the manifest digest (a valid but changed
            # authoritative package)
            node = manifest["root"]
            self.assertEqual(node["type"], "merge")
            inter_path = os.path.join(output, str(node["interleave"]))
            bits = list(unpack_interleave(inter_path, node["length"]))
            rng = random.Random(20260811)
            rng.shuffle(bits)
            replaced = f1.pack_little_endian_bits(bits)
            np.save(inter_path, replaced)
            new_manifest = json.loads(json.dumps(manifest))
            new_manifest["root"]["interleave_sha256"] = _array_sha256_hex(
                replaced)
            with open(os.path.join(output, "provenance.json"), "w") as fp:
                json.dump(new_manifest, fp, indent=2, sort_keys=True)
                fp.write("\n")

            # the authoritative package is now valid under Feature-2 checks
            load_manifest(output)

            # find a pattern+source where the old and new interleaves give
            # different projections so the staleness test is meaningful
            differing = None
            for pattern, sid in old_proj:
                interval, old = old_proj[(pattern, sid)]
                new = naive_project_interval(
                    output, new_manifest, sid, interval[0], interval[1])
                if old != new:
                    differing = (pattern, sid, interval, old, new)
                    break
            self.assertIsNotNone(differing)
            pattern, sid, interval, old, new = differing

            # a reloading index with use_saved_rank=True must NOT reuse the
            # stale cache: results must match the new interleave, not the
            # old projections
            reloaded = MultiSourceQueryIndex(
                output, rank_stride_bytes=1, mmap=False,
                use_saved_rank=True)
            got = reloaded.project_interval(sid, *interval)
            self.assertNotEqual(got, old)
            self.assertEqual(got, new)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_corrupt_and_legacy_rank_caches_are_ignored_and_rebuilt(self):
        index = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        interval = self.merged.findIndicesOfStr("AC")
        expected = index.project_interval("sample01", *interval)
        index.save_loaded_rank_indexes()
        rank_dir = os.path.join(self.output, "provenance", "ranks")
        cache_path = os.listdir(rank_dir)[0]
        full = os.path.join(rank_dir, cache_path)

        # corrupt content
        with open(full, "wb") as fp:
            fp.write(b"not a zip")
        reloaded = MultiSourceQueryIndex(
            self.output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=True)
        self.assertEqual(
            reloaded.project_interval("sample01", *interval), expected)

        # wrong stride must be rejected
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

        # legacy cache without identity fields must be ignored
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

    def test_query_works_after_original_and_intermediate_sources_deleted(self):
        work2 = tempfile.mkdtemp(prefix="f3-py2-portable-")
        try:
            leaves = []
            original_intervals = {}
            for source_name, reads in TEN_SOURCE_READS.items():
                leaf = make_read_derived_leaf(work2, source_name, reads)
                leaves.append(leaf)
                oracle = NaiveSuffixBWT(leaf)
                original_intervals[source_name] = {
                    p: oracle.findIndicesOfStr(p)
                    for p in ("A", "AC", "CGT", "N", "GGGG")}
            output = os.path.join(work2, "portable10")
            work_dir = os.path.join(work2, "work10")
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
            shutil.rmtree(work2, ignore_errors=True)

    def test_projection_trace_has_one_step_per_tree_edge(self):
        interval = self.merged.findIndicesOfStr("ACG")
        source = "sample06"
        projected, trace = self.index.project_interval(
            source, *interval, trace=True)
        self.assertEqual(len(trace), len(self.index.source_path(source)))
        self.assertEqual(trace[0]["before"], interval)
        if trace:
            self.assertEqual(trace[-1]["after"], projected)

    def test_empty_interval_projections_are_exact(self):
        # an empty merged interval projects to an empty local interval
        # (equal bounds); only [0,0) is guaranteed to map to (0,0)
        self.assertEqual(
            self.index.project_interval("sample00", 0, 0), (0, 0))
        for start, end in ((5, 5), (self.index.total_bits,
                                    self.index.total_bits)):
            for sid in ("sample00", "sample07"):
                proj = self.index.project_interval(sid, start, end)
                self.assertEqual(proj[0], proj[1])

    def test_interval_bounds_errors(self):
        for args in ((-1, 5), (5, 3), (0, self.index.total_bits + 1)):
            with self.assertRaises(IndexError):
                self.index.project_interval("sample00", *args)

    def test_unknown_and_ambiguous_source_errors(self):
        with self.assertRaises(KeyError):
            self.index.resolve_source("does-not-exist")
        with self.assertRaises(KeyError):
            self.wrapped.querySource("AC", "not-here")


class NameResolutionPy2Tests(unittest.TestCase):
    def test_duplicate_display_names_require_stable_ids(self):
        work = tempfile.mkdtemp(prefix="f3-py2-names-")
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
            self.assertEqual(index.resolve_source("right"), "right")
        finally:
            shutil.rmtree(work, ignore_errors=True)


class EdgeFixtureQueryTests(unittest.TestCase):
    """Unbalanced trees, duplicates, identical reads, nonuniform, N-heavy,
    single-leaf packages, '$' patterns."""

    def check_all_sources(self, source_reads, tree="balanced", label="edge",
                          queries=None):
        work = tempfile.mkdtemp(prefix="f3-py2-edge-")
        try:
            if tree == "chain":
                # build leaves then merge sequentially (unbalanced)
                leaves = []
                standalone = {}
                for name in sorted(source_reads):
                    leaf = make_read_derived_leaf(work, name, source_reads[name])
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
                output, manifest, _, standalone, _ = build_merged_fixture(
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
                    actual = wrapped.findIndicesForSource(pattern, name)
                    self.assertEqual(
                        actual, expected,
                        (label, pattern, name, expected, actual))
                    naive = naive_project_interval(
                        output, manifest, name, merged_interval[0],
                        merged_interval[1])
                    self.assertEqual(naive, expected)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_unbalanced_three_source_chain(self):
        self.check_all_sources(
            {"s0": ["ACGT", "ACGT"], "s1": ["ACGT", "TGCA"],
             "s2": ["GATTACA", "ACGT"]},
            tree="chain", label="chain3")

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
            {"s0": ["AAA", "AAA"], "s1": ["AAA"], "s2": ["AAA", "AAA", "AAA"]})

    def test_n_heavy_and_nonuniform_reads(self):
        self.check_all_sources(
            {"s0": ["N", "NN", "NACGT", "NNNNN", "ACNNT"],
             "s1": ["NACGT", "GGNCC", "TTAACC"],
             "s2": ["NA", "ANG", "NNNA"]})

    def test_single_leaf_package_projection_is_identity(self):
        work = tempfile.mkdtemp(prefix="f3-py2-leaf-")
        try:
            leaf = make_read_derived_leaf(work, "solo", ["ACGTAC", "GATTACA"])
            index = MultiSourceQueryIndex(leaf, mmap=False)
            self.assertEqual(index.source_count, 1)
            self.assertEqual(index.source_path("solo"), [])
            merged = NaiveSuffixBWT(leaf)
            wrapped = MultiSourceBWT(merged, index)
            for pattern in ("A", "AC", "ACGT", "GATTACA", "TT", "Z"):
                expected = merged.findIndicesOfStr(pattern)
                self.assertEqual(
                    wrapped.findIndicesForSource(pattern, "solo"), expected)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_bwt_length_mismatch_is_rejected(self):
        work = tempfile.mkdtemp(prefix="f3-py2-mismatch-")
        try:
            output, _, merged, _, _ = build_merged_fixture(
                work, {"s0": ["ACGT"], "s1": ["TGCA"]}, name="pair")
            # construct a fake BWT object with a different size
            class WrongSize(object):
                def getTotalSize(self):
                    return merged.getTotalSize() + 1
            with self.assertRaises(MultiSourceQueryError):
                MultiSourceBWT(WrongSize(), MultiSourceQueryIndex(
                    output, mmap=False))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_sequence_normalization_contract(self):
        work = tempfile.mkdtemp(prefix="f3-py2-norm-")
        try:
            output, _, merged, _, _ = build_merged_fixture(
                work, {"s0": ["ACGT"], "s1": ["TGCA"]}, name="pair")
            wrapped = MultiSourceBWT(
                merged, MultiSourceQueryIndex(output, mmap=False))
            for seq in ("AC", "GT", "N"):
                b = seq.encode("ascii")
                u = unicode(seq) if sys.version_info[0] == 2 else seq
                self.assertEqual(
                    wrapped.countOccurrencesForSource(seq, "s0"),
                    wrapped.countOccurrencesForSource(b, "s0"))
                self.assertEqual(
                    wrapped.countOccurrencesForSource(seq, "s0"),
                    wrapped.countOccurrencesForSource(u, "s0"))
            for bad in (42, None, ["AC"]):
                with self.assertRaises(TypeError):
                    wrapped.countOccurrencesForSource(bad, "s0")
        finally:
            shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# REAL modern2 integration (pp + cfpp + GenericMerge through the CLI)
# ---------------------------------------------------------------------------


class RealIntegrationQueryPy2Tests(unittest.TestCase):
    """Level-3 tests: real construction and real GenericMerge merges."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f3-py2-real-")
        cls.harness = f1.SourceHarness(cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def load_standalone(self, path):
        return f1.load_standalone(path)

    def test_canonical_two_source_real_merge_every_query(self):
        a_dir = self.harness.build_fixture_source("f3a", "uniform-a.fastq")
        b_dir = self.harness.build_fixture_source("f3b", "uniform-b.fastq")
        initialize_leaf_provenance(a_dir, source_id="in_a", source_name="in_a")
        initialize_leaf_provenance(b_dir, source_id="in_b", source_name="in_b")
        m_dir = os.path.join(self.work, "f3m")
        merge_two_with_provenance(
            a_dir, b_dir, m_dir, merge_two_func=holt_merge_two_local,
            num_procs=1)

        a_bwt = self.load_standalone(a_dir)
        b_bwt = self.load_standalone(b_dir)
        merged = MultiSourceBWT.load(m_dir, mmap=False)

        queries = f1.build_queries(f1.CANONICAL_READS_A,
                                   f1.CANONICAL_READS_B)
        queries.extend([b"$", b"A$", b"T$", b"ACGTN$"])
        mismatches = []
        comparisons = 0
        for query in queries:
            expected_a = int(a_bwt.countOccurrencesOfSeq(query))
            expected_b = int(b_bwt.countOccurrencesOfSeq(query))
            legacy = int(merged.bwt.countOccurrencesOfSeq(query))
            interval_a = tuple(int(v) for v in a_bwt.findIndicesOfStr(query))
            interval_b = tuple(int(v) for v in b_bwt.findIndicesOfStr(query))

            got_a = merged.countOccurrencesForSource(query, "in_a")
            got_b = merged.countOccurrencesForSource(query, "in_b")
            proj_a = merged.findIndicesForSource(query, "in_a")
            proj_b = merged.findIndicesForSource(query, "in_b")
            comparisons += 4
            if (got_a, got_b) != (expected_a, expected_b):
                mismatches.append((query, got_a, got_b, expected_a,
                                   expected_b))
            if proj_a != interval_a or proj_b != interval_b:
                mismatches.append(("interval", query, proj_a, proj_b,
                                   interval_a, interval_b))
            if got_a + got_b != legacy:
                mismatches.append(("sum", query, got_a + got_b, legacy))
        self.assertEqual(mismatches, [])
        self.assertGreater(comparisons, 200)
        self.assertGreaterEqual(len(queries), 60)

        # committed merged totals from Feature 1 must also hold
        for query, expected_total in f1.COMMITTED_QUERIES.items():
            self.assertEqual(
                merged.bwt.countOccurrencesOfSeq(query), expected_total)

    def test_five_source_balanced_real_merge(self):
        rng = random.Random(SEED + 7)
        leaves = []
        standalone = {}
        for i in range(5):
            reads = f1.make_random_case(rng)[0]
            leaf = self.harness.build_fastq_source("f3s%d" % i, reads)
            initialize_leaf_provenance(leaf, source_id="src%d" % i,
                                       source_name="src%d" % i)
            leaves.append(leaf)
            standalone["src%d" % i] = self.load_standalone(leaf)
        output = os.path.join(self.work, "f3five")
        manifest = merge_many_balanced(
            leaves, output, merge_two_func=holt_merge_two_local,
            num_procs=1)
        self.assertLessEqual(max_depth(manifest["root"]), 3)

        merged = MultiSourceBWT.load(output, mmap=False)
        queries = ["A", "C", "G", "T", "N", "AC", "GT", "NA", "NN",
                   "AAA", "ACGT", "TTA", "CGTAC", "$"]
        mismatches = []
        for query in queries:
            for sid in ("src%d" % i for i in range(5)):
                expected = int(standalone[sid].countOccurrencesOfSeq(query))
                got = merged.countOccurrencesForSource(query, sid)
                if got != expected:
                    mismatches.append((query, sid, got, expected))
                expected_interval = tuple(
                    int(v) for v in standalone[sid].findIndicesOfStr(query))
                proj = merged.findIndicesForSource(query, sid)
                if proj != expected_interval:
                    mismatches.append(("interval", query, sid, proj,
                                       expected_interval))
        self.assertEqual(mismatches, [])

    def test_four_source_unbalanced_real_chain(self):
        rng = random.Random(SEED + 8)
        leaves = []
        standalone = {}
        for i in range(4):
            reads = f1.make_random_case(rng)[0]
            leaf = self.harness.build_fastq_source("f3c%d" % i, reads)
            initialize_leaf_provenance(leaf, source_id="c%d" % i,
                                       source_name="c%d" % i)
            leaves.append(leaf)
            standalone["c%d" % i] = self.load_standalone(leaf)

        current = leaves[0]
        for i, leaf in enumerate(leaves[1:], start=1):
            out = os.path.join(self.work, "f3chain-%d" % i)
            merge_two_with_provenance(current, leaf, out,
                                      merge_two_func=holt_merge_two_local,
                                      num_procs=1)
            current = out

        merged = MultiSourceBWT.load(current, mmap=False)
        queries = ["A", "T", "N", "AC", "GT", "NN", "ACGT", "$", "NA",
                   "TAC"]
        mismatches = []
        for query in queries:
            for sid in ("c%d" % i for i in range(4)):
                expected = int(standalone[sid].countOccurrencesOfSeq(query))
                got = merged.countOccurrencesForSource(query, sid)
                if got != expected:
                    mismatches.append((query, sid, got, expected))
        self.assertEqual(mismatches, [])

    def test_given_range_delegation_real(self):
        a_dir = self.harness.build_fixture_source("f3gr-a", "uniform-a.fastq")
        b_dir = self.harness.build_fixture_source("f3gr-b", "uniform-b.fastq")
        initialize_leaf_provenance(a_dir, source_id="in_a",
                                   source_name="in_a")
        initialize_leaf_provenance(b_dir, source_id="in_b",
                                   source_name="in_b")
        m_dir = os.path.join(self.work, "f3gr-m")
        merge_two_with_provenance(
            a_dir, b_dir, m_dir, merge_two_func=holt_merge_two_local,
            num_procs=1)
        a_bwt = self.load_standalone(a_dir)
        merged = MultiSourceBWT.load(m_dir, mmap=False)

        t_interval = tuple(int(v) for v in merged.bwt.findIndicesOfStr(b"T"))
        direct = tuple(int(v) for v in merged.bwt.findIndicesOfStr(b"GT"))
        via_range = merged.findIndicesForSource(
            b"G", "in_a", givenRange=t_interval)
        self.assertEqual(
            via_range,
            tuple(int(v) for v in a_bwt.findIndicesOfStr(b"GT")))
        self.assertEqual(
            merged.findIndicesOfStr(b"G", givenRange=t_interval), direct)
        # full-range givenRange is equivalent to a full search
        full = merged.findIndicesForSource(b"GT", "in_a")
        ranged = merged.findIndicesForSource(b"GT", "in_a",
                                             givenRange=(0, 48))
        self.assertEqual(full, ranged)

    def test_one_merged_search_per_query_on_real_bwt(self):
        a_dir = self.harness.build_fixture_source("f3os-a", "uniform-a.fastq")
        b_dir = self.harness.build_fixture_source("f3os-b", "uniform-b.fastq")
        initialize_leaf_provenance(a_dir, source_id="in_a",
                                   source_name="in_a")
        initialize_leaf_provenance(b_dir, source_id="in_b",
                                   source_name="in_b")
        m_dir = os.path.join(self.work, "f3os-m")
        merge_two_with_provenance(
            a_dir, b_dir, m_dir, merge_two_func=holt_merge_two_local,
            num_procs=1)
        real = MultiSourceBWT.load(m_dir, mmap=False)
        proxy = f1.CountingProxy(real.bwt)
        wrapped = MultiSourceBWT(
            proxy,
            MultiSourceQueryIndex(m_dir, mmap=False))
        for query in (b"ACGTN", b"A", b"$", b"TTTTT"):
            wrapped.countOccurrencesForSource(query, "in_a")
            wrapped.querySource(query, "in_b")
        self.assertEqual(proxy.search_calls, 8)

    def test_randomized_real_differential_subset(self):
        """Deterministic randomized Level-3 differential (seed 20260811)."""
        rng = random.Random(SEED)
        mismatches = []
        comparisons = 0
        for case_index in range(6):
            source_count = rng.randint(2, 4)
            leaves = []
            standalone = {}
            reads_by_source = {}
            for i in range(source_count):
                reads = f1.make_random_case(rng)[0]
                reads_by_source["r%d" % i] = reads
                leaf = self.harness.build_fastq_source(
                    "f3rd%d-%d" % (case_index, i), reads)
                initialize_leaf_provenance(leaf, source_id="r%d" % i,
                                           source_name="r%d" % i)
                leaves.append(leaf)
                standalone["r%d" % i] = self.load_standalone(leaf)
            output = os.path.join(self.work, "f3rd%d" % case_index)
            manifest = merge_many_balanced(
                leaves, output, merge_two_func=holt_merge_two_local,
                num_procs=1)
            merged = MultiSourceBWT.load(output, mmap=False)
            queries = []
            for reads in reads_by_source.values():
                queries.extend(f1.build_queries(reads, reads))
            queries = sorted(set(queries))
            for query in queries:
                merged_interval = tuple(
                    int(v) for v in merged.bwt.findIndicesOfStr(query))
                for sid in reads_by_source:
                    expected = int(standalone[sid].countOccurrencesOfSeq(
                        query))
                    got = merged.countOccurrencesForSource(query, sid)
                    comparisons += 1
                    if got != expected:
                        mismatches.append({
                            "case": case_index, "query": query, "sid": sid,
                            "got": got, "expected": expected,
                            "reads_by_source": reads_by_source})
                    expected_interval = tuple(
                        int(v) for v in standalone[sid].findIndicesOfStr(
                            query))
                    proj = merged.findIndicesForSource(query, sid)
                    naive = naive_project_interval(
                        output, manifest, sid, merged_interval[0],
                        merged_interval[1])
                    comparisons += 2
                    if proj != expected_interval:
                        mismatches.append({
                            "case": case_index, "query": query, "sid": sid,
                            "kind": "interval", "proj": proj,
                            "expected": expected_interval,
                            "reads_by_source": reads_by_source})
                    if naive != expected_interval:
                        mismatches.append({
                            "case": case_index, "query": query, "sid": sid,
                            "kind": "naive", "naive": naive,
                            "expected": expected_interval,
                            "reads_by_source": reads_by_source})
        self.assertEqual(
            mismatches, [],
            "randomized mismatches (seed %d): %r"
            % (SEED, mismatches[:3]))
        self.assertGreater(comparisons, 1500)


def holt_merge_two_local(left_dir, right_dir, output_dir, num_procs=1,
                         logger=None):
    """REAL GenericMerge through the Feature-2 adapter."""
    from MUS.MultiSourceProvenance import holt_merge_two
    return holt_merge_two(left_dir, right_dir, output_dir,
                          num_procs=num_procs, logger=logger)


if __name__ == "__main__":
    unittest.main()
