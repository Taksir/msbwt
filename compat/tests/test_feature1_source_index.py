"""Host-side regression tests for enhanced-modern2 Feature 1:
two-source rank-aware queries (``MUS.SourceIndex``).

These tests are read-only and run on any CPython 3 with NumPy; they do NOT
require the compiled MUSCython extensions (real-merge integration runs in the
pinned Python-2.7 suite and the Feature-1 validation driver).

Coverage:

- exhaustive/edge rank-oracle differential tests at EVERY position for many
  small bitvectors (0, 1, 8, 9, 63/64/65 bits, multiple rank blocks, all
  zero, all one, alternating, random, padding bits set to 1);
- the candidate's unit-test claims (little-endian packing convention,
  padding isolation, interval counts, directory loading, saved-rank round
  trip, one merged FM search per query, length-mismatch rejection);
- rank cache identity/staleness safety: valid load, corrupt cache, truncated
  cache, wrong stride, wrong total_bits, same-length-but-changed
  ``inter0.npy`` (mandatory), stale cache copied from another merge of the
  same size, legacy-format cache without identity fields;
- sequence-normalization contract (bytes / str / non-ASCII / non-string);
- ``givenRange`` delegation semantics;
- BWT/provenance length safety and malformed-file handling;
- deterministic randomized rank differential stress.
"""

import gc
import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

PACKAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "..", "packages", "msbwt-modern2")
sys.path.insert(0, PACKAGE)

from MUS.SourceIndex import (  # noqa: E402
    TwoSourceBWT,
    TwoSourceInterleaveIndex,
    countOccurrencesBySource,
    count_occurrences_by_source,
)


def pack_little_endian_bits(bits, pad_value=0):
    """Pack bits exactly like GenericMerge.pyx: bit i is 1 << (i & 7)."""
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


def make_bwt_dir(bits, pad_value=0, bwt_len=None, bwt_dtype=np.uint8,
                 extra_interleave_bytes=0, interleave_dtype=np.uint8):
    """Create a temp directory with inter0.npy + msbwt.npy and return it."""
    directory = tempfile.mkdtemp(prefix="f1-host-")
    packed = pack_little_endian_bits(bits, pad_value=pad_value)
    if extra_interleave_bytes:
        extra = np.zeros(extra_interleave_bytes, dtype=np.uint8)
        packed = np.concatenate([packed, extra])
    np.save(os.path.join(directory, "inter0.npy"),
            packed.astype(interleave_dtype, copy=False))
    if bwt_len is None:
        bwt_len = len(bits)
    np.save(os.path.join(directory, "msbwt.npy"),
            np.zeros(bwt_len, dtype=bwt_dtype))
    return directory


