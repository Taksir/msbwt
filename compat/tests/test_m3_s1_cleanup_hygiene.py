"""Stage 1 audit: destructive cleanup and file-handle hygiene in modern3.

* ``mergeNewSeqs`` must never delete a directory that is not MSBWT build output.
* Cleanup of temporary files in ``MSBWTGen`` must not swallow ``BaseException``.
* Public iterators / helpers must release file handles on early exit or error.
"""

import ast
import gc
import os
import shutil
import tempfile
import unittest
import warnings

from MUS import MultiStringBWT, util

MODERN3_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'packages', 'msbwt-modern3'))


class ScratchDirTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='m3s1_clean_')
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _touch(self, *parts):
        p = os.path.join(self.work, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').close()
        return p

    def test_missing_path_is_fine(self):
        MultiStringBWT._clearScratchDir(os.path.join(self.work, 'nope'))

    def test_empty_and_msbwt_directories_are_removed(self):
        os.makedirs(os.path.join(self.work, 'empty'))
        self._touch('built', 'msbwt.npy')
        for name in ('empty', 'built'):
            MultiStringBWT._clearScratchDir(os.path.join(self.work, name))
            self.assertFalse(os.path.exists(os.path.join(self.work, name)))

    def test_user_data_is_never_deleted(self):
        precious = self._touch('mine', 'thesis.txt')
        with self.assertRaises(ValueError):
            MultiStringBWT._clearScratchDir(os.path.join(self.work, 'mine'))
        self.assertTrue(os.path.exists(precious))

    def test_plain_file_and_symlink_are_refused(self):
        f = self._touch('afile')
        with self.assertRaises(ValueError):
            MultiStringBWT._clearScratchDir(f)
        self.assertTrue(os.path.exists(f))
        target = os.path.join(self.work, 'target')
        os.makedirs(target)
        link = os.path.join(self.work, 'link')
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest('symlinks unavailable')
        with self.assertRaises(ValueError):
            MultiStringBWT._clearScratchDir(link)
        self.assertTrue(os.path.isdir(target))

    def test_merge_new_seqs_keeps_neighbouring_user_directory(self):
        out = os.path.join(self.work, 'merged')
        precious = self._touch('merged0', 'notes.txt')
        with self.assertRaises(ValueError):
            MultiStringBWT.mergeNewSeqs(['ACGT$', 'GGTA$', 'TTAC$'], out, 1, True, None)
        self.assertTrue(os.path.exists(precious))


class NoBareExceptTests(unittest.TestCase):
    def test_msbwtgen_has_no_bare_except(self):
        path = os.path.join(MODERN3_DIR, 'MUS', 'MSBWTGen.py')
        with open(path, 'r', encoding='utf-8') as fp:
            tree = ast.parse(fp.read())
        bare = [n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.ExceptHandler) and n.type is None]
        self.assertEqual(bare, [])


class HandleHygieneTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix='m3s1_fh_')
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)

    def _leaks(self, action):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always', ResourceWarning)
            action()
            gc.collect()
        return [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)]

    def test_abandoned_iterators_do_not_leak_handles(self):
        fa = os.path.join(self.work, 'a.fa')
        with open(fa, 'w') as fp:
            fp.write('>a\nACGT\n>b\nGG\n>c\nTT\n')
        fq = os.path.join(self.work, 'a.fq')
        with open(fq, 'w') as fp:
            fp.write('@r\nACGT\n+\nIIII\n@s\nGG\n+\nII\n')

        def abandon(it):
            g = it()
            next(g)
            del g

        self.assertEqual(self._leaks(lambda: abandon(lambda: util.fastaIterator(fa))), [])
        self.assertEqual(self._leaks(lambda: abandon(lambda: util.fastqIterator(fq))), [])

    def test_compare_profiles_closes_first_file_when_second_is_missing(self):
        p1 = os.path.join(self.work, 'p1.csv')
        with open(p1, 'w') as fp:
            fp.write('total,3\nAAA,3\n')

        def run():
            with self.assertRaises(FileNotFoundError):
                MultiStringBWT.compareKmerProfiles(p1, os.path.join(self.work, 'missing.csv'))

        self.assertEqual(self._leaks(run), [])

    def test_compare_profiles_result_unchanged(self):
        p1 = os.path.join(self.work, 'p1.csv')
        p2 = os.path.join(self.work, 'p2.csv')
        with open(p1, 'w') as fp:
            fp.write('total,4\nAAA,2\nCCC,2\n')
        with open(p2, 'w') as fp:
            fp.write('total,4\nAAA,4\n')
        one, two, total, dot = MultiStringBWT.compareKmerProfiles(p1, p2)
        self.assertAlmostEqual(one, 0.5)
        self.assertAlmostEqual(two, (0.5 ** 2 + 0.5 ** 2) ** 0.5)
        self.assertAlmostEqual(total, 1.0)
        self.assertAlmostEqual(dot, 0.5)


if __name__ == '__main__':
    unittest.main()
