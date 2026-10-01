"""Stage 1 audit: FASTQ input handling in the compiled modern3 loaders.

Covers (through the real CLI, in subprocesses):
* gzip-compressed FASTQ must produce exactly the same artifacts as the plain
  file.  On Python 3 the compiled loaders opened ``.gz`` input in binary mode and
  failed with ``TypeError: a bytes-like object is required, not 'str'``.
"""

import gzip
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


if __name__ == '__main__':
    unittest.main()
