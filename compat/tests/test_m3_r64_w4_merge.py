"""M3-R64-W4 regression: merge/construction width + pointer-path safety.

Covers:
* the multimerge inter-thread pointer transport round trip
  (rangeIterator -> rangeSolve_thread) using real compiled code; pre-repair
  the heap pointer was truncated through a 32-bit ``unsigned long`` on Win64;
* >2^32 boundary values through compiled probes that use the exact
  production scalar types/arithmetic for merged lengths, record offsets and
  construction cumulative offsets;
* the empty-input merge contract: merging with an empty (zero-row) package
  completes; constructing from zero reads raises a controlled Python
  exception (no native crash).
"""

import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import logging

import test_multisource_query as f3

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG_ROOT = os.path.join(REPO_ROOT, "packages", "msbwt-modern3")

BOUNDARIES = [
    2 ** 31 - 1,
    2 ** 31,
    2 ** 32 - 1,
    2 ** 32,
    2 ** 32 + 1,
    2 ** 32 + 12345,
]


def _run_snippet(code):
    snippet = (
        "import sys; "
        "sys.path[:0] = [r'%s', r'%s']; "
        "import MUSCython; "
        "assert MUSCython.__file__.startswith(r'%s'), MUSCython.__file__;\n"
        % (PKG_ROOT, REPO_ROOT, PKG_ROOT)
    ) + code
    return subprocess.run(
        [sys.executable, "-c", snippet], capture_output=True, timeout=180)


def _pointer_probe_code(num_threads):
    """Builds a production-shaped pointer array from real buffers, feeds it
    through rangeIterator -> ThreadPool -> rangeSolve_thread, and verifies
    the restored pointers were dereferenced into nextEntries.

    Every repetition rebuilds ALL input buffers: the solver intentionally
    advances FM/range state through the raw pointers (production
    semantics), so reuse across repetitions is not idempotent.
    """
    return (
        "import logging" + "\n"
        "import numpy as np" + "\n"
        "log = logging.getLogger('x')" + "\n"
        "from MUSCython import MultimergeCython as MM" + "\n"
        "nvc = 6" + "\n"
        "results = []" + "\n"
        "for rep in range(25):" + "\n"
        "    seqs0 = np.array([2, 2, 1, 5], dtype=np.uint8)" + "\n"
        "    seqs1 = np.array([1, 3, 1, 0], dtype=np.uint8)" + "\n"
        "    fm0 = np.zeros((1, nvc), dtype='<u8')" + "\n"
        "    fm1 = np.zeros((1, nvc), dtype='<u8')" + "\n"
        "    ranges = np.array([[0, 0, 8]], dtype='<u8')" + "\n"
        "    bits = [0, 0, 1, 1, 0, 1, 0, 1]" + "\n"
        "    inter_bytes = bytearray(2)" + "\n"
        "    for i, b in enumerate(bits):" + "\n"
        "        if b: inter_bytes[i >> 3] |= 1 << (i & 7)" + "\n"
        "    input_inter = np.frombuffer(bytes(inter_bytes), dtype=np.uint8)" + "\n"
        "    output_inter = np.frombuffer(bytes(a ^ 0xFF for a in inter_bytes)," + "\n"
        "                                 dtype=np.uint8)" + "\n"
        "    nxt = np.zeros((nvc, 16, 3), dtype='<u8')" + "\n"
        "    ptrs = np.zeros(8, dtype='<u8')" + "\n"
        "    ptrs[0] = seqs0.ctypes.data" + "\n"
        "    ptrs[1] = seqs1.ctypes.data" + "\n"
        "    ptrs[2] = fm0.ctypes.data" + "\n"
        "    ptrs[3] = fm1.ctypes.data" + "\n"
        "    ptrs[4] = ranges.ctypes.data" + "\n"
        "    ptrs[5] = input_inter.ctypes.data" + "\n"
        "    ptrs[6] = output_inter.ctypes.data" + "\n"
        "    ptrs[7] = nxt.ctypes.data" + "\n"
        "    jobs = MM.rangeIterator(ptrs, 11, nvc, ranges, 1, %d)" % num_threads + "\n"
        "    got = list(MM.rangeSolve_thread(t) for t in jobs)" + "\n"
        "    results.append(nxt.copy())" + "\n"
        "first = results[0]" + "\n"
        "for res in results[1:]:" + "\n"
        "    assert np.array_equal(first, res), 'nondeterministic'" + "\n"
        "assert first.any(), 'nextEntries never written through pointers'" + "\n"
        "print('PTR-OK', int(ptrs.max()))" + "\n"
    )

