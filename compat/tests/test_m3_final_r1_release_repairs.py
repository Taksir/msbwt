"""Regression tests for M3-FINAL-R1: final targeted release repairs.

Each test pins one repair made in response to the M3-FINAL-HOSTILE-
RELEASE-AUDIT and exercises the REAL CLI entry points (subprocess) so
the repaired behavior is what an installed user would see.

Repairs covered:

D1. ``MUS.CommandLineInterface`` ``query <dir> <kmer> -d`` crashed with
    ``TypeError: can't concat str to bytes`` under Python 3 because
    ``recoverString`` returns bytes.  The CLI now decodes the recovered
    sequence to ASCII text at the boundary, preserving the historical
    ``<sequence>,<dollarID>`` output contract.  Tested against Byte BWT,
    RLE BWT, a no-match query, and plain query without ``-d``.
D2. ``MUS.LCP.construct_lcp_from_bwt`` derived its O(N) temporary
    workspace parent via ``os.path.dirname(bwt_dir)``, which returns ''
    for bare relative directory names and crashed in ``os.makedirs``.
    The parent is now derived from ``os.path.abspath(bwt_dir)``.  Final
    LCP persistence (lcps.npy + lcp.json inside the input directory) is
    unchanged.  Tested with bare-relative, ./relative, nested relative,
    and absolute input paths.
D3. ``MUS.SourceRemoval.remove_sources``/``retain_sources`` used the
    same empty-dirname idiom for the output parent.  Now normalized via
    abspath as well.  Tested with bare-relative, ./relative, nested
    relative, and absolute output paths, asserting the input index
    remains byte-identical and the reduced package is correct.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

REPO_ROOT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..'))
MODERN3_DIR = os.path.join(REPO_ROOT, 'packages', 'msbwt-modern3')

_READS_BY_SOURCE = {
    'leaf0': ['ACGTACGT', 'TTTTGGGG'],
    'leaf1': ['ACGTAAGT', 'CCCCGGGG'],
}

_CLI_CODE = (
    'import sys\n'
    'sys.path.insert(0, r"%s")\n'
    'from MUS.CommandLineInterface import mainRun\n'
    'if __name__ == "__main__":\n'
    '    mainRun()\n' % MODERN3_DIR
)

_LCP_CODE = (
    'import sys\n'
    'sys.path.insert(0, r"%s")\n'
    'from tools.lcp import main\n'
    'if __name__ == "__main__":\n'
    '    main()\n' % MODERN3_DIR
)

_REMOVE_SOURCES_CODE = (
    'import sys\n'
    'sys.path.insert(0, r"%s")\n'
    'from tools.remove_sources import main\n'
    'if __name__ == "__main__":\n'
    '    main()\n' % MODERN3_DIR
)


def _run_cli(code, args, cwd):
    """Run a modern3 console-tool entry point in a subprocess."""
    return subprocess.run(
        [sys.executable, '-c', code] + list(args),
        cwd=cwd, capture_output=True)


def _sha256(path):
    with open(path, 'rb') as fp:
        return hashlib.sha256(fp.read()).hexdigest()


def _naive_count(reads, kmer):
    return sum(r.count(kmer) for r in reads)


def _build_leaf(work, name, reads):
    """Build one real (compiled-path) uniform byte-BWT leaf via pp+cfpp."""
    d = os.path.join(work, name)
    fq = os.path.join(work, name + '.fastq')
    with open(fq, 'w', newline='\n') as fp:
        for i, s in enumerate(reads):
            fp.write('@%s_%d\n%s\n+\n%s\n' % (name, i, s, 'I' * len(s)))
    p = _run_cli(_CLI_CODE, ['pp', '-u', d, fq], work)
    assert p.returncode == 0, p.stderr.decode()[-500:]
    p = _run_cli(_CLI_CODE, ['cfpp', '-p', '1', '-u', d], work)
    assert p.returncode == 0, p.stderr.decode()[-500:]
    return d


def _build_provenance_merged(work, name):
    """Real provenance-preserving merge (default holt_merge_two)."""
    from MUS.MultiSourceProvenance import load_manifest, merge_many_balanced
    leaves = [
        _build_leaf(work, sid, reads)
        for sid, reads in sorted(_READS_BY_SOURCE.items())
    ]
    output = os.path.join(work, name)
    merge_many_balanced(leaves, output)
    return load_manifest(output)


class QueryDumpSeqsTests(unittest.TestCase):
    """D1: query -d must print '<seq>,<dollarID>' lines, never crash."""

    KMER = 'ACGT'

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='m3final_d1_')
        cls.byte_dir = os.path.join(cls.work, 'OUT')
        fq = os.path.join(cls.work, 'tiny.fastq')
        all_reads = [r for reads in _READS_BY_SOURCE.values()
                     for r in reads]
        with open(fq, 'w', newline='\n') as fp:
            for i, s in enumerate(all_reads):
                fp.write('@r%d\n%s\n+\n%s\n' % (i, s, 'I' * len(s)))
        p = _run_cli(_CLI_CODE, ['cffq', cls.byte_dir, fq], cls.work)
        assert p.returncode == 0, p.stderr.decode()[-800:]
        cls.rle_dir = os.path.join(cls.work, 'OUT.rle')
        p = _run_cli(_CLI_CODE,
                     ['compress', '-p', '1', cls.byte_dir, cls.rle_dir],
                     cls.work)
        assert p.returncode == 0, p.stderr.decode()[-800:]
        cls.all_reads = all_reads

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def _assert_dump_output(self, result, index_dir):
        self.assertEqual(result.returncode, 0,
                         result.stderr.decode()[-800:])
        self.assertNotIn(b'Traceback', result.stderr)
        lines = result.stdout.decode('ascii').splitlines()
        # logger INFO lines share stdout; the count is the first purely
        # numeric line (dump lines always carry the ',' separator)
        count_line = next(l for l in lines if l.isdigit())
        # first line is the FM count, matching the no-dump contract
        expected_count = sum(
            r.count(self.KMER) for r in self.all_reads)
        self.assertEqual(int(count_line), expected_count)
        dumped = lines[lines.index(count_line) + 1:]
        recovered_seqs = set()
        dollar_ids = set()
        for line in dumped:
            seq, _, dollar_id = line.rpartition(',')
            self.assertGreater(len(seq), 0, line)
            self.assertTrue(dollar_id.isdigit(), line)
            recovered_seqs.add(seq)
            dollar_ids.add(int(dollar_id))
            self.assertNotIn('$', seq)
        # every matching read is recoverable among the dumped sequences
        for read in self.all_reads:
            if read.count(self.KMER):
                self.assertIn(read, recovered_seqs)
        # dollar identifiers are valid row indices within this index
        for d in dollar_ids:
            self.assertGreaterEqual(d, 0)
        self.assertGreaterEqual(len(dumped), 1)

    def test_query_dump_seqs_byte_bwt(self):
        result = _run_cli(_CLI_CODE,
                          ['query', 'OUT', self.KMER, '-d'], self.work)
        self._assert_dump_output(result, self.byte_dir)

    def test_query_dump_seqs_rle_bwt(self):
        result = _run_cli(_CLI_CODE,
                          ['query', 'OUT.rle', self.KMER, '-d'],
                          self.work)
        self._assert_dump_output(result, self.rle_dir)

    def test_query_dump_seqs_no_match(self):
        for index_name in ('OUT', 'OUT.rle'):
            result = _run_cli(_CLI_CODE,
                              ['query', index_name, 'CACCATCAC', '-d'],
                              self.work)
            self.assertEqual(result.returncode, 0,
                             result.stderr.decode()[-800:])
            self.assertNotIn(b'Traceback', result.stderr)
            self.assertEqual(
                [l for l in result.stdout.decode('ascii').splitlines()
                 if l.isdigit()],
                ['0'])

    def test_query_without_dump_unchanged(self):
        for index_name in ('OUT', 'OUT.rle'):
            result = _run_cli(_CLI_CODE,
                              ['query', index_name, self.KMER],
                              self.work)
            self.assertEqual(result.returncode, 0,
                             result.stderr.decode()[-800:])
            numeric = [l for l in result.stdout.decode('ascii')
                       .splitlines() if l.isdigit()]
            # plain query prints ONLY the count line
            self.assertEqual(len(numeric), 1)
            self.assertEqual(
                int(numeric[0]),
                sum(r.count(self.KMER) for r in self.all_reads))


class LCPBareRelativeInputTests(unittest.TestCase):
    """D2: msbwt-lcp construct must accept bare relative --input."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='m3final_d2_')
        cls.manifest = _build_provenance_merged(cls.work, 'MASTER')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def _fresh_copy(self, relative_name):
        destination = os.path.join(self.work, relative_name)
        if os.path.exists(destination):
            shutil.rmtree(destination)
        shutil.copytree(os.path.join(self.work, 'MASTER'), destination)
        return destination

    def _assert_construct_ok(self, relative_input, cli_cwd):
        result = _run_cli(_LCP_CODE,
                          ['construct', '--input', relative_input],
                          cli_cwd)
        self.assertEqual(result.returncode, 0,
                         result.stderr.decode()[-1500:])
        self.assertNotIn(b'Traceback', result.stderr)

        resolved = os.path.join(cli_cwd, relative_input)
        self.assertTrue(os.path.isfile(
            os.path.join(resolved, 'lcps.npy')))
        self.assertTrue(os.path.isfile(
            os.path.join(resolved, 'lcp.json')))

        # persistence layer validates after reopen
        from MUS.LCP import validate_lcp
        metadata = validate_lcp(resolved, full=True)
        self.assertEqual(metadata['format'], 'msbwt-lcp')

        # no temp-workspace residue next to (or inside) the package
        parent_entries = os.listdir(cli_cwd)
        residue = [e for e in parent_entries if '-lcp11a-' in e]
        self.assertEqual(residue, [])

    def test_construct_bare_relative_input(self):
        self._fresh_copy('PFRESH')
        self._assert_construct_ok('PFRESH', self.work)

    def test_construct_dot_relative_input(self):
        self._fresh_copy('PDOT')
        self._assert_construct_ok(os.path.join('.', 'PDOT'), self.work)

    def test_construct_nested_relative_input(self):
        nested = os.path.join('nested', 'relative')
        os.makedirs(os.path.join(self.work, nested), exist_ok=True)
        self._fresh_copy(os.path.join(nested, 'PNEST'))
        self._assert_construct_ok(
            os.path.join(nested, 'PNEST'), self.work)

    def test_construct_absolute_input(self):
        target = self._fresh_copy('PABS')
        self._assert_construct_ok(target, self.work)


