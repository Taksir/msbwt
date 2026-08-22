"""M3-R64-W1 regression: compiled F11A LCP dtype binding.

Pre-repair defect (M3-R64A audit / M3-12): F11A persists ``lcps.npy`` as
``<u4`` while ``BasicBWT.pxd`` bound it through
``cdef np.uint8_t [:] lcps_view``.  Every compiled loader therefore raised

    ValueError: Buffer dtype mismatch, expected 'uint8_t' but got 'uint32'

for any package directory containing an LCP layer -- Byte, RLE and LZW alike,
in every M2/M3 direction.  These tests pin the repaired binding:

* ``<u4`` lcps.npy loads in all three compiled reader families;
* the persisted primary dtype stays ``<u4``;
* a non-contract dtype is rejected explicitly (never truncated/reinterpreted);
* LCP-assisted queries execute consistently across the three loaders.
"""

import logging
import os
import shutil
import tempfile
import unittest

import numpy as np

from MUS.LCP import construct_lcp_from_bwt
from MUS.MSBWTGen import compressBWT
from MUSCython import MultiStringBWTCython as MSB

loadBWT = MSB.loadBWT

LOGGER = logging.getLogger("m3_r64_w1_lcp_binding")

SEQS = ["ACGTAC$", "ACGTTC$", "ACGTAAA$", "TGATCA$", "GGGGGGG$"]
KMER = "ACGT"

# Rotation-distinct reads: the naive leaf builder breaks ties arbitrarily,
# which corrupts raw dollar-ID walks for rotation-degenerate inputs
# (harness constraint, not a production defect).
READS = ["ACGTAC", "GGATC", "TTGCA"]


def _build_byte_package(work, name):
    """Leaf package with provenance manifest (required by
    construct_lcp_from_bwt's identity hash), via the established builder."""
    import test_multisource_query as f3

    return f3.make_read_derived_leaf(work, name, list(READS))


def _expected_total_size():
    return sum(len(r) + 1 for r in READS)


def _copy_lcp_layer(source_dir, dest_dir):
    for fn in ("lcps.npy", "lcp.json"):
        shutil.copy(
            os.path.join(source_dir, fn),
            os.path.join(dest_dir, fn),
        )


class LcpBindingTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="m3r64w1-lcp-")

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_persisted_dtype_is_u4(self):
        directory = _build_byte_package(self.work, "byte")
        construct_lcp_from_bwt(directory, bwt=loadBWT(directory, False, LOGGER))
        raw = np.load(os.path.join(directory, "lcps.npy"))
        self.assertEqual(raw.dtype, np.dtype("<u4"))
        self.assertEqual(raw.shape[0], (sum(len(r) + 1 for r in READS)) - 1)
        index_meta = os.path.exists(os.path.join(directory, "lcp.json"))
        self.assertTrue(index_meta)

    def test_u4_loads_through_compiled_byte_loader(self):
        directory = _build_byte_package(self.work, "byte")
        construct_lcp_from_bwt(directory, bwt=loadBWT(directory, False, LOGGER))
        bwt = loadBWT(directory, False, LOGGER)
        self.assertEqual(int(bwt.getTotalSize()), (sum(len(r) + 1 for r in READS)))
        result = bwt.countSeqMatches(KMER, 2)
        self.assertIsInstance(result, tuple)

    def test_u4_loads_through_compiled_rle_loader(self):
        byte_dir = _build_byte_package(self.work, "byte")
        construct_lcp_from_bwt(byte_dir, bwt=loadBWT(byte_dir, False, LOGGER))
        rle_dir = os.path.join(self.work, "rle")
        os.makedirs(rle_dir)
        compressBWT(
            os.path.join(byte_dir, "msbwt.npy"),
            os.path.join(rle_dir, "comp_msbwt.npy"),
            1,
            LOGGER,
        )
        _copy_lcp_layer(byte_dir, rle_dir)
        rle = MSB.RLE_BWT()
        rle.loadMsbwt(rle_dir, False, LOGGER)
        self.assertEqual(int(rle.getTotalSize()), (sum(len(r) + 1 for r in READS)))
        result = rle.countSeqMatches(KMER, 2)
        self.assertIsInstance(result, tuple)

    def test_u4_loads_through_compiled_lzw_loader(self):
        byte_dir = _build_byte_package(self.work, "byte")
        construct_lcp_from_bwt(byte_dir, bwt=loadBWT(byte_dir, False, LOGGER))
        rle_dir = os.path.join(self.work, "rle")
        os.makedirs(rle_dir)
        compressBWT(
            os.path.join(byte_dir, "msbwt.npy"),
            os.path.join(rle_dir, "comp_msbwt.npy"),
            1,
            LOGGER,
        )

        # Synthesize a minimal single-bin LZW container from the same RLE
        # stream.  Format per LZW_BWTCython.loadMsbwt:
        #   byte 0      : bitPower
        #   bytes 1..8  : uncompressed length, big-endian u64
        #   bytes 9..   : base-32 run stream (identical encoding to RLE)
        # comp_offsets.npy holds absolute per-bin byte offsets into the file.
        stream = np.load(os.path.join(rle_dir, "comp_msbwt.npy"))
        total_size = (sum(len(r) + 1 for r in READS))
        payload = bytes([11]) + total_size.to_bytes(8, "big") + stream.tobytes()

        lzw_dir = os.path.join(self.work, "lzw")
        os.makedirs(lzw_dir)
        with open(os.path.join(lzw_dir, "comp_msbwt.dat"), "wb") as handle:
            handle.write(payload)
        offsets = np.array([9, len(payload)], dtype="<u8")
        np.save(os.path.join(lzw_dir, "comp_offsets.npy"), offsets)
        _copy_lcp_layer(byte_dir, lzw_dir)

        lzw = MSB.LZW_BWT()
        lzw.loadMsbwt(lzw_dir, False, LOGGER)
        self.assertEqual(int(lzw.getTotalSize()), total_size)
        result = lzw.countSeqMatches(KMER, 2)
        self.assertIsInstance(result, tuple)

    def test_lcp_assisted_queries_consistent_across_loaders(self):
        byte_dir = _build_byte_package(self.work, "byte")
        construct_lcp_from_bwt(byte_dir, bwt=loadBWT(byte_dir, False, LOGGER))

        rle_dir = os.path.join(self.work, "rle")
        os.makedirs(rle_dir)
        compressBWT(
            os.path.join(byte_dir, "msbwt.npy"),
            os.path.join(rle_dir, "comp_msbwt.npy"),
            1,
            LOGGER,
        )
        _copy_lcp_layer(byte_dir, rle_dir)
        rle = MSB.RLE_BWT()
        rle.loadMsbwt(rle_dir, False, LOGGER)

        byte_bwt = MSB.ByteBWT(); byte_bwt.loadMsbwt(byte_dir, False, LOGGER)
        seq_matches_byte = byte_bwt.countSeqMatches(KMER, 2)
        seq_matches_rle = rle.countSeqMatches(KMER, 2)
        self.assertEqual(
            int(np.asarray(seq_matches_byte).sum()),
            int(np.asarray(seq_matches_rle).sum()),
        )
        stranded_byte = byte_bwt.countStrandedSeqMatches(KMER, 2)
        stranded_rle = rle.countStrandedSeqMatches(KMER, 2)
        self.assertEqual(
            tuple(int(np.asarray(x).sum()) for x in stranded_byte),
            tuple(int(np.asarray(x).sum()) for x in stranded_rle),
        )
        self.assertEqual(
            int(byte_bwt.countOccurrencesOfSeq(KMER)),
            int(rle.countOccurrencesOfSeq(KMER)),
        )

    def test_noncontract_dtype_rejected_explicitly_never_reinterpreted(self):
        directory = _build_byte_package(self.work, "byte")
        n = (sum(len(r) + 1 for r in READS))
        wide = (np.arange(n - 1, dtype="<u8") % 7).astype("<u8")
        np.save(os.path.join(directory, "lcps.npy"), wide)
        with self.assertRaises(ValueError) as caught:
            loadBWT(directory, False, LOGGER)
        message = str(caught.exception)
        self.assertIn("<u4", message)
        self.assertIn("uint64", message)


if __name__ == "__main__":
    unittest.main()
