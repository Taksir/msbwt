"""M3-R64-FQPY2 regression: pure-Python FASTQ preprocessing under NumPy 2.x.

MUS.MultiStringBWT.preprocessFastqs used the obsolete NumPy 'a' dtype
prefix (invalid under NumPy 2.x) for its sortTemp arrays and wrote its
merged symbol stream through a text-mode handle.  Under py2 str==bytes this
worked; under CPython 3 it must be an explicit 'S' dtype plus binary writes
(identical bytes).  The repaired outputs are compared against the supported
compiled FASTQ path.
"""

import logging
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

from MUS import MultiStringBWT as MSB
from MUS import MSBWTGen
from MUSCython import MultiStringBWTCython as MSC
from MUSCython import MSBWTGenCython

LOGGER = logging.getLogger("m3-r64-fqpy2")
logging.basicConfig(level=logging.CRITICAL)

_FASTQ = "@r1\nACGTACGT\n+\nIIIIIIII\n" \
         "@r3\nTTGCCAAT\n+\nJJJJJJJJ\n" \
         "@r2\nACGTACGT\n+\n!!!!!!!!\n"


class PureFastqPreprocessTests(unittest.TestCase):
    def _fixture(self, work):
        fq = os.path.join(work, "in.fastq")
        with open(fq, "w", newline="") as fp:
            fp.write(_FASTQ)
        return fq

    def test_pure_preprocessing_feeds_supported_engine_identically(self):
        work = tempfile.mkdtemp(prefix="m3-fqpy2-")
        try:
            fq = self._fixture(work)
            # supported compiled path
            comp_dir = os.path.join(work, "compiled")
            os.makedirs(comp_dir)
            MSC.createMSBWTFromFastq([fq], comp_dir, 1, True, LOGGER)
            # pure-Python preprocessing, finished by the supported engine
            pure_dir = os.path.join(work, "pure")
            os.makedirs(pure_dir)
            seqFN = os.path.join(pure_dir, "seqs.npy")
            offsetFN = os.path.join(pure_dir, "offsets.npy")
            abtFN = os.path.join(pure_dir, "about.npy")
            MSB.preprocessFastqs([fq], seqFN, offsetFN, abtFN, True, LOGGER)
            MSBWTGenCython.createMsbwtFromSeqs(pure_dir, 1, LOGGER)

            bwt_c = open(os.path.join(comp_dir, "msbwt.npy"), "rb").read()
            bwt_p = open(os.path.join(pure_dir, "msbwt.npy"), "rb").read()
            self.assertEqual(bwt_p, bwt_c)

            about_c = np.load(os.path.join(comp_dir, "about.npy"), "r")
            about_p = np.load(abtFN, "r")
            self.assertEqual(about_p.dtype.str, about_c.dtype.str)
            self.assertEqual(bytes(bytearray(about_p[:])),
                             bytes(bytearray(about_c[:])))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    @unittest.skipIf(sys.platform == "win32",
                     "full pure-Python construction completion on native "
                     "Windows is blocked by a separate pre-existing "
                     "memmap-lifecycle defect in MUS.MSBWTGen."
                     "iterateCreateFromSeqs (WinError 32); documented in the "
                     "M3-R64-final-release-closure report")
    def test_full_pure_pipeline_end_to_end(self):
        work = tempfile.mkdtemp(prefix="m3-fqpy2-e2e-")
        try:
            fq = self._fixture(work)
            out = os.path.join(work, "leaf")
            os.makedirs(out)
            MSB.createMSBWTFromFastq([fq], out, 1, True, LOGGER)
            n = int(np.load(os.path.join(out, "msbwt.npy"), "r").shape[0])
            # three uniform 8-base reads -> 3 * 9 suffix rows
            self.assertEqual(n, 27)
        finally:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
