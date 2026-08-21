"""Regression tests for M3-5: readers, compression and core persistence parity.

Each test pins one repair made during M3-5 on native Windows against the
NumPy 2.x / Cython 3str reference environment, and exercises the real
compiled modern3 implementation through the CLI (subprocess) so that
multiprocessing spawn semantics are included.

Repairs covered:
1. MultiStringBWTCython preprocessing used the NumPy-1-only dtype alias
   ``'a'+str(n)`` for the bytes dtype; NumPy 2 removed the alias so every
   uniform FASTQ preprocess failed with "data type 'a2' not understood".
   Now spelled ``'S'+str(n)`` (identical dtype object under both).
2. mergeSubSorts wrote the merged sequence payload to a TEXT-mode file;
   Python 3 rejects writing numpy.bytes_ to a text file. Now binary 'wb+'.
3. CompressToRLE / MSBWTCompGenCython / RLE_BWTCython passed Cython-3str
   str values straight into libc fopen(); runtime TypeError. Now .encode().
4. CompressToRLE handcrafted NPY header tail literal produced a malformed
   header ``'shape': (1),), }``; corrected to ``b',), }'``.
5. MSBWTCompGenCython relied on np.memmap raising 'cannot mmap an empty
   file'; NumPy 2 instead succeeds AND grows the empty state file by one
   0x00 byte. Size checks now detect empty state files first.
6. CompressToRLE buffer used ``<bytes>('' * n)`` which under Cython 3str
   silently type-puns a unicode object; now a b'' literal.
"""

import hashlib
import os
import shutil
import random
import subprocess
import sys
import tempfile
import unittest

import numpy as np

REPO_ROOT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..'))
MODERN3_DIR = os.path.join(REPO_ROOT, 'packages', 'msbwt-modern3')
GOLDEN_ROOT = os.path.join(REPO_ROOT, 'compat', 'goldens', 'original-0.3.0')

_NUM_TO_CHAR = '$ACGNT'
_CHAR_TO_NUM = {c: i for i, c in enumerate(_NUM_TO_CHAR)}


def _run_cli(args):
    """Run the msbwt CLI of the package under test in a subprocess."""
    code = ('import sys; sys.path.insert(0, r"%s"); '
            'from MUS.CommandLineInterface import mainRun; mainRun()'
            % MODERN3_DIR)
    return subprocess.run([sys.executable, '-c', code] + list(args),
                          cwd=MODERN3_DIR, capture_output=True)


def _write_fastq(path, reads):
    with open(path, 'w', newline='\n') as fp:
        for i, s in enumerate(reads):
            fp.write('@read%d\n%s\n+\n%s\n' % (i, s, 'I' * len(s)))


def _naive_bwt_codes(reads):
    """Independent oracle: per-read cyclic-rotation BWT as symbol codes.

    The MSBWT sorts the cyclic rotations of EACH read ('$'-terminated);
    rotations never cross read boundaries, so the oracle builds all
    per-read rotations, sorts them globally, and takes the final column.
    """
    rots = []
    for r in reads:
        s = r + '$'
        for i in range(len(s)):
            rots.append(s[i:] + s[:i])
    rots.sort()
    return [_CHAR_TO_NUM[x[-1]] for x in rots]


def _decode_rle(payload):
    out = bytearray()
    prev, mult = None, 1
    for b in payload:
        sym, cnt = b & 7, b >> 3
        if sym == prev:
            mult *= 32
        else:
            mult = 1
        prev = sym
        out.extend([sym] * (cnt * mult))
    return bytes(out)


class M35ParityTestBase(unittest.TestCase):

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='m35_parity_')

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def _fresh(self, name):
        """Return a fresh (nonexistent) path: CLI validators require this."""
        d = os.path.join(self.work, name)
        if os.path.exists(d):
            shutil.rmtree(d)
        return d


class TestUniformPreprocessRawBuild(M35ParityTestBase):
    """Repairs 1+2: pp/cfpp must work on NumPy 2 (dtype 'S') end to end."""

    def test_raw_build_matches_naive_bwt(self):
        rng = random.Random(20260821)
        reads = [''.join(rng.choice('ACGT') for _ in range(12))
                 for _ in range(8)]
        fq = os.path.join(self.work, 'reads.fastq')
        _write_fastq(fq, reads)
        d = self._fresh('raw')

        p = _run_cli(['pp', '-u', d, fq])
        self.assertEqual(p.returncode, 0, p.stderr.decode()[-500:])
        p = _run_cli(['cfpp', '-p', '1', '-u', d])
        self.assertEqual(p.returncode, 0, p.stderr.decode()[-500:])

        descr, shape, _, data, _ = self._read_npy(
            os.path.join(d, 'msbwt.npy'))
        self.assertEqual(descr, '|u1')
        expected = _naive_bwt_codes(reads)
        self.assertEqual(list(data), expected)

    @staticmethod
    def _read_npy(path):
        import struct
        with open(path, 'rb') as fp:
            assert fp.read(6) == b'\x93NUMPY'
            ver = fp.read(2)
            hlen = struct.unpack('<H', fp.read(2))[0] if ver[0] == 1 \
                else struct.unpack('<I', fp.read(4))[0]
            import ast
            hdr = fp.read(hlen).decode('latin1')
            d = ast.literal_eval(hdr.strip())
            return d['descr'], d['shape'], d['fortran_order'], fp.read(), hdr


