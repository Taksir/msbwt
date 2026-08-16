"""msbwt-modern2 bootstrap milestone 1 tests, runnable inside the pinned
Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO
(the validation driver sets it).  These tests execute the real uniform-multifile
slice and compare every artifact byte-for-byte with the committed legacy golden
manifest.

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import hashlib
import json
import os
import platform
import shutil
import StringIO
import sys
import tempfile
import unittest

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

GOLDEN = os.path.join(
    REPO, "compat", "goldens", "original-0.3.0", "uniform-multifile",
    "py27-late-05a7d6d83862", "pyx-historical-cython")
FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")
MSBWT_SHA256 = "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"
EXPECTED_QUERIES = [("AAAAA", 1), ("ACGTN", 3), ("CCCCC", 1), ("AGCTA", 0)]


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class BootstrapEnvironmentTests(unittest.TestCase):
    def test_python_is_cpython_27(self):
        self.assertEqual(sys.version_info[:2], (2, 7))
        self.assertIn("CPython", platform.python_implementation())
        if not sys.platform.startswith("win"):
            # the verified Linux reference is the UCS4 (wide) CPython 2.7
            # build; every native Windows CPython 2.7 distribution is a
            # narrow (UCS2) build, which is the documented Windows
            # environment difference (see COMPATIBILITY.md).
            self.assertTrue(sys.maxunicode > 65535)

    def test_cython_is_exactly_3_0_x(self):
        import Cython
        self.assertTrue(Cython.__version__.startswith("3.0."), Cython.__version__)

    def test_numpy_and_pysam_are_pinned(self):
        import numpy
        self.assertEqual(numpy.__version__, "1.16.6")
        if not sys.platform.startswith("win"):
            import pysam
            self.assertEqual(pysam.__version__, "0.15.4")
        else:
            # pysam has no CPython-2.7 Windows distribution; it is not
            # an install requirement on Windows.  BAM preprocessing is
            # intentionally unavailable.
            try:
                import pysam  # noqa: F401
            except ImportError:
                pass  # expected on Windows
            else:
                self.fail("pysam should not be installed on Windows")


class ImportSurfaceTests(unittest.TestCase):
    def test_import_mus(self):
        import MUS
        import MUS.util
        import MUS.CommandLineInterface
        import MUS.MultiStringBWT
        import MUS.MSBWTGen
        import MUS.TranscriptBuilder
        self.assertEqual(MUS.util.VERSION, "0.3.0")

    def test_import_muscython_compiled(self):
        import MUSCython.AlignmentUtil
        import MUSCython.BasicBWT
        import MUSCython.ByteBWTCython
        import MUSCython.LZW_BWTCython
        import MUSCython.MSBWTCompGenCython
        import MUSCython.MSBWTGenCython
        import MUSCython.MultiStringBWTCython
        import MUSCython.RLE_BWTCython

    def test_import_muscython_stubs(self):
        # milestone 10: LCPGen is the only remaining stub, classified
        # DEAD/PRIVATE (no public CLI/API path reaches it); CompressToRLE is
        # migrated and covered by test_muscython_compress_to_rle_migrated
        import MUSCython.LCPGen
        for module, name in [
            ("MUSCython.LCPGen", "lcpGenerator"),
            ("MUSCython.LCPGen", "linearLcpGenerator"),
        ]:
            callable_ = getattr(__import__(module, fromlist=[name]), name)
            self.assertRaises(NotImplementedError, callable_, "x", 1, None)

    def test_muscython_compress_to_rle_migrated(self):
        # milestone 10: CompressToRLE is the real migrated Cython module
        # (frozen pyx + language_level=2), not a stub anymore
        import MUSCython.CompressToRLE
        self.assertTrue(callable(MUSCython.CompressToRLE.compressInput))
        self.assertFalse(
            hasattr(MUSCython.CompressToRLE, "_not_implemented"))

    def test_muscython_multimerge_migrated(self):
        # milestone 8: MultimergeCython is the real migrated Cython module
        # (frozen pyx + language_level=2), not a stub anymore
        import MUSCython.MultimergeCython
        self.assertTrue(callable(MUSCython.MultimergeCython.preprocessFastqs))
        self.assertTrue(callable(MUSCython.MultimergeCython.interleaveLevelMerge))
        self.assertTrue(callable(MUSCython.MultimergeCython.fastqIterator))
        self.assertTrue(callable(MUSCython.MultimergeCython.memoryBWT))
        self.assertFalse(
            hasattr(MUSCython.MultimergeCython, "_not_implemented"))

    def test_muscython_genericmerge_migrated(self):
        # milestone 9: GenericMerge is the real migrated Cython module
        # (frozen pyx + language_level=2), not a stub anymore
        import MUSCython.GenericMerge
        self.assertTrue(callable(MUSCython.GenericMerge.mergeTwoMSBWTs))
        self.assertTrue(callable(MUSCython.GenericMerge.interleaveTwoBwts))
        self.assertFalse(
            hasattr(MUSCython.GenericMerge, "_not_implemented"))

    def test_load_preference_surface(self):
        from MUSCython import MultiStringBWTCython
        self.assertTrue(callable(MultiStringBWTCython.loadBWT))
        self.assertTrue(callable(MultiStringBWTCython.preprocessFastqs))
        self.assertTrue(callable(MultiStringBWTCython.createMSBWTFromSeqs))


class CliSmokeTests(unittest.TestCase):
    def test_version_output(self):
        from MUS import CommandLineInterface
        old_argv = sys.argv
        old_stderr = sys.stderr
        try:
            sys.argv = ["msbwt", "-V"]
            captured = StringIO.StringIO()
            sys.stderr = captured
            self.assertRaises(SystemExit, CommandLineInterface.mainRun)
        finally:
            sys.argv = old_argv
            sys.stderr = old_stderr
        text = captured.getvalue()
        self.assertIn("0.3.0 in MSBWT 0.3.0", text)


class GoldenSliceTests(unittest.TestCase):
    """The bootstrap vertical slice: uniform-multifile build, reader, query,
    compared byte-for-byte against the committed legacy golden manifest."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="modern2-py2-test-")
        self.out = os.path.join(self.work, "out")
        os.mkdir(self.out)
        for fixture in ("uniform-a.fastq", "uniform-b.fastq"):
            shutil.copy(os.path.join(FIXTURES, fixture), self.work)
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _cli(self, *argv):
        from MUS import CommandLineInterface
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt"] + list(argv)
            CommandLineInterface.mainRun()
        finally:
            sys.argv = old_argv

    def _verify_stage(self, stage, artifact_dir):
        with open(os.path.join(GOLDEN, stage, "manifest.json"), "rb") as handle:
            manifest = json.load(handle)
        actual_names = sorted(os.listdir(artifact_dir))
        expected_names = sorted(entry["path"] for entry in manifest["artifacts"])
        self.assertEqual(actual_names, expected_names)
        for entry in manifest["artifacts"]:
            path = os.path.join(artifact_dir, entry["path"])
            self.assertEqual(os.path.getsize(path), entry["size"], entry["path"])
            self.assertEqual(sha256_file(path), entry["sha256"], entry["path"])

    def test_preprocess_and_build_match_golden_bytes(self):
        self._cli("pp", "-u", self.out,
                  os.path.join(self.work, "uniform-a.fastq"),
                  os.path.join(self.work, "uniform-b.fastq"))
        self._verify_stage("pre", self.out)
        self._cli("cfpp", "-p", "1", "-u", self.out)
        self._verify_stage("build", self.out)

    def test_primary_contract(self):
        self._cli("pp", "-u", self.out,
                  os.path.join(self.work, "uniform-a.fastq"),
                  os.path.join(self.work, "uniform-b.fastq"))
        self._cli("cfpp", "-p", "1", "-u", self.out)
        primary = os.path.join(self.out, "msbwt.npy")
        self.assertEqual(sha256_file(primary), MSBWT_SHA256)
        with open(primary, "rb") as handle:
            data = handle.read()
        self.assertEqual(data[:6], b"\x93NUMPY")
        header_len = ord(data[8]) + ord(data[9]) * 256
        header = data[10:10 + header_len]
        self.assertIn(b"'descr': '|u1'", header)
        self.assertIn(b"'shape': (48L,)", header)
        payload = data[10 + header_len:]
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e")

    def test_reader_and_query_match_legacy_smoke(self):
        self._cli("pp", "-u", self.out,
                  os.path.join(self.work, "uniform-a.fastq"),
                  os.path.join(self.work, "uniform-b.fastq"))
        self._cli("cfpp", "-p", "1", "-u", self.out)
        copy = os.path.join(self.work, "reader-copy")
        shutil.copytree(self.out, copy)
        from MUSCython import MultiStringBWTCython as CompiledBWT
        msbwt = CompiledBWT.loadBWT(copy, logger=None)
        self.assertEqual(type(msbwt).__module__ + "." + type(msbwt).__name__,
                         "MUSCython.ByteBWTCython.ByteBWT")
        self.assertEqual(msbwt.getTotalSize(), 48)
        for kmer, expected in EXPECTED_QUERIES:
            self.assertEqual(msbwt.countOccurrencesOfSeq(kmer), expected)
        side_effects = sorted(os.listdir(copy))
        self.assertEqual(
            side_effects,
            ["about.npy", "fmIndex.npy", "msbwt.npy", "offsets.npy",
             "seqs.npy.0.npy", "seqs.npy.1.npy", "seqs.npy.2.npy",
             "seqs.npy.3.npy", "seqs.npy.4.npy", "seqs.npy.5.npy",
             "totalCounts.npy"])


if __name__ == "__main__":
    unittest.main()
