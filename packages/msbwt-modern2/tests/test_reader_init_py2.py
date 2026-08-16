"""msbwt-modern2 pure reader initialization / index construction milestone 7
tests, runnable inside the pinned Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO
(the validation driver sets it).  These tests characterize the two pure-
Python first-load paths

    CompressedMSBWT.constructTotalCounts
    CompressedMSBWT.constructFMIndex

on completely fresh inputs (all reader-derived caches removed) under
CPython 2.7.18 / NumPy 1.16.6 and protect the generated

    totalCounts.p, comp_fmIndex.npy, comp_refIndex.npy

against the committed frozen-reader evidence and the compiled reader.

Executed verdict (see docs/modernization/MODERN2_MILESTONE7_READER_INIT.md):

- constructTotalCounts is SAFE: `self.totalCounts += np.bincount(...)` on a
  Python-list accumulator performs ELEMENTWISE numpy addition under CPython
  2.7 (the list is converted by ndarray's reflected add and the name is
  rebound to a float64 ndarray) -- NOT list extension (the Python-3
  behavior).  The float64 values are exact integers for all exercised
  inputs and the pickled totalCounts.p bytes are identical to the committed
  frozen-reader evidence.
- constructFMIndex is SAFE: float64 intermediates (countsSoFar, np.add,
  np.bincount) are integral and are cast to '<u8' only at memmap setitem;
  all 516 bins of the >1M evidence validate against an independent per-bin
  FM oracle; the generated files match the committed frozen-reader bytes
  for the single-bin collections.  At bins whose 2048-boundary coincides
  exactly with a run boundary (171 of 516 bins on the tiled evidence) the
  pure sampling records the run CONTAINING the boundary while the compiled
  RLE_BWT records the run ENDING at it; both conventions are oracle-correct
  and the two derived-file sets are fully interchangeable between the
  readers (executed).

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
import pickle
import re
import shutil
import sys
import tempfile
import unittest

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

GOLDENS = os.path.join(REPO, "compat", "goldens", "original-0.3.0")
PROFILE = "py27-late-05a7d6d83862"
ROUTE = "pyx-historical-cython"
BYTE_GOLDEN = os.path.join(
    GOLDENS, "uniform-multifile", PROFILE, ROUTE, "build", "artifacts", "msbwt.npy")
POSTHOC_DIR = os.path.join(
    GOLDENS, "uniform-compress-posthoc", PROFILE, ROUTE, "artifacts")
NONUNI_DIR = os.path.join(
    GOLDENS, "nonuniform-compress-posthoc", PROFILE, ROUTE, "artifacts")

EVIDENCE_PRIMARY_SHA256 = "24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35"
RLE_PRIMARY_SHA256 = "681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99"
TOTAL_SIZE = 1056000
REPEAT_COUNT = 22000

POSITIONS = [0, 1, 2047, 2048, 2049, 6144, 999998, 999999, 1000000, 1000001,
             1055998, 1055999]
COLLECTION_POSITIONS = [0, 1, 2, 5, 10, 20, 40, 47]

# independent decoded-RLE symbol totals (order '$ACGNT')
DECODED_COUNTS = {
    "posthoc48": [8, 9, 9, 9, 4, 9],
    "nonuni30": [7, 5, 4, 3, 2, 9],
    "big": [176000, 198000, 198000, 198000, 88000, 198000],
}

# committed frozen pure-reader side-effect hashes (compression-milestone1
# decompression-failure source-after-manifest)
FROZEN_48 = {
    "totalCounts.p": "c038b778aa21d53a42ba552e59cfe48d036ed7b8f4d6ce77d0ab55ede2638916",
    "comp_fmIndex.npy": "f6565545114d769fbe6ba6010ce125c8690256f2d97562ceb65064b38d48c881",
    "comp_refIndex.npy": "30c0c0f336e69b86ee3da30f0f4ce1d9a138d503845c586e993ff31e8003fee1",
}
FROZEN_30_FM = "d3e57fa28f3b49910012d4fb2a51f48a22f62b112bc773d8fe825a5905c7be55"
FROZEN_30_REF = "30c0c0f336e69b86ee3da30f0f4ce1d9a138d503845c586e993ff31e8003fee1"

# string-level FM counts on the tiled payload (independent oracle values)
EXPECTED_FM_COUNTS = {
    "A": 198000, "AC": 37125, "ACGTN": 111, "AAAAA": 243, "AAAAAA": 45,
    "C": 198000, "CG": 37125, "GT": 37125, "GTGGGTTT": 2, "N": 88000,
    "NACGT": 108, "T": 198000, "TTTTT": 249,
}

COLLECTION_QUERIES = {"AAAAA": 1, "ACGTN": 3, "CCCCC": 1, "AGCTA": 0,
                      "AAAAAA": 0, "GGGGG": 1, "NACGT": 1, "TTTTT": 1,
                      "$": 8}
COLLECTION_RECOVERY = ['AAAAA$', 'ACGTN$', 'ACGTN$', 'ACGTN$', 'CCCCC$',
                       'GGGGG$', 'NACGT$', 'TTTTT$']

FROZEN_SHA256 = "95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0"


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class PureReaderInitTests(unittest.TestCase):
    """Shared fixture: the committed >1M-symbol evidence dataset, the
    48-symbol posthoc RLE, and the 30-symbol nonuniform RLE.  Reader loads
    always run on disposable copies with all derived caches removed."""

    DERIVED = ("totalCounts.p", "comp_fmIndex.npy", "comp_refIndex.npy")

    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.work = tempfile.mkdtemp(prefix="modern2-py2-init-")
        evidence = np.load(BYTE_GOLDEN, "r")
        tiled = np.tile(evidence, REPEAT_COUNT)
        assert tiled.shape == (TOTAL_SIZE,), tiled.shape
        cls.expected_payload = tiled.tostring()
        evidence_root = os.path.join(cls.work, "evidence")
        os.makedirs(evidence_root)
        _npy_compat.save_npy(os.path.join(evidence_root, "msbwt.npy"), tiled)
        assert sha256_file(os.path.join(evidence_root, "msbwt.npy")) == \
            EVIDENCE_PRIMARY_SHA256
        cls.rle = os.path.join(cls.work, "rle")
        os.makedirs(cls.rle)
        cls._cli("compress", "-p", "1", evidence_root, cls.rle)
        assert sha256_file(os.path.join(cls.rle, "comp_msbwt.npy")) == \
            RLE_PRIMARY_SHA256
        # the 48-symbol and 30-symbol collections use the committed golden
        # artifacts directly
        cls.posthoc = os.path.join(cls.work, "posthoc")
        shutil.copytree(POSTHOC_DIR, cls.posthoc)
        cls.nonuni = os.path.join(cls.work, "nonuni")
        shutil.copytree(NONUNI_DIR, cls.nonuni)

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

    def _remove_derived(self, directory):
        for name in self.DERIVED:
            path = os.path.join(directory, name)
            if os.path.exists(path):
                os.remove(path)

    def _load_pure(self, rle_dir):
        from MUS.MultiStringBWT import CompressedMSBWT
        msbwt = CompressedMSBWT()
        msbwt.loadMsbwt(rle_dir, logger=None)
        return msbwt

    def _decode_rle_counts(self, path):
        """Independent base-32 RLE decoder (no reader code).

        Digit order: the encoder writes the LEAST significant base-32
        digit first (``ret[i] = ((delta & mask) << letterBits) + c`` then
        ``delta /= numPower``, MUSCython/MSBWTGenCython.pyx with
        letterBits=3, mask=31, numPower=32), so the first digit of a run
        in the byte stream carries power 32**0 (the RLE reader
        reconstructs with ``digit * powerMultiple`` where
        ``powerMultiple *= numPower`` per following digit,
        MUSCython/RLE_BWTCython.pyx).  The committed golden RLE payloads
        contain only single-digit runs, so this ordering was not
        exercised before the multi-digit regression test below.
        """
        import numpy as np
        raw = np.load(path, "r")
        counts = [0] * 6
        prev_sym = -1
        digits = []
        symbols = []
        for byte in raw.tolist():
            sym = byte & 7
            digit = byte >> 3
            if sym != prev_sym:
                if digits:
                    total = 0
                    for power, d in enumerate(digits):
                        total += d * (32 ** power)
                    counts[prev_sym] += total
                    symbols.extend([prev_sym] * total)
                digits = []
                prev_sym = sym
            digits.append(digit)
        if digits:
            total = 0
            for power, d in enumerate(digits):
                total += d * (32 ** power)
            counts[prev_sym] += total
            symbols.extend([prev_sym] * total)
        return counts, symbols

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

    # ------------------------------------------------------------------
    # CPython-2 list += ndarray semantics (root cause)
    # ------------------------------------------------------------------
    def test_py2_list_iadd_ndarray_is_elementwise_addition(self):
        """Under CPython 2.7 + NumPy 1.16.6, `list += ndarray` performs
        elementwise numpy addition and rebinds the name to an ndarray -- it
        does NOT extend the list (the Python-3 behavior).  This is why the
        frozen `self.totalCounts += np.bincount(...)` accumulator is a
        correct numeric accumulation, not a list-extension bug."""
        import numpy as np
        accumulator = [0] * 6
        letters = np.array([0, 1, 2, 3, 4, 5, 0], dtype=np.uint8)
        counts = np.array([10, 20, 30, 40, 50, 60, 7], dtype="<u8")
        bc = np.bincount(letters, counts, minlength=6)
        self.assertEqual(str(bc.dtype), "float64")
        accumulator += bc
        self.assertIsInstance(accumulator, np.ndarray)
        self.assertEqual(len(accumulator), 6)
        self.assertEqual([float(v) for v in accumulator],
                         [17.0, 20.0, 30.0, 40.0, 50.0, 60.0])
        # a second chunk accumulates elementwise
        accumulator += np.bincount(np.array([0, 1], dtype=np.uint8),
                                   np.array([1, 1], dtype="<u8"), minlength=6)
        self.assertEqual([float(v) for v in accumulator],
                         [18.0, 21.0, 30.0, 40.0, 50.0, 60.0])

    # ------------------------------------------------------------------
    # constructTotalCounts / constructFMIndex runtime semantics
    # ------------------------------------------------------------------
    def test_fresh_constructTotalCounts_runtime_semantics(self):
        """On a completely fresh copy, constructTotalCounts starts from a
        Python list, the first `+=` rebinds to a float64 ndarray, and the
        final pickled totalCounts.p holds the exact per-symbol totals."""
        import numpy as np
        src = self._fresh_copy(self.posthoc, "init-tc")
        self._remove_derived(src)
        from MUS.MultiStringBWT import CompressedMSBWT
        tr = CompressedMSBWT()
        tr.bwt = np.load(os.path.join(src, "comp_msbwt.npy"), "r")
        tr.dirName = src
        tr.vcLen = 6
        tr.letterBits = 3
        tr.numberBits = 8 - tr.letterBits
        tr.numPower = 2 ** tr.numberBits
        tr.mask = 255 >> tr.numberBits
        tr.totalCounts = [0] * tr.vcLen
        self.assertEqual(type(tr.totalCounts).__name__, "list")
        binSize = 2 ** 15
        end = 0
        while end < tr.bwt.shape[0]:
            start = end
            end = end + binSize
            if end > tr.bwt.shape[0]:
                end = tr.bwt.shape[0]
            while end < tr.bwt.shape[0] and (
                    (tr.bwt[end] & tr.mask) == (tr.bwt[end - 1] & tr.mask)):
                end += 1
            letters = np.bitwise_and(tr.bwt[start:end], tr.mask)
            counts = np.right_shift(tr.bwt[start:end], tr.letterBits, dtype="<u8")
            powers = np.zeros(dtype="<u8", shape=(end - start,))
            i = 1
            same = (letters[0:-1] == letters[1:])
            while np.sum(same) > 0:
                (powers[i:])[same] += 1
                i += 1
                same = np.bitwise_and(same[0:-1], same[1:])
            bc = np.bincount(letters,
                             np.multiply(counts, tr.numPower ** powers),
                             minlength=tr.vcLen)
            self.assertEqual(str(bc.dtype), "float64")
            before = type(tr.totalCounts).__name__
            tr.totalCounts += bc
            self.assertEqual(before, "list")
            self.assertIsInstance(tr.totalCounts, np.ndarray)
            self.assertEqual(len(tr.totalCounts), 6)
        self.assertEqual(str(tr.totalCounts.dtype), "float64")
        self.assertEqual([float(v) for v in tr.totalCounts],
                         [float(v) for v in DECODED_COUNTS["posthoc48"]])

    def test_fresh_constructFMIndex_runtime_semantics(self):
        """constructFMIndex runs on float64 intermediates (countsSoFar) and
        stores exact uint64 rows into the comp_fmIndex.npy/comp_refIndex.npy
        memmaps; offsetSum is consistent with the first row."""
        import numpy as np
        src = self._fresh_copy(self.posthoc, "init-fm")
        self._remove_derived(src)
        msbwt = self._load_pure(src)
        counts_so_far = np.cumsum(msbwt.totalCounts) - msbwt.totalCounts
        self.assertEqual(str(counts_so_far.dtype), "float64")
        self.assertEqual([float(v) for v in counts_so_far],
                         [0.0, 8.0, 17.0, 26.0, 35.0, 39.0])
        self.assertEqual(str(msbwt.partialFM.dtype), "uint64")
        self.assertEqual(str(msbwt.refFM.dtype), "uint64")
        self.assertEqual(list(msbwt.partialFM.shape), [1, 6])
        self.assertEqual(int(msbwt.offsetSum), 125)
        self.assertEqual(int(msbwt.getTotalSize()), 48)

    # ------------------------------------------------------------------
    # exact totals + committed frozen evidence
    # ------------------------------------------------------------------
    def test_fresh_load_exact_symbol_totals(self):
        """Fresh loads on all four characterized inputs produce total
        counts equal to the independent decoded-RLE symbol totals."""
        for label, src, expected in (
                ("init-tot-posthoc", self.posthoc, DECODED_COUNTS["posthoc48"]),
                ("init-tot-nonuni", self.nonuni, DECODED_COUNTS["nonuni30"]),
                ("init-tot-big", self.rle, DECODED_COUNTS["big"])):
            directory = self._fresh_copy(src, label)
            self._remove_derived(directory)
            msbwt = self._load_pure(directory)
            tc = pickle.load(open(os.path.join(directory, "totalCounts.p"), "rb"))
            self.assertEqual(type(tc).__name__, "ndarray")
            self.assertEqual(str(tc.dtype), "float64")
            self.assertEqual([int(v) for v in tc], expected)
            self.assertEqual(int(msbwt.getTotalSize()), sum(expected))

    def test_fresh_load_matches_committed_frozen_evidence(self):
        """The pure reader's derived files for the 48-symbol collection are
        byte-identical to the committed frozen-reader side-effect hashes
        (compression-milestone1 decompression-failure evidence).

        On native Windows the pickled totalCounts.p byte framing cannot be
        identical: CPython 2.7 pickles numpy array shapes as py2 longs there
        (numpy converts the C dims via PyLong on Windows), so the protocol-0
        pickle embeds '(6L,)' instead of '(6,)'.  The logical content is
        identical, so on Windows the unpickled array is compared
        semantically (documented in COMPATIBILITY.md)."""
        src = self._fresh_copy(self.posthoc, "init-committed")
        self._remove_derived(src)
        self._load_pure(src)
        for name, digest in FROZEN_48.items():
            if name == "totalCounts.p" and sys.platform.startswith("win"):
                import numpy as np
                tc = pickle.load(open(os.path.join(src, name), "rb"))
                self.assertEqual(type(tc).__name__, "ndarray")
                self.assertEqual(str(tc.dtype), "float64")
                self.assertEqual([int(v) for v in tc],
                                 DECODED_COUNTS["posthoc48"])
                continue
            self.assertEqual(sha256_file(os.path.join(src, name)), digest,
                             name)
        nu = self._fresh_copy(self.nonuni, "init-committed-nu")
        self._remove_derived(nu)
        self._load_pure(nu)
        self.assertEqual(
            sha256_file(os.path.join(nu, "comp_fmIndex.npy")), FROZEN_30_FM)
        self.assertEqual(
            sha256_file(os.path.join(nu, "comp_refIndex.npy")), FROZEN_30_REF)

    def test_fresh_load_creates_exact_derived_file_set(self):
        """A fresh load creates exactly totalCounts.p, comp_fmIndex.npy and
        comp_refIndex.npy next to the untouched primary."""
        src = self._fresh_copy(self.posthoc, "init-set")
        self._remove_derived(src)
        baseline = set(os.listdir(src))
        self._load_pure(src)
        created = set(os.listdir(src)) - baseline
        self.assertEqual(created, set(self.DERIVED))

    # ------------------------------------------------------------------
    # determinism + regeneration
    # ------------------------------------------------------------------
    def test_fresh_load_deterministic_and_regenerable(self):
        """Two fresh copies produce byte-identical derived files, and
        deleting the caches and reloading reproduces them byte-for-byte
        (multi-bin >1M case)."""
        src = self._fresh_copy(self.rle, "init-det-a")
        self._remove_derived(src)
        self._load_pure(src)
        hashes_a = {name: sha256_file(os.path.join(src, name))
                    for name in self.DERIVED}
        src_b = self._fresh_copy(self.rle, "init-det-b")
        self._remove_derived(src_b)
        self._load_pure(src_b)
        hashes_b = {name: sha256_file(os.path.join(src_b, name))
                    for name in self.DERIVED}
        self.assertEqual(hashes_a, hashes_b)
        # regeneration: delete caches and reload
        self._remove_derived(src)
        self._load_pure(src)
        hashes_c = {name: sha256_file(os.path.join(src, name))
                    for name in self.DERIVED}
        self.assertEqual(hashes_a, hashes_c)

    # ------------------------------------------------------------------
    # pure vs compiled semantics on fresh loads
    # ------------------------------------------------------------------
    def test_fresh_load_pure_equals_compiled_equals_oracle(self):
        """On the >1M evidence, a fresh pure load agrees with the compiled
        RLE_BWT reader and the independent FM/char oracles at every boundary
        position, and query counts match the independent string-level FM
        oracle."""
        from MUSCython import MultiStringBWTCython as CompiledBWT
        pure = self._load_pure(self._fresh_copy(self.rle, "init-pure"))
        crle = CompiledBWT.loadBWT(self._fresh_copy(self.rle, "init-crle"),
                                   useMemmap=False, logger=None)
        for position in POSITIONS:
            self.assertEqual([int(v) for v in pure.getFullFMAtIndex(position)],
                             [int(v) for v in crle.getFullFMAtIndex(position)],
                             position)
            self.assertEqual(int(pure.getCharAtIndex(position)),
                             int(crle.getCharAtIndex(position)), position)
        queries = {}
        for kmer in EXPECTED_FM_COUNTS:
            queries[kmer] = int(pure.countOccurrencesOfSeq(kmer))
        self.assertEqual(queries, EXPECTED_FM_COUNTS)
        self.assertEqual(queries,
                         self._fm_counts(self.expected_payload,
                                         EXPECTED_FM_COUNTS.keys()))

    def test_fresh_load_all_516_bins_oracle_validated(self):
        """getFullFMAtIndex at every one of the 516 bin boundaries of the
        pure >1M derived files equals the independent per-bin FM oracle."""
        import numpy as np
        pure = self._load_pure(self._fresh_copy(self.rle, "init-bins"))
        payload = np.fromstring(self.expected_payload, dtype=np.uint8)
        start_index = [0, 176000, 374000, 572000, 770000, 858000]
        for bin_id in range(int(pure.partialFM.shape[0])):
            position = bin_id * 2048
            counts = np.bincount(payload[0:position].astype("int64"),
                                 minlength=6)
            oracle = [start_index[s] + int(counts[s]) for s in range(6)]
            got = [int(v) for v in pure.getFullFMAtIndex(position)]
            self.assertEqual(got, oracle, position)

    def test_pure_vs_compiled_derived_file_convention(self):
        """The pure and compiled >1M derived files differ only at bins whose
        2048-boundary coincides exactly with a run boundary (171 bins, every
        third bin = tile boundary); there the pure refFM points at the run
        CONTAINING the boundary and the compiled refFM at the run ENDING at
        it (pure == compiled + 1).  Both conventions are semantically
        correct (validated in the bin-oracle test and the interchangeability
        test)."""
        from MUSCython import MultiStringBWTCython as CompiledBWT
        import numpy as np
        pure_dir = self._fresh_copy(self.rle, "init-conv-pure")
        self._remove_derived(pure_dir)
        self._load_pure(pure_dir)
        comp_dir = self._fresh_copy(self.rle, "init-conv-comp")
        CompiledBWT.loadBWT(comp_dir, useMemmap=False, logger=None)
        pure_rf = np.load(os.path.join(pure_dir, "comp_refIndex.npy"), "r")
        comp_rf = np.load(os.path.join(comp_dir, "comp_refIndex.npy"), "r")
        diff_bins = [b for b in range(pure_rf.shape[0])
                     if int(pure_rf[b]) != int(comp_rf[b])]
        self.assertEqual(len(diff_bins), 171)
        self.assertTrue(all(b % 3 == 0 for b in diff_bins))
        self.assertTrue(all(int(pure_rf[b]) == int(comp_rf[b]) + 1
                            for b in diff_bins))
        pure_fm = np.load(os.path.join(pure_dir, "comp_fmIndex.npy"), "r")
        comp_fm = np.load(os.path.join(comp_dir, "comp_fmIndex.npy"), "r")
        self.assertTrue(np.array_equal(pure_fm[0], comp_fm[0]))
        self.assertTrue(np.array_equal(pure_fm[-1], comp_fm[-1]))

    def test_interchangeability_pure_and_compiled_files(self):
        """The pure reader loaded against compiled-created FM files and the
        compiled reader loaded against pure-created FM files both return
        oracle-correct FM values at the documented convention-difference
        bins -- the two derived-file conventions are fully
        interchangeable."""
        from MUSCython import MultiStringBWTCython as CompiledBWT
        pure_dir = self._fresh_copy(self.rle, "init-int-pure")
        self._remove_derived(pure_dir)
        self._load_pure(pure_dir)
        comp_dir = self._fresh_copy(self.rle, "init-int-comp")
        CompiledBWT.loadBWT(comp_dir, useMemmap=False, logger=None)
        pure_on_compiled = self._load_pure(comp_dir)
        comp_on_pure = CompiledBWT.loadBWT(pure_dir, useMemmap=False,
                                           logger=None)
        # bin 3 boundary (6144) is an exact run boundary: pure file row is
        # already the oracle value; both cross arrangements agree with it
        self.assertEqual([int(v) for v in pure_on_compiled.getFullFMAtIndex(6144)],
                         [1024, 177152, 375152, 573152, 770512, 859152])
        self.assertEqual([int(v) for v in comp_on_pure.getFullFMAtIndex(6144)],
                         [1024, 177152, 375152, 573152, 770512, 859152])
        self.assertEqual(int(pure_on_compiled.getCharAtIndex(6144)), 1)
        self.assertEqual(int(comp_on_pure.getCharAtIndex(6144)), 1)
        self.assertEqual(int(pure_on_compiled.countOccurrencesOfSeq("AC")), 37125)
        self.assertEqual(int(comp_on_pure.countOccurrencesOfSeq("AC")), 37125)

    # ------------------------------------------------------------------
    # valid collection semantics on fresh loads
    # ------------------------------------------------------------------
    def test_fresh_load_valid_collection_query_recovery(self):
        """On a fresh 48-symbol collection load, queries and recovered
        strings match the committed values and the compiled reader."""
        from MUSCython import MultiStringBWTCython as CompiledBWT
        pure_dir = self._fresh_copy(self.posthoc, "init-col-pure")
        self._remove_derived(pure_dir)
        pure = self._load_pure(pure_dir)
        comp_dir = self._fresh_copy(self.posthoc, "init-col-comp")
        compiled = CompiledBWT.loadBWT(comp_dir, useMemmap=False, logger=None)
        queries = {k: int(pure.countOccurrencesOfSeq(k))
                   for k in COLLECTION_QUERIES}
        self.assertEqual(queries, COLLECTION_QUERIES)
        decoded_counts, decoded_symbols = self._decode_rle_counts(
            os.path.join(self.posthoc, "comp_msbwt.npy"))
        self.assertEqual(decoded_counts, DECODED_COUNTS["posthoc48"])
        dollar_positions = [pos for pos, value in enumerate(decoded_symbols)
                            if value == 0]
        self.assertEqual(len(dollar_positions), 8)
        recovery = [pure.recoverString(pos) for pos in dollar_positions]
        recovery_compiled = [compiled.recoverString(pos)
                             for pos in dollar_positions]
        self.assertEqual(recovery, COLLECTION_RECOVERY)
        self.assertEqual(recovery, recovery_compiled)

    # ------------------------------------------------------------------
    # multi-digit RLE regression (Q1 audit hygiene)
    # ------------------------------------------------------------------
    def test_multidigit_rle_decode_matches_encoder_semantics(self):
        """A run whose length needs multiple base-32 digits must decode as
        LEAST-SIGNIFICANT-DIGIT-FIRST, matching the actual encoder
        semantics

            byte = ((delta & mask) << letterBits) + sym; delta /= numPower

        (MUSCython/MSBWTGenCython.pyx: letterBits=3, mask=31, numPower=32,
        base-32 digits) and the reader's decoder power ordering
        (MUSCython/RLE_BWTCython.pyx: first digit * 32**0, then
        powerMultiple *= numPower).  The committed golden RLE payloads
        contain only single-digit runs (all run lengths <= 32), so they
        cannot distinguish the two digit orders; this regression
        independently derives the expected bytes from the encoder loop
        above and the expected counts/symbols from the base-32 digit
        decomposition.  (An MSB-first decode of the same bytes would
        return 129 instead of 36 for the T run, 131 instead of 100 for
        the C run, and 17345 instead of 2000 for the N run.)
        """
        import numpy as np
        # (symbol index, run length) pairs; 36/100/129/2000 need 2-3
        # base-32 digits (multi-digit), 3 and 1 stay single-digit.
        runs = [(1, 3), (5, 36), (2, 100), (3, 129), (4, 2000), (5, 1)]
        expected_counts = [0, 3, 100, 129, 2000, 37]  # order '$ACGNT'
        expected_length = 3 + 36 + 100 + 129 + 2000 + 1

        # expected digit decomposition derived from delta & mask,
        # delta /= numPower (least significant first), keyed by run length
        expected_digits = {36: [4, 1], 100: [4, 3], 129: [1, 4],
                           2000: [16, 30, 1]}
        for sym, count in runs:
            delta = count
            digits = []
            while delta > 0:
                digits.append(delta & 31)
                delta //= 32
            if count in expected_digits:
                self.assertEqual(digits, expected_digits[count],
                                 "digit decomposition of run %d" % count)

        # encode with the exact encoder semantics
        bytes_out = []
        for sym, count in runs:
            delta = count
            while delta > 0:
                bytes_out.append(((delta & 31) << 3) + sym)
                delta //= 32
        payload_path = os.path.join(self.work, "multidigit_rle.npy")
        _npy_compat.save_npy(payload_path, np.array(bytes_out, dtype=np.uint8))

        counts, symbols = self._decode_rle_counts(payload_path)
        self.assertEqual(counts, expected_counts)
        self.assertEqual(len(symbols), expected_length)
        # the full decoded run expansion must match the input runs
        expansion = []
        for sym, count in runs:
            expansion.extend([sym] * count)
        self.assertEqual(symbols, expansion)
        # totalCounts-style check: sum of decoded counts is the payload
        # length decoded (each byte contributes one run digit)
        self.assertEqual(sum(counts), expected_length)

    # ------------------------------------------------------------------
    # historical classification
    # ------------------------------------------------------------------
    def test_frozen_init_paths_identical_and_unchanged(self):
        """The frozen source is untouched, and the frozen and modern2
        constructTotalCounts/constructFMIndex algorithm texts are identical
        (CRLF-normalized).  The only modern2 deltas are the documented
        Windows-portability binary-mode pickle opens in
        constructTotalCounts (see COMPATIBILITY.md); they are normalized
        away below."""
        frozen_path = os.path.join(REPO, "MUS", "MultiStringBWT.py")
        modern2_path = os.path.join(REPO, "packages", "msbwt-modern2", "MUS",
                                    "MultiStringBWT.py")
        self.assertEqual(sha256_file(frozen_path), FROZEN_SHA256)
        frozen_text = open(frozen_path, "rb").read().decode().replace("\r\n", "\n")
        modern2_text = open(modern2_path, "rb").read().decode().replace("\r\n", "\n")

        def portable_normalize(text):
            # drop documentation comment lines and normalize the pickle open
            # modes back to the historical text-mode forms
            out = []
            for line in text.splitlines():
                if line.strip().startswith("#"):
                    continue
                line = line.replace("'rb'", "'r'").replace("'wb+'", "'w+'")
                out.append(line)
            return "\n".join(out)

        for name in ("constructTotalCounts", "constructFMIndex"):
            pattern = ("(    def %s\\(self, logger\\):.*?\\n        .*?)"
                       "(?=\\n    def |\\nclass |\\ndef )" % name)
            frozen_match = re.search(pattern, frozen_text, re.S)
            modern2_match = re.search(pattern, modern2_text, re.S)
            self.assertTrue(frozen_match and modern2_match, name)
            self.assertEqual(
                portable_normalize(frozen_match.group(1)),
                portable_normalize(modern2_match.group(1)), name)


if __name__ == "__main__":
    unittest.main()
