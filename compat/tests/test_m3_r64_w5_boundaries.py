"""M3-R64-W5 regression: Python numeric boundaries + persisted-width contracts."""
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

import test_multisource_query as f3
from MUSCython import MultiStringBWTCython as MSB

loadBWT = MSB.loadBWT

READS = ["ACGTAC", "GGATC", "TTGCA"]


class Float64RankPromotionTests(unittest.TestCase):
    """getOccurrenceOfCharAtIndex / getFullFMAtIndex (pure-Python path) must
    stay in exact integer arithmetic (uint64+int64 promoted to float64 before
    the W5 repair; float64 is inexact above 2^53)."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="m3r64w5-num-")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.work, ignore_errors=True)

    def test_rank_returns_exact_integers(self):
        # Exercise the REPAIRED pure-Python expressions directly
        # (MUS/MultiStringBWT.py); the compiled reader was always exact.
        import types
        from MUS.MultiStringBWT import MultiStringBWT as PureBWT

        partialFM = np.array([[0, 2, 4, 6, 8, 10],
                              [1, 3, 5, 7, 9, 11]], dtype='<u8')
        bwt = np.array([1, 2, 0, 3, 1, 2, 0, 3], dtype='<u1')
        obj = PureBWT.__new__(PureBWT)
        obj.partialFM = partialFM
        obj.bwt = bwt
        obj.bitPower = 3
        obj.offsetSum = 0
        obj.vcLen = 6

        # scalar path (uint64 + int64 promoted to float64 pre-repair)
        value = obj.getOccurrenceOfCharAtIndex(1, 5)
        self.assertIsInstance(value, int)
        # Holt semantics: getOccurrenceOfCharAtIndex returns C[c]+Occ(c,i)
        expected = int(partialFM[0][1]) + sum(1 for x in bwt[:5] if x == 1)
        self.assertEqual(value, expected)

        # vector path
        full = obj.getFullFMAtIndex(5)
        self.assertEqual(full.dtype, np.dtype('<i8'), full.dtype)
        # full-FM vector = partialFM row + in-bin occurrence counts
        expected = [int(partialFM[0][s]) +
                    int(np.count_nonzero(bwt[:5] == s)) for s in range(6)]
        self.assertEqual([int(x) for x in full], expected)

    def test_source_pin_no_float64_rank_expression(self):
        path = os.path.join(
            REPO_ROOT_W5, "packages", "msbwt-modern3", "MUS",
            "MultiStringBWT.py")
        text = open(path, encoding="utf-8").read()
        self.assertNotIn(
            "ret = self.partialFM[binID][sym] + np.bincount(", text)
        self.assertNotIn(
            "ret = self.partialFM[binID] + np.bincount(", text)


class InsertStateWidthContractTests(unittest.TestCase):
    """Construction insert-state scratch files use '<u8,<u1,<u8': the f2
    sequence-ID field was widened from <u4 (transient state only; the files
    are deleted by cleanupTemporaryFiles/clearAuxiliaryData within the same
    construction run, so there is no persisted contract to break)."""

    def test_source_pin_insert_state_dtype_widened(self):
        path = os.path.join(
            REPO_ROOT_W5, "packages", "msbwt-modern3", "MUS", "MSBWTGen.py")
        text = open(path, encoding="utf-8").read()
        self.assertNotIn("<u8,<u1,<u4", text)
        self.assertIn("'<u8,<u1,<u8'", text)
        cyx = open(os.path.join(
            REPO_ROOT_W5, "packages", "msbwt-modern3", "MUSCython",
            "MSBWTGenCython.pyx"), encoding="utf-8").read()
        live_uses = [l for l in cyx.splitlines()
                     if "<u8,<u1,<u4" in l and not l.strip().startswith("#")]
        self.assertEqual(live_uses, [])


class AboutNpyFileIdContractTests(unittest.TestCase):
    """about.npy persists uint8 file IDs (0xFF reserved as unpaired sentinel
    on BAM paths); >255 input files must raise, never silently wrap."""

    def test_preprocess_fastq_rejects_256_files(self):
        work = tempfile.mkdtemp(prefix="m3r64w5-fnid-")
        try:
            fastqs = []
            for i in range(256):
                p = os.path.join(work, "f%03d.fastq" % i)
                with open(p, "w") as fh:
                    fh.write("")
                fastqs.append(p)
            code = (
                "import sys" + "\n"
                "sys.path.insert(0, r'%s')" % PKG_ROOT_W5 + "\n"
                "import logging" + "\n"
                "from MUSCython import MultiStringBWTCython as MSB" + "\n"
                "try:" + "\n"
                "    MSB.preprocessFastqs(list(range(256)), r'%s', True, "
                "logging.getLogger('x'))" % work + "\n"
                "except ValueError as exc:" + "\n"
                "    assert 'about.npy' in str(exc), exc" + "\n"
                "    print('GUARD-OK')" + "\n"
                "else:" + "\n"
                "    print('NO-GUARD')" + "\n"
            )
            result = subprocess.run([sys.executable, "-c", code],
                                    capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0,
                             result.stderr.decode()[-600:])
            self.assertIn(b"GUARD-OK", result.stdout)
        finally:
            import shutil

            shutil.rmtree(work, ignore_errors=True)


REPO_ROOT_W5 = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG_ROOT_W5 = os.path.join(REPO_ROOT_W5, "packages", "msbwt-modern3")

if __name__ == "__main__":
    unittest.main()
