"""M3-S2-INPUT: construction input validation (modern3).

Before this fix, both compiled construction paths (compiled with
``boundscheck=False``) trusted their input:

- ``MultimergeCython.memoryBWT`` (non-uniform reads, FASTA, FASTQ):
  an unterminated periodic read (``TTTT``) looped forever, an unterminated
  read (``ACGT``) silently produced a wrong BWT, an inner ``$`` was accepted,
  and any byte outside ``$ACGNT`` (soft-masked ``acgt``, IUPAC ``R``) wrote
  past a 6-element buffer: heap corruption or a segfault.  In a pool worker
  the crash left ``msbwt cffq`` hanging forever.
- ``MSBWTGenCython.writeSeqsToFiles`` (uniform reads, ``cffq -u``) mapped the
  same bytes to an out-of-range code; ``cffq -u`` on soft-masked FASTQ hung.

Now every such input raises ``ValueError`` before any unchecked write, the
merge pool is shut down, and valid input produces identical bytes.

Anything that could hang runs in a subprocess with a timeout, so a
regression fails instead of freezing the suite.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

try:
    from MUSCython import MultimergeCython
    HAVE_COMPILED = True
except ImportError:
    HAVE_COMPILED = False

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.normpath(os.path.join(
    TESTS_DIR, "..", "..", "packages", "msbwt-modern3"))
TIMEOUT = 60

INVALID = [
    ("TTTT", "missing the terminal '$'"),
    ("ACGT", "missing the terminal '$'"),
    ("AC$GT$", "'$' before the end"),
    ("acgt$", "invalid symbol b'a'"),
    ("ACGRT$", "invalid symbol b'R'"),
    ("", "empty string"),
]


def run_script(source, *args):
    env = dict(os.environ)
    env["PYTHONPATH"] = PACKAGE
    work = tempfile.mkdtemp(prefix="m3s2-")
    script = os.path.join(work, "probe.py")
    with open(script, "w") as fp:
        fp.write(textwrap.dedent(source))
    try:
        return subprocess.run(
            [sys.executable, script] + list(args),
            env=env, capture_output=True, text=True,
            timeout=TIMEOUT, stdin=subprocess.DEVNULL, check=False)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def rotation_bwt(text):
    """Independent single-string BWT: last column of sorted rotations,
    with '$' as the unique smallest symbol."""
    order = {c: i for i, c in enumerate("$ACGNT")}
    rotations = sorted(
        (text[i:] + text[:i] for i in range(len(text))),
        key=lambda r: [order[c] for c in r])
    return bytes(order[r[-1]] for r in rotations)


@unittest.skipUnless(HAVE_COMPILED, "compiled MUSCython extensions not built")
class MemoryBWTValidationTests(unittest.TestCase):
    def test_invalid_inputs_raise_without_hanging(self):
        result = run_script("""
            import sys
            from MUSCython import MultimergeCython as MM
            for seq in sys.argv[1:]:
                try:
                    MM.memoryBWT(seq)
                except ValueError as exc:
                    print("REJECTED", repr(seq), str(exc))
                else:
                    print("ACCEPTED", repr(seq))
            try:
                MM.memoryBWT(b"ACG\\xe9T$")
            except ValueError as exc:
                print("REJECTED high-byte", str(exc))
        """, *[seq for seq, _ in INVALID])
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), len(INVALID) + 1, result.stdout)
        for (seq, reason), line in zip(INVALID, lines):
            self.assertTrue(line.startswith("REJECTED %r" % seq), line)
            self.assertIn(reason, line)
        self.assertIn("invalid symbol b'\\xe9'", lines[-1])

    def test_valid_inputs_match_rotation_oracle(self):
        for text in ("$", "A$", "ACGT$", "TTTT$", "NNACGTN$", "GATTACA$",
                     "ACGTACGTACGTNNNNTTTT$"):
            bwt, length = MultimergeCython.memoryBWT(text)
            self.assertEqual(length, len(text))
            self.assertEqual(bwt, rotation_bwt(text), text)


@unittest.skipUnless(HAVE_COMPILED, "compiled MUSCython extensions not built")
class ConstructionValidationTests(unittest.TestCase):
    PROBE = """
        import logging, os, sys
        from MUSCython import MultimergeCython as MM
        from MUSCython import MultiStringBWTCython as MSB
        def main():
            out, mode = sys.argv[1], sys.argv[2]
            reads = sys.argv[3:]
            log = logging.getLogger("probe")
            try:
                if mode == "multimerge":
                    MM.createMSBWTFromSeqs(reads, out, 1, False, log)
                else:
                    MSB.createMSBWTFromSeqs(reads, out, 1, True, log)
            except ValueError as exc:
                print("REJECTED", str(exc))
            else:
                print("BUILT")
        if __name__ == "__main__":
            main()
    """

    def build(self, mode, reads):
        work = tempfile.mkdtemp(prefix="m3s2-build-")
        try:
            return run_script(self.PROBE, work, mode, *reads)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_multimerge_rejects_and_shuts_pool_down(self):
        for reads, reason in (
                (["ACGT$", "TTTT"], "missing the terminal '$'"),
                (["ACGT$", "acgt$"], "invalid symbol b'a'"),
                (["ACGT$", "AC$GT$"], "'$' before the end")):
            result = self.build("multimerge", reads)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("REJECTED", result.stdout)
            self.assertIn(reason, result.stdout)
        self.assertIn("BUILT", self.build(
            "multimerge", ["ACGT$", "TTTT$", "GGA$"]).stdout)

    def test_uniform_bauer_rejects(self):
        for reads, reason in (
                (["ACGT$", "acgt$"], "invalid symbol b'a'"),
                (["ACGT$", "ACGRT"], "invalid symbol b'R'"),
                (["ACGT$", "AC$G$"], "'$' before the end"),
                (["ACGT$", "ACGTT"], "missing the terminal '$'")):
            result = self.build("uniform", reads)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("REJECTED", result.stdout, reads)
            self.assertIn(reason, result.stdout, reads)
        self.assertIn("BUILT", self.build(
            "uniform", ["ACGT$", "TTTT$", "GGAN$"]).stdout)


@unittest.skipUnless(HAVE_COMPILED, "compiled MUSCython extensions not built")
class CommandLineValidationTests(unittest.TestCase):
    def test_cffq_fails_fast_on_soft_masked_fastq(self):
        work = tempfile.mkdtemp(prefix="m3s2-cli-")
        try:
            fastq = os.path.join(work, "masked.fq")
            with open(fastq, "w") as fp:
                fp.write("@r1\nACGTACGT\n+\nIIIIIIII\n"
                         "@r2\nacgtTTTT\n+\nIIIIIIII\n")
            for flags in (["-u"], []):
                out = os.path.join(work, "out%d" % len(flags))
                result = run_script("""
                    import sys
                    from MUS.CommandLineInterface import mainRun
                    if __name__ == "__main__":
                        sys.argv = ["msbwt", "cffq"] + sys.argv[1:]
                        mainRun()
                """, *(flags + [out, fastq]))
                self.assertNotEqual(result.returncode, 0, flags)
                self.assertIn("invalid symbol b'a'", result.stderr, flags)
        finally:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
