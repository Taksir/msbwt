"""M3-R64-W3 regression: compiled reader/recovery width repair.

Covers:
* RLE recovery-record serialization carries real 64-bit values (the former
  ``fwrite(&readID, 8, 1, fp)`` read 8 bytes from a 4-byte Win64 scalar);
* LCP-assisted compiled queries fail with a deterministic Python exception
  when the package has no lcps.npy (pre-repair: native access violation
  through the uninitialized lcps_view) and still work when it is present;
* Byte/RLE/LZW readers agree row-for-row on ordinary inputs after widening.
"""

import logging
import os
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from MUS.LCP import construct_lcp_from_bwt
from MUS.MSBWTGen import compressBWT
import test_multisource_query as f3
from MUSCython import MultiStringBWTCython as MSB
from MUSCython import RLE_BWTCython

loadBWT = MSB.loadBWT

READS = ["ACGTAC", "GGATC", "TTGCA"]
BOUNDARIES = [
    2 ** 31 - 1,
    2 ** 31,
    2 ** 32 - 1,
    2 ** 32,
    2 ** 32 + 1,
    2 ** 32 + 12345,
    2 ** 64 - 1,
]

LOGGER = logging.getLogger("m3r64w3-readers")

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RecoverySerializationTests(unittest.TestCase):
    def test_u64_record_serialization_boundaries(self):
        # Exercises the exact little-endian byte sequence used by
        # removeStrings()'s recovery records (deletion_indices.dat holds
        # little-endian <u8 records).
        for value in BOUNDARIES:
            self.assertEqual(
                RLE_BWTCython.recovery_record_u64_le(value),
                struct.pack("<Q", value),
                value,
            )


class LcpAbsenceSafetyTests(unittest.TestCase):
    """No lcps.npy must never crash the interpreter (inherited Modern2 bug).

    The subprocess isolation demonstrates the pre-repair failure mode (a
    native access violation kills the child process) without killing the
    test runner; post-repair the child must exit cleanly with ValueError.
    """

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="m3r64w3-lcpabs-")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.work, ignore_errors=True)

    def _leaf(self, name):
        return f3.make_read_derived_leaf(self.work, name, list(READS))

    def _run_snippet(self, code):
        env_path = os.path.join(REPO_ROOT, "packages", "msbwt-modern3")
        snippet = (
            "import sys; "
            "sys.path.insert(0, r'%s'); "
            "sys.path.insert(0, r'%s');\n" % (env_path, REPO_ROOT)
        ) + code
        return subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            timeout=120,
        )

    def test_count_stranded_without_lcp_raises_not_crashes(self):
        leaf = self._leaf("pkg")
        probe = (
            "from MUSCython import MultiStringBWTCython as MSB\n"
            "bwt = MSB.loadBWT(r'%s', False, None)\n"
            "try:\n"
            "    bwt.countStrandedSeqMatches('ACG', 2)\n"
            "except ValueError as exc:\n"
            "    assert 'lcps.npy' in str(exc), exc\n"
            "    print('VALUEERROR-OK')\n"
            "else:\n"
            "    raise AssertionError('expected ValueError')\n"
        ) % leaf
        result = self._run_snippet(probe)
        self.assertEqual(result.returncode, 0, result.stderr.decode()[-800:])
        self.assertIn(b"VALUEERROR-OK", result.stdout)

    def test_all_guarded_entry_points_raise_without_lcp(self):
        leaf = self._leaf("pkg")
        rle_dir = os.path.join(self.work, "rle")
        os.makedirs(rle_dir)
        compressBWT(
            os.path.join(leaf, "msbwt.npy"),
            os.path.join(rle_dir, "comp_msbwt.npy"),
            1,
            LOGGER,
        )
        probe = (
            "from MUSCython import MultiStringBWTCython as MSB\n"
            "calls = [\n"
            "    lambda b: b.countSeqMatches('ACG', 2),\n"
            "    lambda b: b.countStrandedSeqMatches('ACG', 2),\n"
            "    lambda b: b.countStrandedSeqMatchesNoOther('ACG', 2),\n"
            "    lambda b: b.findKmerThreshold('ACG', 2),\n"
            "    lambda b: b.findKmerThresholdStranded('ACG', 2),\n"
            "    lambda b: b.findKTOtherStranded('ACG', 2),\n"
            "]\n"
            "b = MSB.ByteBWT(); b.loadMsbwt(r'%s', False, None)\n"
            "for fn in calls:\n"
            "    try:\n"
            "        fn(b)\n"
            "    except ValueError:\n"
            "        pass\n"
            "    else:\n"
            "        raise AssertionError(fn)\n"
            "r = MSB.RLE_BWT(); r.loadMsbwt(r'%s', False, None)\n"
            "rcalls = [\n"
            "    lambda b: b.findReadsMatchingSeq('ACGT', 4),\n"
            "    lambda b: b.findReadsMatchingSeqWithError('ACGT', 4),\n"
            "    lambda b: b.findReadsMatchingSeqWithError2('ACGT', 4),\n"
            "]\n"
            "for fn in rcalls:\n"
            "    try:\n"
            "        fn(r)\n"
            "    except ValueError:\n"
            "        pass\n"
            "    else:\n"
            "        raise AssertionError(fn)\n"
            "print('ALL-GUARDED')\n"
        ) % (leaf, rle_dir)
        result = self._run_snippet(probe)
        self.assertEqual(result.returncode, 0, result.stderr.decode()[-800:])
        self.assertIn(b"ALL-GUARDED", result.stdout)

    def test_lcp_present_queries_still_work(self):
        leaf = self._leaf("pkg")
        construct_lcp_from_bwt(
            leaf, bwt=loadBWT(leaf, False, None))
        bwt = loadBWT(leaf, False, None)
        stranded = bwt.countStrandedSeqMatches("ACG", 2)
        self.assertIsInstance(stranded, tuple)
        other = bwt.findKTOtherStranded("ACG", 2)
        self.assertEqual(len(other), len("ACG"))