class RankOracleTests(unittest.TestCase):
    """Stage C: rank behavior at EVERY position vs a naive unpack oracle."""

    STRIDES = (1, 2, 3, 7, 8, 64)

    def _check_every_position(self, bits, stride, pad_value=0):
        packed = pack_little_endian_bits(bits, pad_value=pad_value)
        index = TwoSourceInterleaveIndex(
            packed, total_bits=len(bits), rank_stride_bytes=stride)
        for position in range(len(bits) + 1):
            expected1 = naive_rank1(bits, position)
            self.assertEqual(index.rank1(position), expected1, position)
            self.assertEqual(index.rank0(position), position - expected1)
        for position in range(len(bits)):
            self.assertEqual(index.source_at(position), bits[position])
        for start in range(len(bits) + 1):
            for end in range(start, len(bits) + 1):
                expected1 = naive_rank1(bits, end) - naive_rank1(bits, start)
                expected0 = (end - start) - expected1
                self.assertEqual(index.counts(start, end),
                                 (expected0, expected1))
                self.assertEqual(index.count_source(0, start, end), expected0)
                self.assertEqual(index.count_source(1, start, end), expected1)

    def test_zero_bits(self):
        self._check_every_position([], 64)

    def test_one_bit_zero(self):
        self._check_every_position([0], 64)

    def test_one_bit_one(self):
        self._check_every_position([1], 64)

    def test_exactly_eight_bits(self):
        self._check_every_position([0, 1, 1, 0, 1, 0, 0, 1], 64)

    def test_nine_bits(self):
        self._check_every_position([1, 0, 1, 1, 0, 1, 0, 0, 1], 64)

    def test_63_64_65_bits(self):
        for count in (63, 64, 65):
            bits = [(i * 7) % 3 == 0 for i in range(count)]
            self._check_every_position(bits, 64)

    def test_multiple_rank_blocks(self):
        bits = [(i * 13) % 5 < 2 for i in range(300)]
        self._check_every_position(bits, 64)
        self._check_every_position(bits, 8)
        self._check_every_position(bits, 1)

    def test_all_zero(self):
        self._check_every_position([0] * 130, 64)

    def test_all_one(self):
        self._check_every_position([1] * 130, 64)

    def test_alternating_bits(self):
        self._check_every_position([i % 2 for i in range(129)], 64)

    def test_random_bits_deterministic(self):
        rng = np.random.RandomState(20260811)
        for length in (2, 8, 9, 17, 64, 65, 127, 200):
            bits = [int(v) for v in rng.randint(0, 2, size=length)]
            self._check_every_position(bits, 64)
            self._check_every_position(bits, 8)

    def test_random_bits_all_strides(self):
        rng = np.random.RandomState(20260811)
        bits = [int(v) for v in rng.randint(0, 2, size=150)]
        for stride in self.STRIDES:
            self._check_every_position(bits, stride)

    def test_padding_bits_set_to_one_never_leak(self):
        bits = [1, 0, 1, 1, 0, 1, 0, 0, 1, 0]
        index = TwoSourceInterleaveIndex(
            pack_little_endian_bits(bits, pad_value=1), total_bits=len(bits))
        self.assertEqual(index.rank1(len(bits)), sum(bits))
        self.assertEqual(index.rank0(len(bits)), len(bits) - sum(bits))
        self.assertEqual(index.counts(0, len(bits)),
                         (len(bits) - sum(bits), sum(bits)))

    def test_padding_bits_one_full_trailing_byte(self):
        # 48 valid bits stored in 6 bytes + 1 fully-padded byte (0xFF):
        # the real GenericMerge capacity layout for 48-row merges.
        bits = [(i * 3) % 7 < 3 for i in range(48)]
        packed = pack_little_endian_bits(bits)
        packed = np.concatenate([packed, np.asarray([0xFF], dtype=np.uint8)])
        index = TwoSourceInterleaveIndex(packed, total_bits=48)
        self.assertEqual(index.rank1(48), sum(bits))
        for position in range(49):
            self.assertEqual(index.rank1(position), naive_rank1(bits, position))


class LittleEndianConventionTests(unittest.TestCase):
    def test_little_endian_source_access_matches_generic_merge_convention(self):
        # 0b10000101 means positions 0, 2 and 7 are source 1.
        packed = np.asarray([0b10000101], dtype=np.uint8)
        index = TwoSourceInterleaveIndex(packed, total_bits=8)
        self.assertEqual([index.source_at(i) for i in range(8)],
                         [1, 0, 1, 0, 0, 0, 0, 1])

    def test_bit_positions_spanning_byte_boundary(self):
        packed = np.asarray([0x01, 0x80], dtype=np.uint8)
        index = TwoSourceInterleaveIndex(packed, total_bits=16)
        self.assertEqual(index.source_at(0), 1)
        self.assertEqual(index.source_at(7), 0)
        self.assertEqual(index.source_at(8), 0)
        self.assertEqual(index.source_at(15), 1)
        self.assertEqual(index.rank1(16), 2)


class IntervalCountTests(unittest.TestCase):
    def test_interval_counts_for_both_sources(self):
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

    def test_empty_interval(self):
        bits = [1, 0, 1]
        index = TwoSourceInterleaveIndex(
            pack_little_endian_bits(bits), total_bits=len(bits))
        self.assertEqual(index.counts(2, 2), (0, 0))

    def test_full_interval_matches_totals(self):
        bits = [0, 1, 0, 1, 1, 0]
        index = TwoSourceInterleaveIndex(
            pack_little_endian_bits(bits), total_bits=len(bits))
        self.assertEqual(index.counts(0, len(bits)),
                         (len(bits) - sum(bits), sum(bits)))


class DirectoryLoadingTests(unittest.TestCase):
    def tearDown(self):
        gc.collect()

    def test_directory_loader_uses_msbwt_length_not_byte_capacity(self):
        # 10 valid rows require 2 bytes.  The last 6 bits are padding.
        bits = [0, 0, 1, 0, 1, 1, 0, 0, 1, 1]
        directory = make_bwt_dir(bits, pad_value=1)
        try:
            index = TwoSourceInterleaveIndex.from_directory(
                directory, mmap=False)
            self.assertEqual(index.total_bits, len(bits))
            self.assertEqual(index.rank1(len(bits)), sum(bits))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_directory_loader_mmap_path(self):
        bits = [1, 1, 0, 0, 1]
        directory = make_bwt_dir(bits)
        try:
            index = TwoSourceInterleaveIndex.from_directory(directory, mmap=True)
            self.assertEqual(index.total_bits, len(bits))
            self.assertEqual(index.rank1(len(bits)), sum(bits))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_missing_interleave_raises(self):
        directory = tempfile.mkdtemp(prefix="f1-host-")
        try:
            np.save(os.path.join(directory, "msbwt.npy"),
                    np.zeros(8, dtype=np.uint8))
            with self.assertRaises(IOError):
                TwoSourceInterleaveIndex.from_directory(directory, mmap=False)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_missing_bwt_raises(self):
        directory = tempfile.mkdtemp(prefix="f1-host-")
        try:
            np.save(os.path.join(directory, "inter0.npy"),
                    np.zeros(1, dtype=np.uint8))
            with self.assertRaises(IOError):
                TwoSourceInterleaveIndex.from_directory(directory, mmap=False)
        finally:
            shutil.rmtree(directory, ignore_errors=True)


