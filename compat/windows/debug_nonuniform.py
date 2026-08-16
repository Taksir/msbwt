# -*- coding: utf-8 -*-
"""Debug the nonuniform cfpp path on native Windows (full traceback)."""
from __future__ import print_function
import os
import shutil
import sys
import tempfile
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "packages", "msbwt-modern2"))
FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")


def main():
    from MUS import CommandLineInterface

    work = tempfile.mkdtemp(prefix="win-nu-")
    out = os.path.join(work, "out")
    os.mkdir(out)
    shutil.copy(os.path.join(FIXTURES, "nonuniform.fastq"), work)

    sys.argv = ["msbwt", "pp", out, os.path.join(work, "nonuniform.fastq")]
    CommandLineInterface.mainRun()
    print("PP done:", sorted(os.listdir(out)))

    sys.argv = ["msbwt", "cfpp", "-p", "1", out]
    try:
        CommandLineInterface.mainRun()
        print("CFPP OK")
    except Exception:
        traceback.print_exc()
    print("out:", sorted(os.listdir(out)))


if __name__ == '__main__':
    main()