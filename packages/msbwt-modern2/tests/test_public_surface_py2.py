"""msbwt-modern2 milestone 10 tests: remaining public surface audit + closure.

Runnable inside the pinned Python-2.7 environment:

    python -m unittest discover -s tests

Requires MSBWT_MODERN2_REPO pointing at the repository root (the validation
driver sets it).  Covers the public import/export smoke matrix, the migrated
``MUSCython.CompressToRLE`` / public ``convert`` CLI (byte-identity against
the committed secondary-regenerated-source oracle), the convert failure/
quirk contracts, the public ``massquery`` CLI, the unexercised historical
``MSBWTGenCython.compressBWT`` execution probe, and the LCPGen stub
classification.

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import hashlib
import json
import os
import shutil
import StringIO
import sys
import tempfile
import unittest

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

GOLDENS = os.path.join(REPO, "compat", "goldens", "original-0.3.0")
CONVERT_GOLDEN = os.path.join(GOLDENS, "convert-milestone10")
FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")
UNIFORM_MULTIFILE_BUILD = os.path.join(
    GOLDENS, "uniform-multifile", "py27-late-05a7d6d83862",
    "pyx-historical-cython", "build", "artifacts")
NONUNIFORM_PREFIX_BUILD = os.path.join(
    GOLDENS, "nonuniform-prefix", "py27-late-05a7d6d83862",
    "pyx-historical-cython", "build", "artifacts")

UNIFORM_CONVERT_SHA256 = "121ffb41838b696ed0c543345794f8dad36525373e4d7427de8a45d298ec009b"
NONUNIFORM_CONVERT_SHA256 = "5fb45204712b0177803104d27a8170f11c159ed4f666c1b2521bc8fc614c7517"
UNIFORM_PAYLOAD_SHA256 = "6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb"
NONUNIFORM_PAYLOAD_SHA256 = "5566aa4e33bd1952004221c69ef2591d22ef94f38805b68a96f74913f2042363"
UNIFORM_DIRECT_SHA256 = "0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372"
NONUNIFORM_PYX_COMPRESS_SHA256 = "07692b307c7533626900f1c7ee778f6aaa4cdfc453b86822dec8195c75286fdd"
INVALID_AFTER_NEWLINE_PAYLOAD = "6a9cc3bdeb3bdcfe24fbef1b051e63029b82470a73b2dab39524eef580544a6f"


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def payload_sha256(path):
    data = open(path, "rb").read()
    header_len = ord(data[8]) | (ord(data[9]) << 8)
    return hashlib.sha256(data[10 + header_len:]).hexdigest()


class NullLogger(object):
    def info(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


class ImportSmokeMatrixTests(unittest.TestCase):
    """Public import/export smoke matrix: every documented public symbol
    imports and resolves to a real implementation (no unexplained stubs)."""

    def test_mus_modules(self):
        import MUS
        import MUS.CommandLineInterface
        import MUS.MSBWTGen
        import MUS.MultiStringBWT
        import MUS.TranscriptBuilder
        import MUS.util
        self.assertEqual(MUS.util.VERSION, "0.3.0")
        self.assertEqual(MUS.util.PKG_VERSION, "0.3.0")
        for name in ("initLogger", "mainRun"):
            self.assertTrue(callable(getattr(MUS.CommandLineInterface, name)), name)
        for name in ("compressBWT", "decompressBWT", "createFromSeqs",
                     "writeSeqsToFiles", "clearAuxiliaryData"):
            self.assertTrue(callable(getattr(MUS.MSBWTGen, name)), name)
        for name in ("BasicBWT", "MultiStringBWT", "CompressedMSBWT", "loadBWT",
                     "createMSBWTFromSeqs", "createMSBWTFromFastq",
                     "preprocessFastqs", "reverseComplement"):
            self.assertTrue(callable(getattr(MUS.MultiStringBWT, name)), name)
        for name in ("PathNode", "PathEdge", "Assembler"):
            self.assertTrue(callable(getattr(MUS.TranscriptBuilder, name)), name)
        for name in ("readableFastqFile", "newDirectory", "existingDirectory",
                     "validKmer", "fastaIterator", "fastqIterator"):
            self.assertTrue(callable(getattr(MUS.util, name)), name)

    def test_muscython_compiled_modules(self):
        import MUSCython.AlignmentUtil
        import MUSCython.BasicBWT
        import MUSCython.ByteBWTCython
        import MUSCython.CompressToRLE
        import MUSCython.GenericMerge
        import MUSCython.LZW_BWTCython
        import MUSCython.MSBWTCompGenCython
        import MUSCython.MSBWTGenCython
        import MUSCython.MultiStringBWTCython
        import MUSCython.MultimergeCython
        import MUSCython.RLE_BWTCython
        for module, names in [
            (MUSCython.AlignmentUtil, ("fullAlign", "fullED_score",
                                       "fullED_minimize", "fullAlign_noGO",
                                       "alignChanges")),
            (MUSCython.CompressToRLE, ("compressInput",)),
            (MUSCython.GenericMerge, ("mergeTwoMSBWTs", "interleaveTwoBwts")),
            (MUSCython.MSBWTCompGenCython, ("createMsbwtFromSeqs",)),
            (MUSCython.MSBWTGenCython, ("createMsbwtFromSeqs", "compressBWT",
                                        "compressBWTPoolProcess",
                                        "decompressBWT", "clearAuxiliaryData")),
            (MUSCython.MultiStringBWTCython, ("loadBWT", "createMSBWTFromSeqs",
                                              "createMSBWTCompFromSeqs",
                                              "createMSBWTFromFastq",
                                              "createMSBWTCompFromFastq",
                                              "preprocessFastqs",
                                              "preprocessFastas",
                                              "reverseComplement")),
            (MUSCython.MultimergeCython, ("preprocessFastqs", "fastqIterator",
                                          "fastaIterator", "memoryBWT",
                                          "interleaveLevelMerge",
                                          "formatSeqsForMerge")),
        ]:
            for name in names:
                self.assertTrue(callable(getattr(module, name)), name)
        for module, class_name in [
            (MUSCython.BasicBWT, "BasicBWT"),
            (MUSCython.ByteBWTCython, "ByteBWT"),
            (MUSCython.LZW_BWTCython, "LZW_BWT"),
            (MUSCython.RLE_BWTCython, "RLE_BWT"),
        ]:
            self.assertTrue(callable(getattr(module, class_name)), class_name)

    def test_lcpgen_stub_classified_dead_private(self):
        import MUSCython.LCPGen
        self.assertIn("DEAD/PRIVATE", MUSCython.LCPGen.__doc__)
        for name in ("lcpGenerator", "linearLcpGenerator"):
            callable_ = getattr(MUSCython.LCPGen, name)
            self.assertTrue(callable(callable_), name)
            self.assertRaises(NotImplementedError, callable_, "x", 1, None)

    def test_no_unexplained_stubs(self):
        for module_name in ("MUSCython.AlignmentUtil", "MUSCython.BasicBWT",
                            "MUSCython.ByteBWTCython",
                            "MUSCython.CompressToRLE",
                            "MUSCython.GenericMerge",
                            "MUSCython.LZW_BWTCython",
                            "MUSCython.MSBWTCompGenCython",
                            "MUSCython.MSBWTGenCython",
                            "MUSCython.MultiStringBWTCython",
                            "MUSCython.MultimergeCython",
                            "MUSCython.RLE_BWTCython"):
            module = __import__(module_name, fromlist=["x"])
            self.assertFalse(hasattr(module, "_not_implemented"), module_name)

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
        self.assertIn("0.3.0 in MSBWT 0.3.0", captured.getvalue())


class ConvertCliTests(unittest.TestCase):
    """Public `convert` CLI: byte-identity with the committed oracle,
    determinism, stdin route, reader semantics, failure contracts."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="modern2-convert-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.uniform_input = os.path.join(CONVERT_GOLDEN, "inputs", "uniform.txt")
        self.nonuniform_input = os.path.join(CONVERT_GOLDEN, "inputs", "nonuniform.txt")
        self.uniform_artifact = os.path.join(
            CONVERT_GOLDEN, "uniform", "secondary-regenerated-source",
            "artifacts", "comp_msbwt.npy")
        self.nonuniform_artifact = os.path.join(
            CONVERT_GOLDEN, "nonuniform", "secondary-regenerated-source",
            "artifacts", "comp_msbwt.npy")

    def _cli(self, *argv):
        from MUS import CommandLineInterface
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt"] + list(argv)
            CommandLineInterface.mainRun()
        finally:
            sys.argv = old_argv

    def test_convert_uniform_matches_oracle(self):
        dst = os.path.join(self.work, "dst-u")
        self._cli("convert", "-i", self.uniform_input, dst)
        primary = os.path.join(dst, "comp_msbwt.npy")
        self.assertEqual(sorted(os.listdir(dst)), ["comp_msbwt.npy"])
        self.assertEqual(sha256_file(primary), UNIFORM_CONVERT_SHA256)
        self.assertEqual(payload_sha256(primary), UNIFORM_PAYLOAD_SHA256)
        # byte-identical to the committed oracle artifact
        self.assertEqual(
            sha256_file(primary), sha256_file(self.uniform_artifact))

    def test_convert_nonuniform_matches_oracle(self):
        dst = os.path.join(self.work, "dst-n")
        self._cli("convert", "-i", self.nonuniform_input, dst)
        primary = os.path.join(dst, "comp_msbwt.npy")
        self.assertEqual(sorted(os.listdir(dst)), ["comp_msbwt.npy"])
        self.assertEqual(sha256_file(primary), NONUNIFORM_CONVERT_SHA256)
        self.assertEqual(payload_sha256(primary), NONUNIFORM_PAYLOAD_SHA256)

    def test_convert_stdin_route_identical(self):
        from MUS import CommandLineInterface
        dst_a = os.path.join(self.work, "dst-a")
        dst_stdin = os.path.join(self.work, "dst-stdin")
        self._cli("convert", "-i", self.uniform_input, dst_a)
        # compressInput reads the C-level stdin (libc FILE*), so the test
        # redirects file descriptor 0 rather than sys.stdin
        old_argv = sys.argv
        stdin_fd = os.dup(0)
        try:
            sys.argv = ["msbwt", "convert", dst_stdin]
            with open(self.uniform_input, "rb") as source:
                os.dup2(source.fileno(), 0)
                CommandLineInterface.mainRun()
        finally:
            os.dup2(stdin_fd, 0)
            os.close(stdin_fd)
            sys.argv = old_argv
        self.assertEqual(
            sha256_file(os.path.join(dst_a, "comp_msbwt.npy")),
            sha256_file(os.path.join(dst_stdin, "comp_msbwt.npy")))

    def test_convert_deterministic_repeated_runs(self):
        dst_a = os.path.join(self.work, "dst-a")
        dst_b = os.path.join(self.work, "dst-b")
        self._cli("convert", "-i", self.uniform_input, dst_a)
        self._cli("convert", "-i", self.uniform_input, dst_b)
        self.assertEqual(
            sha256_file(os.path.join(dst_a, "comp_msbwt.npy")),
            sha256_file(os.path.join(dst_b, "comp_msbwt.npy")))
        self.assertEqual(sha256_file(os.path.join(dst_a, "comp_msbwt.npy")),
                         UNIFORM_CONVERT_SHA256)

    def test_converted_output_loads_as_rle_bwt(self):
        dst = os.path.join(self.work, "dst")
        self._cli("convert", "-i", self.uniform_input, dst)
        copy = os.path.join(self.work, "copy")
        shutil.copytree(dst, copy)
        from MUSCython import MultiStringBWTCython
        reader = MultiStringBWTCython.loadBWT(copy, useMemmap=False)
        self.assertEqual(
            type(reader).__module__ + "." + type(reader).__name__,
            "MUSCython.RLE_BWTCython.RLE_BWT")
        self.assertEqual(reader.getTotalSize(), 48)
        self.assertEqual(reader.getSymbolCount(0), 8)
        for kmer, expected in [("AAAAA", 1), ("ACGTN", 3), ("CCCCC", 1),
                               ("AGCTA", 0), ("AA", 4), ("A", 9)]:
            self.assertEqual(reader.countOccurrencesOfSeq(kmer), expected)
        derived = sorted(os.listdir(copy))
        self.assertEqual(
            derived,
            ["comp_fmIndex.npy", "comp_msbwt.npy", "comp_refIndex.npy",
             "totalCounts.npy"])

    def test_invalid_after_newline_quirk(self):
        # documented legacy quirk: everything after the first newline is
        # silently dropped; exit 0; payload is the RLE of the prefix
        invalid = os.path.join(self.work, "invalid.txt")
        with open(invalid, "wb") as handle:
            handle.write(b"ACGTN\nX\nACGTN\n")
        dst = os.path.join(self.work, "dst-invalid")
        self._cli("convert", "-i", invalid, dst)
        primary = os.path.join(dst, "comp_msbwt.npy")
        self.assertEqual(sorted(os.listdir(dst)), ["comp_msbwt.npy"])
        self.assertEqual(payload_sha256(primary), INVALID_AFTER_NEWLINE_PAYLOAD)

    def test_invalid_before_newline_masked_typeerror(self):
        # documented legacy quirk: the intended Exception is masked by
        # TypeError (PyNumber_Add(str, int) on the C unsigned char)
        invalid = os.path.join(self.work, "invalid.txt")
        with open(invalid, "wb") as handle:
            handle.write(b"ACGTX\nACGTN\n")
        dst = os.path.join(self.work, "dst-invalid")
        from MUS import CommandLineInterface
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt", "convert", "-i", invalid, dst]
            self.assertRaises(TypeError, CommandLineInterface.mainRun)
        finally:
            sys.argv = old_argv
        self.assertEqual(sorted(os.listdir(dst)), ["comp_msbwt.npy"])


