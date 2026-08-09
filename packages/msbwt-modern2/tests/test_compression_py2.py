"""msbwt-modern2 compression milestone 2 tests, runnable inside the pinned
Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO
(the validation driver sets it).  These tests execute the first RLE/compression
slice (direct split, direct wrapper, post-hoc compress) with the modern2
package and compare every persistent byte and decoded product against the
committed legacy route-specific goldens.

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

DIRECT_SHA256 = "0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372"
POSTHOC_SHA256 = "53d82b388a9d565afa96ead611d5db964bee199869fd07f96b8c84258ba099a3"
PAYLOAD_SHA256 = "6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb"
DECODED_SHA256 = "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e"
DECODED_BWT = "ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$"
DIRECT_FILES = ["about.npy", "comp_msbwt.npy", "offsets.npy",
                "seqs.npy.0.npy", "seqs.npy.1.npy", "seqs.npy.2.npy",
                "seqs.npy.3.npy", "seqs.npy.4.npy", "seqs.npy.5.npy"]
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
RLE_SIDE_EFFECTS = {
    "comp_fmIndex.npy": "f6565545114d769fbe6ba6010ce125c8690256f2d97562ceb65064b38d48c881",
    "comp_refIndex.npy": "30c0c0f336e69b86ee3da30f0f4ce1d9a138d503845c586e993ff31e8003fee1",
    "totalCounts.npy": "ea104b616fe89d7b786acdff7ca0db61f6339a59c31fbf0fff066ad7384c1c2b",
}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_decode_rle_npy(path):
    """Independent host-side NPY v1 + RLE decoder (no NumPy, no pickle)."""
    with open(path, "rb") as handle:
        data = handle.read()
    assert data[:6] == b"\x93NUMPY", "not an NPY file"
    header_len = ord(data[8]) + ord(data[9]) * 256
    header = data[10:10 + header_len]
    assert b"'descr': '|u1'" in header
    assert b"'fortran_order': False" in header
    payload = data[10 + header_len:]
    symbol_order = "$ACGNT"
    runs = []
    decoded = bytearray()
    index = 0
    while index < len(payload):
        symbol_index = ord(payload[index]) & 0x07
        assert symbol_index < len(symbol_order), "unknown symbol index"
        count = 0
        offset = 0
        while (index + offset) < len(payload) and (
                ord(payload[index + offset]) & 0x07) == symbol_index:
            digit = (ord(payload[index + offset]) >> 3) & 0x1F
            count += digit * (32 ** offset)
            offset += 1
        assert count > 0, "non-positive run length"
        runs.append([symbol_order[symbol_index], count])
        decoded += bytearray([symbol_index]) * count
        index += offset
    return {
        "header": header.rstrip("\n"),
        "runs": runs,
        "run_count": len(runs),
        "decoded_length": len(decoded),
        "decoded_sha256": hashlib.sha256(bytes(decoded)).hexdigest(),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
    }


class CompressionSliceTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="modern2-py2-comp-")
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

    def test_direct_split_matches_committed_golden(self):
        out = self._build_direct(os.path.join(self.work, "out"))
        self.assertEqual(sorted(os.listdir(out)), DIRECT_FILES)
        primary = os.path.join(out, "comp_msbwt.npy")
        self.assertEqual(sha256_file(primary), DIRECT_SHA256)
        decoded = safe_decode_rle_npy(primary)
        self.assertIn("'shape': (22L,)", decoded["header"])
        self.assertEqual(decoded["payload_sha256"], PAYLOAD_SHA256)
        self.assertEqual(decoded["run_count"], 22)
        self.assertEqual(decoded["decoded_length"], 48)
        self.assertEqual(decoded["decoded_sha256"], DECODED_SHA256)
        self.assertEqual(self._golden_decoded("uniform-direct-split"), decoded)

    def test_posthoc_matches_committed_golden(self):
        src = os.path.join(self.work, "src")
        dst = os.path.join(self.work, "dst")
        os.makedirs(src)
        shutil.copy(os.path.join(BYTE_GOLDEN, "msbwt.npy"), src)
        self._cli("compress", "-p", "1", src, dst)
        self.assertEqual(sorted(os.listdir(dst)), ["comp_msbwt.npy"])
        primary = os.path.join(dst, "comp_msbwt.npy")
        self.assertEqual(sha256_file(primary), POSTHOC_SHA256)
        decoded = safe_decode_rle_npy(primary)
        self.assertIn("'shape': (22,)", decoded["header"])
        self.assertEqual(decoded["payload_sha256"], PAYLOAD_SHA256)
        self.assertEqual(decoded["run_count"], 22)
        self.assertEqual(decoded["decoded_length"], 48)
        self.assertEqual(decoded["decoded_sha256"], DECODED_SHA256)
        self.assertEqual(self._golden_decoded("uniform-compress-posthoc"), decoded)

    def test_direct_wrapper_matches_committed_golden(self):
        out = os.path.join(self.work, "out")
        self._cli("cffq", "-p", "1", "-u", "-c", out,
                  os.path.join(self.work, "uniform-a.fastq"),
                  os.path.join(self.work, "uniform-b.fastq"))
        self.assertEqual(sorted(os.listdir(out)),
                         ["about.npy", "comp_msbwt.npy"])
        primary = os.path.join(out, "comp_msbwt.npy")
        self.assertEqual(sha256_file(primary), DIRECT_SHA256)
        decoded = safe_decode_rle_npy(primary)
        self.assertIn("'shape': (22L,)", decoded["header"])
        self.assertEqual(decoded["payload_sha256"], PAYLOAD_SHA256)
        self.assertEqual(self._golden_decoded("uniform-direct-wrapper"), decoded)

    def test_direct_and_posthoc_headers_differ_only_in_shape_literal(self):
        direct = self._build_direct(os.path.join(self.work, "direct"))
        posthoc_src = os.path.join(self.work, "posthoc-src")
        posthoc_dst = os.path.join(self.work, "posthoc-dst")
        os.makedirs(posthoc_src)
        shutil.copy(os.path.join(BYTE_GOLDEN, "msbwt.npy"), posthoc_src)
        self._cli("compress", "-p", "1", posthoc_src, posthoc_dst)
        d = safe_decode_rle_npy(os.path.join(direct, "comp_msbwt.npy"))
        p = safe_decode_rle_npy(os.path.join(posthoc_dst, "comp_msbwt.npy"))
        self.assertEqual(d["payload_sha256"], p["payload_sha256"])
        self.assertEqual(d["runs"], p["runs"])
        self.assertEqual(d["decoded_sha256"], p["decoded_sha256"])
        self.assertEqual(len(d["header"]), len(p["header"]))
        self.assertEqual(
            d["header"].rstrip(" ").replace("(22L,)", "(22,)"),
            p["header"].rstrip(" "))

    def test_p1_equals_p2_byte_for_byte(self):
        out1 = self._build_direct(os.path.join(self.work, "out1"))
        out2 = os.path.join(self.work, "out2")
        self._cli("pp", "-u", out2,
                  os.path.join(self.work, "uniform-a.fastq"),
                  os.path.join(self.work, "uniform-b.fastq"))
        self._cli("cfpp", "-p", "2", "-u", "-c", out2)
        self.assertEqual(
            sorted(os.listdir(out1)), sorted(os.listdir(out2)))
        for name in sorted(os.listdir(out1)):
            self.assertEqual(
                sha256_file(os.path.join(out1, name)),
                sha256_file(os.path.join(out2, name)), name)

        src = os.path.join(self.work, "src")
        dst1 = os.path.join(self.work, "dst1")
        dst2 = os.path.join(self.work, "dst2")
        os.makedirs(src)
        shutil.copy(os.path.join(BYTE_GOLDEN, "msbwt.npy"), src)
        self._cli("compress", "-p", "1", src, dst1)
        self._cli("compress", "-p", "2", src, dst2)
        self.assertEqual(
            sha256_file(os.path.join(dst1, "comp_msbwt.npy")),
            sha256_file(os.path.join(dst2, "comp_msbwt.npy")))

    def test_reader_rle_behavior_on_disposable_copies(self):
        for label, build in (
                ("direct", lambda d: self._build_direct(d)),
                ("posthoc", None)):
            if label == "direct":
                out = build(os.path.join(self.work, "direct-" + label))
            else:
                src = os.path.join(self.work, "src-" + label)
                dst = os.path.join(self.work, "dst-" + label)
                os.makedirs(src)
                shutil.copy(os.path.join(BYTE_GOLDEN, "msbwt.npy"), src)
                self._cli("compress", "-p", "1", src, dst)
                out = dst
            copy = os.path.join(self.work, "reader-" + label)
            shutil.copytree(out, copy)
            from MUSCython import MultiStringBWTCython as CompiledBWT
            msbwt = CompiledBWT.loadBWT(copy, useMemmap=False, logger=None)
            self.assertEqual(
                type(msbwt).__module__ + "." + type(msbwt).__name__,
                "MUSCython.RLE_BWTCython.RLE_BWT", label)
            self.assertEqual(msbwt.getTotalSize(), 48, label)
            self.assertEqual(int(msbwt.getSymbolCount(0)), 8, label)
            for kmer, expected in EXPECTED_QUERIES:
                self.assertEqual(msbwt.countOccurrencesOfSeq(kmer), expected,
                                 (label, kmer))
            recovered = sorted(
                msbwt.recoverString(index) for index in range(8))
            self.assertEqual(recovered, EXPECTED_RECOVERED, label)
            present = {}
            for name in RLE_SIDE_EFFECTS:
                path = os.path.join(copy, name)
                self.assertTrue(os.path.exists(path), (label, name))
                present[name] = sha256_file(path)
            self.assertEqual(present, RLE_SIDE_EFFECTS, label)

    def _golden_decoded(self, case):
        path = os.path.join(GOLDENS, case, PROFILE, ROUTE, "decoded-rle.json")
        with open(path, "rb") as handle:
            committed = json.load(handle)
        return {
            "header": committed["header_text"],
            "runs": [[run["symbol"], run["count"]] for run in committed["runs"]],
            "run_count": committed["run_count"],
            "decoded_length": committed["decoded_length"],
            "decoded_sha256": committed["decoded_sha256"],
            "payload_sha256": committed["payload_sha256"],
        }


if __name__ == "__main__":
    unittest.main()
