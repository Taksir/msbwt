"""Host-side tests for roadmap 8B.0: the bidirectional (2BWT) correctness
prototype (``MUS.Bidirectional``).

Gate (roadmap step 10):

    bidir_extend_left(P, c)  == ordinary_search(cP)
    bidir_extend_right(P, c) == ordinary_search(Pc)

checked on both intervals of the state for every intermediate pattern, plus
an independent string oracle for the occurrence count.  Edge cases from the
roadmap: duplicate reads, N-containing reads, full-read matches, read-end
boundaries, empty intervals, every alphabet symbol, and source-specific
intervals.  Real Holt construction (Multimerge) and the compiled loader
are used, so the module skips when the extensions are not built.
"""

import itertools
import json
import logging
import os
import random
import shutil
import tempfile
import unittest

try:
    from MUSCython import MultimergeCython
    from MUSCython import MultiStringBWTCython  # noqa: F401
    HAVE_COMPILED = True
except ImportError:
    HAVE_COMPILED = False

try:
    from MUS import Bidirectional as bd
except ImportError:  # selected package predates 8B.0
    bd = None

import test_multisource_query as f3  # noqa: E402
import test_read_provenance as f9  # noqa: E402

READS = [
    "ACGTACGTTA", "GGACGTAC", "TTTT", "CACGTACGA", "ACGTACGTTA",  # duplicate
    "A", "NNACGT", "ACGTNACG", "TTTTA", "GTAC",
]


def count_occurrences(reads, pattern):
    return sum(f9.overlapping_count(r, pattern) for r in reads)


def build_index(directory, reads):
    os.makedirs(directory)
    MultimergeCython.createMSBWTFromSeqs(
        [r + "$" for r in reads], directory, 1, False,
        logging.getLogger("test-bidirectional"))
    return directory


def grow(index, pattern, seed, order):
    """Build ``pattern`` from the empty state: start at ``seed`` and apply
    ``order`` ('L'/'R'), yielding (substring, state) after every step."""
    state = index.empty_pattern()
    i = j = seed
    for step in order:
        if (step == "L" and i > 0) or j == len(pattern):
            i -= 1
            state = index.extend_left(state, pattern[i:i + 1])
        else:
            state = index.extend_right(state, pattern[j:j + 1])
            j += 1
        yield pattern[i:j], state


@unittest.skipUnless(bd is not None, "8B.0 not in the selected package")
@unittest.skipUnless(HAVE_COMPILED, "compiled MUSCython extensions not built")
class TwoBWTTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="bidir-")
        cls.forward = build_index(os.path.join(cls.work, "F"), READS)
        cls.reverse = os.path.join(cls.work, "R")
        cls.metadata = bd.build_reverse_companion(cls.forward, cls.reverse)
        cls.index = bd.BidirectionalIndex.load(cls.forward, cls.reverse)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def assert_state(self, pattern, state):
        expected = self.index.search(pattern)
        self.assertEqual(state, expected, pattern)
        self.assertEqual(
            state.size, count_occurrences(READS, pattern.decode()), pattern)

    def test_companion_holds_reversed_reads(self):
        self.assertEqual(self.metadata["read_count"], len(READS))
        companion = MultiStringBWTCython.loadBWT(self.reverse)
        recovered = sorted(
            bytes(companion.recoverString(i))[1:].decode()
            for i in range(len(READS)))
        self.assertEqual(recovered, sorted(r[::-1] for r in READS))

    def test_exhaustive_short_patterns_every_order(self):
        checked = 0
        for k in range(1, 4):
            for letters in itertools.product("ACGNT", repeat=k):
                pattern = "".join(letters).encode()
                for seed in range(k + 1):
                    for order in itertools.product("LR", repeat=k):
                        for sub, state in grow(
                                self.index, pattern, seed, order):
                            self.assertEqual(
                                state, self.index.search(sub), (sub, order))
                        self.assert_state(pattern, state)
                        checked += 1
        # sum over k of 5^k patterns * (k+1) seeds * 2^k orders
        self.assertEqual(checked, 4320)

    def test_read_substrings_and_full_reads(self):
        rng = random.Random(20261008)
        for read in READS:
            for i in range(len(read)):
                for j in range(i + 1, len(read) + 1):
                    pattern = read[i:j].encode()
                    seed = rng.randint(0, len(pattern))
                    order = [rng.choice("LR") for _ in pattern]
                    for _, state in grow(self.index, pattern, seed, order):
                        pass
                    self.assert_state(pattern, state)

    def test_read_end_boundaries_and_empty_intervals(self):
        # "TTTT" is a full read; extending right past its end needs an
        # occurrence that continues, which only "TTTTA" provides.
        state = self.index.search(b"TTTT")
        children = self.index.extend_right_all(state)
        self.assertEqual(children[b"A"].size, 1)
        for symbol in b"CGNT":
            self.assertEqual(children[bytes([symbol])].size, 0)
        # Left of "NN" there is only a read start.
        left = self.index.extend_left_all(self.index.search(b"NN"))
        self.assertTrue(all(s.size == 0 for s in left.values()))
        empty = self.index.search(b"GGGG")
        self.assertEqual(empty, bd.BiInterval(0, 0, 0))
        self.assertEqual(self.index.extend_left(empty, "A"), empty)
        self.assertEqual(self.index.extend_right(empty, "T"), empty)

    def test_children_partition_the_parent(self):
        for pattern in (b"A", b"AC", b"T", b"TT", b"N", b"GTAC"):
            state = self.index.search(pattern)
            for side in ("left", "right"):
                children = getattr(self.index, "extend_%s_all" % side)(state)
                self.assertEqual(sorted(children), [bytes([b]) for b in
                                                    b"ACGNT"])
                total = sum(c.size for c in children.values())
                boundary = count_occurrences(
                    [r for r in READS], pattern.decode()) - total
                # The remainder is occurrences touching a read end.
                ends = sum(
                    1 for r in READS for i in range(len(r))
                    if r.startswith(pattern.decode(), i)
                    and (i == 0 if side == "left"
                         else i + len(pattern) == len(r)))
                self.assertEqual(boundary, ends, (pattern, side))

    def test_invalid_input(self):
        state = self.index.empty_pattern()
        for bad in ("$", "AC", "X", ""):
            with self.assertRaises(bd.BidirectionalError):
                self.index.extend_left(state, bad)
        with self.assertRaises(bd.BidirectionalError):
            self.index.search("AC$")

    def test_binding_rejects_stale_or_reused_companion(self):
        with self.assertRaises(bd.BidirectionalError):
            bd.build_reverse_companion(self.forward, self.reverse)
        other = build_index(os.path.join(self.work, "other"), ["ACGT"])
        with self.assertRaises(bd.BidirectionalError):
            bd.BidirectionalIndex.load(other, self.reverse)
        copy = os.path.join(self.work, "R_copy")
        shutil.copytree(self.reverse, copy)
        meta_path = os.path.join(copy, bd.COMPANION_METADATA)
        with open(meta_path) as fp:
            doc = json.load(fp)
        doc["companion_bwt_sha256"] = "0" * 64
        with open(meta_path, "w") as fp:
            json.dump(doc, fp)
        with self.assertRaises(bd.BidirectionalError):
            bd.BidirectionalIndex.load(self.forward, copy)


