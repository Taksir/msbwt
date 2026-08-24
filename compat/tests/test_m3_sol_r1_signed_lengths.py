"""M3-SOL-R1 regressions: LLP64-safe compiled sequence/pattern LENGTH domain.

SOL HIGH final audit finding D1: on native Win64 (LLP64),
``sizeof(long) == sizeof(unsigned long) == 4``, so every
``cdef unsigned long s = len(seq)`` / ``cdef long x`` in the active query
paths wrapped reported pattern lengths >= 2**32 (a 2**32 probe behaved as the
empty pattern).  The repaired contract (docs/modernization/NUMERIC_WIDTH_POLICY.md,
"Signed length/difference" row) is ``Py_ssize_t`` for every scalar that
represents ``len(...)`` or a derived pattern position.

These tests prove, without allocating multi-GiB strings:

1. *Length transport* -- compiled probes inside BasicBWT.pyx /
   AlignmentUtil.pyx execute the exact production declarations/arithmetic
   (``s = len(seq)``; descending loop bound) against hostile reported lengths
   at 2^31-1 .. 2^32+12345 and must preserve them exactly (2**32 does NOT
   become 0; 2**32+1 does NOT become 1) and must start iterating (NOT the
   empty-pattern short-circuit).
2. *Ordinary semantics* -- the real production query entry points
   (countOccurrencesOfSeq / findIndicesOfStr / findStrWithError /
   countPileup / LCP-assisted counting / AlignmentUtil tracebacks) still
   agree with independent naive or frozen-Modern2 oracles on
   empty, one-symbol, multi-symbol, absent and longer-than-read patterns
   over duplicate-heavy input, on both Byte BWT and RLE BWT readers.
"""

import os
import shutil
import struct
import tempfile
import unittest

import numpy as np

from MUSCython import AlignmentUtil
from MUSCython import BasicBWT
from MUSCython import CompressToRLE
from MUSCython import MultiStringBWTCython as MSB

loadBWT = MSB.loadBWT
LOGGER = None

# The mandatory >2^32 boundary grid from the SOL HIGH repair order.
BOUNDARY_VALUES = [
    2 ** 31 - 1,
    2 ** 31,
    2 ** 32 - 1,
    2 ** 32,
    2 ** 32 + 1,
    2 ** 32 + 12345,
]

READS = ["ACGTAC", "ACGTAC", "GGATCCA", "TTGCA", "TTGCA", "NNNN"]
ALPHABET = "$ACGNT"


class _ReportedLengthStr(str):
    """A str whose REAL content is tiny but whose reported len() is huge.

    Crossing this object through the compiled boundary exercises the exact
    ``len(seq)`` transport used by the production query paths without ever
    allocating a 4-billion-character string.
    """

    def __new__(cls, content, reported_length):
        obj = super(_ReportedLengthStr, cls).__new__(cls, content)
        obj._reported_length = reported_length
        return obj

    def __len__(self):
        return self._reported_length


def naive_overlapping_count(reads, pattern):
    # Independent oracle: overlapping occurrences across all input reads.
    # Empty-pattern FM semantics cover the whole terminated index, so the
    # expected count is the total row count.
    if pattern == "":
        return sum(len(r) + 1 for r in reads)
    return sum(_naive_window_count(r, pattern) for r in reads)


def _naive_window_count(text, pattern):
    if pattern == "":
        return len(text) + 1
    return sum(1 for i in range(0, len(text) - len(pattern) + 1)
               if text[i:i + len(pattern)] == pattern)


def _write_bwt_text(work, name, symbols):
    src_fn = os.path.join(work, name + ".txt")
    with open(src_fn, "w", newline="") as fp:
        fp.write("".join(ALPHABET[int(s)] for s in symbols))
    return src_fn


