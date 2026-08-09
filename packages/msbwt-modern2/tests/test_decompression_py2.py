"""msbwt-modern2 decompression milestone 3 tests, runnable inside the pinned
Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO
(the validation driver sets it).  These tests execute the first intentional
correctness fix in modern2: successful post-hoc decompression of the uniform
RLE MSBWT back to the authoritative byte-BWT payload.

The historical frozen decompression fails deterministically with
``TypeError: slice indices must be integers or None or have an __index__
method`` at ``MUS/MultiStringBWT.py:662`` because the ``<u8`` run-count scalar
plus a Python ``int`` promotes to NumPy ``float64`` under CPython 2.7 / NumPy
1.16.6.  Modern2 fixes that index arithmetic with an explicit value-preserving
``int()`` conversion and establishes the decompression SUCCESS contract here.
The committed legacy expected-failure evidence is read-only and must remain
unchanged (test_legacy_decompression_failure_evidence_preserved).

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

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
FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")
BYTE_GOLDEN = os.path.join(
    GOLDENS, "uniform-multifile", PROFILE, ROUTE, "build", "artifacts")
FAILURE_EVIDENCE = os.path.join(
    GOLDENS, "compression-milestone1", "decompression-failure", "uniform")

# The decompressed primary is written by the pure-Python path through
# np.lib.format.open_memmap with a Python-int shape, so the NumPy v1 header
# serializes the shape literal as (48,) -- byte-identical to the committed
# legacy decompression preallocation header (the committed all-zero
# destination manifest), NOT the (48L,) literal of the compiled byte builder.
# The payload is byte-identical to the committed uniform byte-BWT golden
# payload.  These constants are the modern2 decompression SUCCESS contract.
DECOMPRESSED_WHOLE_SHA256 = "f536d60f356ed4a34e8253eecdd91e90db8c2ba3430c2e3d3e1855bb49007ef4"
GOLDEN_PAYLOAD_SHA256 = "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e"
GOLDEN_WHOLE_SHA256 = "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"
DECOMPRESSED_SHAPE_LITERAL = "(48,)"
DECOMPRESSED_SIZE = 176
DECOMPRESSED_PAYLOAD_SIZE = 48

DIRECT_SHA256 = "0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372"
POSTHOC_SHA256 = "53d82b388a9d565afa96ead611d5db964bee199869fd07f96b8c84258ba099a3"

# legacy byte-reader derived indexes on the uniform byte payload
BYTE_READER_SIDE_EFFECTS = {
    "totalCounts.npy": "ea104b616fe89d7b786acdff7ca0db61f6339a59c31fbf0fff066ad7384c1c2b",
    "fmIndex.npy": "a5b4bf06726fcadf535245d03ef65e04a4a5248d368b3aa53639c190028b933f",
}

EXPECTED_QUERIES = [
    ("A", 9), ("AA", 4), ("AAA", 3), ("AAAA", 2), ("AAAAA", 1), ("AAAAAA", 0),
    ("AC", 4), ("ACG", 4), ("ACGT", 4), ("ACGTN", 3),
    ("C", 9), ("CC", 4), ("CCC", 3), ("CCCC", 2), ("CCCCC", 1),
    ("CG", 4), ("CGT", 4), ("CGTN", 3),
    ("G", 9), ("GG", 4), ("GGG", 3), ("GGGG", 2), ("GGGGG", 1),
    ("GT", 4), ("GTN", 3),
    ("N", 4), ("NA", 1), ("NAC", 1), ("NACG", 1), ("NACGT", 1),
    ("T", 9), ("TN", 3), ("TT", 4), ("TTT", 3), ("TTTT", 2), ("TTTTT", 1),
]
EXPECTED_RECOVERED = ["$AAAAA", "$ACGTN", "$ACGTN", "$ACGTN", "$CCCCC",
                      "$GGGGG", "$NACGT", "$TTTTT"]


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


def golden_payload():
    return read_npy_framing(os.path.join(BYTE_GOLDEN, "msbwt.npy"))["payload"]


class DecompressionSliceTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="modern2-py2-dec-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        for fixture in ("uniform-a.fastq", "uniform-b.fastq"):
            shutil.copy(os.path.join(FIXTURES, fixture), self.work)

    def _cli(self, *argv):
        from MUS import CommandLineInterface
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt"] + list(argv)
            CommandLineInterface.mainRun()
        finally:
            sys.argv = old_argv

    def _build_direct(self, out):
        self._cli("pp", "-u", out,
                  os.path.join(self.work, "uniform-a.fastq"),
                  os.path.join(self.work, "uniform-b.fastq"))
        self._cli("cfpp", "-p", "1", "-u", "-c", out)
        return out

    def _build_posthoc(self, src, dst):
        os.makedirs(src)
        shutil.copy(os.path.join(BYTE_GOLDEN, "msbwt.npy"), src)
        self._cli("compress", "-p", "1", src, dst)
        return dst

    def _decompress(self, src, dst, procs=1):
        self._cli("decompress", "-p", str(procs), src, dst)
        return dst

    def _fresh_compressed_source(self, route, label):
        """A source directory containing ONLY the compressed primary."""
        src = os.path.join(self.work, "src-%s-%s" % (route, label))
        os.makedirs(src)
        if route == "direct":
            direct = self._build_direct(
                os.path.join(self.work, "direct-build-%s" % label))
            shutil.copy(os.path.join(direct, "comp_msbwt.npy"), src)
        else:
            posthoc = self._build_posthoc(
                os.path.join(self.work, "posthoc-src-%s" % label),
                os.path.join(self.work, "posthoc-%s" % label))
            shutil.copy(os.path.join(posthoc, "comp_msbwt.npy"), src)
        return src

    def _assert_decompressed_contract(self, dst, label):
        files = sorted(os.listdir(dst))
        self.assertEqual(files, ["msbwt.npy"], label)
        primary = os.path.join(dst, "msbwt.npy")
        framing = read_npy_framing(primary)
        self.assertEqual(framing["size"], DECOMPRESSED_SIZE, label)
        self.assertEqual(sha256_file(primary), DECOMPRESSED_WHOLE_SHA256, label)
        self.assertIn(b"'shape': (48,),", framing["header"], label)
        self.assertNotIn(b"(48L,)", framing["header"], label)
        committed = json.load(open(os.path.join(
            FAILURE_EVIDENCE, "destination-manifest.json")))
        self.assertEqual(framing["header"],
                         committed["artifacts"][0]["npy"]["header_text"].rstrip("\n"),
                         label)
        self.assertEqual(framing["payload_sha256"], GOLDEN_PAYLOAD_SHA256, label)
        self.assertEqual(framing["payload"], golden_payload(), label)
        return primary

    def test_decompress_direct_rle_matches_byte_golden_payload(self):
        src = self._fresh_compressed_source("direct", "a")
        dst = self._decompress(src, os.path.join(self.work, "dst-direct-a"))
        self._assert_decompressed_contract(dst, "direct")

    def test_decompress_posthoc_rle_matches_byte_golden_payload(self):
        src = self._fresh_compressed_source("posthoc", "a")
        dst = self._decompress(src, os.path.join(self.work, "dst-posthoc-a"))
        self._assert_decompressed_contract(dst, "posthoc")

    def test_direct_and_posthoc_decompressed_primaries_byte_identical(self):
        outputs = []
        for route in ("direct", "posthoc"):
            src = self._fresh_compressed_source(route, "cmp")
            dst = self._decompress(src, os.path.join(self.work, "dst-" + route))
            outputs.append(os.path.join(dst, "msbwt.npy"))
        self.assertEqual(sha256_file(outputs[0]), sha256_file(outputs[1]))

    def test_decompress_p1_equals_p2_byte_for_byte(self):
        for route in ("direct", "posthoc"):
            results = []
            for procs in (1, 2):
                src = self._fresh_compressed_source(route, "p%d" % procs)
                dst = self._decompress(
                    src, os.path.join(self.work, "dst-%s-p%d" % (route, procs)),
                    procs=procs)
                results.append(sha256_file(os.path.join(dst, "msbwt.npy")))
            self.assertEqual(results[0], results[1], route)

    def test_decompression_deterministic_across_repeated_runs(self):
        for route in ("direct", "posthoc"):
            trees = []
            for run in ("a", "b"):
                src = self._fresh_compressed_source(route, run)
                dst = self._decompress(
                    src, os.path.join(self.work, "dst-%s-%s" % (route, run)))
                trees.append(self._tree(route + "-" + run, src, dst))
            self.assertEqual(trees[0], trees[1], route)

    def _tree(self, label, src, dst):
        result = {}
        for directory, prefix in ((src, "src"), (dst, "dst")):
            for name in sorted(os.listdir(directory)):
                result["%s:%s" % (prefix, name)] = \
                    sha256_file(os.path.join(directory, name))
        return result

    def test_decompression_source_and_destination_side_effects(self):
        src = self._fresh_compressed_source("direct", "fx")
        compressed_sha = sha256_file(os.path.join(src, "comp_msbwt.npy"))
        dst = self._decompress(src, os.path.join(self.work, "dst-fx"))
        self.assertEqual(sorted(os.listdir(dst)), ["msbwt.npy"])
        # source gains exactly the three loadMsbwt support files; the primary
        # is untouched (matches the legacy decompression source-after set)
        self.assertEqual(sorted(os.listdir(src)),
                         ["comp_fmIndex.npy", "comp_msbwt.npy",
                          "comp_refIndex.npy", "totalCounts.p"])
        self.assertEqual(sha256_file(os.path.join(src, "comp_msbwt.npy")),
                         compressed_sha)

    def test_round_trip_byte_golden_compress_then_decompress(self):
        # byte golden -> modern2 compress -> RLE -> modern2 decompress -> byte
        src = os.path.join(self.work, "rt-src")
        rle = os.path.join(self.work, "rt-rle")
        os.makedirs(src)
        shutil.copy(os.path.join(BYTE_GOLDEN, "msbwt.npy"), src)
        self._cli("compress", "-p", "1", src, rle)
        self.assertEqual(sha256_file(os.path.join(rle, "comp_msbwt.npy")),
                         POSTHOC_SHA256)
        back = self._decompress(rle, os.path.join(self.work, "rt-back"))
        primary = os.path.join(back, "msbwt.npy")
        # final decompressed primary: payload equals the byte golden payload
        # byte-for-byte; whole file matches the decompression SUCCESS contract
        framing = read_npy_framing(primary)
        self.assertEqual(framing["payload"], golden_payload())
        self.assertEqual(framing["payload_sha256"], GOLDEN_PAYLOAD_SHA256)
        self.assertEqual(sha256_file(primary), DECOMPRESSED_WHOLE_SHA256)

    def test_reader_byte_bwt_on_decompressed_primary(self):
        for route in ("direct", "posthoc"):
            src = self._fresh_compressed_source(route, "rd")
            dst = self._decompress(src, os.path.join(self.work, "rd-" + route))
            copy = os.path.join(self.work, "reader-copy-" + route)
            shutil.copytree(dst, copy)
            from MUSCython import MultiStringBWTCython as CompiledBWT
            msbwt = CompiledBWT.loadBWT(copy, useMemmap=False, logger=None)
            self.assertEqual(
                type(msbwt).__module__ + "." + type(msbwt).__name__,
                "MUSCython.ByteBWTCython.ByteBWT", route)
            self.assertEqual(msbwt.getTotalSize(), 48, route)
            self.assertEqual(int(msbwt.getSymbolCount(0)), 8, route)
            for kmer, expected in EXPECTED_QUERIES:
                self.assertEqual(msbwt.countOccurrencesOfSeq(kmer), expected,
                                 (route, kmer))
            recovered = sorted(
                msbwt.recoverString(index) for index in range(8))
            self.assertEqual(recovered, EXPECTED_RECOVERED, route)
            present = {}
            for name in BYTE_READER_SIDE_EFFECTS:
                path = os.path.join(copy, name)
                self.assertTrue(os.path.exists(path), (route, name))
                present[name] = sha256_file(path)
            self.assertEqual(present, BYTE_READER_SIDE_EFFECTS, route)

    def test_getBWTRange_uint64_index_regression(self):
        """Focused regression: the exact bug site.

        Legacy (and pre-fix modern2) raised TypeError at
        ``MUS/MultiStringBWT.py:662`` because ``s + counts[lInd]`` promotes
        the ``<u8`` run-count scalar to NumPy float64, which has no
        ``__index__``.  This test drives the same arithmetic through the
        pure-Python ``CompressedMSBWT.getBWTRange``/``decompressBlocks`` on a
        disposable copy and requires the exact byte payload; it fails if the
        value-preserving int() conversion is ever removed.
        """
        src = self._fresh_compressed_source("direct", "reg")
        copy = os.path.join(self.work, "reg-copy")
        shutil.copytree(src, copy)
        from MUS.MultiStringBWT import CompressedMSBWT
        msbwt = CompressedMSBWT()
        msbwt.loadMsbwt(copy, logger=None)
        self.assertEqual(msbwt.getTotalSize(), 48)
        block_range = msbwt.decompressBlocks(0, 0)
        self.assertEqual(block_range.dtype, "<u1")
        self.assertEqual(block_range.shape[0], 48)
        full_range = msbwt.getBWTRange(0, 48)
        self.assertEqual(full_range.tostring(), golden_payload())
        self.assertEqual(block_range.tostring(), golden_payload())
        # a partial range must return the identical sub-slice
        self.assertEqual(msbwt.getBWTRange(10, 20).tostring(),
                         golden_payload()[10:20])

    def test_legacy_decompression_failure_evidence_preserved(self):
        """The historical failure is documented separately, not rewritten.

        The committed legacy evidence must keep its deterministic-failure
        contract (exit 1, TypeError at line 662, the three source side effects,
        and the all-zero preallocated destination) so the intentional modern2
        correction remains a documented deviation.
        """
        record = json.load(open(os.path.join(FAILURE_EVIDENCE, "record.json")))
        self.assertEqual(record["exit_code"], 1)
        self.assertEqual(record["exception"],
                         "TypeError: slice indices must be integers or None or have an __index__ method")
        self.assertEqual(record["source_side_effects"],
                         ["comp_fmIndex.npy", "comp_refIndex.npy", "totalCounts.p"])
        self.assertIn("MUS/MultiStringBWT.py\", line 662",
                      record["traceback_locations"])
        preallocated = record["preallocated_primary"]
        self.assertEqual(preallocated["dtype"], "|u1")
        self.assertEqual(preallocated["shape"], [48])
        self.assertEqual(preallocated["payload_size"], 48)
        self.assertEqual(preallocated["payload_sha256"],
                         "17b0761f87b081d5cf10757ccc89f12be355c70e2e29df288b65b30710dcbcd1")
        stderr = open(os.path.join(FAILURE_EVIDENCE, "stderr.txt")).read()
        self.assertIn("TypeError: slice indices must be integers or None or have an __index__ method", stderr)
        self.assertIn("MUS/MultiStringBWT.py\", line 662, in decompressBlocks", stderr)
        self.assertIn("ret[s:s+counts[lInd]] = letters[lInd]", stderr)


if __name__ == "__main__":
    import sys
    unittest.main()
