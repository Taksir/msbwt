"""Stage 1 audit finding #1: totalCounts.p must never execute pickle payloads.

``<DIR>/totalCounts.p`` is a pickle of a 1-D integer (byte BWT) or float64 (RLE BWT) NumPy array.  Datasets are
untrusted input, so the reader accepts only the globals a genuine array needs.
The on-disk format is unchanged: files written by the existing writer (any
pickle protocol) must still load, byte-for-byte equal in content.
"""

import os
import pickle
import tempfile
import unittest

import numpy as np

from MUS import util


_RAN = []


def _mark():
    _RAN.append(1)


class _Payload(object):
    """Pickles to a call of _mark, a harmless stand-in for code execution."""
    def __reduce__(self):
        return (_mark, ())


class TotalCountsLoaderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "totalCounts.p")
        del _RAN[:]

    def _write(self, obj, protocol=None):
        with open(self.path, "wb") as fp:
            pickle.dump(obj, fp, protocol=protocol)

    def test_genuine_arrays_load_under_every_protocol(self):
        arrays = [
            np.bincount(np.array([1, 2, 2, 5], dtype="u1"), minlength=6),
            np.array([0, 3, 0, 1, 2, 9], dtype="<u8"),
            np.array([5, 0, 0, 0, 0, 7], dtype="<u4"),
            # the RLE writer stores float64 (np.bincount with weights)
            np.bincount(np.array([0, 1, 1]), np.array([1, 2, 3]), minlength=6),
        ]
        for arr in arrays:
            for protocol in range(2, pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(dtype=str(arr.dtype), protocol=protocol):
                    self._write(arr, protocol)
                    loaded = util.loadTotalCounts(self.path)
                    self.assertEqual(loaded.dtype, arr.dtype)
                    self.assertEqual(loaded.tolist(), arr.tolist())

    def test_executable_pickle_is_rejected_and_not_run(self):
        self._write(_Payload())
        # control: a plain pickle.load does run the payload, so the check below is meaningful
        with open(self.path, "rb") as fp:
            pickle.load(fp)
        self.assertEqual(_RAN, [1])
        del _RAN[:]
        with self.assertRaises(ValueError):
            util.loadTotalCounts(self.path)
        self.assertEqual(_RAN, [])

    def test_other_codecs_are_rejected(self):
        # protocol-2 style _codecs.encode with a non-latin1 codec
        data = (b"\x80\x02c_codecs\nencode\nq\x00X\x01\x00\x00\x00aq\x01X\x03\x00\x00\x00zipq\x02\x86q\x03Rq\x04.")
        with open(self.path, "wb") as fp:
            fp.write(data)
        with self.assertRaises(ValueError):
            util.loadTotalCounts(self.path)

    def test_wrong_shapes_and_types_are_rejected(self):
        for label, obj in [
            ("list", [0, 1, 2]),
            ("2d", np.zeros((2, 2), dtype="<u8")),
            ("complex", np.zeros(6, dtype="<c16")),
            ("object", np.array([1, 2], dtype=object)),
            ("int", 5),
        ]:
            with self.subTest(case=label):
                self._write(obj)
                with self.assertRaises(ValueError):
                    util.loadTotalCounts(self.path)

    def test_truncated_and_empty_files_are_rejected(self):
        self._write(np.arange(6, dtype="<u8"))
        with open(self.path, "rb") as fp:
            data = fp.read()
        for label, blob in [("truncated", data[: len(data) // 2]), ("empty", b""), ("garbage", b"not a pickle")]:
            with self.subTest(case=label):
                with open(self.path, "wb") as fp:
                    fp.write(blob)
                with self.assertRaises(ValueError):
                    util.loadTotalCounts(self.path)


if __name__ == "__main__":
    unittest.main()