class TestDirectRLEBuild(M35ParityTestBase):
    """Repair 5: RLE direct build must tolerate empty per-symbol groups."""

    def test_missing_symbol_groups_build_and_decode(self):
        # Only $, A, T groups have content; C/G/N state files stay empty,
        # which previously crashed the final join via math.log(0).
        reads = ['AAAAAAAA'] * 3 + ['TTTTTTTT']
        fq = os.path.join(self.work, 'reads.fastq')
        _write_fastq(fq, reads)
        d_pp = self._fresh('pp')
        p = _run_cli(['pp', '-u', d_pp, fq])
        self.assertEqual(p.returncode, 0, p.stderr.decode()[-500:])

        d_rle = self._fresh('rle')
        shutil.copytree(d_pp, d_rle)
        p = _run_cli(['cfpp', '-p', '1', '-u', '-c', d_rle])
        self.assertEqual(p.returncode, 0, p.stderr.decode()[-800:])

        comp = np.load(os.path.join(d_rle, 'comp_msbwt.npy'))
        raw = np.array(_naive_bwt_codes(reads), dtype=np.uint8)
        self.assertEqual(list(_decode_rle(comp)), list(raw))

    def test_decompress_roundtrip_restores_payload(self):
        reads = ['ACGTACGT'] * 2 + ['TTTTGGGG']
        fq = os.path.join(self.work, 'reads.fastq')
        _write_fastq(fq, reads)
        d_pp = self._fresh('pp')
        _run_cli(['pp', '-u', d_pp, fq])
        d_rle = self._fresh('rle')
        shutil.copytree(d_pp, d_rle)
        _run_cli(['cfpp', '-p', '1', '-u', '-c', d_rle])
        d_dec = self._fresh('dec')
        p = _run_cli(['decompress', '-p', '1', d_rle, d_dec])
        self.assertEqual(p.returncode, 0, p.stderr.decode()[-500:])
        a = np.load(os.path.join(d_rle, 'comp_msbwt.npy'))
        dec = _decode_rle(a)
        b = np.load(os.path.join(d_dec, 'msbwt.npy'))
        self.assertEqual(list(dec), list(b))


class TestConvert(M35ParityTestBase):
    """Repairs 3+4+6: convert output must be valid NPY and byte-exact."""

    GOLDEN_INPUT = os.path.join(
        GOLDEN_ROOT, 'convert-milestone10', 'inputs', 'uniform.txt')
    GOLDEN_ARTIFACT = os.path.join(
        GOLDEN_ROOT, 'convert-milestone10', 'uniform',
        'secondary-regenerated-source', 'artifacts', 'comp_msbwt.npy')

    def test_convert_matches_oracle_golden_bytes(self):
        out = self._fresh('golden_convert')
        p = _run_cli(['convert', '-i', self.GOLDEN_INPUT, out])
        self.assertEqual(p.returncode, 0, p.stderr.decode()[-500:])
        got = open(os.path.join(out, 'comp_msbwt.npy'), 'rb').read()
        want = open(self.GOLDEN_ARTIFACT, 'rb').read()
        self.assertEqual(hashlib.sha256(got).hexdigest(),
                         hashlib.sha256(want).hexdigest())

    def test_convert_output_is_loadable_npy(self):
        txt = os.path.join(self.work, 'tiny.txt')
        with open(txt, 'wb') as fp:
            fp.write(b'TTTTTTTTT$\n')
        out = self._fresh('tiny_convert')
        p = _run_cli(['convert', '-i', txt, out])
        self.assertEqual(p.returncode, 0, p.stderr.decode()[-2000:])
        arr = np.load(os.path.join(out, 'comp_msbwt.npy'))  # must parse
        self.assertEqual(arr.dtype.descr[0][0], '')
        decoded = _decode_rule_free(arr)
        self.assertEqual(decoded.decode('ascii'), 'TTTTTTTTT$')


def _decode_rule_free(payload):
    """Decode an RLE uint8 payload into ASCII symbol bytes."""
    out = bytearray()
    prev, mult = None, 1
    for b in payload:
        sym, cnt = int(b) & 7, int(b) >> 3
        if sym == prev:
            mult *= 32
        else:
            mult = 1
        prev = sym
        out.extend([ord(_NUM_TO_CHAR[sym])] * (cnt * mult))
    return bytes(out)


class TestSourceGuards(unittest.TestCase):
    """Cheap source-level guards pinning the exact repairs."""

    def test_no_numpy1_only_bytes_dtype_alias(self):
        src_path = os.path.join(MODERN3_DIR, 'MUSCython',
                                'MultiStringBWTCython.pyx')
        with open(src_path, 'r') as fp:
            src = fp.read()
        self.assertNotIn("'a'+str(", src)
        self.assertIn("'S'+str(", src)

    def test_compress_to_rle_buffer_literal_is_bytes(self):
        src_path = os.path.join(MODERN3_DIR, 'MUSCython',
                                'CompressToRLE.pyx')
        with open(src_path, 'r') as fp:
            src = fp.read()
        self.assertIn("b'\\x00' * BUFFER_SIZE", src)
        self.assertNotIn("<bytes>(", src)


if __name__ == '__main__':
    unittest.main()