class SourceRemovalBareRelativeOutputTests(unittest.TestCase):
    """D3: msbwt-remove-sources must accept bare relative --output."""

    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix='m3final_d3_')
        cls.master_manifest = _build_provenance_merged(
            cls.work, 'MASTER')
        master = os.path.join(cls.work, 'MASTER')
        cls.input_rows = int(np.load(
            os.path.join(master, 'msbwt.npy')).shape[0])
        cls.all_ids = [s['id'] for s in cls.master_manifest['sources']]
        cls.removed_id = cls.all_ids[0]
        cls.retained_ids = cls.all_ids[1:]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def _fresh_input_copy(self, relative_name):
        destination = os.path.join(self.work, relative_name)
        if os.path.exists(destination):
            shutil.rmtree(destination)
        shutil.copytree(os.path.join(self.work, 'MASTER'), destination)
        return destination

    def _input_fingerprint(self, directory):
        return (
            _sha256(os.path.join(directory, 'msbwt.npy')),
            _sha256(os.path.join(directory, 'provenance.json')),
        )

    def _assert_removal_ok(self, input_relative, output_relative,
                           cli_cwd):
        resolved_input = os.path.join(cli_cwd, input_relative)
        resolved_output = os.path.join(cli_cwd, output_relative)
        if os.path.exists(resolved_output):
            shutil.rmtree(resolved_output)
        fingerprint_before = self._input_fingerprint(resolved_input)

        result = _run_cli(
            _REMOVE_SOURCES_CODE,
            ['--input', input_relative,
             '--output', output_relative,
             '--remove', self.removed_id,
             '--drop-lcp'],
            cli_cwd)
        self.assertEqual(result.returncode, 0,
                         result.stderr.decode()[-1500:])
        self.assertNotIn(b'Traceback', result.stderr)
        self.assertTrue(os.path.isdir(resolved_output))

        # input index bytes remain untouched
        self.assertEqual(
            fingerprint_before, self._input_fingerprint(resolved_input))

        # provenance semantics: only the requested source was removed
        from MUS.MultiSourceProvenance import load_manifest
        out_manifest = load_manifest(resolved_output)
        self.assertEqual(
            [s['id'] for s in out_manifest['sources']],
            self.retained_ids)

        # reduced payload carries exactly the retained rows
        out_rows = int(np.load(
            os.path.join(resolved_output, 'msbwt.npy')).shape[0])
        per_source_rows = self.input_rows // len(self.all_ids)
        self.assertEqual(
            out_rows, per_source_rows * len(self.retained_ids))

        # resulting count semantics: retained reads only, naive oracle
        from MUS.MultiStringBWT import loadBWT
        bwt = loadBWT(resolved_output)
        retained_reads = [
            r for sid, reads in sorted(_READS_BY_SOURCE.items())
            if sid != 'leaf0'
            for r in reads
        ]
        for kmer in ('ACGT', 'GGGG', 'TTTT'):
            interval = bwt.findIndicesOfStr(kmer)
            self.assertEqual(
                int(interval[1] - interval[0]),
                _naive_count(retained_reads, kmer),
                kmer)

        # no point10 temp residue beside the output
        residue = [e for e in os.listdir(cli_cwd)
                   if '.point10-' in e]
        self.assertEqual(residue, [])

    def test_removal_bare_relative_output(self):
        self._fresh_input_copy('PFRESH')
        self._assert_removal_ok('PFRESH', 'REMOVED', self.work)

    def test_removal_dot_relative_output(self):
        self._fresh_input_copy('PDOT')
        self._assert_removal_ok(
            os.path.join('.', 'PDOT'),
            os.path.join('.', 'REMOVED'),
            self.work)

    def test_removal_nested_relative_output(self):
        nested = os.path.join('nested', 'relative')
        os.makedirs(os.path.join(self.work, nested), exist_ok=True)
        self._fresh_input_copy(os.path.join(nested, 'PNEST'))
        self._assert_removal_ok(
            os.path.join(nested, 'PNEST'),
            os.path.join(nested, 'REMOVED'),
            self.work)

    def test_removal_absolute_output(self):
        self._fresh_input_copy('PABS')
        self._assert_removal_ok(
            'PABS',
            os.path.join(self.work, 'REMOVED_ABS'),
            self.work)


if __name__ == '__main__':
    unittest.main()
