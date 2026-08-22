"""M3-R64-W2 regression: core compiled row/index ABI width (R64-0/R64-1).

Pre-repair, the central ``BasicBWT`` ABI represented BWT lengths, FM interval
bounds and occurrence counts as ``unsigned long`` -- 32 bits under Win64
LLP64 -- so any value >= 2^32 silently wrapped.  These tests pin the repaired
contract defined by ``docs/modernization/NUMERIC_WIDTH_POLICY.md``:

* compiled probes carry synthetic >2^32 (and signed-boundary 2^31) values
  through real Cython scalar and ``bwtRange``-struct boundaries exactly;
* the platform data model is documented (sizeof(unsigned long) == 4 on
  win_amd64 -- the reason ``long`` was dangerous);
* the authoritative ``BasicBWT.pxd`` declares the widened types;
* real reader/query semantics are unchanged on ordinary inputs.
"""

import os
import shutil
import tempfile
import unittest

import numpy as np

from MUSCython import MultiStringBWTCython as MSB
from MUSCython import BasicBWT
from MUSCython import ByteBWTCython

loadBWT = MSB.loadBWT

BOUNDARY_VALUES = [
    2 ** 31 - 1,
    2 ** 31,
    2 ** 32 - 1,
    2 ** 32,
    2 ** 32 + 1,
    2 ** 32 + 12345,
]

READS = ["ACGTAC", "GGATC", "TTGCA"]


def _pxd_source():
    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(
        repo_root, "packages", "msbwt-modern3", "MUSCython", "BasicBWT.pxd"
    )
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class CoreAbiWidthTests(unittest.TestCase):
    def test_platform_data_model_documented(self):
        # LLP64 fact: this constant explains WHY unsigned long was unsafe.
        # It must be present and consistent across rebuilt core modules.
        self.assertEqual(int(BasicBWT.SIZEOF_UNSIGNED_LONG), 4)
        self.assertEqual(int(ByteBWTCython.SIZEOF_UNSIGNED_LONG), 4)

    def test_u64_scalar_roundtrip_boundaries(self):
        for value in BOUNDARY_VALUES:
            expected = (value * 3 + 7) % 2 ** 64
            self.assertEqual(
                int(BasicBWT.u64_roundtrip(value)), expected, value
            )

    def test_bwt_range_struct_roundtrip_boundaries(self):
        pairs = [
            (0, 1),
            (2 ** 31 - 1, 2 ** 31),
            (2 ** 32 - 1, 2 ** 32),
            (2 ** 32 + 1, 2 ** 32 + 12345),
        ]
        for lo, hi in pairs:
            self.assertEqual(
                tuple(BasicBWT.bwt_range_roundtrip(lo, hi)), (lo, hi),
                (lo, hi),
            )

    def test_pxd_declares_widened_core_abi(self):
        source = _pxd_source()
        self.assertIn("cdef struct bwtRange:", source)
        struct_block = source.split("cdef struct bwtRange:", 1)[1]
        struct_block = struct_block.split("};", 1)[0] if "};" in struct_block \
            else struct_block.split("cdef class", 1)[0]
        self.assertIn("np.uint64_t l", struct_block)
        self.assertIn("np.uint64_t h", struct_block)
        for member in ("totalSize", "fileSize", "iterIndex"):
            self.assertIn(
                "cdef np.uint64_t %s" % member, source, member)
        self.assertNotIn(
            "unsigned long totalSize", source)
        # W1 contract must remain untouched.
        self.assertIn("np.uint32_t [:] lcps_view", source)


class CoreAbiSemanticPreservationTests(unittest.TestCase):
    """The widened ABI must behave identically on ordinary (<2^32) inputs."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="m3r64w2-coreabi-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_real_package_queries_unchanged(self):
        import test_multisource_query as f3

        directory = f3.make_read_derived_leaf(
            self.work, "pkg", list(READS))
        bwt = loadBWT(directory, False, None)

        n_rows = sum(len(r) + 1 for r in READS)
        self.assertEqual(int(bwt.getTotalSize()), n_rows)

        low, high = bwt.findIndicesOfStr("ACG")
        self.assertLessEqual(low, high)
        count = bwt.countOccurrencesOfSeq("ACG")
        self.assertEqual(count, high - low)

        recovered = sorted(
            bwt.recoverString(d).decode("ascii").replace("$", "")
            for d in range(len(READS))
        )
        self.assertEqual(recovered, sorted(READS))
        # NOTE: LCP-assisted queries (countSeqMatches etc.) are deliberately
        # NOT exercised here: this leaf has no lcps.npy layer, and the
        # loosening loops access lcps_view without a lcpsPresent guard —
        # a pre-existing latent hazard recorded for the W3 reader unit.

    def test_given_range_conversion_exact_at_boundary(self):
        import test_multisource_query as f3

        directory = f3.make_read_derived_leaf(self.work, "pkg", list(READS))
        bwt = loadBWT(directory, False, None)
        n_rows = sum(len(r) + 1 for r in READS)

        # Whole-index interval expressed explicitly; exercises the
        # Python-int -> repaired-scalar conversion of givenRange against
        # the implicit whole-range default.
        low_full, high_full = bwt.findIndicesOfStr("GG")
        low_explicit, high_explicit = bwt.findIndicesOfStr("GG", (0, n_rows))
        self.assertEqual((low_explicit, high_explicit), (low_full, high_full))
        self.assertEqual(
            int(bwt.countOccurrencesOfSeq("GG", (0, n_rows))),
            int(bwt.countOccurrencesOfSeq("GG")),
        )
        self.assertEqual(
            int(bwt.countOccurrencesOfSeq("GG")), high_full - low_full
        )


if __name__ == "__main__":
    unittest.main()
