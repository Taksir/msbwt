"""Stage 1 audit: FASTQ input handling in the compiled modern3 loaders.

Covers (through the real CLI, in subprocesses):
* gzip-compressed FASTQ must produce exactly the same artifacts as the plain
  file.  On Python 3 the compiled loaders opened ``.gz`` input in binary mode and
  failed with ``TypeError: a bytes-like object is required, not 'str'``.
* an input whose line count is not a multiple of 4 (a truncated final record) must
  be an error, not a silently shortened dataset.
"""

import gzip
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..'))
MODERN3_DIR = os.path.join(REPO_ROOT, 'packages', 'msbwt-modern3')


def _run_cli(args):
    """Run the msbwt CLI of the package under test in a subprocess."""
    code = ('import sys; sys.path.insert(0, r"%s"); '
            'from MUS.CommandLineInterface import mainRun; mainRun()'
            % MODERN3_DIR)
    return subprocess.run([sys.executable, '-c', code] + list(args),
                          cwd=MODERN3_DIR, capture_output=True)


def _fastq_text(reads):
    return ''.join('@read%d\n%s\n+\n%s\n' % (i, s, 'I' * len(s))
                   for i, s in enumerate(reads))


def _tree_bytes(root):
    out = {}
    for name in sorted(os.listdir(root)):
        with open(os.path.join(root, name), 'rb') as fp:
            out[name] = fp.read()
    return out


class FastqInputTestBase(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='m3s1_fastq_')
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.work, name)

    def write_plain(self, name, text):
        p = self.path(name)
        with open(p, 'w', newline='\n') as fp:
            fp.write(text)
        return p

    def write_gz(self, name, text):
        p = self.path(name)
        with gzip.open(p, 'wt', newline='\n') as fp:
            fp.write(text)
        return p


class GzipInputTests(FastqInputTestBase):
    UNIFORM = ['ACGTAC', 'GGTACA', 'TTACGA', 'ACGTAC']
    NONUNIFORM = ['ACGT', 'GGTACAT', 'TTA', 'ACGTACGTAC']

    def _pp_equal(self, reads, flags):
        plain = self.write_plain('in.fq', _fastq_text(reads))
        gz = self.write_gz('in.fq.gz', _fastq_text(reads))
        out_plain, out_gz = self.path('out_plain'), self.path('out_gz')
        for out, src in ((out_plain, plain), (out_gz, gz)):
            res = _run_cli(['pp'] + flags + [out, src])
            self.assertEqual(res.returncode, 0, res.stderr.decode(errors='replace')[-800:])
        self.assertEqual(_tree_bytes(out_plain), _tree_bytes(out_gz))

    def test_uniform_preprocess_gz_matches_plain(self):
        self._pp_equal(self.UNIFORM, ['-u'])

    def test_nonuniform_preprocess_gz_matches_plain(self):
        self._pp_equal(self.NONUNIFORM, [])

    def test_uniform_build_gz_matches_plain(self):
        plain = self.write_plain('in.fq', _fastq_text(self.UNIFORM))
        gz = self.write_gz('in.fq.gz', _fastq_text(self.UNIFORM))
        out_plain, out_gz = self.path('b_plain'), self.path('b_gz')
        for out, src in ((out_plain, plain), (out_gz, gz)):
            res = _run_cli(['cffq', '-u', out, src])
            self.assertEqual(res.returncode, 0, res.stderr.decode(errors='replace')[-800:])
        self.assertEqual(_tree_bytes(out_plain)['msbwt.npy'], _tree_bytes(out_gz)['msbwt.npy'])


class TruncatedInputTests(FastqInputTestBase):
    MESSAGE = b'Truncated FASTQ'
    READS = ['ACGTAC', 'GGTACA', 'TTACGA']

    def _truncated_texts(self):
        full = _fastq_text(self.READS)
        lines = full.splitlines(True)
        # drop 1, 2, or 3 trailing lines of the last record
        return dict(('missing%d' % k, ''.join(lines[:-k])) for k in (1, 2, 3))

    def _assert_rejected(self, flags, make_file):
        for label, text in sorted(self._truncated_texts().items()):
            with self.subTest(case=label):
                src = make_file('t_' + label, text)
                out = self.path('o_' + label + os.path.basename(src))
                res = _run_cli(['pp'] + flags + [out, src])
                self.assertNotEqual(res.returncode, 0)
                self.assertIn(self.MESSAGE, res.stderr)

    def test_uniform_preprocess_rejects_truncated_plain(self):
        self._assert_rejected(['-u'], lambda n, t: self.write_plain(n + '.fq', t))

    def test_uniform_preprocess_rejects_truncated_gz(self):
        self._assert_rejected(['-u'], lambda n, t: self.write_gz(n + '.fq.gz', t))

    def test_nonuniform_preprocess_rejects_truncated_plain(self):
        self._assert_rejected([], lambda n, t: self.write_plain(n + '.fq', t))

    def test_nonuniform_preprocess_rejects_truncated_gz(self):
        self._assert_rejected([], lambda n, t: self.write_gz(n + '.fq.gz', t))

    def test_complete_input_still_accepted(self):
        src = self.write_plain('ok.fq', _fastq_text(self.READS))
        res = _run_cli(['pp', '-u', self.path('o_ok'), src])
        self.assertEqual(res.returncode, 0, res.stderr.decode(errors='replace')[-800:])

    def test_util_fastq_iterator_yields_complete_records_then_raises(self):
        from MUS import util
        src = self.write_plain('t.fq', ''.join(_fastq_text(self.READS).splitlines(True)[:-1]))
        seen = []
        with self.assertRaises(ValueError) as ctx:
            for rec in util.fastqIterator(src):
                seen.append(rec[1])
        self.assertEqual(seen, self.READS[:2])
        self.assertIn('Truncated FASTQ', str(ctx.exception))
        # a complete file iterates without error
        ok = self.write_plain('ok.fq', _fastq_text(self.READS))
        self.assertEqual([r[1] for r in util.fastqIterator(ok)], self.READS)

    def test_pure_python_loader_rejects_truncated(self):
        from MUS import MultiStringBWT
        logger = logging.getLogger('m3s1-test')
        src = self.write_plain('t.fq', ''.join(_fastq_text(self.READS).splitlines(True)[:-1]))
        d = self.path('pure')
        os.makedirs(d)
        with self.assertRaises(ValueError) as ctx:
            MultiStringBWT.preprocessFastqs([src], d + '/seqs.npy', d + '/offsets.npy',
                                            d + '/about.npy', True, logger)
        self.assertIn('Truncated FASTQ', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