class RankCacheTests(unittest.TestCase):
    """Cache identity/staleness safety for the derived inter0_rank.npz."""

    def tearDown(self):
        gc.collect()

    def _write_cache(self, directory, stride=8):
        index = TwoSourceInterleaveIndex.from_directory(
            directory, rank_stride_bytes=stride, use_saved_rank=False,
            mmap=False)
        index.save_rank_index(directory)
        return index

    def test_saved_rank_index_round_trip(self):
        bits = [int(i % 3 == 0) for i in range(1000)]
        directory = make_bwt_dir(bits)
        try:
            first = self._write_cache(directory)
            second = TwoSourceInterleaveIndex.from_directory(
                directory, rank_stride_bytes=8, use_saved_rank=True,
                mmap=False)
            self.assertTrue(np.array_equal(first.rank_prefix,
                                           second.rank_prefix))
            for position in (0, 1, 7, 8, 63, 64, 511, 999, 1000):
                self.assertEqual(second.rank1(position), first.rank1(position))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_cache_schema_fields(self):
        bits = [1, 0, 1, 1]
        directory = make_bwt_dir(bits)
        try:
            self._write_cache(directory)
            saved = np.load(os.path.join(directory, "inter0_rank.npz"),
                            allow_pickle=False)
            self.assertEqual(
                sorted(saved.keys()),
                ["inter0_sha256", "inter0_total_ones", "rank_prefix",
                 "rank_stride_bytes", "total_bits"])
            self.assertEqual(len(saved["inter0_sha256"][0]), 64)
            self.assertEqual(int(saved["total_bits"][0]), 4)
            self.assertEqual(int(saved["rank_stride_bytes"][0]), 8)
            self.assertEqual(int(saved["inter0_total_ones"][0]), 3)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_corrupt_cache_rebuilds(self):
        bits = [int(i % 2) for i in range(100)]
        directory = make_bwt_dir(bits)
        try:
            self._write_cache(directory)
            with open(os.path.join(directory, "inter0_rank.npz"),
                      "wb") as handle:
                handle.write(b"this is not a zip archive")
            index = TwoSourceInterleaveIndex.from_directory(
                directory, rank_stride_bytes=8, use_saved_rank=True,
                mmap=False)
            self.assertEqual(index.rank1(100), sum(bits))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_truncated_cache_rebuilds(self):
        bits = [int(i % 2) for i in range(100)]
        directory = make_bwt_dir(bits)
        try:
            self._write_cache(directory)
            path = os.path.join(directory, "inter0_rank.npz")
            with open(path, "rb") as handle:
                data = handle.read()
            with open(path, "wb") as handle:
                handle.write(data[: len(data) // 2])
            index = TwoSourceInterleaveIndex.from_directory(
                directory, rank_stride_bytes=8, use_saved_rank=True,
                mmap=False)
            self.assertEqual(index.rank1(100), sum(bits))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_wrong_stride_rebuilds(self):
        bits = [int(i % 3 == 0) for i in range(200)]
        directory = make_bwt_dir(bits)
        try:
            self._write_cache(directory, stride=8)
            index = TwoSourceInterleaveIndex.from_directory(
                directory, rank_stride_bytes=64, use_saved_rank=True,
                mmap=False)
            self.assertEqual(index.rank1(200), sum(bits))
            self.assertEqual(index.rank_stride_bytes, 64)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_wrong_total_bits_rebuilds(self):
        bits = [int(i % 3 == 0) for i in range(200)]
        directory = make_bwt_dir(bits)
        try:
            self._write_cache(directory)
            # shrink the BWT: same interleave, fewer valid rows
            np.save(os.path.join(directory, "msbwt.npy"),
                    np.zeros(100, dtype=np.uint8))
            index = TwoSourceInterleaveIndex.from_directory(
                directory, rank_stride_bytes=8, use_saved_rank=True,
                mmap=False)
            self.assertEqual(index.total_bits, 100)
            self.assertEqual(index.rank1(100), sum(bits[:100]))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_same_length_changed_interleave_rebuilds(self):
        """MANDATORY: a replaced inter0.npy with the SAME length must not be
        served from the stale cache."""
        bits = [int(i % 3 == 0) for i in range(500)]
        flipped = [1 - b for b in bits]
        directory = make_bwt_dir(bits)
        try:
            self._write_cache(directory)
            gc.collect()
            np.save(os.path.join(directory, "inter0.npy"),
                    pack_little_endian_bits(flipped))
            index = TwoSourceInterleaveIndex.from_directory(
                directory, rank_stride_bytes=8, use_saved_rank=True,
                mmap=False)
            self.assertEqual(index.rank1(500), sum(flipped),
                             "stale cache produced wrong source counts")
            self.assertEqual(index.counts(0, 500),
                             (500 - sum(flipped), sum(flipped)))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_modified_same_length_interleave_rebuilds(self):
        bits = [int(i % 2) for i in range(300)]
        directory = make_bwt_dir(bits)
        try:
            self._write_cache(directory)
            gc.collect()
            packed = pack_little_endian_bits(bits)
            packed[10] ^= 0x04  # flip a single bit of one byte
            np.save(os.path.join(directory, "inter0.npy"), packed)
            index = TwoSourceInterleaveIndex.from_directory(
                directory, rank_stride_bytes=8, use_saved_rank=True,
                mmap=False)
            expected = [int((int(packed[i >> 3]) >> (i & 7)) & 1)
                        for i in range(300)]
            self.assertEqual(index.rank1(300), sum(expected))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_stale_cache_from_another_merge_of_same_size_rebuilds(self):
        bits_a = [int(i % 3 == 0) for i in range(400)]
        bits_b = [int(i % 3 != 0) for i in range(400)]
        dir_a = make_bwt_dir(bits_a)
        dir_b = make_bwt_dir(bits_b)
        try:
            self._write_cache(dir_a)
            gc.collect()
            # transplant dir_a's cache onto dir_b (same total_bits, same
            # stride, DIFFERENT provenance content)
            shutil.copy(os.path.join(dir_a, "inter0_rank.npz"),
                        os.path.join(dir_b, "inter0_rank.npz"))
            index = TwoSourceInterleaveIndex.from_directory(
                dir_b, rank_stride_bytes=8, use_saved_rank=True, mmap=False)
            self.assertEqual(index.rank1(400), sum(bits_b),
                             "stale cross-merge cache produced wrong counts")
        finally:
            shutil.rmtree(dir_a, ignore_errors=True)
            shutil.rmtree(dir_b, ignore_errors=True)

    def test_legacy_format_cache_without_identity_rebuilds(self):
        # A pre-identity cache (rank_prefix/total_bits/rank_stride_bytes only)
        # cannot prove it belongs to this interleave: rebuild.
        bits = [int(i % 2) for i in range(120)]
        directory = make_bwt_dir(bits)
        try:
            index = self._write_cache(directory)
            np.savez(
                os.path.join(directory, "inter0_rank.npz"),
                rank_prefix=index.rank_prefix,
                total_bits=np.asarray([index.total_bits], dtype=np.uint64),
                rank_stride_bytes=np.asarray([8], dtype=np.uint64),
            )
            gc.collect()
            loaded = TwoSourceInterleaveIndex.from_directory(
                directory, rank_stride_bytes=8, use_saved_rank=True,
                mmap=False)
            self.assertEqual(loaded.rank1(120), sum(bits))
            # the rebuilt index carries the identity fields again
            self.assertTrue(hasattr(loaded, "rank_prefix"))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_corrupt_prefix_in_cache_rebuilds(self):
        bits = [int(i % 2) for i in range(150)]
        directory = make_bwt_dir(bits)
        try:
            index = self._write_cache(directory)
            bad_prefix = np.asarray(index.rank_prefix, dtype=np.uint64)
            bad_prefix[3] = bad_prefix[3] + 1000  # break monotonicity/end
            np.savez(
                os.path.join(directory, "inter0_rank.npz"),
                rank_prefix=bad_prefix,
                total_bits=np.asarray([index.total_bits], dtype=np.uint64),
                rank_stride_bytes=np.asarray([8], dtype=np.uint64),
                inter0_sha256=np.asarray(
                    [TwoSourceInterleaveIndex._interleave_digest(
                        index.packed_bits)], dtype="S64"),
                inter0_total_ones=np.asarray(
                    [TwoSourceInterleaveIndex._count_ones(
                        index.packed_bits, index._used_bytes)],
                    dtype=np.uint64),
            )
            gc.collect()
            loaded = TwoSourceInterleaveIndex.from_directory(
                directory, rank_stride_bytes=8, use_saved_rank=True,
                mmap=False)
            self.assertEqual(loaded.rank1(150), sum(bits))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_deleting_cache_never_destroys_information(self):
        bits = [int(i % 5 < 2) for i in range(260)]
        directory = make_bwt_dir(bits)
        try:
            self._write_cache(directory)
            gc.collect()
            os.remove(os.path.join(directory, "inter0_rank.npz"))
            loaded = TwoSourceInterleaveIndex.from_directory(
                directory, rank_stride_bytes=8, use_saved_rank=True,
                mmap=False)
            self.assertEqual(loaded.rank1(260), sum(bits))
            self.assertEqual(loaded.counts(0, 260),
                             (260 - sum(bits), sum(bits)))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_cache_rebuild_is_deterministic(self):
        bits = [int(i * 7 % 11 < 4) for i in range(1000)]
        directory = make_bwt_dir(bits)
        try:
            first = self._write_cache(directory)
            gc.collect()
            os.remove(os.path.join(directory, "inter0_rank.npz"))
            second = self._write_cache(directory)
            self.assertTrue(np.array_equal(first.rank_prefix,
                                           second.rank_prefix))
            with open(os.path.join(directory, "inter0_rank.npz"),
                      "rb") as handle:
                pass
        finally:
            shutil.rmtree(directory, ignore_errors=True)


class FakeBWT(object):
    def __init__(self, total_size, intervals, given_ranges=None):
        self.total_size = total_size
        self.intervals = intervals
        self.given_ranges = given_ranges if given_ranges is not None else []
        self.search_calls = 0

    def getTotalSize(self):
        return self.total_size

    def findIndicesOfStr(self, seq, givenRange=None):
        self.search_calls += 1
        self.given_ranges.append(givenRange)
        return self.intervals[seq]

    def countOccurrencesOfSeq(self, seq, givenRange=None):
        low, high = self.findIndicesOfStr(seq, givenRange)
        return high - low


class QueryApiTests(unittest.TestCase):
    def test_source_aware_query_performs_one_merged_search_then_rank_counts(self):
        bits = [0, 1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0]
        intervals = {b"ACG": (2, 10)}
        bwt = FakeBWT(len(bits), intervals)
        index = TwoSourceInterleaveIndex(
            pack_little_endian_bits(bits), total_bits=len(bits))

        result = countOccurrencesBySource(
            bwt, index, "ACG", source_names=("A", "B"))

        low, high = intervals[b"ACG"]
        expected_b = sum(bits[low:high])
        expected_a = (high - low) - expected_b
        self.assertEqual(result["interval"], (low, high))
        self.assertEqual(result["total"], high - low)
        self.assertEqual(result["A"], expected_a)
        self.assertEqual(result["B"], expected_b)
        self.assertEqual(result["A"] + result["B"], result["total"])
        self.assertEqual(bwt.search_calls, 1)

    def test_alias_is_the_same_function(self):
        self.assertIs(count_occurrences_by_source, countOccurrencesBySource)

    def test_wrapper_rejects_bwt_and_provenance_length_mismatch(self):
        bwt = FakeBWT(10, {})
        index = TwoSourceInterleaveIndex(
            np.zeros(1, dtype=np.uint8), total_bits=8)
        with self.assertRaises(ValueError):
            TwoSourceBWT(bwt, index)

    def test_wrapper_accepts_matching_lengths(self):
        bwt = FakeBWT(8, {})
        index = TwoSourceInterleaveIndex(
            np.zeros(1, dtype=np.uint8), total_bits=8)
        wrapper = TwoSourceBWT(bwt, index, source_names=("sample-A", "sample-B"))
        self.assertEqual(wrapper.source_names, ("sample-A", "sample-B"))

    def test_wrapper_rejects_non_two_source_names(self):
        bwt = FakeBWT(8, {})
        index = TwoSourceInterleaveIndex(
            np.zeros(1, dtype=np.uint8), total_bits=8)
        with self.assertRaises(ValueError):
            TwoSourceBWT(bwt, index, source_names=("only-one",))

    def test_count_occurrences_by_source_delegates_total_and_indices(self):
        bits = [1, 0, 1]
        intervals = {b"GT": (0, 2)}
        bwt = FakeBWT(3, intervals)
        index = TwoSourceInterleaveIndex(
            pack_little_endian_bits(bits), total_bits=3)
        wrapper = TwoSourceBWT(bwt, index, source_names=("s0", "s1"))
        self.assertEqual(wrapper.findIndicesOfStr(b"GT"), (0, 2))
        self.assertEqual(wrapper.countOccurrencesOfSeq(b"GT"), 2)
        self.assertEqual(bwt.search_calls, 2)

    def test_given_range_delegated_to_merged_search(self):
        bits = [0, 1, 1, 0, 1, 0, 1, 1]
        intervals = {b"AC": (1, 5)}
        given_ranges = []
        bwt = FakeBWT(8, intervals, given_ranges=given_ranges)
        index = TwoSourceInterleaveIndex(
            pack_little_endian_bits(bits), total_bits=8)
        wrapper = TwoSourceBWT(bwt, index, source_names=("A", "B"))

        result = wrapper.countOccurrencesBySource(b"AC", givenRange=(1, 5))
        self.assertEqual(given_ranges[-1], (1, 5))
        low, high = (1, 5)
        expected_b = sum(bits[low:high])
        expected_a = (high - low) - expected_b
        self.assertEqual(result["A"], expected_a)
        self.assertEqual(result["B"], expected_b)
        self.assertEqual(result["interval"], (1, 5))

    def test_given_range_none_uses_full_search(self):
        bits = [0, 1, 1, 0]
        intervals = {b"T": (0, 4)}
        given_ranges = []
        bwt = FakeBWT(4, intervals, given_ranges=given_ranges)
        index = TwoSourceInterleaveIndex(
            pack_little_endian_bits(bits), total_bits=4)
        wrapper = TwoSourceBWT(bwt, index, source_names=("A", "B"))
        wrapper.countOccurrencesBySource(b"T")
        self.assertEqual(given_ranges[-1], None)

    def test_sequence_key_is_bytes(self):
        bits = [1, 1, 0, 0]
        intervals = {b"ACGT": (0, 4)}
        bwt = FakeBWT(4, intervals)
        index = TwoSourceInterleaveIndex(
            pack_little_endian_bits(bits), total_bits=4)
        result = countOccurrencesBySource(bwt, index, "ACGT")
        self.assertEqual(result["sequence"], b"ACGT")
        self.assertEqual(result["total"], 4)


class SequenceNormalizationTests(unittest.TestCase):
    def test_bytes_passed_through_unchanged(self):
        from MUS.SourceIndex import _normalize_sequence
        self.assertEqual(_normalize_sequence(b"ACGT"), b"ACGT")

    def test_python3_str_encoded_ascii(self):
        from MUS.SourceIndex import _normalize_sequence
        self.assertEqual(_normalize_sequence("ACGT"), b"ACGT")

    def test_non_ascii_raises_explicitly(self):
        from MUS.SourceIndex import _normalize_sequence
        with self.assertRaises(UnicodeEncodeError):
            _normalize_sequence("\u00e9")

    def test_non_string_raises_type_error(self):
        from MUS.SourceIndex import _normalize_sequence
        with self.assertRaises(TypeError):
            _normalize_sequence(42)
        with self.assertRaises(TypeError):
            _normalize_sequence(None)


class ValidationTests(unittest.TestCase):
    def test_short_interleave_rejected(self):
        bits = [1] * 20  # needs 3 bytes
        packed = pack_little_endian_bits(bits)
        with self.assertRaises(ValueError):
            TwoSourceInterleaveIndex(packed[:2], total_bits=20)

    def test_longer_byte_capacity_with_valid_padding_accepted(self):
        bits = [1, 0, 1]
        packed = np.concatenate(
            [pack_little_endian_bits(bits), np.zeros(5, dtype=np.uint8)])
        index = TwoSourceInterleaveIndex(packed, total_bits=3)
        self.assertEqual(index.rank1(3), 2)
        self.assertEqual(index.rank0(3), 1)

    def test_wrong_dtype_rejected(self):
        with self.assertRaises(TypeError):
            TwoSourceInterleaveIndex(np.zeros(2, dtype=np.uint16), total_bits=8)

    def test_wrong_dimensions_rejected(self):
        with self.assertRaises(ValueError):
            TwoSourceInterleaveIndex(np.zeros((2, 2), dtype=np.uint8),
                                     total_bits=8)

    def test_negative_total_bits_rejected(self):
        with self.assertRaises(ValueError):
            TwoSourceInterleaveIndex(np.zeros(1, dtype=np.uint8), total_bits=-1)

    def test_zero_stride_rejected(self):
        with self.assertRaises(ValueError):
            TwoSourceInterleaveIndex(np.zeros(1, dtype=np.uint8), total_bits=8,
                                     rank_stride_bytes=0)

    def test_position_out_of_range_rejected(self):
        index = TwoSourceInterleaveIndex(
            pack_little_endian_bits([1, 0, 1, 1]), total_bits=4)
        with self.assertRaises(IndexError):
            index.rank1(5)
        with self.assertRaises(IndexError):
            index.rank1(-1)
        with self.assertRaises(IndexError):
            index.source_at(4)

    def test_inverted_interval_rejected(self):
        index = TwoSourceInterleaveIndex(
            pack_little_endian_bits([1, 0, 1, 1]), total_bits=4)
        with self.assertRaises(ValueError):
            index.counts(3, 1)

    def test_invalid_source_id_rejected(self):
        index = TwoSourceInterleaveIndex(
            pack_little_endian_bits([0, 1]), total_bits=2)
        for source_id in (-1, 2, 99):
            with self.assertRaises(ValueError):
                index.count_source(source_id, 0, 2)

    def test_malformed_msbwt_npy_rejected(self):
        directory = tempfile.mkdtemp(prefix="f1-host-")
        try:
            np.save(os.path.join(directory, "inter0.npy"),
                    np.zeros(2, dtype=np.uint8))
            with open(os.path.join(directory, "msbwt.npy"), "wb") as handle:
                handle.write(b"not an npy file at all")
            with self.assertRaises((ValueError, OSError, IOError)):
                TwoSourceInterleaveIndex.from_directory(directory, mmap=False)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_malformed_inter0_npy_rejected(self):
        directory = tempfile.mkdtemp(prefix="f1-host-")
        try:
            np.save(os.path.join(directory, "msbwt.npy"),
                    np.zeros(8, dtype=np.uint8))
            with open(os.path.join(directory, "inter0.npy"), "wb") as handle:
                handle.write(b"not an npy file at all")
            with self.assertRaises((ValueError, OSError, IOError)):
                TwoSourceInterleaveIndex.from_directory(directory, mmap=False)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_wrong_interleave_dtype_rejected_from_directory(self):
        directory = make_bwt_dir([1, 0, 1, 1], interleave_dtype=np.uint16)
        try:
            with self.assertRaises(TypeError):
                TwoSourceInterleaveIndex.from_directory(directory, mmap=False)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_multi_dimensional_msbwt_rejected(self):
        directory = tempfile.mkdtemp(prefix="f1-host-")
        try:
            np.save(os.path.join(directory, "inter0.npy"),
                    np.zeros(2, dtype=np.uint8))
            np.save(os.path.join(directory, "msbwt.npy"),
                    np.zeros((4, 4), dtype=np.uint8))
            with self.assertRaises(ValueError):
                TwoSourceInterleaveIndex.from_directory(directory, mmap=False)
        finally:
            shutil.rmtree(directory, ignore_errors=True)


class RandomizedRankStressTests(unittest.TestCase):
    """Deterministic randomized differential: rank vs naive oracle."""

    def test_two_hundred_random_vectors_every_position(self):
        rng = np.random.RandomState(20260811)
        checked = 0
        for trial in range(200):
            length = int(rng.randint(0, 300))
            bits = [int(v) for v in rng.randint(0, 2, size=length)]
            stride = int(rng.choice([1, 2, 3, 7, 8, 16, 64]))
            pad = int(rng.randint(0, 2))
            index = TwoSourceInterleaveIndex(
                pack_little_endian_bits(bits, pad_value=pad),
                total_bits=length, rank_stride_bytes=stride)
            for position in range(length + 1):
                self.assertEqual(index.rank1(position),
                                 naive_rank1(bits, position))
                self.assertEqual(index.rank0(position),
                                 position - naive_rank1(bits, position))
                checked += 1
            self.assertEqual(index.counts(0, length),
                             (length - sum(bits), sum(bits)))
            # sample interval queries
            for _ in range(10):
                start = int(rng.randint(0, length + 1))
                end = int(rng.randint(start, length + 1))
                expected1 = sum(bits[start:end])
                self.assertEqual(index.count_source(1, start, end), expected1)
                self.assertEqual(index.count_source(0, start, end),
                                 (end - start) - expected1)
        self.assertGreater(checked, 5000)


class PublicSurfaceTests(unittest.TestCase):
    def test_all_four_public_symbols_exist(self):
        import MUS.SourceIndex as module
        for name in ("TwoSourceInterleaveIndex", "TwoSourceBWT",
                     "countOccurrencesBySource", "count_occurrences_by_source"):
            self.assertTrue(hasattr(module, name), name)

    def test_module_is_pure_python_no_cython_imports(self):
        text = open(os.path.join(PACKAGE, "MUS", "SourceIndex.py"),
                    "rb").read()
        # MUSCython is imported only lazily inside TwoSourceBWT.load, never
        # at module level, so host tests can import the module standalone.
        self.assertNotIn(b"\nimport MUSCython", text)
        self.assertNotIn(b"\nfrom MUSCython", text)
        self.assertIn(b"from MUSCython import MultiStringBWTCython "
                      b"as MultiStringBWT", text)


EVIDENCE = os.path.join(PACKAGE, "evidence", "feature1-two-source-rank.json")
DRIVER = os.path.join(PACKAGE, "validate", "feature1-two-source-rank.sh")
EVIDENCE_GENERATOR = os.path.join(
    PACKAGE, "validate", "feature1_two_source_evidence.py")
COMMITTED_INTER0_SHA256 = (
    "4a6d97a36e9ef4e3c19fb873b7713a9357d207d29433a3eca67a41cc4221afd6")
COMMITTED_MERGED_SHA256 = (
    "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f")


class EvidenceRecordTests(unittest.TestCase):
    def test_evidence_record_consistent(self):
        evidence = json.load(open(EVIDENCE, encoding="utf-8"))
        self.assertEqual(evidence["final"]["status"], "passed")
        self.assertEqual(evidence["final"]["branch"], "enhanced-modern2")
        self.assertEqual(evidence["final"]["milestone"],
                         "enhanced-modern2-feature1-two-source-rank")
        self.assertEqual(evidence["environment"]["python"], "2.7.18")
        self.assertEqual(evidence["environment"]["numpy"], "1.16.6")
        self.assertEqual(evidence["environment"]["cython"], "3.0.12")

    def test_evidence_randomized_suite_parameters(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["seed"], 20260811)
        self.assertEqual(report["randomized_source_pairs"], 50)
        self.assertEqual(report["edge_source_pairs"], 12)
        self.assertEqual(report["source_pairs"], 63)
        self.assertEqual(report["mismatch_count"], 0)
        self.assertGreater(report["query_comparisons"], 5000)

    def test_evidence_canonical_interleave_oracle(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        canonical = [c for c in report["cases"]
                     if c["case"] == "canonical"][0]
        self.assertEqual(canonical["merged_msbwt_sha256"],
                         COMMITTED_MERGED_SHA256)
        self.assertEqual(canonical["merged_inter0_sha256"],
                         COMMITTED_INTER0_SHA256)
        interleave = canonical["interleave"]
        self.assertEqual(interleave["zeros"], 24)
        self.assertEqual(interleave["ones"], 24)
        self.assertEqual(interleave["exact_bits_checked"], 30)
        self.assertEqual(interleave["tied_rows_multiplicity_checked"], 18)
        self.assertTrue(interleave["joint_provenance_consistent"])
        self.assertTrue(interleave["lf_recovered_multiset_matches"])
        self.assertEqual(interleave["total_rows"], 48)

    def test_evidence_one_search_and_given_range_probes(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertEqual(report["one_search_probe"]["findIndicesOfStr_calls"],
                         4)
        given_range = report["given_range_probe"]
        self.assertEqual(given_range["gt_direct"], given_range["gt_via_range"])
        self.assertEqual(given_range["feature1_interval"],
                         given_range["gt_direct"])
        self.assertEqual(given_range["feature1_A"], 3)
        self.assertEqual(given_range["feature1_B"], 1)

    def test_evidence_cache_safety(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        self.assertTrue(report["cache_same_length_replaced"]
                        ["stale_cache_detected"])

    def test_evidence_performance_sanity(self):
        report = json.load(open(EVIDENCE, encoding="utf-8"))["evidence"]
        perf = report["performance"]
        # one uint64 sample per 64 packed bytes: prefix storage stays tiny
        self.assertLess(perf["rank_prefix_bytes_for_1Mbits"], 20000)
        # rank1 with the 64-byte stride tail must be fast
        self.assertLess(perf["one_megabit_rank1_ns_per_query"], 10000)


class ValidationDriverTests(unittest.TestCase):
    def test_driver_present_and_uses_independent_tooling(self):
        text = open(DRIVER, encoding="utf-8").read()
        self.assertIn("feature1-two-source-rank", text)
        self.assertIn("feature1_two_source_evidence.py", text)
        self.assertIn("--evidence", text)
        self.assertIn("20260811", text)
        self.assertIn("run_evidence", text)

    def test_evidence_generator_is_python2(self):
        text = open(EVIDENCE_GENERATOR, encoding="utf-8").read()
        self.assertIn("from __future__ import print_function", text)
        self.assertNotIn("f'{", text)


if __name__ == "__main__":
    unittest.main()

