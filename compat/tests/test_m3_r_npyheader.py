"""M3-R-NPYHEADER regression: .npy headers must never embed NumPy-2 scalar
reprs in persisted shapes.

Under NumPy >= 2 (NEP 51 scalar repr), passing a NumPy integer as an
open_memmap shape element serializes headers like ``shape: (np.int64(15),)``
which numpy itself cannot parse back.  The pure-Python non-uniform fallback
(MUS.MSBWTGen.writeSeqsToFiles) and createFromSeqs' total-size allocation
both derived shapes from NumPy scalars; they must normalize to builtin ints.
"""

import os
import struct
import tempfile
import unittest

import numpy as np

from MUS.MSBWTGen import writeSeqsToFiles


def read_npy_header(path):
    with open(path, "rb") as fp:
        raw = fp.read(10)
        magic = raw[:6]
        assert magic == b"\x93NUMPY", magic
        version = (raw[6], raw[7])
        if version[0] == 1:
            hlen = struct.unpack("<H", fp.read(2))[0]
        else:
            hlen = struct.unpack("<I", fp.read(4))[0]
        return fp.read(hlen)


class NpyHeaderScalarShapeTests(unittest.TestCase):
    def _work(self):
        return tempfile.mkdtemp(prefix="m3-r-npyheader-")

    def test_nonuniform_seqs_header_is_builtin_int_shape(self):
        work = self._work()
        try:
            # non-uniform corpus -> lenSums[-1] is a NumPy uint64 scalar
            reads = ["ACGT$", "TTG$", "GCA$", "A$"]
            arr = np.frombuffer("".join(reads).encode("ascii"), dtype=np.uint8)
            seqPrefix = os.path.join(work, "seqs")
            offsetFN = os.path.join(work, "offsets.npy")
            writeSeqsToFiles(arr, seqPrefix, offsetFN, None)

            header = read_npy_header(seqPrefix + ".npy")
            self.assertNotIn(b"np.int64", header)
            self.assertNotIn(b"np.uint64", header)
            self.assertIn(b"'shape': (15,)", header)

            # the generated file must reload through ordinary numpy
            seqs = np.load(seqPrefix + ".npy", "r")
            self.assertEqual(seqs.shape, (sum(len(r) for r in reads),))

            offs = np.load(offsetFN, "r")
            self.assertEqual(offs.shape, (len(reads) + 1,))
            self.assertEqual(int(offs[-1]), sum(len(r) for r in reads))
        finally:
            pass

    def test_uniform_path_header_unchanged(self):
        work = self._work()
        try:
            reads = ["ACGTA$", "CATTA$"]
            arr = np.frombuffer("".join(reads).encode("ascii"), dtype=np.uint8)
            seqPrefix = os.path.join(work, "useqs")
            offsetFN = os.path.join(work, "uoffsets.npy")
            writeSeqsToFiles(arr, seqPrefix, offsetFN, 6)

            header = read_npy_header(seqPrefix + ".0.npy")
            self.assertIn(b"'shape': (2,)", header)
            self.assertNotIn(b"np.", header)
            seqs = np.load(seqPrefix + ".0.npy", "r")
            self.assertEqual(seqs.shape, (2,))
            self.assertEqual(int(np.load(offsetFN, "r")[0]), 6)
        finally:
            pass

    def test_scalar_shape_poison_documented_by_probe(self):
        # documents the root cause at the numpy layer: any numpy scalar
        # shape element poisons the header under numpy>=2; builtin int is
        # the contract the production code must satisfy.
        work = self._work()
        try:
            fn = os.path.join(work, "poison.npy")
            np.lib.format.open_memmap(fn, "w+", "<u1", (np.int64(4),))
            header = read_npy_header(fn)
            self.assertIn(b"np.int64(4)", header)
            with self.assertRaises(ValueError):
                np.load(fn, "r")

            fn2 = os.path.join(work, "fixed.npy")
            np.lib.format.open_memmap(fn2, "w+", "<u1", (int(np.int64(4)),))
            self.assertEqual(np.load(fn2, "r").shape, (4,))
        finally:
            pass


if __name__ == "__main__":
    unittest.main()