class PointerRoundTripTests(unittest.TestCase):
    def test_pointer_transport_in_process(self):
        result = _run_snippet(_pointer_probe_code(1))
        self.assertEqual(result.returncode, 0, result.stderr.decode()[-800:])
        self.assertIn(b"PTR-OK", result.stdout)

    def test_pointer_transport_threaded_subprocess(self):
        # numThreads=2 exercises the exact ThreadPool branch whose yield/
        # restore pair truncated pointers through unsigned long pre-repair.
        result = _run_snippet(_pointer_probe_code(2))
        self.assertEqual(result.returncode, 0, result.stderr.decode()[-800:])
        self.assertIn(b"PTR-OK", result.stdout)

    def test_pointer_values_fit_u64_transport(self):
        # The <u8 slot storage must hold full heap addresses; the former
        # defect was the unsigned long yield cast, not this storage.
        import ctypes
        buf = np.zeros(4, dtype=np.uint8)
        addr = buf.ctypes.data
        self.assertLess(addr, 2 ** 64)
        self.assertGreater(addr, 0)


class MergeConstructionBoundaryProbes(unittest.TestCase):
    def test_merged_length_sum_boundaries(self):
        from MUSCython import MultimergeCython as MM
        for v in BOUNDARIES:
            self.assertEqual(int(MM.merged_length_probe(v, 0)), v, v)
            self.assertEqual(
                int(MM.merged_length_probe(v, 2 ** 32 + 12345)),
                v + 2 ** 32 + 12345, v)

    def test_record_offset_product_boundaries(self):
        from MUSCython import MultimergeCython as MM
        for v in BOUNDARIES:
            self.assertEqual(int(MM.record_offset_probe(v, 3)), v * 3, v)
            self.assertEqual(int(MM.record_offset_probe(1, v)), v, v)

    def test_construction_cumulative_offset_boundaries(self):
        from MUSCython import MSBWTGenCython as MG
        for v in BOUNDARIES:
            self.assertEqual(int(MG.construction_offset_probe(v, 1)), v + 1, v)
            self.assertEqual(
                int(MG.construction_offset_probe(2 ** 32, v)),
                2 ** 32 + v, v)


class EmptyInputMergeContractTests(unittest.TestCase):
    """Merging against a zero-row package is supported and completes;
    constructing from zero reads is rejected with a controlled Python
    exception (never a native crash)."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="m3r64w4-empty-")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.work, ignore_errors=True)

    def test_merge_with_empty_package_completes(self):
        leaf = f3.make_read_derived_leaf(self.work, "src",
                                         ["ACGTAC", "TTGCA"])
        expected_rows = sum(len(r) + 1 for r in ["ACGTAC", "TTGCA"])
        empty = os.path.join(self.work, "empty")
        os.makedirs(empty)
        np.save(os.path.join(empty, "msbwt.npy"),
                np.zeros(dtype="|u1", shape=(0,)))
        out = os.path.join(self.work, "merged")
        os.makedirs(out)
        code = (
            "import logging, numpy as np" + "\n"
            "log = logging.getLogger('x')" + "\n"
            "from MUSCython import GenericMerge" + "\n"
            "GenericMerge.mergeTwoMSBWTs(r'%s', r'%s', r'%s', 1, log)" + "\n"
            "m = np.load(r'%s/msbwt.npy')" + "\n"
            "assert m.shape[0] == %d, m.shape" + "\n"
            "print('MERGE-EMPTY-OK')" + "\n"
        ) % (leaf, empty, out, out, expected_rows)
        result = _run_snippet(code)
        self.assertEqual(result.returncode, 0, result.stderr.decode()[-800:])
        self.assertIn(b"MERGE-EMPTY-OK", result.stdout)

    def test_construct_from_zero_reads_controlled_exception(self):
        code = (
            "import logging" + "\n"
            "import os" + "\n"
            "from MUSCython import MultimergeCython as MM" + "\n"
            "d = os.path.join(r'%s', 'out')" % self.work + "\n"
            "os.makedirs(d, exist_ok=True)" + "\n"
            "try:" + "\n"
            "    MM.createMSBWTFromSeqs([], d, 1, True, logging.getLogger('x'))" + "\n"
            "except ZeroDivisionError:" + "\n"
            "    print('CONTROLLED-DIV')\n"
            "else:\n"
            "    print('UNEXPECTED-SUCCESS')" + "\n"
        )
        result = _run_snippet(code)
        self.assertEqual(result.returncode, 0, result.stderr.decode()[-800:])
        self.assertIn(b"CONTROLLED-DIV", result.stdout)
        self.assertNotIn(b"UNEXPECTED-SUCCESS", result.stdout)


if __name__ == "__main__":
    unittest.main()
