"""M3-R64-W6 regressions (audit findings A-1).

A-1: findKTOtherStranded's alternative-symbol FM-width scalars (maxAlt/altVal)
were declared ``unsigned long`` -- 32 bits on Win64 LLP64 -- although they receive
``highArray_view[altC] - lowArray_view[altC]`` from uint64 FM interval bounds and
can validly exceed 2^32-1.  They are now ``np.uint64_t``.

The compiled probe below executes the exact production statement sequence
(u64 view reads -> u64 subtraction -> u64 comparison -> max) so >2^32 widths are
verified without a >4-billion-row BWT fixture.  A source declaration pin
supplements (does not replace) the behavioral checks.
"""

import os
import unittest

import numpy as np

from MUSCython import BasicBWT

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WIDTHS = [
    2 ** 31 - 1,
    2 ** 31,
    2 ** 32 - 1,
    2 ** 32,
    2 ** 32 + 1,
    2 ** 32 + 12345,
]


class StrandedAltWidthTests(unittest.TestCase):
    def _probe(self, widths):
        """widths: dict symbol->interval width (low=0)."""
        low = np.zeros(dtype='<u8', shape=(6,))
        high = np.zeros(dtype='<u8', shape=(6,))
        for sym, w in widths.items():
            high[sym] = w
        return BasicBWT.stranded_max_alt_probe(low, high)

    def test_alt_width_boundaries_exact(self):
        # every boundary width must survive the u64 subtraction/comparison path
        for w in WIDTHS:
            got = int(self._probe({1: w}))
            self.assertEqual(got, w, w)

    def test_max_alt_picks_widest_interval_exactly(self):
        widths = {1: 2 ** 32 - 1, 2: 2 ** 32, 3: 2 ** 32 + 1,
                  4: 2 ** 32 + 12345, 5: 7}
        self.assertEqual(int(self._probe(widths)), 2 ** 32 + 12345)
        # a wrap mod 2^32 would turn 2^32+12345 into 12345 and pick 2^32-1
        # instead; assert the full value survives a '<u8' result-array store
        # exactly as production writes ret_view[x] = maxAlt.
        ret = np.zeros(dtype='<u8', shape=(1,))
        ret[0] = self._probe(widths)
        self.assertEqual(int(ret[0]), 2 ** 32 + 12345)


class SourceDeclarationPinTests(unittest.TestCase):
    """Supplementary pin: the repaired declarations exist and the old narrow
    ones are gone (behavioral coverage above is authoritative)."""

    def test_findktotherstranded_scalars_are_u64(self):
        path = os.path.join(REPO_ROOT, "packages", "msbwt-modern3",
                            "MUSCython", "BasicBWT.pyx")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("cdef np.uint64_t maxAlt, altVal", text)
        self.assertNotIn("unsigned long maxAlt", text)


if __name__ == "__main__":
    unittest.main()
