"""M3-R64-COMPRESS4G regression: RLE compression counters are 64-bit safe.

The historical `unsigned long` declarations for `bytesWritten` and
`currCount` were 32-bit on Win64 LLP64: output beyond 2^32-1 bytes wrapped
the .npy header shape counter and single runs longer than 2^32-1 symbols
wrapped the run accumulator.  Linux LP64 masked both defects.

This regression exercises the production scalar types/arithmetic through the
compiled boundary probe (source-text pins alone are insufficient), verifies
the downstream header-shape calculation, and protects ordinary Byte->RLE->
load/query/decompress behavior plus the persisted header semantics.
"""

import os
import struct
import tempfile
import unittest

import numpy as np

from MUSCython import CompressToRLE
from MUS.MSBWTGen import decompressBWT

import logging

LOGGER = logging.getLogger("m3-r64-compress4g")
logging.basicConfig(level=logging.CRITICAL)


def _oracle_chunks(v):
    """Pure-Python mirror of the production chunk-count arithmetic."""
    n = 0
    while v > 0:
        n += 1
        v >>= 5
    return n


class CounterBoundaryTests(unittest.TestCase):
    def test_boundary_values_exact(self):
        boundaries = [
            0,
            1,
            31,
            32,
            1023,
            2 ** 32 - 1,
            2 ** 32,
            2 ** 32 + 1,
            2 ** 32 + 12345,
            2 ** 40 + 7,
        ]
        for v in boundaries:
            got_bytes, got_shape = CompressToRLE.rle_counter_boundary_probe(v)
            want = _oracle_chunks(v)
            self.assertEqual(int(got_bytes), want,
                             "byte count wrong for %d" % v)
            self.assertEqual(got_shape, ("(%d,)" % want).encode("ascii"),
                             "header shape field wrong for %d" % v)

    def test_counter_declarations_are_64bit(self):
        # secondary pin: the production declarations must be fixed-width u64
        mod_dir = os.path.dirname(os.path.abspath(CompressToRLE.__file__))
        src = None
        for cand in (os.path.join(mod_dir, "CompressToRLE.pyx"),
                     os.path.join(mod_dir, os.pardir, os.pardir,
                                  "packages", "msbwt-modern3", "MUSCython",
                                  "CompressToRLE.pyx")):
            if os.path.exists(cand):
                with open(cand, "r", encoding="utf-8") as fp:
                    src = fp.read()
                break
        if src is None:
            self.skipTest("pyx source not found near built module")
        self.assertIn("cdef np.uint64_t currCount", src)
        self.assertIn("cdef np.uint64_t bytesWritten", src)
        self.assertNotIn("cdef unsigned long currCount", src)
        self.assertNotIn("cdef unsigned long bytesWritten", src)


class OrdinaryRoundTripTests(unittest.TestCase):
    def _write_input(self, work, text):
        srcFN = os.path.join(work, "bwt.txt")
        with open(srcFN, "w", newline="") as fp:
            fp.write(text)
        return srcFN

    def test_compress_input_round_trip_and_header(self):
        # Established convert contract (msbwt.wiki Constructing-the-MSBWT):
        # the input is a single raw BWT symbol stream on one line.
        work = tempfile.mkdtemp(prefix="m3-r64-compress4g-")
        reads = ["ACGT$" * 3 + "ACG",
                 "TTGCCAAT" * 2,
                 "NNGGCAN" * 3]
        text = "".join(reads)
        srcFN = self._write_input(work, text)
        outDir = os.path.join(work, "rle")
        os.makedirs(outDir)
        CompressToRLE.compressInput(srcFN, outDir)

        comp_path = os.path.join(outDir, "comp_msbwt.npy")
        with open(comp_path, "rb") as fp:
            self.assertEqual(fp.read(6), b"\x93NUMPY")
            fp.read(2)  # version
            hlen = struct.unpack("<H", fp.read(2))[0]
            header = fp.read(hlen).decode("latin1")
        # header shape must equal the exact payload size on disk
        import re
        m = re.search(r"'shape': \((\d+),\)", header)
        self.assertIsNotNone(m, header)
        declared = int(m.group(1))
        actual = os.path.getsize(comp_path) - (10 + hlen)
        self.assertEqual(declared, actual,
                         "header shape != payload size (%d vs %d)"
                         % (declared, actual))

        # logical round trip: decompress and compare symbol codes
        dec_dir = os.path.join(work, "dec")
        os.makedirs(dec_dir)
        decompressBWT(outDir, dec_dir, 1, LOGGER)
        dec = np.load(os.path.join(dec_dir, "msbwt.npy"), "r")
        code = {"$": 0, "A": 1, "C": 2, "G": 3, "N": 4, "T": 5}
        expect = bytes(code[c] for c in text)
        self.assertEqual(int(dec.shape[0]), len(expect))
        self.assertEqual(bytes(bytearray(dec[:])), expect)

    def test_run_splitting_invariant_on_long_runs(self):
        # a single run far longer than any single encoded chunk must be
        # split into multiple 5-bit chunks by the producer; verify the
        # encoding invariant directly on a moderate run.
        work = tempfile.mkdtemp(prefix="m3-r64-compress4g-run-")
        run_len = 100000
        srcFN = os.path.join(work, "bwt.txt")
        with open(srcFN, "w", newline="") as fp:
            fp.write("A" * run_len + "\n")
        outDir = os.path.join(work, "rle")
        os.makedirs(outDir)
        CompressToRLE.compressInput(srcFN, outDir)
        comp_path = os.path.join(outDir, "comp_msbwt.npy")
        arr = np.load(comp_path, "r")
        payload = bytes(bytearray(arr[:]))
        # decode: little-endian base-32 chunks, symbol in low 3 bits;
        # a single run splits across ceil(bits/5) bytes -- proving the
        # persisted representation already supports arbitrary run lengths.
        total = 0
        for pos, b in enumerate(payload):
            self.assertEqual(b & 0x07, 1)
            total += (b >> 3) * (32 ** pos)
        self.assertEqual(total, run_len)

    def test_documented_first_newline_quirk_unchanged(self):
        # msbwt.wiki "Notes on the legacy quirks": convert silently drops
        # everything after the first newline of the input.  Pin this
        # documented behavior so the counter repair cannot alter it.
        work = tempfile.mkdtemp(prefix="m3-r64-compress4g-nl-")
        out1 = os.path.join(work, "rle1")
        out2 = os.path.join(work, "rle2")
        os.makedirs(out1)
        os.makedirs(out2)
        src1 = self._write_input(work, "ACGT$ACGT\nTTTTTTTT")
        src2 = os.path.join(work, "bwt2.txt")
        with open(src2, "w", newline="") as fp:
            fp.write("ACGT$ACGT")
        CompressToRLE.compressInput(src1, out1)
        CompressToRLE.compressInput(src2, out2)
        a = np.load(os.path.join(out1, "comp_msbwt.npy"), "r")
        b = np.load(os.path.join(out2, "comp_msbwt.npy"), "r")
        self.assertEqual(bytes(bytearray(a[:])), bytes(bytearray(b[:])))


if __name__ == "__main__":
    unittest.main()
