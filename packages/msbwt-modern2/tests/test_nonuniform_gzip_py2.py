"""msbwt-modern2 milestone 8 tests: nonuniform construction + gzip input,
runnable inside the pinned Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO
(the validation driver sets it).  These tests execute the real nonuniform
(``pp`` + ``cfpp -p 1`` without ``-u``) and gzip-input (``pp`` of the .gz
fixtures + ``cfpp -p 1``) slices and compare every artifact byte-for-byte
with the committed legacy golden manifests.

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

NONUNIFORM_PRE = {
    "offsets.npy": ("da7fcb73c1fa0bdc0c84ee2f137e566ce2ba506a15aad58c2358d8c446e6d08e", 64),
    "seqs.npy": ("f4239e43bfeffcfa48e4439b27faafa670dc6f16b117e8a92b3d3f7a4bbff303", 30),
}
NONUNIFORM_BUILD = {
    "msbwt.npy": ("da28963ca3726568dd7a26eccea35f107bd4cb8b295c909de628374db38dd4b2", 158),
    "offsets.npy": NONUNIFORM_PRE["offsets.npy"],
    "seqs.npy": NONUNIFORM_PRE["seqs.npy"],
}
NONUNIFORM_PAYLOAD = "7a97b19addd3c41a79dbd6ce5e43609766eca78a971576e1ab2b32e3df80ca03"
NONUNIFORM_SIDE_EFFECTS = {
    "fmIndex.npy": ("fc626114ba15fd9a1b242c1671aa5ea166492393d76b1ba840ce93859950cd0c", 176),
    "totalCounts.npy": ("2959abbf39535b8c8b4a080d8d3f3458ec0e4eadc9e2aa478156e84361af6f5c", 176),
}

GZIP_PRE = {
    "offsets.npy": ("9f96565f1486a66ea7726b0f8cb68da50871469c1e16f99b2a800573cc1f6194", 96),
    "seqs.npy": ("605c199e1023112d5e113dc1a4f9761b66d52937d2d56eeeaad4d51521ecf8c9", 54),
}
GZIP_BUILD = {
    "msbwt.npy": ("da40d02ef42d4cf61d7b4814a2bc2c44c48f3516a53d6111a19bf2fdba8ff33b", 182),
    "offsets.npy": GZIP_PRE["offsets.npy"],
    "seqs.npy": GZIP_PRE["seqs.npy"],
}
GZIP_PAYLOAD = "13c687364c3ca7ebae5379d4f8d9814d880616dd23968fdfa2c2697ced9f24ee"
GZIP_SIDE_EFFECTS = {
    "fmIndex.npy": ("9207663ec63508a3dd5dfc179f3963ac5aa2b5e046ed84dee6de5fd049cf82d4", 176),
    "totalCounts.npy": ("d5a953fe54e57854b58000639cbc29511f93736abf57819b7ee87f54ea54911f", 176),
}

GZIP_FIXTURES = {
    "uniform-a.fastq.gz": ("dc8bdc5aedc346f364e5e73a34734f61a55cb1b97f9788ac10ff774c16aaeadb", 138),
    "nonuniform.fastq.gz": ("93936b82d32a57dc8d1e7658fc8421ea61819db69414ac1464c5287e7148ccd8", 151),
}
NONUNIFORM_FIXTURE = ("nonuniform.fastq",
                      "e19ef01c7683cd81534fada1f8142ddf35710a2e1bf9b70d92bb8de2acb1973e", 246)

COMPRESSED_GOLDEN = "9d19222eaa78c1d89304e79ff14a8a0a5f0c21c3ae979d179f570f1d8d5c1e66"


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_smoke(case):
    with open(os.path.join(GOLDENS, case, PROFILE, ROUTE, "reader-smoke.json"),
              "rb") as handle:
        smoke = json.load(handle)
    assert smoke["status"] == "passed"
    return smoke


class Milestone8EnvironmentTests(unittest.TestCase):
    def test_python_is_cpython_27(self):
        self.assertEqual(sys.version_info[:2], (2, 7))

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

    def test_multimergecython_is_the_migrated_module(self):
        import MUSCython.MultimergeCython
        module = MUSCython.MultimergeCython
        self.assertTrue(callable(module.preprocessFastqs))
        self.assertTrue(callable(module.interleaveLevelMerge))
        self.assertTrue(callable(module.fastqIterator))
        self.assertTrue(callable(module.memoryBWT))
        self.assertTrue(callable(module.formatSeqsForMerge))
        self.assertFalse(hasattr(module, "_not_implemented"))

    def test_multimerge_pyx_diff_is_language_level_only(self):
        import difflib
        frozen_path = os.path.join(REPO, "MUSCython", "MultimergeCython.pyx")
        modern_path = os.path.join(REPO, "packages", "msbwt-modern2",
                                   "MUSCython", "MultimergeCython.pyx")
        frozen_text = open(frozen_path, "rb").read().replace(b"\r\n", b"\n")
        modern_text = open(modern_path, "rb").read().replace(b"\r\n", b"\n")
        diff = list(difflib.unified_diff(
            frozen_text.decode("utf-8").splitlines(),
            modern_text.decode("utf-8").splitlines(), lineterm=""))
        added = [line[1:] for line in diff
                 if line.startswith("+") and not line.startswith("+++")]
        removed = [line[1:] for line in diff
                   if line.startswith("-") and not line.startswith("---")]
        # The only removed lines are the three documented Windows-portability
        # writer replacements (np.save -> open_memmap, cumsum dtype fix).
        self.assertEqual(removed, [
            "        np.save(interleaveFN0, inter0)",
            "    cdef np.ndarray[np.uint64_t, ndim=1, mode='c'] fmOffsets = np.cumsum(totalCounts)-totalCounts",
            "        np.save(mergedDir+'/msbwt.npy', seqs)",
        ])
        self.assertEqual(added[0], "#cython: language_level=2")
        # Every other added line is part of the documented Windows
        # portability changes (see COMPATIBILITY.md): .npy header shape
        # normalization (_int_shape helper + open_memmap writers), the
        # memmap-close guards before os.remove(), and the forced-u8 cumsum.
        for line in added[1:]:
            self.assertTrue(
                "(Windows portability)" in line
                or line.startswith("def _int_shape")
                or line.startswith("    return tuple(int(x) for x in shape)")
                or line.startswith("        _mm = ")
                or line.startswith("        _mm[:] = ")
                or line.startswith("        del _mm")
                or line.strip().startswith("_int_shape(")
                or line.startswith("        if (<object>")
                or line.startswith("            (<object>")
                or line.strip().startswith(
                    "cdef np.ndarray[np.uint64_t, ndim=1, mode='c'] fmOffsets = "
                    "np.cumsum(totalCounts, dtype='<u8')-totalCounts")
                or line == ""
                or line.strip().startswith("#"),  # documentation comments
                repr(line))


class CaseHarness(object):
    """Runs the modern2 CLI for one committed case and checks the artifacts."""

    def __init__(self, case, work):
        self.case = case
        self.work = work

    def _cli(self, *argv):
        from MUS import CommandLineInterface
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt"] + list(argv)
            CommandLineInterface.mainRun()
        finally:
            sys.argv = old_argv

    def preprocess(self, target_dir):
        if self.case == "nonuniform-prefix":
            self._cli("pp", target_dir,
                      os.path.join(FIXTURES, "nonuniform.fastq"))
        else:
            self._cli("pp", target_dir,
                      os.path.join(FIXTURES, "uniform-a.fastq.gz"),
                      os.path.join(FIXTURES, "nonuniform.fastq.gz"))

    def build(self, target_dir, processes="1"):
        self._cli("cfpp", "-p", processes, target_dir)

    def run(self):
        out = os.path.join(self.work, "out")
        os.mkdir(out)
        self.preprocess(out)
        pre_files = dict(
            (name, (sha256_file(os.path.join(out, name)),
                    os.path.getsize(os.path.join(out, name))))
            for name in sorted(os.listdir(out)))
        self.build(out)
        build_files = dict(
            (name, (sha256_file(os.path.join(out, name)),
                    os.path.getsize(os.path.join(out, name))))
            for name in sorted(os.listdir(out)))
        return out, pre_files, build_files


class NonuniformCaseTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="modern2-py2-nonuni-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_preprocess_exact_contract(self):
        harness = CaseHarness("nonuniform-prefix", self.work)
        out = os.path.join(self.work, "out")
        os.mkdir(out)
        harness.preprocess(out)
        files = dict(
            (name, (sha256_file(os.path.join(out, name)),
                    os.path.getsize(os.path.join(out, name))))
            for name in sorted(os.listdir(out)))
        self.assertEqual(files, NONUNIFORM_PRE)

    def test_build_exact_golden(self):
        harness = CaseHarness("nonuniform-prefix", self.work)
        out, pre_files, build_files = harness.run()
        self.assertEqual(build_files, NONUNIFORM_BUILD)

    def test_primary_header_and_payload(self):
        harness = CaseHarness("nonuniform-prefix", self.work)
        out, _, _ = harness.run()
        with open(os.path.join(out, "msbwt.npy"), "rb") as handle:
            data = handle.read()
        self.assertEqual(data[:6], b"\x93NUMPY")
        header_len = ord(data[8]) + ord(data[9]) * 256
        header = data[10:10 + header_len]
        self.assertIn(b"'descr': '|u1'", header)
        self.assertIn(b"'shape': (30,)", header)
        payload = data[10 + header_len:]
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         NONUNIFORM_PAYLOAD)

    def test_deterministic_independent_runs(self):
        harness_a = CaseHarness("nonuniform-prefix", self.work)
        out_a, pre_a, build_a = harness_a.run()
        work_b = os.path.join(self.work, "work-b")
        os.mkdir(work_b)
        harness_b = CaseHarness("nonuniform-prefix", work_b)
        out_b, pre_b, build_b = harness_b.run()
        self.assertEqual(pre_a, pre_b)
        self.assertEqual(build_a, build_b)

    def test_p2_build_byte_identical_to_p1(self):
        harness = CaseHarness("nonuniform-prefix", self.work)
        out, _, build = harness.run()
        out2 = os.path.join(self.work, "out-p2")
        os.mkdir(out2)
        harness.preprocess(out2)
        harness.build(out2, "2")
        build2 = dict(
            (name, (sha256_file(os.path.join(out2, name)),
                    os.path.getsize(os.path.join(out2, name))))
            for name in sorted(os.listdir(out2)))
        self.assertEqual(build, build2)

    def test_reader_queries_recovery_side_effects(self):
        harness = CaseHarness("nonuniform-prefix", self.work)
        out, _, _ = harness.run()
        smoke = read_smoke("nonuniform-prefix")
        copy = os.path.join(self.work, "reader-copy")
        shutil.copytree(out, copy)
        from MUSCython import MultiStringBWTCython as CompiledBWT
        reader = CompiledBWT.loadBWT(copy, useMemmap=False, logger=None)
        self.assertEqual(type(reader).__module__ + "." + type(reader).__name__,
                         "MUSCython.ByteBWTCython.ByteBWT")
        self.assertEqual(reader.getTotalSize(), smoke["total_size"])
        self.assertEqual(int(reader.getSymbolCount(0)), smoke["dollar_count"])
        for kmer, expected in smoke["expected_queries"].items():
            self.assertEqual(int(reader.countOccurrencesOfSeq(str(kmer))),
                             int(expected), kmer)
        recovered = sorted(reader.recoverString(i)
                           for i in range(int(reader.getSymbolCount(0))))
        self.assertEqual([str(v) for v in recovered],
                         [str(v) for v in smoke["expected_recovered_strings"]])
        side_effects = dict(
            (name, (sha256_file(os.path.join(copy, name)),
                    os.path.getsize(os.path.join(copy, name))))
            for name in ("fmIndex.npy", "totalCounts.npy"))
        self.assertEqual(side_effects, NONUNIFORM_SIDE_EFFECTS)


class GzipCaseTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="modern2-py2-gzip-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_gzip_fixture_hashes(self):
        for name, (digest, size) in GZIP_FIXTURES.items():
            path = os.path.join(FIXTURES, name)
            self.assertEqual(os.path.getsize(path), size, name)
            self.assertEqual(sha256_file(path), digest, name)

    def test_preprocess_exact_contract(self):
        harness = CaseHarness("gzip-input", self.work)
        out = os.path.join(self.work, "out")
        os.mkdir(out)
        harness.preprocess(out)
        files = dict(
            (name, (sha256_file(os.path.join(out, name)),
                    os.path.getsize(os.path.join(out, name))))
            for name in sorted(os.listdir(out)))
        self.assertEqual(files, GZIP_PRE)

    def test_build_exact_golden(self):
        harness = CaseHarness("gzip-input", self.work)
        out, pre_files, build_files = harness.run()
        self.assertEqual(build_files, GZIP_BUILD)

    def test_primary_header_and_payload(self):
        harness = CaseHarness("gzip-input", self.work)
        out, _, _ = harness.run()
        with open(os.path.join(out, "msbwt.npy"), "rb") as handle:
            data = handle.read()
        self.assertEqual(data[:6], b"\x93NUMPY")
        header_len = ord(data[8]) + ord(data[9]) * 256
        header = data[10:10 + header_len]
        self.assertIn(b"'descr': '|u1'", header)
        self.assertIn(b"'shape': (54,)", header)
        payload = data[10 + header_len:]
        self.assertEqual(hashlib.sha256(payload).hexdigest(), GZIP_PAYLOAD)

    def test_gzip_and_plain_inputs_identical_preprocess(self):
        # the .gz fixtures decompress byte-identically to the plain fixtures;
        # the preprocessing of both must produce identical artifacts
        import gzip as gzip_module
        for name in ("uniform-a.fastq", "nonuniform.fastq"):
            plain = open(os.path.join(FIXTURES, name), "rb").read()
            compressed = gzip_module.open(
                os.path.join(FIXTURES, name + ".gz"), "rb").read()
            self.assertEqual(plain, compressed, name)
        gzip_out = os.path.join(self.work, "gzip-out")
        os.mkdir(gzip_out)
        harness = CaseHarness("gzip-input", self.work)
        harness.preprocess(gzip_out)
        gzip_files = dict(
            (name, (sha256_file(os.path.join(gzip_out, name)),
                    os.path.getsize(os.path.join(gzip_out, name))))
            for name in sorted(os.listdir(gzip_out)))
        plain_out = os.path.join(self.work, "plain-out")
        os.mkdir(plain_out)
        from MUS import CommandLineInterface
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt", "pp", plain_out,
                        os.path.join(FIXTURES, "uniform-a.fastq"),
                        os.path.join(FIXTURES, "nonuniform.fastq")]
            CommandLineInterface.mainRun()
        finally:
            sys.argv = old_argv
        plain_files = dict(
            (name, (sha256_file(os.path.join(plain_out, name)),
                    os.path.getsize(os.path.join(plain_out, name))))
            for name in sorted(os.listdir(plain_out)))
        self.assertEqual(gzip_files, plain_files)
        self.assertEqual(gzip_files, GZIP_PRE)

    def test_deterministic_independent_runs(self):
        harness_a = CaseHarness("gzip-input", self.work)
        out_a, pre_a, build_a = harness_a.run()
        work_b = os.path.join(self.work, "work-b")
        os.mkdir(work_b)
        harness_b = CaseHarness("gzip-input", work_b)
        out_b, pre_b, build_b = harness_b.run()
        self.assertEqual(pre_a, pre_b)
        self.assertEqual(build_a, build_b)

    def test_p2_build_byte_identical_to_p1(self):
        harness = CaseHarness("gzip-input", self.work)
        out, _, build = harness.run()
        out2 = os.path.join(self.work, "out-p2")
        os.mkdir(out2)
        harness.preprocess(out2)
        harness.build(out2, "2")
        build2 = dict(
            (name, (sha256_file(os.path.join(out2, name)),
                    os.path.getsize(os.path.join(out2, name))))
            for name in sorted(os.listdir(out2)))
        self.assertEqual(build, build2)

    def test_reader_queries_recovery_side_effects(self):
        harness = CaseHarness("gzip-input", self.work)
        out, _, _ = harness.run()
        smoke = read_smoke("gzip-input")
        copy = os.path.join(self.work, "reader-copy")
        shutil.copytree(out, copy)
        from MUSCython import MultiStringBWTCython as CompiledBWT
        reader = CompiledBWT.loadBWT(copy, useMemmap=False, logger=None)
        self.assertEqual(type(reader).__module__ + "." + type(reader).__name__,
                         "MUSCython.ByteBWTCython.ByteBWT")
        self.assertEqual(reader.getTotalSize(), smoke["total_size"])
        self.assertEqual(int(reader.getSymbolCount(0)), smoke["dollar_count"])
        for kmer, expected in smoke["expected_queries"].items():
            self.assertEqual(int(reader.countOccurrencesOfSeq(str(kmer))),
                             int(expected), kmer)
        recovered = sorted(reader.recoverString(i)
                           for i in range(int(reader.getSymbolCount(0))))
        self.assertEqual([str(v) for v in recovered],
                         [str(v) for v in smoke["expected_recovered_strings"]])
        side_effects = dict(
            (name, (sha256_file(os.path.join(copy, name)),
                    os.path.getsize(os.path.join(copy, name))))
            for name in ("fmIndex.npy", "totalCounts.npy"))
        self.assertEqual(side_effects, GZIP_SIDE_EFFECTS)


class NonuniformCompressRoundtripTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="modern2-py2-compress-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_byte_compress_decompress_roundtrip(self):
        from MUS import CommandLineInterface
        src = os.path.join(self.work, "src")
        comp = os.path.join(self.work, "comp")
        decomp = os.path.join(self.work, "decomp")
        for directory in (src, comp, decomp):
            os.mkdir(directory)

        def cli(*argv):
            old_argv = sys.argv
            try:
                sys.argv = ["msbwt"] + list(argv)
                CommandLineInterface.mainRun()
            finally:
                sys.argv = old_argv

        cli("pp", src, os.path.join(FIXTURES, "nonuniform.fastq"))
        cli("cfpp", "-p", "1", src)
        self.assertEqual(sha256_file(os.path.join(src, "msbwt.npy")),
                         NONUNIFORM_BUILD["msbwt.npy"][0])
        cli("compress", "-p", "1", src, comp)
        self.assertEqual(sha256_file(os.path.join(comp, "comp_msbwt.npy")),
                         COMPRESSED_GOLDEN)
        cli("decompress", "-p", "1", comp, decomp)
        self.assertEqual(sha256_file(os.path.join(decomp, "msbwt.npy")),
                         NONUNIFORM_BUILD["msbwt.npy"][0])


if __name__ == "__main__":
    unittest.main()