class LengthTransportBoundaryTests(unittest.TestCase):
    """Compiled length-domain transport at hostile reported lengths."""

    def test_basicbwt_seq_length_transport_preserves_boundaries(self):
        for value in BOUNDARY_VALUES:
            observed, iterations = BasicBWT.sol_r1_seq_length_transport(
                _ReportedLengthStr("A", value))
            self.assertEqual(observed, value, value)
            # An LLP64 narrowing through 32-bit long/unsigned long would
            # report value % 2**32 here (2**32 -> 0, 2**32+1 -> 1).
            if value >= 2 ** 32:
                self.assertNotEqual(observed, value % 2 ** 32, value)

    def test_basicbwt_loop_starts_no_empty_pattern_shortcut(self):
        # The descending loop bound arithmetic must actually start iterating;
        # zero iterations is exactly the empty-pattern behavior that the
        # installed-wheel audit probe exposed.
        for value in BOUNDARY_VALUES:
            observed, iterations = BasicBWT.sol_r1_seq_length_transport(
                _ReportedLengthStr("A", value))
            self.assertGreater(iterations, 0, value)
            self.assertEqual(iterations, 3, value)

    def test_basicbwt_small_and_empty_lengths(self):
        self.assertEqual(BasicBWT.sol_r1_seq_length_transport(""), (0, 0))
        self.assertEqual(BasicBWT.sol_r1_seq_length_transport("A"), (1, 1))
        self.assertEqual(BasicBWT.sol_r1_seq_length_transport("ACGT"), (4, 3))

    def test_alignmentutil_length_transport_preserves_boundaries(self):
        for value in BOUNDARY_VALUES:
            big = _ReportedLengthStr("A", value)
            o_len, m_len, o1, m1 = AlignmentUtil.sol_r1_align_length_transport(
                big, big)
            self.assertEqual(o_len, value, value)
            self.assertEqual(m_len, value, value)
            self.assertEqual(o1, value + 1, value)
            self.assertEqual(m1, value + 1, value)

    def test_alignmentutil_small_lengths(self):
        self.assertEqual(
            AlignmentUtil.sol_r1_align_length_transport("", "AC"),
            (0, 2, 1, 3))
        self.assertEqual(
            AlignmentUtil.sol_r1_align_length_transport("ACGT", "ACGT"),
            (4, 4, 5, 5))

    def test_alignment_traceback_store_and_difference_boundaries(self):
        for value in BOUNDARY_VALUES:
            stored, difference, accumulated, itemsize = (
                AlignmentUtil.sol_r1_traceback_width_transport(value))
            self.assertEqual(
                (stored, difference, accumulated),
                (value, value, value),
                value)
            self.assertEqual(itemsize, 8)


