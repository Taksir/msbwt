"""M3-13C regression: BAM/pysam is explicitly unsupported in modern3.

The legacy pysam-based BAM ingestion entry points must reject deterministically
with a controlled NotImplementedError on every platform, regardless of whether
pysam happens to be installed, and must not touch the filesystem.  Ordinary
FASTQ workflows are unaffected.
"""

import logging
import os
import tempfile
import unittest

import numpy as np

from MUS import MultiStringBWT as MSB
from MUSCython import MultiStringBWTCython as MSC

LOGGER = logging.getLogger("m3-13c")
logging.basicConfig(level=logging.CRITICAL)

_EXPECTED = "BAM input is explicitly unsupported"


class BamExplicitlyUnsupportedTests(unittest.TestCase):
    def _assert_rejected(self, fn):
        try:
            fn()
        except NotImplementedError as exc:
            self.assertIn(_EXPECTED, str(exc))
        else:
            self.fail("BAM entry point did not reject explicitly")

    def test_pure_python_entry_points_reject(self):
        work = tempfile.mkdtemp(prefix="m3-13c-py-")
        self._assert_rejected(lambda: MSB.createMSBWTFromBam(
            ["x.bam"], os.path.join(work, "o"), 1, True, LOGGER))
        self._assert_rejected(lambda: MSB.preprocessBams(
            ["x.bam"], os.path.join(work, "s"), os.path.join(work, "f"),
            os.path.join(work, "a"), True, LOGGER))
        # no partial filesystem state may appear
        self.assertEqual(os.listdir(work), [])

    def test_compiled_entry_points_reject(self):
        work = tempfile.mkdtemp(prefix="m3-13c-cy-")
        self._assert_rejected(lambda: MSC.createMSBWTFromBam(
            ["x.bam"], os.path.join(work, "o"), 1, True, LOGGER))
        self._assert_rejected(lambda: MSC.preprocessBams(
            ["x.bam"], os.path.join(work, "o2"), True, LOGGER))
        self.assertEqual(os.listdir(work), [])

    def test_pysam_absence_is_orthogonal(self):
        # The rejection must not depend on pysam being installed or absent:
        # it fires before any pysam import or file access.
        try:
            import pysam  # noqa: F401
            installed = True
        except ImportError:
            installed = False
        work = tempfile.mkdtemp(prefix="m3-13c-orth-")
        self._assert_rejected(lambda: MSC.createMSBWTFromBam(
            ["x.bam"], os.path.join(work, "o"), 1, True, LOGGER))
        # record for diagnostics; the assertion above is the real contract
        self.assertIn(installed, (True, False))

    def test_fastq_workflow_unaffected(self):
        import MUSCython.MultiStringBWTCython as MSC

        work = tempfile.mkdtemp(prefix="m3-13c-fq-")
        fq = os.path.join(work, "in.fastq")
        with open(fq, "w") as fp:
            fp.write("@r1\nACGTACGT\n+\nIIIIIIII\n"
                     "@r2\nTTGCCAAT\n+\nJJJJJJJJ\n")
        out = os.path.join(work, "leaf")
        os.makedirs(out)
        MSC.createMSBWTFromFastq([fq], out, 1, True, LOGGER)
        n = int(np.load(os.path.join(out, "msbwt.npy"), "r").shape[0])
        self.assertEqual(n, 18)


if __name__ == "__main__":
    unittest.main()
