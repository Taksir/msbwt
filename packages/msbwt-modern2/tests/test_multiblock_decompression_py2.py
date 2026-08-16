"""msbwt-modern2 multi-block decompression milestone 4 tests, runnable inside
the pinned Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO
(the validation driver sets it).  These tests execute the second intentional
correctness fix in modern2: successful MULTI-BLOCK decompression of a
deterministic uniform RLE MSBWT whose logical decoded size (1,056,000 symbols)
exceeds the decompression work size (1,000,000), splitting decompression into
two work regions.

The compressed input is exactly the committed legacy m3c2 evidence dataset:
the committed uniform byte golden tiled 22000x (evidence primary whole-file
SHA-256 24447374bcdf...) compressed by modern2 `compress -p 1` to
comp_msbwt.npy (SHA-256 681caf56aa..., byte-identical to the committed m3c2
clean-compression primary).

The historical frozen implementation fails on this input in the first worker
tuple with `IndexError` at MUS/MultiStringBWT.py:630: the `<u8` refFM scalar
plus the Python int 1 promotes to NumPy float64 under CPython 2.7 / NumPy
1.16.6, and float64 cannot index the compressed BWT.  Modern2 fixes that
boundary arithmetic with an explicit value-preserving int() conversion
(`endRange = int(self.refFM[endBlock+1])+1`), the second documented
decompression index-boundary correction; the milestone-3 line-662 fill-loop
correction is unchanged and the single-block decompression contract remains
regression-protected by test_decompression_py2.py.

NOTE on reader semantics: the tiled evidence primary is a byte string, not a
valid collection BWT (tiling the BWT interleaves equal rotations instead of
grouping them, so the LF cycles do not decompose into the 8 fixture reads).
Reader query counts are therefore validated only as string-level FM counts
against an independent backward search in this test; collection-semantics
query/recovery expectations are not applicable.  The decompression correctness
contract is byte-level and is validated independently here (length, symbol
counts, payload hash, boundary neighborhoods, whole-file hash).

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import _npy_compat  # noqa: E402 (platform-consistent .npy writer)

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

GOLDENS = os.path.join(REPO, "compat", "goldens", "original-0.3.0")
PROFILE = "py27-late-05a7d6d83862"
ROUTE = "pyx-historical-cython"
BYTE_GOLDEN = os.path.join(
    GOLDENS, "uniform-multifile", PROFILE, ROUTE, "build", "artifacts", "msbwt.npy")
M3C2_RELATIONSHIP = os.path.join(GOLDENS, "compression-milestone3", "relationship-m3c2.json")
M3C2_MANIFEST = os.path.join(GOLDENS, "compression-milestone3", "partial", "m3c2-run-a.manifest.json")

# committed m3c2 evidence dataset and modern2 multi-block decompression SUCCESS
# contract constants
EVIDENCE_PRIMARY_SHA256 = "24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35"
RLE_PRIMARY_SHA256 = "681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99"
PAYLOAD_SHA256 = "7c27ccd61dec44ede4a02c883459eef78f5d909b8f30be327584c1a24391cc78"
TOTAL_SIZE = 1056000
WORK_SIZE = 1000000
REPEAT_COUNT = 22000
BOUNDARY = 1000000
EXPECTED_COUNTS = {"$": 176000, "A": 198000, "C": 198000,
                   "G": 198000, "N": 88000, "T": 198000}

# string-level FM counts on the tiled payload, independently verified in
# validate/decompression-milestone4.sh against bwt_oracle.backward_count
EXPECTED_FM_COUNTS = {
    "A": 198000, "AC": 37125, "ACGTN": 111, "AAAAA": 243, "AAAAAA": 45,
    "C": 198000, "CG": 37125, "GT": 37125, "GTGGGTTT": 2, "N": 88000,
    "NACGT": 108, "T": 198000, "TTTTT": 249,
}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_npy_framing(path):
    """Independent NPY v1 framing read (no NumPy, no pickle)."""
    with open(path, "rb") as handle:
        data = handle.read()
    assert data[:6] == b"\x93NUMPY", "not an NPY file"
    assert data[6:8] == b"\x01\x00", "not an NPY v1.0 file"
    header_len = ord(data[8]) + ord(data[9]) * 256
    header = data[10:10 + header_len]
    assert b"'descr': '|u1'" in header
    assert b"'fortran_order': False" in header
    payload = data[10 + header_len:]
    return {
        "size": len(data),
        "header": header.rstrip(b"\n"),
        "header_len": header_len,
        "payload": payload,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
    }


class MultiBlockDecompressionTests(unittest.TestCase):
    """Shared fixture: the committed m3c2 evidence dataset compressed once.

    The evidence primary is regenerated deterministically (np.tile of the
    committed uniform byte golden, 22000x) and hash-checked against the
    committed evidence primary, then compressed by modern2 and hash-checked
    against the committed m3c2 RLE primary.  Every decompression run uses a
    fresh source copy containing ONLY comp_msbwt.npy.
    """

    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.work = tempfile.mkdtemp(prefix="modern2-py2-mb-")
        cls.expected_payload = None
        evidence = np.load(BYTE_GOLDEN, "r")
        tiled = np.tile(evidence, REPEAT_COUNT)
        assert tiled.shape == (TOTAL_SIZE,), tiled.shape
        cls.expected_payload = tiled.tostring()
        evidence_root = os.path.join(cls.work, "evidence")
        os.makedirs(evidence_root)
        _npy_compat.save_npy(os.path.join(evidence_root, "msbwt.npy"), tiled)
        assert sha256_file(os.path.join(evidence_root, "msbwt.npy")) == EVIDENCE_PRIMARY_SHA256
        cls.rle = os.path.join(cls.work, "rle")
        os.makedirs(cls.rle)
        cls._cli("compress", "-p", "1", evidence_root, cls.rle)
        assert sha256_file(os.path.join(cls.rle, "comp_msbwt.npy")) == RLE_PRIMARY_SHA256

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    @classmethod
    def _cli(cls, *argv):
        from MUS import CommandLineInterface
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt"] + list(argv)
            CommandLineInterface.mainRun()
        finally:
            sys.argv = old_argv

    def _fresh_source(self, label):
        src = os.path.join(self.work, "src-" + label)
        shutil.copytree(self.rle, src)
        return src

    def _decompress(self, src, dst, procs=1):
        self._cli("decompress", "-p", str(procs), src, dst)
        return dst

    def _assert_decompressed_contract(self, dst, label):
        import numpy as np
        files = sorted(os.listdir(dst))
        self.assertEqual(files, ["msbwt.npy"], label)
        primary = os.path.join(dst, "msbwt.npy")
        framing = read_npy_framing(primary)
        # whole-file SHA-256 is byte-identical to the committed evidence primary
        self.assertEqual(sha256_file(primary), EVIDENCE_PRIMARY_SHA256, label)
        self.assertIn(b"'shape': (1056000,),", framing["header"], label)
        self.assertEqual(framing["payload_sha256"], PAYLOAD_SHA256, label)
        payload = framing["payload"]
        self.assertEqual(len(payload), TOTAL_SIZE, label)
        self.assertEqual(payload, self.expected_payload, label)
        counts = {"$": 0, "A": 0, "C": 0, "G": 0, "N": 0, "T": 0}
        for value in bytearray(payload):
            counts["$ACGNT"[value]] += 1
        self.assertEqual(counts, EXPECTED_COUNTS, label)
        return primary

    def _assert_boundaries(self, payload):
        for position in (BOUNDARY - 2, BOUNDARY - 1, BOUNDARY, BOUNDARY + 1,
                         BOUNDARY + 2, 0, 1, TOTAL_SIZE - 2, TOTAL_SIZE - 1):
            self.assertEqual(payload[position], self.expected_payload[position],
                             (position, payload[position], self.expected_payload[position]))

    def test_multiblock_decompression_success_p1(self):
        src = self._fresh_source("mb-a")
        dst = self._decompress(src, os.path.join(self.work, "dst-mb-a"))
        primary = self._assert_decompressed_contract(dst, "p1-run-a")
        self._assert_boundaries(read_npy_framing(primary)["payload"])

    def test_multiblock_decompression_deterministic_across_runs(self):
        trees = []
        for run in ("a", "b"):
            src = self._fresh_source("det-" + run)
            dst = self._decompress(src, os.path.join(self.work, "dst-det-" + run))
            self._assert_decompressed_contract(dst, "det-" + run)
            tree = {}
            for name in sorted(os.listdir(dst)):
                tree["dst:" + name] = sha256_file(os.path.join(dst, name))
            for name in sorted(os.listdir(src)):
                tree["src:" + name] = sha256_file(os.path.join(src, name))
            trees.append(tree)
        self.assertEqual(trees[0], trees[1])

    def test_multiblock_decompression_p1_equals_p2(self):
        results = []
        for procs in (1, 2):
            src = self._fresh_source("p%d" % procs)
            dst = self._decompress(src, os.path.join(self.work, "dst-p%d" % procs),
                                   procs=procs)
            self._assert_decompressed_contract(dst, "p%d" % procs)
            results.append(sha256_file(os.path.join(dst, "msbwt.npy")))
        self.assertEqual(results[0], results[1])

    def test_decompressed_logical_length_and_symbol_counts(self):
        src = self._fresh_source("len")
        dst = self._decompress(src, os.path.join(self.work, "dst-len"))
        framing = read_npy_framing(os.path.join(dst, "msbwt.npy"))
        self.assertEqual(len(framing["payload"]), 1056000)
        self.assertEqual(sum(EXPECTED_COUNTS.values()), 1056000)

    def test_payload_equals_tiled_golden_and_boundaries(self):
        src = self._fresh_source("bd")
        dst = self._decompress(src, os.path.join(self.work, "dst-bd"))
        payload = read_npy_framing(os.path.join(dst, "msbwt.npy"))["payload"]
        self.assertEqual(payload, self.expected_payload)
        self._assert_boundaries(payload)

    def test_decompression_source_side_effects(self):
        src = self._fresh_source("fx")
        compressed_sha = sha256_file(os.path.join(src, "comp_msbwt.npy"))
        dst = self._decompress(src, os.path.join(self.work, "dst-fx"))
        self.assertEqual(sorted(os.listdir(dst)), ["msbwt.npy"])
        self.assertEqual(sorted(os.listdir(src)),
                         ["comp_fmIndex.npy", "comp_msbwt.npy",
                          "comp_refIndex.npy", "totalCounts.p"])
        self.assertEqual(sha256_file(os.path.join(src, "comp_msbwt.npy")),
                         compressed_sha)

    def test_uint64_plus_int_promotion_root_cause(self):
        """Concrete runtime type evidence for the line-630 failure mechanism.

        Under CPython 2.7.18 / NumPy 1.16.6 the `<u8` refFM scalar plus the
        Python int 1 promotes to NumPy float64, which cannot index the
        compressed BWT (the committed m3c2 `IndexError` at line 630).  The
        int() conversion preserves the exact mathematical value and restores
        an index-legal type.
        """
        import numpy as np
        scalar = np.uint64(459008)
        promoted = scalar + 1
        self.assertIsInstance(promoted, np.float64)
        self.assertEqual(promoted, 459009.0)
        self.assertNotIn("__index__", dir(promoted))
        fixed = int(scalar) + 1
        self.assertIsInstance(fixed, int)
        self.assertEqual(fixed, 459009)
        # int() is exact for every uint64 value (including the long case);
        # note: uint64 + int promotes to float64 here, so 2**63+5 rounds to
        # 2**63 -- construct the scalar directly to prove the conversion
        big = np.uint64(9223372036854775813)
        self.assertEqual(int(big), 9223372036854775813L)
        # float64 integral setitem into a <u8 element is exact (the `dist`
        # skip-loop value in the tail region)
        counts = np.zeros(1, dtype="<u8")
        counts[0] = 5
        counts[0] -= np.float64(2.0)
        self.assertEqual(int(counts[0]), 3)

    def test_getBWTRange_line_630_fix_regression(self):
        """Focused regression: both work regions decode exactly.

        Without the `int(self.refFM[endBlock+1])+1` conversion, region 1
        ([0,1000000)) raises IndexError at MUS/MultiStringBWT.py:630 because
        `refFM[endBlock+1]+1` is np.float64.  This test drives the real
        pure-Python CompressedMSBWT path for BOTH regions on a disposable copy
        and requires the exact expected sub-payloads.
        """
        src = self._fresh_source("reg")
        from MUS.MultiStringBWT import CompressedMSBWT
        msbwt = CompressedMSBWT()
        msbwt.loadMsbwt(src, logger=None)
        self.assertEqual(msbwt.getTotalSize(), TOTAL_SIZE)
        self.assertEqual(str(msbwt.refFM.dtype), "uint64")
        for start, end in ((0, 1000000), (1000000, 1056000)):
            rng = msbwt.getBWTRange(start, end)
            self.assertEqual(rng.dtype, "<u1")
            self.assertEqual(rng.shape[0], end - start)
            self.assertEqual(rng.tostring(), self.expected_payload[start:end])

    def test_reader_byte_bwt_on_multiblock_primary(self):
        """Reader loads the >1M primary and FM queries match an independent
        backward search (string-level counts; collection semantics are not
        applicable to the tiled byte string)."""
        src = self._fresh_source("rd")
        dst = self._decompress(src, os.path.join(self.work, "rd-dst"))
        copy = os.path.join(self.work, "rd-copy")
        shutil.copytree(dst, copy)
        from MUSCython import MultiStringBWTCython as CompiledBWT
        msbwt = CompiledBWT.loadBWT(copy, useMemmap=False, logger=None)
        self.assertEqual(
            type(msbwt).__module__ + "." + type(msbwt).__name__,
            "MUSCython.ByteBWTCython.ByteBWT")
        self.assertEqual(msbwt.getTotalSize(), TOTAL_SIZE)
        self.assertEqual(int(msbwt.getSymbolCount(0)), 176000)
        payload = self.expected_payload
        expected = self._fm_counts(payload, EXPECTED_FM_COUNTS.keys())
        for kmer, count in sorted(expected.items()):
            self.assertEqual(int(msbwt.countOccurrencesOfSeq(kmer)), count,
                             kmer)
        for name in ("totalCounts.npy", "fmIndex.npy"):
            self.assertTrue(os.path.exists(os.path.join(copy, name)), name)

    def _fm_counts(self, payload, kmers):
        """Independent FM backward search (pure Python; no reader code).

        Python 2 bytes iteration yields 1-char strings, so the payload is
        converted to bytearray for integer element access.
        """
        symbols = "$ACGNT"
        positions = {}
        for index, symbol in enumerate(symbols):
            positions[symbol] = [pos for pos, value in enumerate(bytearray(payload))
                                 if value == index]
        c_table = {}
        running = 0
        for symbol in symbols:
            c_table[symbol] = running
            running += len(positions[symbol])

        def occ(char, index):
            return sum(1 for pos in positions[char] if pos < index)

        result = {}
        for kmer in kmers:
            lo, hi = 0, len(payload)
            for char in reversed(kmer):
                lo = c_table[char] + occ(char, lo)
                hi = c_table[char] + occ(char, hi)
                if lo >= hi:
                    break
            result[kmer] = hi - lo
        return result

    def test_legacy_m3c2_failure_evidence_preserved(self):
        """The committed multi-block failure evidence stays read-only.

        The historical frozen decompression of the same evidence input fails
        deterministically in the first worker tuple with IndexError at
        MUS/MultiStringBWT.py:630, exit 87, tuple count 2, source side effects
        exactly the three loadMsbwt support files, and an all-zero preallocated
        destination primary; the modern2 correction is a documented deviation.
        """
        record = json.load(open(M3C2_RELATIONSHIP))
        self.assertEqual(record["status"], "passed")
        worker = record["worker"]
        self.assertEqual(worker["exception_type"], "IndexError")
        self.assertEqual(
            worker["exception"],
            "only integers, slices (`:`), ellipsis (`...`), numpy.newaxis (`None`) and integer or boolean arrays are valid indices")
        self.assertIn("MUS/MultiStringBWT.py\", line 630",
                      worker["traceback_locations"])
        self.assertEqual(worker["exit_code"], 87)
        self.assertEqual(worker["mode"], "first-tuple-worker-failed-naturally")
        self.assertEqual(worker["first_tuple"],
                         ["SOURCE", "DESTINATION", 0, 1000000])
        self.assertEqual(record["unwritten_regions"], 2)
        self.assertEqual(record["completed_regions"], 0)
        self.assertEqual(record["clean_compression"]["shape"], [484000])
        self.assertEqual(record["clean_compression"]["primary_sha256"],
                         RLE_PRIMARY_SHA256)
        self.assertEqual(record["evidence_primary"]["shape"], [TOTAL_SIZE])
        self.assertEqual(record["evidence_primary"]["sha256"],
                         EVIDENCE_PRIMARY_SHA256)
        self.assertEqual(record["destination"]["shape"], [TOTAL_SIZE])
        self.assertEqual(record["destination"]["primary_sha256"],
                         "d77f2be75db0b24fac38eb10296701625652fc7c98d77ebf9cf59b53fcd0a691")
        manifest = json.load(open(M3C2_MANIFEST))
        self.assertEqual(manifest["content_sha256"],
                         "aa9815561102054a366db6992b7c5504dbe0b1c77a836c074e27eb92a290f33e")
        self.assertEqual(manifest["artifacts"][0]["npy"]["payload_size"],
                         TOTAL_SIZE)
        self.assertEqual(manifest["artifacts"][0]["npy"]["payload_sha256"],
                         "75855919076ba96440de78fc73f23378edaddb409dbef7dc865f43d5d60b2948")


if __name__ == "__main__":
    import unittest as _u
    _u.main()