class ProductionQuerySemanticsTests(unittest.TestCase):
    """Ordinary (<2^32) query semantics unchanged after the width repair."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="m3-sol-r1-lengths-")
        import test_multisource_query as f3
        self.f3 = f3
        self.directory = f3.make_read_derived_leaf(self.work, "pkg", READS)
        self.bwt = loadBWT(self.directory, False, LOGGER)
        self.total_rows = sum(len(r) + 1 for r in READS)

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_empty_pattern_contract(self):
        # Established BasicBWT semantics: an empty pattern never enters the
        # loop and returns the full interval width.
        self.assertEqual(int(self.bwt.countOccurrencesOfSeq("")),
                         self.total_rows)
        low, high = self.bwt.findIndicesOfStr("")
        self.assertEqual((int(low), int(high)), (0, self.total_rows))

    def test_one_symbol_pattern_matches_naive_oracle(self):
        for sym in ("A", "C", "G", "T", "N"):
            expected = naive_overlapping_count(READS, sym)
            observed = int(self.bwt.countOccurrencesOfSeq(sym))
            self.assertEqual(observed, expected, sym)

    def test_multi_symbol_patterns_match_naive_oracle(self):
        patterns = ["AC", "CG", "ACGT", "ACGTAC", "TGCA", "GGAT", "NN",
                    "ACGTACG"]  # last one longer than some reads
        for pattern in patterns:
            expected = naive_overlapping_count(READS, pattern)
            observed = int(self.bwt.countOccurrencesOfSeq(pattern))
            self.assertEqual(observed, expected, pattern)
            low, high = self.bwt.findIndicesOfStr(pattern)
            self.assertEqual(int(high) - int(low), expected, pattern)

    def test_absent_pattern_returns_zero(self):
        for pattern in ("AAAAAAAA", "TTTTTTTT", "GCGCGCGC", "ACACACAC"):
            self.assertEqual(int(self.bwt.countOccurrencesOfSeq(pattern)),
                             0, pattern)

    def test_longer_than_read_pattern_returns_zero(self):
        longest = max(len(r) for r in READS)
        pattern = "ACGTACGTACGT"[:longest + 5]
        self.assertGreater(len(pattern), longest)
        self.assertEqual(int(self.bwt.countOccurrencesOfSeq(pattern)), 0)

    def test_duplicate_heavy_counts_exact(self):
        # ACGTAC appears twice; TTGCA twice -- duplicates with identical
        # rows must each be counted.
        self.assertEqual(int(self.bwt.countOccurrencesOfSeq("ACGTAC")), 2)
        self.assertEqual(int(self.bwt.countOccurrencesOfSeq("TTGCA")), 2)
        self.assertEqual(int(self.bwt.countOccurrencesOfSeq("ACGTA")), 2)

    def test_find_str_with_error_still_returns_dollar_ranges(self):
        results = self.bwt.findStrWithError("ACGTAC", "A")
        self.assertTrue(results)
        for low, high in results:
            self.assertLessEqual(int(low), int(high))

    def test_count_pileup_str_and_bytes_match_independent_oracle(self):
        seq = "ACGTAC"
        kmer_size = 2
        expected = []
        for i in range(len(seq) - kmer_size + 1):
            kmer = seq[i:i + kmer_size]
            reverse = MSB.reverseComplement(kmer)
            expected.append(
                naive_overlapping_count(READS, kmer) +
                naive_overlapping_count(READS, reverse))
        expected = np.asarray(expected, dtype='<u8')
        np.testing.assert_array_equal(
            self.bwt.countPileup(seq, kmer_size), expected)
        np.testing.assert_array_equal(
            self.bwt.countPileup(seq.encode('ascii'), kmer_size), expected)


class AlignmentSemanticsTests(unittest.TestCase):
    """Traceback-width repair preserves frozen Modern2 ordinary outputs."""

    CASES = [
        ("", "", [], [(0, '=')], 0, 0),
        ("A", "A", [(1, '=')], [(1, '=')], 0, 0),
        ("A", "C", [(1, 'X')], [(1, 'X'), (0, '=')], 1, 1),
        ("AC", "A", [(1, '='), (1, 'D')],
         [(1, '='), (1, 'D'), (0, '=')], 1, 2),
        ("A", "AC", [(1, '='), (1, 'I')],
         [(1, '='), (1, 'I'), (0, '=')], 1, 2),
        ("ACGT", "AGT", [(1, '='), (1, 'D'), (2, '=')],
         [(1, '='), (1, 'D'), (2, '=')], 1, 1),
    ]

    def test_alignment_outputs_match_frozen_modern2(self):
        for original, modified, cigar, cigar_no_go, score, changes in self.CASES:
            self.assertEqual(
                AlignmentUtil.fullAlign(original, modified), cigar)
            self.assertEqual(
                AlignmentUtil.fullAlign_noGO(original, modified),
                cigar_no_go)
            self.assertEqual(
                int(AlignmentUtil.fullED_score(original, modified)), score)
            self.assertEqual(
                int(AlignmentUtil.alignChanges(original, modified)), changes)


class LcpAssistedQueryTests(unittest.TestCase):
    """LCP-assisted counting length arithmetic (numCounts etc.) stays correct."""

    # Rotation-distinct reads (see test_m3_r64_w1_lcp_binding: the naive
    # leaf builder breaks ties arbitrarily for degenerate rotations).
    READS = ["ACGTAC", "GGATC", "TTGCA"]
    SEQ = "ACGTACGG"
    KMER_SIZE = 2

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="m3-sol-r1-lcpq-")
        import test_multisource_query as f3
        from MUS.LCP import construct_lcp_from_bwt
        self.directory = f3.make_read_derived_leaf(
            self.work, "pkg", list(self.READS))
        bwt = loadBWT(self.directory, False, None)
        construct_lcp_from_bwt(self.directory, bwt=bwt)
        self.bwt = loadBWT(self.directory, False, None)

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_stranded_counts_match_naive_kmer_oracle(self):
        counts, _other = self.bwt.countStrandedSeqMatches(
            self.SEQ, self.KMER_SIZE)
        self.assertEqual(counts.shape[0],
                         len(self.SEQ) - self.KMER_SIZE + 1)
        for i in range(counts.shape[0]):
            kmer = self.SEQ[i:i + self.KMER_SIZE]
            expected = naive_overlapping_count(self.READS, kmer)
            self.assertEqual(int(counts[i]), expected,
                             (i, kmer, int(counts[i]), expected))

    def test_count_seq_matches_combines_both_strands(self):
        combined, _other = self.bwt.countSeqMatches(self.SEQ, self.KMER_SIZE)
        rev_comp = MSB.reverseComplement(self.SEQ)
        for i in range(combined.shape[0]):
            kmer = self.SEQ[i:i + self.KMER_SIZE]
            mirror = rev_comp[len(rev_comp) - i - 1 -
                              (self.KMER_SIZE - 1):
                              len(rev_comp) - i]
            expected = (naive_overlapping_count(self.READS, kmer) +
                        naive_overlapping_count(self.READS, mirror))
            self.assertEqual(int(combined[i]), expected,
                             (i, kmer, int(combined[i]), expected))


class RleReaderSemanticsTests(unittest.TestCase):
    """The RLE reader shares the repaired BasicBWT length domain."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="m3-sol-r1-rle-")
        import test_multisource_query as f3
        self.reads = ["ACGTAC", "ACGTAC", "TTGCA", "GGGCCCT"]
        directory = f3.make_read_derived_leaf(self.work, "pkg", self.reads)
        symbols = np.load(os.path.join(directory, "msbwt.npy"))
        src_fn = _write_bwt_text(self.work, "stream", symbols)
        out_dir = os.path.join(self.work, "rle")
        os.makedirs(out_dir)
        CompressToRLE.compressInput(src_fn, out_dir)
        self.rle_bwt = loadBWT(out_dir, False, None)
        self.assertIsNotNone(self.rle_bwt)

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_rle_query_semantics_match_naive_oracle(self):
        patterns = ["", "A", "AC", "ACGTAC", "TGCA", "GGGCCC", "TTTTTTTT",
                    "ACGTACGTAC"]
        for pattern in patterns:
            expected = naive_overlapping_count(self.reads, pattern)
            observed = int(self.rle_bwt.countOccurrencesOfSeq(pattern))
            self.assertEqual(observed, expected, pattern)

    def test_rle_count_pileup_matches_independent_oracle(self):
        seq = "ACGTAC"
        kmer_size = 2
        expected = []
        for i in range(len(seq) - kmer_size + 1):
            kmer = seq[i:i + kmer_size]
            reverse = MSB.reverseComplement(kmer)
            expected.append(
                naive_overlapping_count(self.reads, kmer) +
                naive_overlapping_count(self.reads, reverse))
        expected = np.asarray(expected, dtype='<u8')
        np.testing.assert_array_equal(
            self.rle_bwt.countPileup(seq, kmer_size), expected)
        np.testing.assert_array_equal(
            self.rle_bwt.countPileup(seq.encode('ascii'), kmer_size),
            expected)


if __name__ == "__main__":
    unittest.main()