class MassqueryCliTests(unittest.TestCase):
    """Public `massquery` CLI (previously unvalidated): CSV contract and
    determinism on the canonical uniform dataset."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="modern2-massquery-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.out = os.path.join(self.work, "out")
        os.mkdir(self.out)
        for fixture in ("uniform-a.fastq", "uniform-b.fastq"):
            shutil.copy(os.path.join(FIXTURES, fixture), self.work)
        from MUS import CommandLineInterface
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt", "pp", "-u", self.out,
                        os.path.join(self.work, "uniform-a.fastq"),
                        os.path.join(self.work, "uniform-b.fastq")]
            CommandLineInterface.mainRun()
            sys.argv = ["msbwt", "cfpp", "-p", "1", "-u", self.out]
            CommandLineInterface.mainRun()
        finally:
            sys.argv = old_argv
        self.kmer_file = os.path.join(self.work, "kmers.txt")
        with open(self.kmer_file, "w") as handle:
            handle.write("ACGTN\nAAAAA\nAGCTA\nAA\n")

    def _cli(self, *argv):
        from MUS import CommandLineInterface
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt"] + list(argv)
            CommandLineInterface.mainRun()
        finally:
            sys.argv = old_argv

    def test_massquery_csv_contract(self):
        output = os.path.join(self.work, "counts.csv")
        self._cli("massquery", self.out, self.kmer_file, output)
        with open(output, "rb") as handle:
            text = handle.read()
        self.assertEqual(
            text,
            b"k-mer,counts\nACGTN,3\nAAAAA,1\nAGCTA,0\nAA,4\n")

    def test_massquery_revcomp_contract(self):
        output = os.path.join(self.work, "counts-rc.csv")
        self._cli("massquery", "-r", self.out, self.kmer_file, output)
        with open(output, "rb") as handle:
            text = handle.read()
        self.assertEqual(
            text,
            b"k-mer,counts,revCompCounts\nACGTN,3,1\nAAAAA,1,1\nAGCTA,0,0\nAA,4,4\n")

    def test_massquery_deterministic(self):
        output_a = os.path.join(self.work, "counts-a.csv")
        output_b = os.path.join(self.work, "counts-b.csv")
        self._cli("massquery", "-r", self.out, self.kmer_file, output_a)
        self._cli("massquery", "-r", self.out, self.kmer_file, output_b)
        self.assertEqual(sha256_file(output_a), sha256_file(output_b))


class CompressBwtPyxProbeTests(unittest.TestCase):
    """MSBWTGenCython.compressBWT is exported but unreachable from any
    public path (the CLI `compress` uses the pure-Python MSBWTGen).  The
    executed probe proves the unexercised historical internal still agrees
    with the established RLE contract under Cython 3.0.12, including the
    typed-division combine path at -p 2."""

    def test_uniform_matches_direct_golden(self):
        from MUSCython import MSBWTGenCython
        source = os.path.join(UNIFORM_MULTIFILE_BUILD, "msbwt.npy")
        outputs = []
        for procs in (1, 2):
            out = os.path.join(self.work_dir(), "comp-u-p%d.npy" % procs)
            MSBWTGenCython.compressBWT(source, out, procs, NullLogger())
            outputs.append(out)
        self.assertEqual(sha256_file(outputs[0]), UNIFORM_DIRECT_SHA256)
        self.assertEqual(sha256_file(outputs[1]), UNIFORM_DIRECT_SHA256)
        self.assertEqual(payload_sha256(outputs[0]), UNIFORM_PAYLOAD_SHA256)

    def test_nonuniform_matches_posthoc_payload(self):
        from MUSCython import MSBWTGenCython
        source = os.path.join(NONUNIFORM_PREFIX_BUILD, "msbwt.npy")
        outputs = []
        for procs in (1, 2):
            out = os.path.join(self.work_dir(), "comp-n-p%d.npy" % procs)
            MSBWTGenCython.compressBWT(source, out, procs, NullLogger())
            outputs.append(out)
        self.assertEqual(sha256_file(outputs[0]), NONUNIFORM_PYX_COMPRESS_SHA256)
        self.assertEqual(sha256_file(outputs[1]), NONUNIFORM_PYX_COMPRESS_SHA256)
        self.assertEqual(payload_sha256(outputs[0]), NONUNIFORM_PAYLOAD_SHA256)

    def work_dir(self):
        directory = os.path.join(self.work, "compressbwt")
        if not os.path.isdir(directory):
            os.makedirs(directory)
        return directory

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="modern2-compressbwt-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