class ReaderConsistencyTests(unittest.TestCase):
    """Byte/RLE/LZW must agree symbol-for-symbol and rank-for-rank."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="m3r64w3-readers-")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.work, ignore_errors=True)

    def _build_all_three(self):
        leaf = f3.make_read_derived_leaf(self.work, "byte", list(READS))
        n_rows = sum(len(r) + 1 for r in READS)

        rle_dir = os.path.join(self.work, "rle")
        os.makedirs(rle_dir)
        compressBWT(
            os.path.join(leaf, "msbwt.npy"),
            os.path.join(rle_dir, "comp_msbwt.npy"),
            1,
            LOGGER,
        )
        rle = MSB.RLE_BWT()
        rle.loadMsbwt(rle_dir, False, LOGGER)

        byte = loadBWT(leaf, False, LOGGER)
        return byte, rle, n_rows

    def test_cross_reader_symbol_and_rank_agreement(self):
        # NOTE: LZW is excluded: no LZW encoder exists in any generation of
        # this repository, so a behaviorally valid container cannot be
        # synthesized.  LZW width repairs are validated statically via the
        # warning audit (W3 report).
        byte, rle, n_rows = self._build_all_three()

        for index in range(n_rows):
            self.assertEqual(
                int(byte.getCharAtIndex(index)),
                int(rle.getCharAtIndex(index)),
                index,
            )

        for sym in range(1, 6):
            for index in range(0, n_rows + 1, 3):
                expected = int(byte.getOccurrenceOfCharAtIndex(sym, index))
                self.assertEqual(
                    expected,
                    int(rle.getOccurrenceOfCharAtIndex(sym, index)),
                    (sym, index),
                )

    def test_remove_strings_round_trip_on_tiny_package(self):
        leaf = f3.make_read_derived_leaf(self.work, "rledel", list(READS))
        rle_dir = os.path.join(self.work, "rledel_rle")
        os.makedirs(rle_dir)
        compressBWT(
            os.path.join(leaf, "msbwt.npy"),
            os.path.join(rle_dir, "comp_msbwt.npy"),
            1,
            LOGGER,
        )

        rle = MSB.RLE_BWT()
        rle.loadMsbwt(rle_dir, False, None)
        before = int(rle.getTotalSize())
        removed_read_len = len(sorted(r + '$' for r in READS)[1])

        # removeStrings writes deletion_indices.dat through the repaired
        # serialization path and reloads in place.
        rle.removeStrings({1})
        self.assertFalse(
            os.path.exists(os.path.join(rle_dir, "deletion_indices.dat"))
        )

        reloaded = MSB.RLE_BWT()
        reloaded.loadMsbwt(rle_dir, False, None)
        self.assertEqual(int(reloaded.getTotalSize()),
                         before - removed_read_len)

        recovered = sorted(
            reloaded.recoverString(d).decode("ascii").replace("$", "")
            for d in range(2)
        )
        self.assertEqual(recovered, sorted(READS[i] for i in (0, 2)))


if __name__ == "__main__":
    unittest.main()