@unittest.skipUnless(bd is not None, "8B.0 not in the selected package")
@unittest.skipUnless(HAVE_COMPILED, "compiled MUSCython extensions not built")
class SourceAwareTwoBWTTests(unittest.TestCase):
    """The forward side of every state is an ordinary merged interval, so
    source queries and 8A extensions apply to it directly."""

    @classmethod
    def setUpClass(cls):
        from MUS.MultiSourceQuery import MultiSourceBWT, MultiSourceQueryIndex
        cls.work = tempfile.mkdtemp(prefix="bidir-src-")
        cls.leaves, cls.output, cls.manifest, cls.oracle = (
            f9.build_fixture_with_reads(cls.work, f3.TEN_SOURCE_READS))
        cls.reverse = os.path.join(cls.work, "R")
        bd.build_reverse_companion(cls.output, cls.reverse)
        cls.index = bd.BidirectionalIndex.load(cls.output, cls.reverse)
        cls.sources = MultiSourceQueryIndex(cls.output)
        cls.wrapped = MultiSourceBWT(
            MultiStringBWTCython.loadBWT(cls.output), cls.sources)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def test_source_counts_from_bidirectional_state(self):
        rng = random.Random(20261009)
        patterns = set()
        for reads in f3.TEN_SOURCE_READS.values():
            for read in reads:
                for i in range(len(read)):
                    patterns.add(read[i:i + rng.randint(1, 4)])
        for pattern in sorted(patterns):
            order = [rng.choice("LR") for _ in pattern]
            seed = rng.randint(0, len(pattern))
            for _, state in grow(self.index, pattern.encode(), seed, order):
                pass
            for sid, reads in f3.TEN_SOURCE_READS.items():
                expected = sum(f9.overlapping_count(r, pattern)
                               for r in reads)
                got = (self.sources.count_interval(
                    sid, state.forward, state.forward + state.size)
                    if state.size else 0)
                self.assertEqual(got, expected, (pattern, sid))

    def test_matches_8a_right_extension(self):
        for pattern in ("A", "AC", "GT", "TAC", "CAT", "N"):
            state = self.index.search(pattern)
            children = self.index.extend_right_all(state)
            reference = self.wrapped.extendRight(pattern, alphabet="ACGNT")
            for record in reference["extensions"]:
                self.assertEqual(
                    children[record["base"]].size, record["count"],
                    (pattern, record["base"]))


if __name__ == "__main__":
    unittest.main()
