# -*- coding: utf-8 -*-
"""Debug the pure-Python compressBWT path on Windows."""
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

    work = tempfile.mkdtemp(prefix="win-comp-")
    out = os.path.join(work, "out")
    os.mkdir(out)
    for f in ("uniform-a.fastq", "uniform-b.fastq"):
        shutil.copy(os.path.join(FIXTURES, f), work)

    sys.argv = ["msbwt", "pp", "-u", out,
                os.path.join(work, "uniform-a.fastq"),
                os.path.join(work, "uniform-b.fastq")]
    CommandLineInterface.mainRun()
    sys.argv = ["msbwt", "cfpp", "-p", "1", "-u", out]
    CommandLineInterface.mainRun()

    comp_src = os.path.join(work, "src")
    comp_dir = os.path.join(work, "comp")
    shutil.copytree(out, comp_src)
    sys.argv = ["msbwt", "compress", comp_src, comp_dir]
    try:
        CommandLineInterface.mainRun()
        print("COMPRESS OK")
    except Exception:
        traceback.print_exc()
    print("comp dir:", sorted(os.listdir(comp_dir)) if os.path.isdir(comp_dir) else "MISSING")


if __name__ == '__main__':
    main()
