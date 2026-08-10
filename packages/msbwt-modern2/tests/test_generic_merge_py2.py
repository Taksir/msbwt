"""msbwt-modern2 milestone 9 tests: GenericMerge migration + public merge CLI,
runnable inside the pinned Python-2.7 environment.

Run with:

    python -m unittest discover -s tests

Requires the repository root in the environment variable MSBWT_MODERN2_REPO
(the validation driver sets it).  These tests execute the canonical merge of
the two uniform byte BWTs (``uniform-a.fastq`` + ``uniform-b.fastq``) through
the modern2 public CLI for both ``merge -p 1`` and ``merge -p 2`` and compare
every artifact byte-for-byte with the committed secondary-regenerated-source
merge oracle (``compat/goldens/original-0.3.0/merge-milestone1/``).

The frozen ``merge -p 1`` UnboundLocalError defect is preserved: a functional
regression loads the *frozen* ``MUS/CommandLineInterface.py`` and proves the
historical failure still exists, while the modern2 CLI (documented deviation,
COMPATIBILITY.md entry 2) succeeds.

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import difflib
import hashlib
import imp
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
MILESTONE = os.path.join(GOLDENS, "merge-milestone1")
FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")

# committed merge-milestone1 contract (secondary-regenerated-source oracle)
MERGED_PRIMARY_SHA256 = "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"
MERGED_PAYLOAD_SHA256 = "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e"
INTERLEAVE_SHA256 = "4a6d97a36e9ef4e3c19fb873b7713a9357d207d29433a3eca67a41cc4221afd6"
INTERLEAVE_PAYLOAD_SHA256 = "688c323fa4aed411bb303322c616e6640e31fffdf707d0a596fad2c4f386ca2b"
INPUT_A_SHA256 = "e277c7e5c529808c230fb9dae61626a24eeddad54df2f38e22357a12520f69a1"
INPUT_B_SHA256 = "15f40b98ce3310dfe71c15c34509075e68a271bcc93b125b7005cd2b8f82ff08"
INPUT_A_PAYLOAD = "03ad79575d8bb793ff10796eb678101b67bd8bcae89cdd7aac8c1b1b724742ff"
INPUT_B_PAYLOAD = "0de0ad12b21ffa120a371c1f2d02e22b697396092c39eed12ce3178859ce4c13"
MERGED_SIDE_EFFECTS = {
    "fmIndex.npy": ("a5b4bf06726fcadf535245d03ef65e04a4a5248d368b3aa53639c190028b933f", 176),
    "totalCounts.npy": ("ea104b616fe89d7b786acdff7ca0db61f6339a59c31fbf0fff066ad7384c1c2b", 176),
}

FIXTURES_EXPECTED = {
    "uniform-a.fastq": ("da3466b992e0ba4ef4da2d0731062661f13e66b83ec154b56471ec4286798180", 173),
    "uniform-b.fastq": ("04124b73a3dde82da5cd70d9d244180d6e076a952dda404e4746b1e9388e1029", 162),
    "nonuniform.fastq": ("e19ef01c7683cd81534fada1f8142ddf35710a2e1bf9b70d92bb8de2acb1973e", 246),
}

READS_A = ["ACGTN", "AAAAA", "ACGTN", "NACGT"]
READS_B = ["ACGTN", "CCCCC", "GGGGG", "TTTTT"]
READS_MERGED = sorted(READS_A + READS_B)
SYMBOLS = "$ACGNT"
SYMBOL_COUNTS_EXPECTED = {"$": 8, "A": 9, "C": 9, "G": 9, "N": 4, "T": 9}

FROZEN_GENERICMERGE_PYX = "fe8b699c73a0e671b63cbbe7f2eeba941b91a321156a02df44bf0e010cedce87"
FROZEN_CLI_PY = "5265558e9a04e41eab33493a4fed440e2c640c1198b99ae493810647d1b23189"
FROZEN_MULTISTRINGBWT_PY = "95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0"


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    with open(path, "rb") as handle:
        return json.load(handle)


def unified_diff_added_removed(frozen_path, modern_path):
    frozen_text = open(frozen_path, "rb").read().replace(b"\r\n", b"\n").decode("utf-8")
    modern_text = open(modern_path, "rb").read().replace(b"\r\n", b"\n").decode("utf-8")
    diff = list(difflib.unified_diff(
        frozen_text.splitlines(), modern_text.splitlines(), lineterm=""))
    added = [line[1:] for line in diff
             if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:] for line in diff
               if line.startswith("-") and not line.startswith("---")]
    return added, removed


def read_relationship_reader():
    return read_json(os.path.join(MILESTONE, "relationship-reader.json"))


def payload_of(path):
    with open(path, "rb") as handle:
        data = handle.read()
    header_len = ord(data[8]) + ord(data[9]) * 256
    return data[10 + header_len:]


# --- small independent host-side oracle logic (pure Python 2) ----------------

def symbol_counts(payload):
    counts = dict((symbol, 0) for symbol in SYMBOLS)
    for value in payload:
        counts[SYMBOLS[ord(value)]] += 1
    return counts


def backward_count(payload, pattern):
    counts = symbol_counts(payload)
    c_table = {}
    running = 0
    for symbol in SYMBOLS:
        c_table[symbol] = running
        running += counts[symbol]
    occ = []
    tally = dict((symbol, 0) for symbol in SYMBOLS)
    for value in payload:
        tally[SYMBOLS[ord(value)]] += 1
        occ.append(dict(tally))
    lo, hi = 0, len(payload)
    for char in reversed(pattern):
        lo = c_table[char] + (occ[lo - 1][char] if lo > 0 else 0)
        hi = c_table[char] + (occ[hi - 1][char] if hi > 0 else 0)
        if lo >= hi:
            return 0
    return hi - lo


def lf_recover_reads(payload):
    n = len(payload)
    counts = symbol_counts(payload)
    c_table = {}
    running = 0
    for symbol in SYMBOLS:
        c_table[symbol] = running
        running += counts[symbol]
    occ = []
    tally = dict((symbol, 0) for symbol in SYMBOLS)
    for value in payload:
        tally[SYMBOLS[ord(value)]] += 1
        occ.append(dict(tally))

    def lf(index):
        symbol = SYMBOLS[ord(payload[index])]
        return c_table[symbol] + occ[index][symbol] - 1

    reads = []
    for start in range(n):
        if ord(payload[start]) != 0:
            continue
        reversed_chars = []
        index = start
        while True:
            index = lf(index)
            if ord(payload[index]) == 0:
                break
            reversed_chars.append(SYMBOLS[ord(payload[index])])
        reads.append("".join(reversed(reversed_chars)))
    return sorted(reads)


def rotation_sort_bwt(reads):
    rotations = []
    for read in reads:
        terminated = read + "$"
        length = len(terminated)
        for start in range(length):
            rotations.append(terminated[start:] + terminated[:start])
    rotations.sort()
    return bytes(bytearray(SYMBOLS.index(rotation[-1]) for rotation in rotations))


def interleave_bits(path, total_positions):
    payload = payload_of(path)
    bits = []
    for value in payload:
        for bit_index in range(8):
            if len(bits) < total_positions:
                bits.append((ord(value) >> bit_index) & 1)
    return bits


# --- CLI harness --------------------------------------------------------------

class CliHarness(object):
    def __init__(self, work):
        self.work = work

    def cli(self, *argv):
        from MUS import CommandLineInterface
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt"] + list(argv)
            CommandLineInterface.mainRun()
        finally:
            sys.argv = old_argv

    def build_uniform(self, target_dir, *fastqs):
        os.mkdir(target_dir)
        self.cli("pp", "-u", target_dir, *[os.path.join(FIXTURES, name) for name in fastqs])
        self.cli("cfpp", "-p", "1", "-u", target_dir)
        return target_dir

    def merge(self, out_dir, in_a, in_b, processes):
        self.cli("merge", "-p", processes, out_dir, in_a, in_b)
        return out_dir

    def inventory(self, directory):
        return dict(
            (name, (sha256_file(os.path.join(directory, name)),
                    os.path.getsize(os.path.join(directory, name))))
            for name in sorted(os.listdir(directory))
            if os.path.isfile(os.path.join(directory, name)))

    def fresh_run(self, run_id):
        """Build fresh IN_A/IN_B/CLEAN and merge with both -p 1 and -p 2."""
        root = os.path.join(self.work, run_id)
        os.mkdir(root)
        in_a = self.build_uniform(os.path.join(root, "in_a"), "uniform-a.fastq")
        in_b = self.build_uniform(os.path.join(root, "in_b"), "uniform-b.fastq")
        clean = self.build_uniform(os.path.join(root, "clean"),
                                   "uniform-a.fastq", "uniform-b.fastq")
        inputs_before = dict(
            (path, self.inventory(path)) for path in (in_a, in_b))
        merged_p1 = self.merge(os.path.join(root, "merged_p1"), in_a, in_b, "1")
        merged_p2 = self.merge(os.path.join(root, "merged_p2"), in_a, in_b, "2")
        inputs_after = dict(
            (path, self.inventory(path)) for path in (in_a, in_b))
        return {
            "in_a": in_a, "in_b": in_b, "clean": clean,
            "merged_p1": merged_p1, "merged_p2": merged_p2,
            "inputs_before": inputs_before, "inputs_after": inputs_after,
        }


class Milestone9EnvironmentTests(unittest.TestCase):
    def test_python_is_cpython_27(self):
        self.assertEqual(sys.version_info[:2], (2, 7))

    def test_cython_is_exactly_3_0_x(self):
        import Cython
        self.assertTrue(Cython.__version__.startswith("3.0."), Cython.__version__)

    def test_numpy_and_pysam_are_pinned(self):
        import numpy
        import pysam
        self.assertEqual(numpy.__version__, "1.16.6")
        self.assertEqual(pysam.__version__, "0.15.4")

    def test_genericmerge_is_the_migrated_module(self):
        import MUSCython.GenericMerge
        module = MUSCython.GenericMerge
        self.assertTrue(callable(module.mergeTwoMSBWTs))
        self.assertTrue(callable(module.interleaveTwoBwts))
        self.assertFalse(hasattr(module, "_not_implemented"))

    def test_genericmerge_pyx_diff_is_language_level_only(self):
        added, removed = unified_diff_added_removed(
            os.path.join(REPO, "MUSCython", "GenericMerge.pyx"),
            os.path.join(REPO, "packages", "msbwt-modern2",
                         "MUSCython", "GenericMerge.pyx"))
        self.assertEqual(added, ["#cython: language_level=2"])
        self.assertEqual(removed, [])

    def test_modern2_cli_diff_is_exactly_the_numprocs_fix(self):
        added, removed = unified_diff_added_removed(
            os.path.join(REPO, "MUS", "CommandLineInterface.py"),
            os.path.join(REPO, "packages", "msbwt-modern2",
                         "MUS", "CommandLineInterface.py"))
        self.assertEqual(added, ["        numProcs = 1"])
        self.assertEqual(removed, [])

    def test_frozen_cli_source_still_has_the_numprocs_bug(self):
        # frozen regression: numProcs must still be bound only inside the
        # args.numProcesses > 1 branch of the frozen merge CLI
        text = open(os.path.join(REPO, "MUS", "CommandLineInterface.py"),
                    "rb").read()
        self.assertEqual(sha256_bytes(text), FROZEN_CLI_PY)
        merge_branch = text[text.find(b"subparserID == 'merge'"):]
        self.assertNotIn(b"numProcs = 1", merge_branch.split(b"if args.numProcesses > 1")[0])
        self.assertIn(b"if args.numProcesses > 1:", merge_branch)
        self.assertIn(b"numProcs = 1", merge_branch.split(b"if args.numProcesses > 1")[1])

    def test_multistringbwt_whitelist_unchanged(self):
        added, removed = unified_diff_added_removed(
            os.path.join(REPO, "MUS", "MultiStringBWT.py"),
            os.path.join(REPO, "packages", "msbwt-modern2",
                         "MUS", "MultiStringBWT.py"))
        self.assertEqual(len(added), 7)
        self.assertEqual(len(removed), 6)

    def test_frozen_genericmerge_pyx_untouched(self):
        self.assertEqual(
            sha256_file(os.path.join(REPO, "MUSCython", "GenericMerge.pyx")),
            FROZEN_GENERICMERGE_PYX)


class FrozenCliFailureTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="modern2-py2-frozencli-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def test_frozen_merge_p1_still_raises_unboundlocalerror(self):
        # Load the FROZEN CLI source (repository root MUS/, byte-identical to
        # the committed manifest) as a module inside the MUS package so its
        # implicit-relative imports resolve against the modern2 modules.  The
        # historical defect must still reproduce: merge -p 1 raises
        # UnboundLocalError for numProcs, the output directory is created
        # empty, and the inputs are unchanged.
        frozen_cli = imp.load_source(
            "MUS.frozen_cli",
            os.path.join(REPO, "MUS", "CommandLineInterface.py"))
        root = os.path.join(self.work, "root")
        os.mkdir(root)
        harness = CliHarness(self.work)
        in_a = harness.build_uniform(os.path.join(root, "in_a"), "uniform-a.fastq")
        in_b = harness.build_uniform(os.path.join(root, "in_b"), "uniform-b.fastq")
        out = os.path.join(root, "out")
        before_a = harness.inventory(in_a)
        before_b = harness.inventory(in_b)
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt", "merge", "-p", "1", out, in_a, in_b]
            self.assertRaises(UnboundLocalError, frozen_cli.mainRun)
        finally:
            sys.argv = old_argv
        self.assertTrue(os.path.isdir(out))
        self.assertEqual(os.listdir(out), [])
        self.assertEqual(harness.inventory(in_a), before_a)
        self.assertEqual(harness.inventory(in_b), before_b)


class CanonicalMergeTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="modern2-py2-merge-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.harness = CliHarness(self.work)

    def test_fixture_hashes(self):
        for name, (digest, size) in FIXTURES_EXPECTED.items():
            path = os.path.join(FIXTURES, name)
            self.assertEqual(os.path.getsize(path), size, name)
            self.assertEqual(sha256_file(path), digest, name)

    def test_inputs_match_committed_hashes(self):
        run = self.harness.fresh_run("run-a")
        self.assertEqual(
            sha256_file(os.path.join(run["in_a"], "msbwt.npy")), INPUT_A_SHA256)
        self.assertEqual(
            sha256_file(os.path.join(run["in_b"], "msbwt.npy")), INPUT_B_SHA256)
        self.assertEqual(
            sha256_file(os.path.join(run["clean"], "msbwt.npy")),
            MERGED_PRIMARY_SHA256)
        self.assertEqual(
            sha256_bytes(payload_of(os.path.join(run["in_a"], "msbwt.npy"))),
            INPUT_A_PAYLOAD)
        self.assertEqual(
            sha256_bytes(payload_of(os.path.join(run["in_b"], "msbwt.npy"))),
            INPUT_B_PAYLOAD)

    def _assert_merged_contract(self, merged_dir):
        files = self.harness.inventory(merged_dir)
        self.assertEqual(sorted(files.keys()), ["inter0.npy", "msbwt.npy"])
        self.assertEqual(files["msbwt.npy"][0], MERGED_PRIMARY_SHA256)
        self.assertEqual(files["msbwt.npy"][1], 176)
        self.assertEqual(files["inter0.npy"][0], INTERLEAVE_SHA256)
        self.assertEqual(files["inter0.npy"][1], 135)
        data = open(os.path.join(merged_dir, "msbwt.npy"), "rb").read()
        self.assertEqual(data[:6], b"\x93NUMPY")
        header_len = ord(data[8]) + ord(data[9]) * 256
        self.assertEqual(header_len, 118)
        header = data[10:10 + header_len]
        self.assertIn(b"'descr': '|u1'", header)
        self.assertIn(b"'shape': (48L,)", header)
        payload = data[10 + header_len:]
        self.assertEqual(len(payload), 48)
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         MERGED_PAYLOAD_SHA256)

    def test_merge_p2_exact_committed_contract(self):
        run = self.harness.fresh_run("run-a")
        self._assert_merged_contract(run["merged_p2"])

    def test_merge_p1_exact_committed_contract(self):
        run = self.harness.fresh_run("run-a")
        self._assert_merged_contract(run["merged_p1"])

    def test_p1_and_p2_byte_identical(self):
        run = self.harness.fresh_run("run-a")
        for name in ("msbwt.npy", "inter0.npy"):
            p1 = open(os.path.join(run["merged_p1"], name), "rb").read()
            p2 = open(os.path.join(run["merged_p2"], name), "rb").read()
            self.assertEqual(p1, p2, name)

    def test_merged_equals_clean_whole_file(self):
        run = self.harness.fresh_run("run-a")
        merged = open(os.path.join(run["merged_p1"], "msbwt.npy"), "rb").read()
        clean = open(os.path.join(run["clean"], "msbwt.npy"), "rb").read()
        self.assertEqual(merged, clean)

    def test_deterministic_independent_runs_p1_and_p2(self):
        run_a = self.harness.fresh_run("run-a")
        run_b = self.harness.fresh_run("run-b")
        for name in ("msbwt.npy", "inter0.npy"):
            self.assertEqual(
                open(os.path.join(run_a["merged_p1"], name), "rb").read(),
                open(os.path.join(run_b["merged_p1"], name), "rb").read(),
                "p1 " + name)
            self.assertEqual(
                open(os.path.join(run_a["merged_p2"], name), "rb").read(),
                open(os.path.join(run_b["merged_p2"], name), "rb").read(),
                "p2 " + name)

    def test_input_side_effects_exactly_lazy_reader_indexes(self):
        run = self.harness.fresh_run("run-a")
        for key in ("in_a", "in_b"):
            before = run["inputs_before"][run[key]]
            after = run["inputs_after"][run[key]]
            added = set(after) - set(before)
            self.assertEqual(sorted(added), ["fmIndex.npy", "totalCounts.npy"], key)
            for name in before:
                self.assertEqual(after[name], before[name], (key, name))

    def test_reader_matches_committed_relationship_reader(self):
        relationship = read_relationship_reader()
        smoke = relationship["reader_smoke"]
        run = self.harness.fresh_run("run-a")
        copy = os.path.join(self.work, "reader-copy")
        shutil.copytree(run["merged_p1"], copy)
        from MUSCython import MultiStringBWTCython as CompiledBWT
        reader = CompiledBWT.loadBWT(copy, useMemmap=False, logger=None)
        self.assertEqual(type(reader).__module__ + "." + type(reader).__name__,
                         "MUSCython.ByteBWTCython.ByteBWT")
        self.assertEqual(reader.getTotalSize(), 48)
        self.assertEqual(int(reader.getSymbolCount(0)), 8)
        for kmer, expected in smoke["expected_queries"].items():
            self.assertEqual(int(reader.countOccurrencesOfSeq(str(kmer))),
                             int(expected), kmer)
        recovered = sorted(reader.recoverString(i)
                           for i in range(int(reader.getSymbolCount(0))))
        self.assertEqual([str(v) for v in recovered],
                         [str(v) for v in smoke["recovered_by_dollar_id"]])
        side_effects = dict(
            (name, (sha256_file(os.path.join(copy, name)),
                    os.path.getsize(os.path.join(copy, name))))
            for name in ("fmIndex.npy", "totalCounts.npy"))
        self.assertEqual(side_effects, MERGED_SIDE_EFFECTS)

    def test_derived_index_regeneration_and_interleave_classification(self):
        run = self.harness.fresh_run("run-a")
        copy = os.path.join(self.work, "classify-copy")
        shutil.copytree(run["merged_p1"], copy)
        from MUSCython import MultiStringBWTCython as CompiledBWT

        def load_and_inventory():
            reader = CompiledBWT.loadBWT(copy, useMemmap=False, logger=None)
            inventory = dict(
                (name, (sha256_file(os.path.join(copy, name)),
                        os.path.getsize(os.path.join(copy, name))))
                for name in sorted(os.listdir(copy)))
            return reader, inventory

        reader, first = load_and_inventory()
        self.assertEqual(int(reader.getSymbolCount(0)), 8)
        # derived indexes are deletable and regenerate byte-identically
        for name in ("totalCounts.npy", "fmIndex.npy"):
            os.remove(os.path.join(copy, name))
        reader2, second = load_and_inventory()
        self.assertEqual(int(reader2.getSymbolCount(0)), 8)
        self.assertEqual(second, first)
        # inter0.npy is merge provenance, NOT required by the reader
        os.remove(os.path.join(copy, "inter0.npy"))
        reader3, third = load_and_inventory()
        self.assertEqual(int(reader3.getSymbolCount(0)), 8)
        self.assertEqual(int(reader3.getTotalSize()), 48)
        self.assertNotIn("inter0.npy", third)

    def test_cli_query_count_and_dump(self):
        from MUS import CommandLineInterface
        run = self.harness.fresh_run("run-a")
        copy = os.path.join(self.work, "query-copy")
        shutil.copytree(run["merged_p1"], copy)
        import cStringIO
        old_argv = sys.argv
        old_stdout = sys.stdout
        try:
            captured = cStringIO.StringIO()
            sys.stdout = captured
            sys.argv = ["msbwt", "query", copy, "ACGTN"]
            CommandLineInterface.mainRun()
            count_text = captured.getvalue()
            captured = cStringIO.StringIO()
            sys.stdout = captured
            sys.argv = ["msbwt", "query", "-d", copy, "ACGTN"]
            CommandLineInterface.mainRun()
            dump_text = captured.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.argv = old_argv
        # the logger INFO lines precede the actual CLI output on stdout
        count_lines = count_text.splitlines()
        self.assertEqual(count_lines[-1], "3")
        dump_lines = dump_text.splitlines()
        self.assertEqual(dump_lines[-4], "3")
        dumped = sorted(line.split(",")[0] for line in dump_lines[-3:])
        self.assertEqual(dumped, ["ACGTN", "ACGTN", "ACGTN"])

    def test_symbol_counts_from_payload(self):
        run = self.harness.fresh_run("run-a")
        payload = payload_of(os.path.join(run["merged_p1"], "msbwt.npy"))
        self.assertEqual(symbol_counts(payload), SYMBOL_COUNTS_EXPECTED)

    def test_independent_py2_oracle_semantics(self):
        relationship = read_relationship_reader()
        smoke = relationship["reader_smoke"]
        run = self.harness.fresh_run("run-a")
        payload = payload_of(os.path.join(run["merged_p1"], "msbwt.npy"))
        self.assertEqual(rotation_sort_bwt(READS_MERGED), payload)
        for kmer, expected in smoke["expected_queries"].items():
            self.assertEqual(backward_count(payload, str(kmer)),
                             int(expected), kmer)
        self.assertEqual(lf_recover_reads(payload), READS_MERGED)

    def test_interleave_invariants(self):
        run = self.harness.fresh_run("run-a")
        bits = interleave_bits(
            os.path.join(run["merged_p1"], "inter0.npy"), 48)
        self.assertEqual(len(bits), 48)
        self.assertEqual(sum(1 for bit in bits if bit == 0), 24)
        self.assertEqual(sum(1 for bit in bits if bit == 1), 24)
        bits2 = interleave_bits(
            os.path.join(run["merged_p2"], "inter0.npy"), 48)
        self.assertEqual(bits, bits2)


if __name__ == "__main__":
    unittest.main()
