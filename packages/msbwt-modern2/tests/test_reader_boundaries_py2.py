"""msbwt-modern2 reader/index boundary milestone 5 tests, runnable inside the
pinned Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO
(the validation driver sets it).  These tests exercise reader and query
operations on the committed >1M-symbol evidence dataset (the uniform byte
golden tiled 22000x, logical size 1,056,000, compressed RLE 484,000 bytes,
516 FM bins of 2048 symbols) at beginning / bin-boundary / work-boundary /
end positions, and validate the three reader-side index-boundary corrections
added in this milestone:

1. MUS/MultiStringBWT.py CompressedMSBWT.getCharAtIndex
   `endRange = int(self.refFM[binID+1])+1`
2. MUS/MultiStringBWT.py CompressedMSBWT.getFullFMAtIndex
   `endRange = int(self.refFM[binID+1])+1`
3. MUSCython/RLE_BWTCython.pyx RLE_BWT.decompressBlocks
   `endRange = int(self.refFM[endBlock+1])+1`

Root cause (same mechanism as the committed decompression corrections): under
CPython 2.7.18 / NumPy 1.16.6 the `<u8` refFM scalar plus the Python int 1
promotes to NumPy float64, and float64 cannot index the compressed BWT, so
every non-last-bin character/FM lookup raised the committed IndexError and
the compiled RLE_BWT.getBWTRange failed for every range ending before the
last block.  The int() conversions preserve the exact mathematical value
(compressed-file byte offsets, always integral) and only change the Python
representation at the index boundary.

FROZEN LEGACY DEFECT (fixed in milestone 6, frozen arithmetic unchanged): the
pure-Python CompressedMSBWT.getFullFMAtIndex fill line
`ret += np.bincount(letters[0:x-1], counts[0:x-1], minlength=self.vcLen)`
raised `TypeError: Cannot cast ufunc add output from dtype('float64') to
dtype('uint64') with casting rule 'same_kind'` whenever more than one run
precedes the target position (`np.bincount` with weights returns float64 and
NumPy 1.16.6 in-place same_kind casting rejects float64 -> uint64).  The
modern2 fill line is now `np.add.at(ret, letters[0:x-1], counts[0:x-1])`,
which performs the same exact-integer per-symbol accumulation as the typed
Cython RLE_BWT reader (`ret_view[prevChar] += prevCount`).  The frozen
original source (`MUS/MultiStringBWT.py`) keeps the failing expression as
historical evidence and still raises the TypeError at line 725; the compiled
RLE_BWT reader (the normal API) always implemented the same function with
typed Cython arithmetic.

NOTE on reader semantics: the tiled evidence primary is a byte string, not a
valid collection BWT, so reader query counts are validated only as
string-level FM counts against an independent backward search; collection
semantics are validated on the committed uniform 48-symbol fixtures.

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import _npy_compat  # noqa: E402 (platform-consistent .npy writer)

import hashlib
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
EXPECTED_BYTES = {0: 1, 1: 4, 2047: 2, 2048: 2, 2049: 2, 999998: 0,
                  999999: 0, 1000000: 0, 1000001: 2, 1055998: 5, 1055999: 0}

# string-level FM counts on the tiled payload (independent oracle values)
EXPECTED_FM_COUNTS = {
    "A": 198000, "AC": 37125, "ACGTN": 111, "AAAAA": 243, "AAAAAA": 45,
    "C": 198000, "CG": 37125, "GT": 37125, "GTGGGTTT": 2, "N": 88000,
    "NACGT": 108, "T": 198000, "TTTTT": 249,
}

# committed reader-created side-effect hashes for the >1M byte primary
# (decompression-milestone4.json) and for the 48-symbol byte primary
# (decompression-milestone3.json)
BYTE_READER_SIDE_EFFECTS_LARGE = {
    "totalCounts.npy": "e7fe29a99498d61a278845772782b10d22256a9556e865704d75a54e160fe348",
    "fmIndex.npy": "16e19742f54504b19ff72d278cea134b6063a0c51eac77f784699659013d8040",
}
BYTE_READER_SIDE_EFFECTS_SMALL = {
    "totalCounts.npy": "ea104b616fe89d7b786acdff7ca0db61f6339a59c31fbf0fff066ad7384c1c2b",
    "fmIndex.npy": "a5b4bf06726fcadf535245d03ef65e04a4a5248d368b3aa53639c190028b933f",
}

# the documented frozen legacy defect inside pure CompressedMSBWT
# getFullFMAtIndex (frozen line 725 == modern2 line 726)
LEGACY_BINCOUNT_ERROR = ("Cannot cast ufunc add output from dtype('float64') "
                         "to dtype('uint64') with casting rule 'same_kind'")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class ReaderBoundaryTests(unittest.TestCase):
    """Shared fixture: the committed >1M-symbol evidence dataset.

    The evidence primary is regenerated deterministically (np.tile of the
    committed uniform byte golden, 22000x), hash-checked, and compressed by
    modern2 to the committed RLE primary.  Reader loads always run on
    disposable copies.
    """

    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.work = tempfile.mkdtemp(prefix="modern2-py2-rb-")
        cls.expected_payload = None
        evidence = np.load(BYTE_GOLDEN, "r")
        tiled = np.tile(evidence, REPEAT_COUNT)
        assert tiled.shape == (TOTAL_SIZE,), tiled.shape
        cls.expected_payload = tiled.tostring()
        evidence_root = os.path.join(cls.work, "evidence")
        os.makedirs(evidence_root)
        _npy_compat.save_npy(os.path.join(evidence_root, "msbwt.npy"), tiled)
        assert sha256_file(os.path.join(evidence_root, "msbwt.npy")) == EVIDENCE_PRIMARY_SHA256
        cls.rle = os.path.join(cls.work, "rle")
        os.makedirs(cls.rle)
        cls._cli("compress", "-p", "1", evidence_root, cls.rle)
        assert sha256_file(os.path.join(cls.rle, "comp_msbwt.npy")) == RLE_PRIMARY_SHA256

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

    def _fresh_rle_copy(self, label):
        src = os.path.join(self.work, "rle-" + label)
        shutil.copytree(self.rle, src)
        return src

    def _fresh_byte_copy(self, label):
        src = os.path.join(self.work, "byte-" + label)
        os.makedirs(src)
        import numpy as np
        _npy_compat.save_npy(os.path.join(src, "msbwt.npy"),
                np.fromstring(self.expected_payload, dtype="<u1"))
        return src

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

    # ------------------------------------------------------------------
    # root cause
    # ------------------------------------------------------------------
    def test_uint64_plus_int_promotion_root_cause(self):
        """The mechanism at the reader sites is the committed promotion.

        Under CPython 2.7.18 / NumPy 1.16.6 the `<u8` refFM scalar plus the
        Python int 1 promotes to NumPy float64, which cannot index the
        compressed BWT.  int() conversion preserves the exact value and
        restores an index-legal type.
        """
        import numpy as np
        scalar = np.uint64(459008)
        promoted = scalar + 1
        self.assertIsInstance(promoted, np.float64)
        self.assertEqual(promoted, 459009.0)
        self.assertNotIn("__index__", dir(promoted))
        fixed = int(scalar) + 1
        self.assertIsInstance(fixed, int)
        self.assertEqual(fixed, 459009)
        big = np.uint64(9223372036854775813)
        self.assertEqual(int(big), 9223372036854775813L)

    # ------------------------------------------------------------------
    # pure-Python CompressedMSBWT reader sites
    # ------------------------------------------------------------------
    def test_pure_getCharAtIndex_all_boundaries(self):
        """Pure CompressedMSBWT.getCharAtIndex returns the raw primary byte
        at every boundary position (fails with IndexError at line 575 if the
        int() conversion is removed)."""
        src = self._fresh_rle_copy("gci")
        from MUS.MultiStringBWT import CompressedMSBWT
        msbwt = CompressedMSBWT()
        msbwt.loadMsbwt(src, logger=None)
        self.assertEqual(msbwt.getTotalSize(), TOTAL_SIZE)
        self.assertEqual(str(msbwt.refFM.dtype), "uint64")
        self.assertEqual(msbwt.refFM.shape[0], 516)
        for position in POSITIONS:
            value = int(msbwt.getCharAtIndex(position))
            self.assertEqual(value, EXPECTED_BYTES[position], position)
        # runtime type evidence at the fixed site
        self.assertEqual(int(msbwt.refFM[488 + 1]) + 1, 459009)
        self.assertIsInstance(int(msbwt.refFM[488 + 1]) + 1, int)

    def test_pure_getCharAtIndex_small_single_bin_unchanged(self):
        """The 48-symbol single-bin case keeps working (no regression)."""
        import numpy as np
        small_ev = os.path.join(self.work, "small-ev")
        os.makedirs(small_ev)
        _npy_compat.save_npy(os.path.join(small_ev, "msbwt.npy"), np.load(BYTE_GOLDEN, "r"))
        small_rle = os.path.join(self.work, "small-rle")
        os.makedirs(small_rle)
        self._cli("compress", "-p", "1", small_ev, small_rle)
        from MUS.MultiStringBWT import CompressedMSBWT
        msbwt = CompressedMSBWT()
        msbwt.loadMsbwt(small_rle, logger=None)
        self.assertEqual(msbwt.refFM.shape[0], 1)
        golden = np.load(BYTE_GOLDEN, "r")
        for position in (0, 10, 47):
            self.assertEqual(int(msbwt.getCharAtIndex(position)),
                             int(golden[position]), position)

    def test_pure_getFullFMAtIndex_promotion_site_fixed(self):
        """Pure CompressedMSBWT.getFullFMAtIndex works at positions whose
        region starts within the first run (x <= 1) and equals the
        independent oracle (fails with IndexError at line 708 if the int()
        conversion is removed)."""
        src = self._fresh_rle_copy("ffm")
        from MUS.MultiStringBWT import CompressedMSBWT
        msbwt = CompressedMSBWT()
        msbwt.loadMsbwt(src, logger=None)
        oracle = self._full_fm_oracle
        for position in (0, 1, 2048, 2049):
            ret = msbwt.getFullFMAtIndex(position)
            self.assertEqual(ret.dtype, "<u8")
            self.assertEqual([int(v) for v in ret],
                             oracle(self.expected_payload, position), position)

    def test_pure_getFullFMAtIndex_legacy_bincount_defect_fixed(self):
        """The frozen line-725/726 float64 bincount cast defect is fixed in
        modern2 and preserved in the frozen original.

        For positions preceded by more than one run the modern2 fill line
        `np.add.at(ret, letters[0:x-1], counts[0:x-1])` now performs the
        exact-integer per-symbol accumulation and returns a <u8 FM vector
        equal to the independent oracle; the FROZEN original fill line
        `ret += np.bincount(...)` still raises the documented TypeError
        (float64 bincount output cannot be added in-place into the <u8 array
        under NumPy 1.16.6).
        """
        import imp
        # modern2 checkout: correct integer FM vectors at every position
        src = self._fresh_rle_copy("legacy-fixed")
        from MUS.MultiStringBWT import CompressedMSBWT
        msbwt = CompressedMSBWT()
        msbwt.loadMsbwt(src, logger=None)
        oracle = self._full_fm_oracle
        for position in (2047, 999998, 1000000, 1055999):
            ret = msbwt.getFullFMAtIndex(position)
            self.assertEqual(ret.dtype, "<u8", position)
            self.assertEqual([int(v) for v in ret],
                             oracle(self.expected_payload, position), position)
        # frozen original: historical TypeError preserved (last-bin positions
        # reach the line-725 bincount fill; non-last bins fail earlier at the
        # pre-fix float64 endRange index)
        frozen_src = self._fresh_rle_copy("legacy-frozen")
        # the frozen module imports MSBWTGen at module scope; put the modern2
        # MUS package on the path (loadMsbwt only, no builder code runs)
        package = os.path.join(REPO, "packages", "msbwt-modern2")
        sys.path.insert(0, package)
        sys.path.insert(0, os.path.join(package, "MUS"))
        frozen = imp.load_source("frozen_msbwt",
                                 os.path.join(REPO, "MUS",
                                              "MultiStringBWT.py"))
        fmsbwt = frozen.CompressedMSBWT()
        fmsbwt.loadMsbwt(frozen_src, logger=None)
        for position in (1055998, 1055999):
            try:
                fmsbwt.getFullFMAtIndex(position)
            except TypeError as exc:
                self.assertIn(LEGACY_BINCOUNT_ERROR, str(exc), position)
                self.assertIn("ret += np.bincount", traceback.format_exc(),
                              position)
            else:
                self.fail("frozen position %d did not raise the documented "
                          "legacy TypeError" % position)

    # ------------------------------------------------------------------
    # compiled RLE_BWT reader sites (decompressBlocks / getBWTRange)
    # ------------------------------------------------------------------
    def test_compiled_rle_getBWTRange_all_ranges(self):
        """Compiled RLE_BWT.getBWTRange decodes every range byte-identically
        to the expected payload slice and to the fixed pure-Python path
        (fails with IndexError at RLE_BWTCython.pyx:375 if the int()
        conversion is removed)."""
        src = self._fresh_rle_copy("bwtr")
        from MUS.MultiStringBWT import CompressedMSBWT
        from MUSCython import MultiStringBWTCython as CompiledBWT
        pure = CompressedMSBWT()
        pure.loadMsbwt(src, logger=None)
        crle = CompiledBWT.loadBWT(src, useMemmap=False, logger=None)
        self.assertEqual(type(crle).__module__ + "." + type(crle).__name__,
                         "MUSCython.RLE_BWTCython.RLE_BWT")
        for start, end in ((0, 2048), (0, 1000000), (1000000, 1056000),
                           (LAST_BIN_START, 1056000), (0, TOTAL_SIZE)):
            rng = crle.getBWTRange(start, end)
            self.assertEqual(rng.dtype, "<u1", (start, end))
            self.assertEqual(rng.shape[0], end - start, (start, end))
            self.assertEqual(rng.tostring(),
                             self.expected_payload[start:end], (start, end))
            pure_rng = pure.getBWTRange(start, end)
            self.assertEqual(rng.tostring(), pure_rng.tostring(), (start, end))

    def test_compiled_rle_getCharAtIndex_and_full_fm(self):
        """Compiled RLE_BWT character/FM lookups at boundaries match the
        independent byte-level oracles."""
        src = self._fresh_rle_copy("rlelookup")
        from MUSCython import MultiStringBWTCython as CompiledBWT
        crle = CompiledBWT.loadBWT(src, useMemmap=False, logger=None)
        for position in POSITIONS:
            self.assertEqual(int(crle.getCharAtIndex(position)),
                             EXPECTED_BYTES[position], position)
        oracle = self._full_fm_oracle
        for position in (0, 2048, 1000000, TOTAL_SIZE - 1):
            ret = crle.getFullFMAtIndex(position)
            self.assertEqual([int(v) for v in ret],
                             oracle(self.expected_payload, position), position)

    def test_compiled_rle_queries_match_independent_oracle(self):
        """Compressed-reference-index FM queries equal the independent
        string-level backward counts on the same payload."""
        src = self._fresh_rle_copy("rleq")
        from MUSCython import MultiStringBWTCython as CompiledBWT
        crle = CompiledBWT.loadBWT(src, useMemmap=False, logger=None)
        expected = self._fm_counts(self.expected_payload,
                                   EXPECTED_FM_COUNTS.keys())
        for kmer, count in sorted(expected.items()):
            self.assertEqual(int(crle.countOccurrencesOfSeq(kmer)), count, kmer)

    # ------------------------------------------------------------------
    # compiled ByteBWT on the >1M byte primary
    # ------------------------------------------------------------------
    def test_compiled_byte_reader_boundaries_and_queries(self):
        """Compiled ByteBWT character/FM/query operations on the >1M primary
        match the independent byte-level oracles."""
        src = self._fresh_byte_copy("bytet")
        from MUSCython import MultiStringBWTCython as CompiledBWT
        msbwt = CompiledBWT.loadBWT(src, useMemmap=False, logger=None)
        self.assertEqual(type(msbwt).__module__ + "." + type(msbwt).__name__,
                         "MUSCython.ByteBWTCython.ByteBWT")
        self.assertEqual(msbwt.getTotalSize(), TOTAL_SIZE)
        self.assertEqual(int(msbwt.getSymbolCount(0)), 176000)
        for position in POSITIONS:
            self.assertEqual(int(msbwt.getCharAtIndex(position)),
                             EXPECTED_BYTES[position], position)
        oracle = self._full_fm_oracle
        for position in (0, 2048, 1000000, TOTAL_SIZE - 1):
            ret = msbwt.getFullFMAtIndex(position)
            self.assertEqual([int(v) for v in ret],
                             oracle(self.expected_payload, position), position)
        expected = self._fm_counts(self.expected_payload,
                                   EXPECTED_FM_COUNTS.keys())
        for kmer, count in sorted(expected.items()):
            self.assertEqual(int(msbwt.countOccurrencesOfSeq(kmer)), count, kmer)
        # committed deterministic reader side effects
        added = {name: sha256_file(os.path.join(src, name))
                 for name in ("totalCounts.npy", "fmIndex.npy")}
        self.assertEqual(added, BYTE_READER_SIDE_EFFECTS_LARGE)

    # ------------------------------------------------------------------
    # valid collection regression (uniform byte + RLE, 48 symbols)
    # ------------------------------------------------------------------
    def test_valid_collection_queries_and_recovery_unchanged(self):
        """The committed uniform 48-symbol collection keeps its query counts
        and recovered strings on both compiled readers (byte and RLE)."""
        import numpy as np
        ev = os.path.join(self.work, "col-ev")
        os.makedirs(ev)
        _npy_compat.save_npy(os.path.join(ev, "msbwt.npy"), np.load(BYTE_GOLDEN, "r"))
        rle = os.path.join(self.work, "col-rle")
        os.makedirs(rle)
        self._cli("compress", "-p", "1", ev, rle)
        from MUSCython import MultiStringBWTCython as CompiledBWT
        byte_reader = CompiledBWT.loadBWT(ev, useMemmap=False, logger=None)
        rle_reader = CompiledBWT.loadBWT(rle, useMemmap=False, logger=None)
        self.assertEqual(byte_reader.getTotalSize(), 48)
        self.assertEqual(rle_reader.getTotalSize(), 48)
        for kmer, expected in (("AAAAA", 1), ("ACGTN", 3), ("CCCCC", 1),
                               ("AGCTA", 0), ("AAAAAA", 0), ("GGGGG", 1),
                               ("NACGT", 1), ("TTTTT", 1), ("$", 8)):
            self.assertEqual(int(byte_reader.countOccurrencesOfSeq(kmer)),
                             expected, kmer)
            self.assertEqual(int(rle_reader.countOccurrencesOfSeq(kmer)),
                             expected, kmer)
        # recovered strings: cross-reader equality over every dollar position
        payload = np.load(os.path.join(ev, "msbwt.npy"), "r")
        dollar_positions = [pos for pos, value in enumerate(payload) if value == 0]
        self.assertEqual(len(dollar_positions), 8)
        for position in dollar_positions:
            self.assertEqual(byte_reader.recoverString(position),
                             rle_reader.recoverString(position), position)
        # committed byte-reader side-effect hashes for the 48-symbol case
        added = {name: sha256_file(os.path.join(ev, name))
                 for name in ("totalCounts.npy", "fmIndex.npy")}
        self.assertEqual(added, BYTE_READER_SIDE_EFFECTS_SMALL)


if __name__ == "__main__":
    unittest.main()
