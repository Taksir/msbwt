# -*- coding: utf-8 -*-
"""Debug pp stage on native Windows (full traceback)."""
from __future__ import print_function
import os
import shutil
import sys
import tempfile
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "packages", "msbwt-modern2"))
FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")

from MUS import CommandLineInterface

work = tempfile.mkdtemp(prefix="win-dbg-")
out = os.path.join(work, "out")
os.mkdir(out)
for f in ("uniform-a.fastq", "uniform-b.fastq"):
    shutil.copy(os.path.join(FIXTURES, f), work)

sys.argv = ["msbwt", "pp", "-u", out,
            os.path.join(work, "uniform-a.fastq"),
            os.path.join(work, "uniform-b.fastq")]
try:
    CommandLineInterface.mainRun()
    print("PP OK")
except Exception:
    traceback.print_exc()
print("out dir:", os.listdir(out) if os.path.isdir(out) else "MISSING")