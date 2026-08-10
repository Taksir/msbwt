"""msbwt-modern2 pure-Python FM reader milestone 6 tests, runnable inside the
pinned Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO
(the validation driver sets it).  These tests validate the fix of the frozen
pure-Python CompressedMSBWT.getFullFMAtIndex fill defect:

    frozen line 725 == modern2 line 726 pre-fix:
        ret += np.bincount(letters[0:x-1], counts[0:x-1], minlength=self.vcLen)

which raised ``TypeError: Cannot cast ufunc add output from dtype('float64')
to dtype('uint64') with casting rule 'same_kind'`` under CPython 2.7.18 /
NumPy 1.16.6 whenever more than one run precedes the target position
(``np.bincount`` with weights returns float64 and NumPy 1.16.6 in-place
same_kind casting rejects float64 -> uint64).  The modern2 fill line is now
the exact-integer accumulation:

    np.add.at(ret, letters[0:x-1], counts[0:x-1])

which matches the typed Cython RLE_BWT reader arithmetic
(``ret_view[prevChar] += prevCount``).

Executed semantic contract for every exercised position:

    pure-Python CompressedMSBWT.getFullFMAtIndex
        == compiled RLE_BWT.getFullFMAtIndex
        == independent FM oracle (startIndex + cumulative symbol counts)

Backward-search query counts (countOccurrencesOfSeq) on the pure reader route
through getOccurrenceOfCharAtIndex -> getFullFMAtIndex and are validated
against the compiled readers and the independent string-level FM oracle.  The
FROZEN original source is not modified and still raises the documented
TypeError at line 725 (historical failure evidence preserved).

NOTE on reader semantics: the tiled evidence primary is a byte string, not a
valid collection BWT, so reader query counts are validated only as
string-level FM counts against an independent backward search; collection
semantics are validated on the committed uniform 48-symbol fixtures.

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import hashlib
import imp
import os
import shutil
import sys
import tempfile
import traceback
import unittest

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

GOLDENS = os.path.join(REPO, "compat", "goldens", "original-0.3.0")
PROFILE = "py27-late-05a7d6d83862"
ROUTE = "pyx-historical-cython"
BYTE_GOLDEN = os.path.join(
    GOLDENS, "uniform-multifile", PROFILE, ROUTE, "build", "artifacts", "msbwt.npy")

EVIDENCE_PRIMARY_SHA256 = "24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35"
RLE_PRIMARY_SHA256 = "681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99"
TOTAL_SIZE = 1056000
REPEAT_COUNT = 22000
BIN_SIZE = 2048
LAST_BIN_START = 1054720  # bin 515 covers [1054720, 1056000)

# boundary positions: beginning, before/at/after an FM bin boundary, around
# the decompression work boundary 1000000, near the end (last bin)
POSITIONS = [0, 1, 2047, 2048, 2049, 999998, 999999, 1000000, 1000001,
             1055998, 1055999]
COLLECTION_POSITIONS = [0, 1, 2, 5, 10, 20, 40, 47]

# string-level FM counts on the tiled payload (independent oracle values)
EXPECTED_FM_COUNTS = {
    "A": 198000, "AC": 37125, "ACGTN": 111, "AAAAA": 243, "AAAAAA": 45,
    "C": 198000, "CG": 37125, "GT": 37125, "GTGGGTTT": 2, "N": 88000,
    "NACGT": 108, "T": 198000, "TTTTT": 249,
}

# committed reader-created side-effect hashes for the >1M byte primary and
# for the 48-symbol byte primary
BYTE_READER_SIDE_EFFECTS_LARGE = {
    "totalCounts.npy": "e7fe29a99498d61a278845772782b10d22256a9556e865704d75a54e160fe348",
    "fmIndex.npy": "16e19742f54504b19ff72d278cea134b6063a0c51eac77f784699659013d8040",
}
BYTE_READER_SIDE_EFFECTS_SMALL = {
    "totalCounts.npy": "ea104b616fe89d7b786acdff7ca0db61f6339a59c31fbf0fff066ad7384c1c2b",
    "fmIndex.npy": "a5b4bf06726fcadf535245d03ef65e04a4a5248d368b3aa53639c190028b933f",
}

# the frozen legacy defect inside pure CompressedMSBWT getFullFMAtIndex
LEGACY_BINCOUNT_ERROR = ("Cannot cast ufunc add output from dtype('float64') "
                         "to dtype('uint64') with casting rule 'same_kind'")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class PureFMReaderTests(unittest.TestCase):
    """Shared fixture: the committed >1M-symbol evidence dataset and the
    48-symbol valid uniform collection.

    The evidence primary is regenerated deterministically (np.tile of the
    committed uniform byte golden, 22000x), hash-checked, and compressed by
    modern2 to the committed RLE primary.  Reader loads always run on
    disposable copies.
    """

    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.work = tempfile.mkdtemp(prefix="modern2-py2-ffm-")
        cls.expected_payload = None
        evidence = np.load(BYTE_GOLDEN, "r")
        tiled = np.tile(evidence, REPEAT_COUNT)
        assert tiled.shape == (TOTAL_SIZE,), tiled.shape
        cls.expected_payload = tiled.tostring()
        cls.col_payload = evidence.tostring()
        evidence_root = os.path.join(cls.work, "evidence")
        os.makedirs(evidence_root)
        np.save(os.path.join(evidence_root, "msbwt.npy"), tiled)
        assert sha256_file(os.path.join(evidence_root, "msbwt.npy")) == EVIDENCE_PRIMARY_SHA256
        cls.rle = os.path.join(cls.work, "rle")
        os.makedirs(cls.rle)
        cls._cli("compress", "-p", "1", evidence_root, cls.rle)
        assert sha256_file(os.path.join(cls.rle, "comp_msbwt.npy")) == RLE_PRIMARY_SHA256
        cls.col = os.path.join(cls.work, "col")
        os.makedirs(cls.col)
        np.save(os.path.join(cls.col, "msbwt.npy"), evidence)
        cls.col_rle = os.path.join(cls.work, "col-rle")
        os.makedirs(cls.col_rle)
        cls._cli("compress", "-p", "1", cls.col, cls.col_rle)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    @classmethod
    def _cli(cls, *argv):
        from MUS import CommandLineInterface
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt"] + list(argv)
            CommandLineInterface.mainRun()
        finally:
            sys.argv = old_argv

    def _fresh_copy(self, src, label):
        dst = os.path.join(self.work, label)
        shutil.copytree(src, dst)
        return dst

    # ------------------------------------------------------------------
    # independent oracles (pure Python, no reader code)
    # ------------------------------------------------------------------
    def _fm_counts(self, payload, kmers):
        symbols = "$ACGNT"
        positions = {}
        for index, symbol in enumerate(symbols):
            positions[symbol] = [pos for pos, value in enumerate(bytearray(payload))
                                 if value == index]
        c_table = {}
        running = 0
        for symbol in symbols:
            c_table[symbol] = running
            running += len(positions[symbol])

        def occ(char, index):
            return sum(1 for pos in positions[char] if pos < index)

        result = {}
        for kmer in kmers:
            lo, hi = 0, len(payload)
            for char in reversed(kmer):
                lo = c_table[char] + occ(char, lo)
                hi = c_table[char] + occ(char, hi)
                if lo >= hi:
                    break
            result[kmer] = hi - lo
        return result

    def _full_fm_oracle(self, payload, index):
        """startIndex + cumulative symbol counts of payload[0:index]."""
        counts = [0] * 6
        payload_bytes = bytearray(payload)
        for pos in range(0, index):
            counts[payload_bytes[pos]] += 1
        result = []
        running = 0
        for sym in range(6):
            result.append(running + counts[sym])
            running += sum(1 for value in payload_bytes if value == sym)
        return result

    def _load_pure(self, rle_dir):
        from MUS.MultiStringBWT import CompressedMSBWT
        msbwt = CompressedMSBWT()
        msbwt.loadMsbwt(rle_dir, logger=None)
        return msbwt

    # ------------------------------------------------------------------
    # dtype / casting root cause
    # ------------------------------------------------------------------
    def test_bincount_float64_inplace_add_typeerror_root_cause(self):
        """np.bincount with weights returns float64, and the in-place add
        `ret += bincount(...)` into the <u8 FM array raises the documented
        TypeError under NumPy 1.16.6.  np.add.at performs the same
        per-symbol accumulation in exact integer arithmetic."""
        import numpy as np
        src = self._fresh_copy(self.rle, "ffm-dtype")
        msbwt = self._load_pure(src)
        index = TOTAL_SIZE - 2  # last bin, preceded by many runs
        binID = index >> msbwt.bitPower
        bwtIndex = msbwt.refFM[binID]
        ret = np.copy(msbwt.partialFM[binID])
        trueIndex = np.sum(ret) - msbwt.offsetSum
        dist = index - trueIndex
        endRange = msbwt.bwt.shape[0]
        letters = np.bitwise_and(msbwt.bwt[bwtIndex:endRange], msbwt.mask)
        counts = np.right_shift(msbwt.bwt[bwtIndex:endRange],
                                msbwt.letterBits, dtype="<u8")
        i = 1
        same = (letters[0:-1] == letters[1:])
        while np.count_nonzero(same) > 0:
            (counts[i:])[same] *= msbwt.numPower
            i += 1
            same = np.bitwise_and(same[0:-1], same[1:])
        cs = np.subtract(np.cumsum(counts), counts)
        x = int(np.searchsorted(cs, dist, "left"))
        self.assertGreater(x, 1)  # more than one run precedes the target
        self.assertEqual(str(ret.dtype), "uint64")
        self.assertEqual(str(counts.dtype), "uint64")
        self.assertEqual(str(letters.dtype), "uint8")
        bc = np.bincount(letters[0:x - 1], counts[0:x - 1],
                         minlength=msbwt.vcLen)
        self.assertEqual(str(bc.dtype), "float64")
        try:
            ret += bc
        except TypeError as exc:
            self.assertIn(LEGACY_BINCOUNT_ERROR, str(exc))
        else:
            self.fail("in-place uint64 += float64 did not raise the "
                      "documented TypeError")
        # np.add.at is exact integer accumulation
        addat = np.copy(ret)
        np.add.at(addat, letters[0:x - 1], counts[0:x - 1])
        self.assertEqual(str(addat.dtype), "uint64")
        self.assertEqual([int(v) for v in addat],
                         [int(v) for v in ret + bc])

    # ------------------------------------------------------------------
    # pure vs compiled vs oracle on the >1M evidence
    # ------------------------------------------------------------------
    def test_pure_getFullFMAtIndex_matches_compiled_and_oracle(self):
        """Pure CompressedMSBWT.getFullFMAtIndex returns a <u8 FM vector
        equal to the compiled RLE_BWT reader and the independent oracle at
        every boundary position."""
        from MUSCython import MultiStringBWTCython as CompiledBWT
        pure = self._load_pure(self._fresh_copy(self.rle, "ffm-pure"))
        crle = CompiledBWT.loadBWT(self._fresh_copy(self.rle, "ffm-crle"),
                                   useMemmap=False, logger=None)
        oracle = self._full_fm_oracle
        for position in POSITIONS:
            ret = pure.getFullFMAtIndex(position)
            self.assertEqual(ret.dtype, "<u8", position)
            self.assertEqual([int(v) for v in ret],
                             [int(v) for v in crle.getFullFMAtIndex(position)],
                             position)
            self.assertEqual([int(v) for v in ret],
                             oracle(self.expected_payload, position), position)

    def test_pure_getFullFMAtIndex_all_symbols_represented(self):
        """The returned FM vector represents all six alphabet symbols (every
        symbol occurs in the tiled payload, so the near-end FM vector has a
        positive occurrence count for each symbol)."""
        pure = self._load_pure(self._fresh_copy(self.rle, "ffm-syms"))
        final_fm = [int(v) for v in pure.getFullFMAtIndex(TOTAL_SIZE - 1)]
        self.assertEqual(len(final_fm), 6)
        self.assertTrue(all(v > 0 for v in final_fm))
        # FM entries are cumulative and non-decreasing
        self.assertEqual(final_fm, sorted(final_fm))

    def test_pure_backward_search_queries_match_independent_oracle(self):
        """Pure CompressedMSBWT.countOccurrencesOfSeq routes through
        getFullFMAtIndex and matches the independent string-level FM oracle
        and the compiled RLE reader on the >1M evidence."""
        from MUSCython import MultiStringBWTCython as CompiledBWT
        pure = self._load_pure(self._fresh_copy(self.rle, "ffm-q"))
        crle = CompiledBWT.loadBWT(self._fresh_copy(self.rle, "ffm-qrle"),
                                   useMemmap=False, logger=None)
        expected = self._fm_counts(self.expected_payload,
                                   EXPECTED_FM_COUNTS.keys())
        for kmer, count in sorted(expected.items()):
            self.assertEqual(int(pure.countOccurrencesOfSeq(kmer)), count, kmer)
            self.assertEqual(int(crle.countOccurrencesOfSeq(kmer)), count, kmer)

    # ------------------------------------------------------------------
    # 48-symbol valid collection
    # ------------------------------------------------------------------
    def test_collection_pure_full_fm_matches_oracle(self):
        """On the 48-symbol single-bin collection the pure reader returns the
        correct <u8 FM vector at every exercised position (including
        positions inside later runs that previously raised the TypeError)."""
        import numpy as np
        from MUSCython import MultiStringBWTCython as CompiledBWT
        pcol = self._load_pure(self._fresh_copy(self.col_rle, "col-pure"))
        col_rle = CompiledBWT.loadBWT(
            self._fresh_copy(self.col_rle, "col-rle2"), useMemmap=False,
            logger=None)
        golden = np.load(BYTE_GOLDEN, "r")
        self.assertEqual(int(pcol.totalSize), 48)
        oracle = self._full_fm_oracle
        for position in COLLECTION_POSITIONS:
            ret = pcol.getFullFMAtIndex(position)
            self.assertEqual(ret.dtype, "<u8", position)
            self.assertEqual([int(v) for v in ret],
                             [int(v) for v in col_rle.getFullFMAtIndex(position)],
                             position)
            self.assertEqual([int(v) for v in ret],
                             oracle(golden.tostring(), position), position)

    def test_collection_queries_and_recovery_unchanged(self):
        """The 48-symbol collection keeps its query counts and recovered
        strings on the pure reader and both compiled readers; the pure-reader
        recovery now equals the compiled readers."""
        from MUSCython import MultiStringBWTCython as CompiledBWT
        import numpy as np
        pcol = self._load_pure(self._fresh_copy(self.col_rle, "col-qpure"))
        col_ev = self._fresh_copy(self.col, "col-ev")
        col_rle = CompiledBWT.loadBWT(
            self._fresh_copy(self.col_rle, "col-qrle"), useMemmap=False,
            logger=None)
        byte_reader = CompiledBWT.loadBWT(col_ev, useMemmap=False, logger=None)
        queries = ("AAAAA", "ACGTN", "CCCCC", "AGCTA", "AAAAAA",
                   "GGGGG", "NACGT", "TTTTT", "$")
        expected = {"AAAAA": 1, "ACGTN": 3, "CCCCC": 1, "AGCTA": 0,
                    "AAAAAA": 0, "GGGGG": 1, "NACGT": 1, "TTTTT": 1, "$": 8}
        for kmer in queries:
            self.assertEqual(int(pcol.countOccurrencesOfSeq(kmer)),
                             expected[kmer], kmer)
            self.assertEqual(int(byte_reader.countOccurrencesOfSeq(kmer)),
                             expected[kmer], kmer)
            self.assertEqual(int(col_rle.countOccurrencesOfSeq(kmer)),
                             expected[kmer], kmer)
        payload = np.load(os.path.join(self.col, "msbwt.npy"), "r")
        dollar_positions = [pos for pos, value in enumerate(payload)
                            if value == 0]
        self.assertEqual(len(dollar_positions), 8)
        pure_recovery = []
        byte_recovery = []
        for position in dollar_positions:
            pure_recovery.append(pcol.recoverString(position))
            byte_recovery.append(byte_reader.recoverString(position))
            self.assertEqual(byte_reader.recoverString(position),
                             col_rle.recoverString(position), position)
        self.assertEqual(pure_recovery, byte_recovery)
        added = {name: sha256_file(os.path.join(col_ev, name))
                 for name in ("totalCounts.npy", "fmIndex.npy")}
        self.assertEqual(added, BYTE_READER_SIDE_EFFECTS_SMALL)

    # ------------------------------------------------------------------
    # historical failure evidence preserved (frozen original)
    # ------------------------------------------------------------------
    def test_frozen_original_still_raises_bincount_typeerror(self):
        """The FROZEN original source keeps the failing
        `ret += np.bincount(...)` expression and still raises the documented
        TypeError at line 725 for last-bin positions on both the >1M evidence
        and the 48-symbol single-bin collection."""
        package = os.path.join(REPO, "packages", "msbwt-modern2")
        sys.path.insert(0, package)
        sys.path.insert(0, os.path.join(package, "MUS"))
        frozen = imp.load_source("frozen_msbwt",
                                 os.path.join(REPO, "MUS",
                                              "MultiStringBWT.py"))
        fbig = frozen.CompressedMSBWT()
        fbig.loadMsbwt(self._fresh_copy(self.rle, "frozen-big"), logger=None)
        for position in (TOTAL_SIZE - 2, TOTAL_SIZE - 1):
            try:
                fbig.getFullFMAtIndex(position)
            except TypeError as exc:
                self.assertIn(LEGACY_BINCOUNT_ERROR, str(exc), position)
                self.assertIn("ret += np.bincount", traceback.format_exc(),
                              position)
            else:
                self.fail("frozen position %d did not raise the documented "
                          "legacy TypeError" % position)
        fcol = frozen.CompressedMSBWT()
        fcol.loadMsbwt(self._fresh_copy(self.col_rle, "frozen-col"),
                       logger=None)
        try:
            fcol.getFullFMAtIndex(2)
        except TypeError as exc:
            self.assertIn(LEGACY_BINCOUNT_ERROR, str(exc))
            self.assertIn("ret += np.bincount", traceback.format_exc())
        else:
            self.fail("frozen collection position 2 did not raise the "
                      "documented legacy TypeError")

    def test_modern2_fill_line_is_exact_integer_accumulation(self):
        """The modern2 source uses np.add.at (exact integer per-symbol
        accumulation) and the frozen expression is gone from the checkout."""
        text = open(os.path.join(REPO, "packages", "msbwt-modern2", "MUS",
                                 "MultiStringBWT.py")).read()
        self.assertIn("np.add.at(ret, letters[0:x-1], counts[0:x-1])", text)
        self.assertNotIn("ret += np.bincount(letters[0:x-1], counts[0:x-1], "
                         "minlength=self.vcLen)", text)
        # frozen original still has the failing expression
        frozen = open(os.path.join(REPO, "MUS", "MultiStringBWT.py")).read()
        self.assertIn("ret += np.bincount(letters[0:x-1], counts[0:x-1], "
                      "minlength=self.vcLen)", frozen)


if __name__ == "__main__":
    unittest.main()
