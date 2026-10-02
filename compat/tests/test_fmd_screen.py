"""Host-side tests for the FMD feasibility screen (``MUS.Bidirectional``
with ``build_fmd_index`` / ``BidirectionalIndex.load_fmd``).

The screen asks whether FMD-index bidirectional search is exact on Holt's
``$ACGNT`` alphabet (``N`` is its own complement and sorts between ``G``
and ``T``, so complementing does not reverse the symbol order).  The same
extension code as the 2BWT prototype is used with the reverse-complement
transform.

Oracles: occurrence counts over both strands of the original reads, plus
the FMD symmetry ``state(revcomp(P)) == state(P)`` with sides swapped.
"""

import itertools
import os
import random
import shutil
import tempfile
import unittest

try:
    from MUSCython import MultimergeCython  # noqa: F401
    HAVE_COMPILED = True
except ImportError:
    HAVE_COMPILED = False

try:
    from MUS import Bidirectional as bd
    HAS_FMD = hasattr(bd, "build_fmd_index")
except ImportError:
    bd = None
    HAS_FMD = False

import test_bidirectional as t2  # noqa: E402
import test_multisource_query as f3  # noqa: E402
import test_read_provenance as f9  # noqa: E402

READS = t2.READS + ["ACGT", "AACGTT", "GAATTC"]   # palindromes included


def revcomp(text):
    return text[::-1].translate(str.maketrans("ACGNT", "TGCNA"))


def both_strand_count(reads, pattern):
    return (t2.count_occurrences(reads, pattern)
            + t2.count_occurrences(reads, revcomp(pattern)))


@unittest.skipUnless(HAS_FMD, "FMD screen not in the selected package")
@unittest.skipUnless(HAVE_COMPILED, "compiled MUSCython extensions not built")
class FMDScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="fmd-")
        cls.forward = t2.build_index(os.path.join(cls.work, "F"), READS)
        cls.fmd_dir = os.path.join(cls.work, "FMD")
        cls.metadata = bd.build_fmd_index(cls.forward, cls.fmd_dir)
        cls.index = bd.BidirectionalIndex.load_fmd(cls.fmd_dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def assert_state(self, pattern, state):
        self.assertEqual(state, self.index.search(pattern), pattern)
        self.assertEqual(
            state.size, both_strand_count(READS, pattern.decode()), pattern)
        mirror = self.index.search(revcomp(pattern.decode()))
        self.assertEqual(
            (mirror.forward, mirror.reverse, mirror.size),
            (state.reverse, state.forward, state.size), pattern)

    def test_index_holds_both_strands(self):
        self.assertEqual(self.metadata["read_count"], 2 * len(READS))
        self.assertEqual(self.index.total,
                         2 * sum(len(r) + 1 for r in READS))

    def test_exhaustive_short_patterns_every_order(self):
        checked = 0
        for k in range(1, 4):
            for letters in itertools.product("ACGNT", repeat=k):
                pattern = "".join(letters).encode()
                for seed in range(k + 1):
                    for order in itertools.product("LR", repeat=k):
                        for sub, state in t2.grow(
                                self.index, pattern, seed, order):
                            self.assertEqual(
                                state, self.index.search(sub), (sub, order))
                        self.assert_state(pattern, state)
                        checked += 1
        self.assertEqual(checked, 4320)

    def test_read_substrings_palindromes_and_n(self):
        rng = random.Random(20261010)
        for read in READS:
            for i in range(len(read)):
                for j in range(i + 1, len(read) + 1):
                    pattern = read[i:j].encode()
                    order = [rng.choice("LR") for _ in pattern]
                    for _, state in t2.grow(
                            self.index, pattern,
                            rng.randint(0, len(pattern)), order):
                        pass
                    self.assert_state(pattern, state)
        for palindrome in (b"ACGT", b"AATT", b"GAATTC", b"N", b"NN"):
            state = self.index.search(palindrome)
            self.assertEqual(state.forward, state.reverse, palindrome)

    def test_rejects_wrong_or_modified_index(self):
        with self.assertRaises(bd.BidirectionalError):
            bd.build_fmd_index(self.forward, self.fmd_dir)
        with self.assertRaises(bd.BidirectionalError):
            bd.BidirectionalIndex.load_fmd(self.forward)


@unittest.skipUnless(HAS_FMD, "FMD screen not in the selected package")
@unittest.skipUnless(HAVE_COMPILED, "compiled MUSCython extensions not built")
class FMDFromMergedFixtureTests(unittest.TestCase):
    """FMD from a 10-source merged package: counts are exact, but source
    identity is gone, which is the semantic cost the screen records."""

    def test_counts_match_both_strands(self):
        work = tempfile.mkdtemp(prefix="fmd-src-")
        try:
            _, output, _, _ = f9.build_fixture_with_reads(
                work, f3.TEN_SOURCE_READS)
            fmd_dir = os.path.join(work, "FMD")
            bd.build_fmd_index(output, fmd_dir)
            index = bd.BidirectionalIndex.load_fmd(fmd_dir)
            reads = [r for rs in f3.TEN_SOURCE_READS.values() for r in rs]
            for k in (1, 2, 3):
                for letters in itertools.product("ACGT", repeat=k):
                    pattern = "".join(letters)
                    self.assertEqual(index.search(pattern).size,
                                     both_strand_count(reads, pattern))
            self.assertFalse(os.path.exists(
                os.path.join(fmd_dir, "provenance.json")))
        finally:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
