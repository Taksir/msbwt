"""msbwt-modern2 enhanced Feature 1 tests: two-source rank-aware queries
(``MUS.SourceIndex``), runnable inside the pinned Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO.
These tests execute REAL modern2 construction (``pp`` + ``cfpp``) and REAL
``GenericMerge`` merges through the modern2 CLI, then load the merged
directory with ``MUS.SourceIndex.TwoSourceBWT`` and compare source-aware
counts against the standalone source BWTs (oracles for testing only).

Coverage:

- rank/access behavior at every position vs a naive unpack oracle
  (0/1/8/9/63/64/65 bits, multiple rank blocks, all-zero, all-one,
  alternating, random, padding bits set to 1);
- rank-cache identity/staleness safety under NumPy 1.16.6 (round trip,
  same-length replaced ``inter0.npy``, corrupt/truncated cache);
- Python-2 sequence-normalization contract (str/bytes/unicode/TypeError);
- canonical two-source integration: uniform-a + uniform-b merged, every
  committed query compared as source0/source1/sum against standalone A/B
  and the legacy merged count;
- ``givenRange`` legacy semantics preserved by the Feature-1 layer;
- one merged FM search per source-aware query (instrumented real BWT);
- deterministic edge corpus (12 source-pair classes);
- deterministic randomized differential subset (seed 20260811).

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import os
import random
import shutil
import sys
import tempfile
import unittest

import numpy as np

from MUS.SourceIndex import (
    TwoSourceBWT,
    TwoSourceInterleaveIndex,
)

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")

FIXTURES_EXPECTED = {
    "uniform-a.fastq": ("da3466b992e0ba4ef4da2d0731062661f13e66b83ec154b56471ec4286798180", 173),
    "uniform-b.fastq": ("04124b73a3dde82da5cd70d9d244180d6e076a952dda404e4746b1e9388e1029", 162),
}

CANONICAL_READS_A = ["ACGTN", "AAAAA", "ACGTN", "NACGT"]
CANONICAL_READS_B = ["ACGTN", "CCCCC", "GGGGG", "TTTTT"]

# committed reader query table for the canonical merged BWT
COMMITTED_QUERIES = {
    "A": 9, "AA": 4, "AAA": 3, "AAAA": 2, "AAAAA": 1, "AAAAAA": 0,
    "AC": 4, "ACG": 4, "ACGT": 4, "ACGTN": 3,
    "C": 9, "CC": 4, "CCC": 3, "CCCC": 2, "CCCCC": 1,
    "CG": 4, "CGT": 4, "CGTN": 3,
    "G": 9, "GG": 4, "GGG": 3, "GGGG": 2, "GGGGG": 1,
    "GT": 4, "GTN": 3,
    "N": 4, "NA": 1, "NAC": 1, "NACG": 1, "NACGT": 1,
    "T": 9, "TN": 3, "TT": 4, "TTT": 3, "TTTT": 2, "TTTTT": 1,
}

# required additional categories for Feature-1 queries
CANONICAL_EXTRA_QUERIES = [
    b"$",                    # dollar query (8 dollars total, 4 per source)
    b"AAAAAA",               # absent
    b"CCCCCCC",              # absent
    b"GGGAAA",               # absent
    b"ACGTNACGTN",           # absent (longer than any read)
    b"AAAAA",                # present only in A
    b"NACGT",                # present only in A
    b"CCCCC",                # present only in B
    b"GGGGG",                # present only in B
    b"TTTTT",                # present only in B
    b"ACGTN",                # present in BOTH sources
    b"A$",                   # reads ending in A (AAAAA)
    b"T$",                   # reads ending in T (NACGT)
]

SEED = 20260811


def write_fastq(path, reads):
    with open(path, "w") as handle:
        for index, read in enumerate(reads):
            handle.write("@read%d\n" % index)
            handle.write(read + "\n")
            handle.write("+\n")
            handle.write("I" * len(read) + "\n")


def pack_little_endian_bits(bits, pad_value=0):
    bits = [int(b) for b in bits]
    nbytes = (len(bits) + 7) // 8
    arr = np.zeros(nbytes, dtype=np.uint8)
    for i, bit in enumerate(bits):
        if bit:
            arr[i >> 3] |= np.uint8(1 << (i & 7))
    if bits and pad_value:
        for i in range(len(bits), nbytes * 8):
            arr[i >> 3] |= np.uint8(1 << (i & 7))
    return arr


def naive_rank1(bits, position):
    return sum(bits[:position])


class SourceHarness(object):
    """In-process CLI harness building real modern2 MSBWTs and merges."""

    def __init__(self, work):
        self.work = work

    def cli(self, *argv):
        from MUS import CommandLineInterface
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt"] + list(argv)
            CommandLineInterface.mainRun()
        finally:
            sys.argv = old_argv

    def build_fastq_source(self, name, reads):
        fastq = os.path.join(self.work, name + ".fastq")
        write_fastq(fastq, reads)
        out = os.path.join(self.work, name)
        os.mkdir(out)
        uniform = all(len(read) == len(reads[0]) for read in reads)
        if uniform:
            self.cli("pp", "-u", out, fastq)
            self.cli("cfpp", "-p", "1", "-u", out)
        else:
            # mixed-length reads require the nonuniform multimerge route
            self.cli("pp", out, fastq)
            self.cli("cfpp", "-p", "1", out)
        return out

    def build_fixture_source(self, name, fixture_name):
        out = os.path.join(self.work, name)
        os.mkdir(out)
        self.cli("pp", "-u", out, os.path.join(FIXTURES, fixture_name))
        self.cli("cfpp", "-p", "1", "-u", out)
        return out

    def merge(self, name, in_a, in_b):
        out = os.path.join(self.work, name)
        self.cli("merge", "-p", "1", out, in_a, in_b)
        return out


def load_standalone(path):
    from MUSCython import MultiStringBWTCython
    return MultiStringBWTCython.loadBWT(path, useMemmap=False, logger=None)


def build_queries(reads_a, reads_b):
    """Deterministic query set: singles, all substrings, full reads,
    $-adjacent strings, plus absent-style extra strings."""
    queries = ["A", "C", "G", "T", "N", "$"]
    seen = set()
    for read in reads_a + reads_b:
        for start in range(len(read)):
            for end in range(start + 1, len(read) + 1):
                seen.add(read[start:end])
        seen.add(read)
        seen.add("$" + read)
        seen.add(read + "$")
    queries.extend(sorted(seen))
    queries.extend([
        "NNNN", "AAAAAA", "CCCCCCCC", "GGGGGGG", "TTTTTT",
        "NACN", "ACNNT", "ACGTACGTACGTACGT", "TAGCTAGCTAGC",
    ])
    return queries


def verify_case(harness, reads_a, reads_b, queries, label, results):
    """Build A, build B, merge, load Feature-1, compare every query.

    Every mismatch is recorded with seed/reads/query/interval/counts so a
    failure is immediately minimizable.
    """
    a_dir = harness.build_fastq_source(label + "-a", reads_a)
    b_dir = harness.build_fastq_source(label + "-b", reads_b)
    m_dir = harness.merge(label + "-m", a_dir, b_dir)
    a_bwt = load_standalone(a_dir)
    b_bwt = load_standalone(b_dir)
    merged = TwoSourceBWT.load(m_dir, source_names=("A", "B"))

    mismatches = []
    comparisons = 0
    for query in queries:
        expected_a = int(a_bwt.countOccurrencesOfSeq(query))
        expected_b = int(b_bwt.countOccurrencesOfSeq(query))
        legacy = int(merged.bwt.countOccurrencesOfSeq(query))
        result = merged.countOccurrencesBySource(query)
        got_a = int(result["A"])
        got_b = int(result["B"])
        comparisons += 3
        for kind, got, expected in (
            ("source0", got_a, expected_a),
            ("source1", got_b, expected_b),
            ("sum_vs_merged", got_a + got_b, legacy),
        ):
            if got != expected:
                mismatches.append({
                    "case": label, "query": query,
                    "kind": kind, "got": got, "expected": expected,
                    "interval": result["interval"],
                    "reads_a": reads_a, "reads_b": reads_b,
                })
    results["mismatches"] = mismatches
    results["comparisons"] = comparisons
    results["total_queries"] = len(queries)
    return a_dir, b_dir, m_dir, a_bwt, b_bwt, merged


# --- rank / cache / normalization unit tests ---------------------------------

class RankUnitTests(unittest.TestCase):
    def check_every_position(self, bits, stride, pad_value=0):
        packed = pack_little_endian_bits(bits, pad_value=pad_value)
        index = TwoSourceInterleaveIndex(
            packed, total_bits=len(bits), rank_stride_bytes=stride)
        for position in range(len(bits) + 1):
            expected1 = naive_rank1(bits, position)
            self.assertEqual(index.rank1(position), expected1)
            self.assertEqual(index.rank0(position), position - expected1)
        for position in range(len(bits)):
            self.assertEqual(index.source_at(position), bits[position])
        self.assertEqual(
            index.counts(0, len(bits)),
            (len(bits) - sum(bits), sum(bits)))

    def test_zero_one_eight_nine_bits(self):
        for bits in ([], [0], [1], [0, 1, 1, 0, 1, 0, 0, 1],
                     [1, 0, 1, 1, 0, 1, 0, 0, 1]):
            self.check_every_position(bits, 64)

    def test_63_64_65_bits(self):
        for count in (63, 64, 65):
            self.check_every_position([(i * 7) % 3 == 0 for i in range(count)],
                                      64)

    def test_multiple_rank_blocks_and_random(self):
        rng = random.Random(SEED)
        for trial in range(30):
            length = rng.randint(0, 250)
            bits = [rng.randint(0, 1) for _ in range(length)]
            stride = rng.choice([1, 2, 3, 7, 8, 64])
            self.check_every_position(bits, stride)

    def test_all_zero_all_one_alternating(self):
        self.check_every_position([0] * 130, 64)
        self.check_every_position([1] * 130, 64)
        self.check_every_position([i % 2 for i in range(129)], 64)

    def test_padding_bits_set_to_one_never_leak(self):
        bits = [1, 0, 1, 1, 0, 1, 0, 0, 1, 0]
        index = TwoSourceInterleaveIndex(
            pack_little_endian_bits(bits, pad_value=1), total_bits=len(bits))
        self.assertEqual(index.rank1(len(bits)), sum(bits))
        self.assertEqual(index.rank0(len(bits)), len(bits) - sum(bits))
        self.assertEqual(index.counts(0, len(bits)),
                         (len(bits) - sum(bits), sum(bits)))

    def test_padding_byte_after_full_valid_bytes(self):
        # 48 valid bits + one fully-padded 0xFF byte (GenericMerge layout)
        bits = [(i * 3) % 7 < 3 for i in range(48)]
        packed = pack_little_endian_bits(bits)
        packed = np.concatenate([packed, np.asarray([0xFF], dtype=np.uint8)])
        index = TwoSourceInterleaveIndex(packed, total_bits=48)
        self.assertEqual(index.rank1(48), sum(bits))
        for position in range(49):
            self.assertEqual(index.rank1(position), naive_rank1(bits, position))

    def test_interval_counts_and_invalid_source_ids(self):
        bits = [0, 1, 1, 0, 0, 1, 0, 1, 1, 0]
        index = TwoSourceInterleaveIndex(
            pack_little_endian_bits(bits), total_bits=len(bits))
        start, end = 2, 9
        expected_source1 = sum(bits[start:end])
        expected_source0 = (end - start) - expected_source1
        self.assertEqual(index.counts(start, end),
                         (expected_source0, expected_source1))
        self.assertEqual(index.count_source(0, start, end), expected_source0)
        self.assertEqual(index.count_source(1, start, end), expected_source1)
        self.assertEqual(index.counts(2, 2), (0, 0))
        for source_id in (-1, 2, 99):
            with self.assertRaises(ValueError):
                index.count_source(source_id, 0, 10)

    def test_validation_errors(self):
        with self.assertRaises(TypeError):
            TwoSourceInterleaveIndex(np.zeros(2, dtype=np.uint16), total_bits=8)
        with self.assertRaises(ValueError):
            TwoSourceInterleaveIndex(np.zeros((2, 2), dtype=np.uint8),
                                     total_bits=8)
        with self.assertRaises(ValueError):
            TwoSourceInterleaveIndex(np.zeros(2, dtype=np.uint8), total_bits=30)
        index = TwoSourceInterleaveIndex(np.zeros(1, dtype=np.uint8),
                                         total_bits=8)
        with self.assertRaises(IndexError):
            index.rank1(9)
        with self.assertRaises(IndexError):
            index.source_at(8)
        with self.assertRaises(ValueError):
            index.counts(5, 2)


class RankCachePy2Tests(unittest.TestCase):
    """Cache identity under NumPy 1.16.6 (the pinned Python-2 profile)."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="f1-py2-cache-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def make_dir(self, name, bits):
        directory = os.path.join(self.work, name)
        os.mkdir(directory)
        np.save(os.path.join(directory, "inter0.npy"),
                pack_little_endian_bits(bits))
        np.save(os.path.join(directory, "msbwt.npy"),
                np.zeros(len(bits), dtype=np.uint8))
        return directory

    def test_saved_rank_round_trip_and_schema(self):
        bits = [int(i % 3 == 0) for i in range(1000)]
        directory = self.make_dir("rt", bits)
        first = TwoSourceInterleaveIndex.from_directory(
            directory, rank_stride_bytes=8, use_saved_rank=False)
        first.save_rank_index(directory)
        saved = np.load(os.path.join(directory, "inter0_rank.npz"),
                        allow_pickle=False)
        self.assertEqual(
            sorted(saved.keys()),
            ["inter0_sha256", "inter0_total_ones", "rank_prefix",
             "rank_stride_bytes", "total_bits"])
        self.assertEqual(len(saved["inter0_sha256"][0]), 64)
        second = TwoSourceInterleaveIndex.from_directory(
            directory, rank_stride_bytes=8, use_saved_rank=True)
        self.assertTrue(np.array_equal(first.rank_prefix, second.rank_prefix))
        for position in (0, 1, 7, 8, 63, 64, 511, 999, 1000):
            self.assertEqual(second.rank1(position), first.rank1(position))

    def test_same_length_replaced_interleave_rebuilds(self):
        bits = [int(i % 3 == 0) for i in range(500)]
        flipped = [1 - b for b in bits]
        directory = self.make_dir("replaced", bits)
        index = TwoSourceInterleaveIndex.from_directory(
            directory, rank_stride_bytes=8, use_saved_rank=False)
        index.save_rank_index(directory)
        del index
        np.save(os.path.join(directory, "inter0.npy"),
                pack_little_endian_bits(flipped))
        loaded = TwoSourceInterleaveIndex.from_directory(
            directory, rank_stride_bytes=8, use_saved_rank=True)
        self.assertEqual(loaded.rank1(500), sum(flipped),
                         "stale cache produced wrong source counts")
        self.assertEqual(loaded.counts(0, 500),
                         (500 - sum(flipped), sum(flipped)))

    def test_corrupt_cache_rebuilds(self):
        bits = [int(i % 2) for i in range(100)]
        directory = self.make_dir("corrupt", bits)
        index = TwoSourceInterleaveIndex.from_directory(
            directory, rank_stride_bytes=8, use_saved_rank=False)
        index.save_rank_index(directory)
        del index
        with open(os.path.join(directory, "inter0_rank.npz"), "wb") as handle:
            handle.write(b"this is not a zip archive")
        loaded = TwoSourceInterleaveIndex.from_directory(
            directory, rank_stride_bytes=8, use_saved_rank=True)
        self.assertEqual(loaded.rank1(100), sum(bits))

    def test_truncated_cache_rebuilds(self):
        bits = [int(i % 2) for i in range(100)]
        directory = self.make_dir("truncated", bits)
        index = TwoSourceInterleaveIndex.from_directory(
            directory, rank_stride_bytes=8, use_saved_rank=False)
        index.save_rank_index(directory)
        del index
        path = os.path.join(directory, "inter0_rank.npz")
        with open(path, "rb") as handle:
            data = handle.read()
        with open(path, "wb") as handle:
            handle.write(data[: len(data) // 2])
        loaded = TwoSourceInterleaveIndex.from_directory(
            directory, rank_stride_bytes=8, use_saved_rank=True)
        self.assertEqual(loaded.rank1(100), sum(bits))

    def test_legacy_cache_without_identity_rebuilds(self):
        bits = [int(i % 2) for i in range(120)]
        directory = self.make_dir("legacy", bits)
        index = TwoSourceInterleaveIndex.from_directory(
            directory, rank_stride_bytes=8, use_saved_rank=False)
        np.savez(
            os.path.join(directory, "inter0_rank.npz"),
            rank_prefix=index.rank_prefix,
            total_bits=np.asarray([index.total_bits], dtype=np.uint64),
            rank_stride_bytes=np.asarray([8], dtype=np.uint64),
        )
        del index
        loaded = TwoSourceInterleaveIndex.from_directory(
            directory, rank_stride_bytes=8, use_saved_rank=True)
        self.assertEqual(loaded.rank1(120), sum(bits))


class SequenceNormalizationPy2Tests(unittest.TestCase):
    def test_str_is_bytes_and_passes_through(self):
        from MUS.SourceIndex import _normalize_sequence
        self.assertTrue(str is bytes)  # Python 2 semantics
        self.assertEqual(_normalize_sequence("ACGT"), "ACGT")
        self.assertEqual(_normalize_sequence(b"ACGT"), b"ACGT")

    def test_ascii_unicode_encoded(self):
        from MUS.SourceIndex import _normalize_sequence
        self.assertEqual(_normalize_sequence(u"ACGT"), "ACGT")

    def test_non_ascii_unicode_raises(self):
        from MUS.SourceIndex import _normalize_sequence
        with self.assertRaises(UnicodeEncodeError):
            _normalize_sequence(u"\xe9")

    def test_non_string_raises_type_error(self):
        from MUS.SourceIndex import _normalize_sequence
        with self.assertRaises(TypeError):
            _normalize_sequence(42)
        with self.assertRaises(TypeError):
            _normalize_sequence(None)


class Feature1EnvironmentTests(unittest.TestCase):
    def test_python_is_cpython_27(self):
        self.assertEqual(sys.version_info[:2], (2, 7))

    def test_numpy_is_pinned(self):
        self.assertEqual(np.__version__, "1.16.6")

    def test_public_api_surface(self):
        import MUS.SourceIndex as module
        for name in ("TwoSourceInterleaveIndex", "TwoSourceBWT",
                     "countOccurrencesBySource", "count_occurrences_by_source"):
            self.assertTrue(hasattr(module, name), name)
        self.assertIs(module.count_occurrences_by_source,
                      module.countOccurrencesBySource)

    def test_module_imports_without_musc_cython_at_module_level(self):
        text = open(os.path.join(os.path.dirname(__file__), "..", "MUS",
                                 "SourceIndex.py"), "rb").read()
        self.assertNotIn(b"\nimport MUSCython", text)
        self.assertNotIn(b"\nfrom MUSCython", text)


class CountingProxy(object):
    """Attribute proxy counting findIndicesOfStr calls on a real ByteBWT."""

    def __init__(self, bwt):
        self._bwt = bwt
        self.search_calls = 0

    def __getattr__(self, name):
        attr = getattr(self._bwt, name)
        if name == "findIndicesOfStr":
            def counted(*args, **kwargs):
                self.search_calls += 1
                return attr(*args, **kwargs)
            return counted
        return attr

    def getTotalSize(self):
        return self._bwt.getTotalSize()


class CanonicalTwoSourceIntegrationTests(unittest.TestCase):
    """Real modern2 merge of the canonical fixtures through Feature 1."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f1-py2-canonical-")
        cls.harness = SourceHarness(cls.work)
        cls.a_dir = cls.harness.build_fixture_source("in_a", "uniform-a.fastq")
        cls.b_dir = cls.harness.build_fixture_source("in_b", "uniform-b.fastq")
        cls.m_dir = cls.harness.merge("merged", cls.a_dir, cls.b_dir)
        cls.a_bwt = load_standalone(cls.a_dir)
        cls.b_bwt = load_standalone(cls.b_dir)
        cls.merged = TwoSourceBWT.load(
            cls.m_dir, source_names=("A", "B"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_merged_contract_hashes(self):
        import hashlib

        def sha256_file(path):
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
            return digest.hexdigest()

        self.assertEqual(
            sha256_file(os.path.join(self.m_dir, "msbwt.npy")),
            "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f")
        self.assertEqual(
            sha256_file(os.path.join(self.m_dir, "inter0.npy")),
            "4a6d97a36e9ef4e3c19fb873b7713a9357d207d29433a3eca67a41cc4221afd6")
        self.assertEqual(int(self.merged.bwt.getTotalSize()), 48)
        self.assertEqual(self.merged.source_index.total_bits, 48)
        # per-source totals come from the provenance: 24 rows each
        totals = self.merged.source_index.counts(0, 48)
        self.assertEqual(totals, (24, 24))

    def test_saved_rank_cache_is_actually_loaded_for_real_merge(self):
        # the real merged interleave has 7 stored bytes for 48 valid rows
        # (6 used bytes + 1 padding byte): the cache identity must agree
        # with the used-byte ones count so the cache is LOADED, not rebuilt
        cache_path = os.path.join(self.m_dir, "inter0_rank.npz")
        if os.path.exists(cache_path):
            os.remove(cache_path)
        index = TwoSourceInterleaveIndex.from_directory(
            self.m_dir, use_saved_rank=False)
        index.save_rank_index(self.m_dir)
        self.assertEqual(index.rank1(48), 24)

        original = TwoSourceInterleaveIndex._build_rank_prefix

        def fail_if_rebuilt(self):
            raise AssertionError("saved rank cache was NOT used")

        TwoSourceInterleaveIndex._build_rank_prefix = fail_if_rebuilt
        try:
            reloaded = TwoSourceInterleaveIndex.from_directory(
                self.m_dir, use_saved_rank=True)
            self.assertEqual(reloaded.rank1(48), 24)
            self.assertEqual(reloaded.rank0(48), 24)
        finally:
            TwoSourceInterleaveIndex._build_rank_prefix = original
            os.remove(cache_path)

    def test_every_committed_query_source_split(self):
        for query, expected_total in COMMITTED_QUERIES.items():
            result = self.merged.countOccurrencesBySource(query)
            self.assertEqual(result["total"], expected_total, query)
            self.assertEqual(result["A"] + result["B"], expected_total, query)
            expected_a = int(self.a_bwt.countOccurrencesOfSeq(query))
            expected_b = int(self.b_bwt.countOccurrencesOfSeq(query))
            self.assertEqual(result["A"], expected_a, query)
            self.assertEqual(result["B"], expected_b, query)

    def test_required_query_categories(self):
        for query in CANONICAL_EXTRA_QUERIES:
            result = self.merged.countOccurrencesBySource(query)
            expected_a = int(self.a_bwt.countOccurrencesOfSeq(query))
            expected_b = int(self.b_bwt.countOccurrencesOfSeq(query))
            self.assertEqual(result["A"], expected_a, query)
            self.assertEqual(result["B"], expected_b, query)
            self.assertEqual(result["total"], expected_a + expected_b, query)
            self.assertEqual(result["total"],
                             int(self.merged.bwt.countOccurrencesOfSeq(query)),
                             query)
            self.assertEqual(result["interval"][1] - result["interval"][0],
                             result["total"])

    def test_dollar_query_counts_reads_per_source(self):
        result = self.merged.countOccurrencesBySource(b"$")
        self.assertEqual(result["total"], 8)
        self.assertEqual(result["A"], 4)
        self.assertEqual(result["B"], 4)
        self.assertEqual(int(self.a_bwt.countOccurrencesOfSeq(b"$")), 4)
        self.assertEqual(int(self.b_bwt.countOccurrencesOfSeq(b"$")), 4)

    def test_absent_queries_are_zero(self):
        for query in (b"AAAAAA", b"CCCCCCC", b"GGGAAA", b"ACGTNACGTN"):
            result = self.merged.countOccurrencesBySource(query)
            self.assertEqual(result["total"], 0)
            self.assertEqual(result["A"], 0)
            self.assertEqual(result["B"], 0)
            self.assertEqual(result["interval"][0], result["interval"][1])

    def test_one_merged_search_per_source_aware_query(self):
        proxy = CountingProxy(self.merged.bwt)
        index = self.merged.source_index
        wrapper = TwoSourceBWT(proxy, index, source_names=("A", "B"))
        for query in (b"ACGTN", b"A", b"$", b"TTTTT"):
            wrapper.countOccurrencesBySource(query)
        self.assertEqual(proxy.search_calls, 4)
        # and no standalone BWT is queried at runtime: the wrapper only
        # delegates to the merged BWT object we supplied
        self.assertTrue(hasattr(wrapper.bwt, "_bwt"))

    def test_given_range_preserves_legacy_semantics(self):
        # legacy semantics: givenRange is the FM interval of the
        # already-searched SUFFIX.  findIndicesOfStr('G', interval('T'))
        # must equal findIndicesOfStr('GT'), and Feature 1 must delegate
        # the identical call.
        t_interval = tuple(int(v) for v in self.merged.bwt.findIndicesOfStr(b"T"))
        gt_direct = tuple(int(v) for v in self.merged.bwt.findIndicesOfStr(b"GT"))
        gt_via_range = tuple(
            int(v) for v in self.merged.bwt.findIndicesOfStr(
                b"G", givenRange=t_interval))
        self.assertEqual(gt_via_range, gt_direct)
        self.assertEqual(
            int(self.merged.bwt.countOccurrencesOfSeq(
                b"G", givenRange=t_interval)),
            gt_direct[1] - gt_direct[0])
        # Feature-1 layer with the same givenRange: identical interval and
        # correct source split (GT: 3 in A, 1 in B)
        result = self.merged.countOccurrencesBySource(
            b"G", givenRange=t_interval)
        self.assertEqual(result["interval"], gt_direct)
        self.assertEqual(result["total"], gt_direct[1] - gt_direct[0])
        self.assertEqual(result["A"], 3)
        self.assertEqual(result["B"], 1)
        expected_a = int(self.a_bwt.countOccurrencesOfSeq(b"GT"))
        expected_b = int(self.b_bwt.countOccurrencesOfSeq(b"GT"))
        self.assertEqual(result["A"], expected_a)
        self.assertEqual(result["B"], expected_b)

    def test_given_range_none_matches_full_search(self):
        full = self.merged.countOccurrencesBySource(b"GT")
        ranged = self.merged.countOccurrencesBySource(
            b"GT", givenRange=(0, 48))
        self.assertEqual(full, ranged)
        self.assertEqual(full["interval"], tuple(self.merged.bwt.findIndicesOfStr(b"GT")))

    def test_result_structure(self):
        result = self.merged.countOccurrencesBySource(b"ACGTN")
        self.assertEqual(
            sorted(result.keys()),
            ["A", "B", "interval", "sequence", "total"])
        self.assertEqual(result["sequence"], b"ACGTN")
        self.assertEqual(result["total"], 3)
        self.assertEqual(
            result["interval"],
            tuple(int(v) for v in self.merged.bwt.findIndicesOfStr(b"ACGTN")))

    def test_source_names_used_as_keys(self):
        named = TwoSourceBWT.load(self.m_dir,
                                  source_names=("sample-A", "sample-B"))
        result = named.countOccurrencesBySource(b"ACGTN")
        self.assertEqual(result["sample-A"], 2)
        self.assertEqual(result["sample-B"], 1)
        self.assertEqual(result["total"], 3)

    def test_functional_api_matches_wrapper(self):
        from MUS.SourceIndex import countOccurrencesBySource
        result = countOccurrencesBySource(
            self.merged.bwt, self.merged.source_index, b"ACGTN",
            source_names=("A", "B"))
        self.assertEqual(result["A"], 2)
        self.assertEqual(result["B"], 1)
        self.assertEqual(result["total"], 3)


EDGE_CORPUS = [
    # (label, reads_a, reads_b)
    ("unequal-sizes", ["ACGT", "ACGT", "ACGT", "ACGT", "ACGT", "ACGT"], ["TT"]),
    ("duplicates-in-A", ["ACGT", "ACGT", "ACGT", "GG"], ["TT", "CC"]),
    ("duplicates-in-B", ["TT", "CC"], ["ACGT", "ACGT", "ACGT", "GG"]),
    ("same-reads-both", ["ACGT", "GG", "TT"], ["ACGT", "GG", "TT"]),
    ("all-identical", ["AAAA", "AAAA"], ["AAAA", "AAAA"]),
    ("prefix-sharing", ["AAAAAC", "AAAAAG", "AAAAAT"], ["AAAAAA", "AAAAACC"]),
    ("suffix-sharing", ["CAAAA", "GAAAA", "TAAAA"], ["AAAAA", "CAAAAA"]),
    ("n-heavy", ["ACNNGT", "NNACGT", "ANNTN"], ["NNNN", "ACNTN"]),
    ("single-base", ["A", "C", "G"], ["T", "A", "N"]),
    ("mixed-lengths", ["A", "ACG", "ACGTACGT", "TTGCA", "N"],
                      ["ACGTACGTACGT", "C", "GGGG"]),
    ("repeated-motifs", ["ACGTACGT", "ACGTACGT", "TGTGTG"],
                        ["ACGTACGTACGT", "TGTGTGTG"]),
    ("lexicographic-similar", ["AAAAA", "AAAAC", "AAAAG", "AAAAT"],
                              ["AAAAN", "AAACA", "AAAGA", "AACAA"]),
]


class DeterministicEdgeCorpusTests(unittest.TestCase):
    """12 source-pair classes: source0/1/sum invariants for every query."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f1-py2-edge-")
        cls.harness = SourceHarness(cls.work)
        cls.results = {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_all_edge_pairs_satisfy_source_invariants(self):
        total_comparisons = 0
        for label, reads_a, reads_b in EDGE_CORPUS:
            queries = build_queries(reads_a, reads_b)
            result = {}
            a_dir, b_dir, m_dir, a_bwt, b_bwt, merged = verify_case(
                self.harness, reads_a, reads_b, queries, label, result)
            self.assertEqual(
                result["mismatches"], [],
                "edge case %r mismatches: %r" % (label, result["mismatches"][:3]))
            # spot-check interval arithmetic on a few queries per pair
            for query in queries[:6]:
                legacy = merged.bwt.findIndicesOfStr(query)
                outcome = merged.countOccurrencesBySource(query)
                self.assertEqual(outcome["interval"],
                                 (int(legacy[0]), int(legacy[1])))
                self.assertEqual(outcome["total"],
                                 outcome["interval"][1] - outcome["interval"][0])
            total_comparisons += result["comparisons"]
        self.results["comparisons"] = total_comparisons
        self.assertGreater(total_comparisons, 500)


def make_random_case(rng):
    """Deterministic random source pair (identical on py2 and py3)."""

    def reads():
        count = rng.randint(1, 6)
        out = []
        for _ in range(count):
            length = rng.randint(1, 12)
            chars = []
            for _ in range(length):
                if rng.random() < 0.15:
                    chars.append("N")
                else:
                    chars.append("ACGT"[rng.randint(0, 3)])
            out.append("".join(chars))
        return out

    return reads(), reads()


class RandomizedDifferentialTests(unittest.TestCase):
    """Deterministic randomized Feature-1 differential (seed 20260811)."""

    CASES = 10

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="f1-py2-random-")
        cls.harness = SourceHarness(cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_randomized_source_invariants(self):
        rng = random.Random(SEED)
        mismatches = []
        comparisons = 0
        for case_index in range(self.CASES):
            reads_a, reads_b = make_random_case(rng)
            queries = build_queries(reads_a, reads_b)
            result = {}
            verify_case(self.harness, reads_a, reads_b, queries,
                        "rand-%02d" % case_index, result)
            comparisons += result["comparisons"]
            if result["mismatches"]:
                mismatches.extend(result["mismatches"])
        self.assertEqual(
            mismatches, [],
            "randomized mismatches (seed %d): %r" % (SEED, mismatches[:3]))
        self.assertGreater(comparisons, 1000)


if __name__ == "__main__":
    unittest.main()

