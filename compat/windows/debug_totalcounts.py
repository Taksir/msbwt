# -*- coding: utf-8 -*-
import os
import pickle
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "packages", "msbwt-modern2"))


def main():
    import numpy as np
    from MUS import CommandLineInterface

    work = tempfile.mkdtemp(prefix='tot-')
    out = os.path.join(work, 'out')
    os.mkdir(out)
    for f in ('uniform-a.fastq', 'uniform-b.fastq'):
        shutil.copy(os.path.join(REPO, 'compat', 'fixtures', 'synthetic', f), work)
    sys.argv = ['msbwt', 'pp', '-u', out,
                os.path.join(work, 'uniform-a.fastq'),
                os.path.join(work, 'uniform-b.fastq')]
    CommandLineInterface.mainRun()
    sys.argv = ['msbwt', 'cfpp', '-p', '1', '-u', out]
    CommandLineInterface.mainRun()

    # pure reader load -> creates totalCounts.p
    from MUS.MultiStringBWT import MultiStringBWT
    msbwt = MultiStringBWT()
    msbwt.loadMsbwt(out, logger=None)

    fn = os.path.join(out, 'totalCounts.p')
    print('totalCounts.p exists:', os.path.exists(fn))
    if os.path.exists(fn):
        import pickletools
        class Sink(object):
            def write(self, s):
                if 'GLOBAL' in s:
                    print('GLOBAL:', s.strip())
        pickletools.dis(open(fn, 'rb'), out=Sink())
        tc = pickle.load(open(fn, 'rb'))
        print('unpickled:', type(tc).__name__, tc.dtype, list(tc))


if __name__ == '__main__':
    main()
