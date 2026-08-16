# -*- coding: utf-8 -*-
"""Process-count invariance tests for native Windows.

Verifies that -p 1, -p 2, and -p 4 produce byte-identical artifacts
for both uniform and nonuniform builds.  Uses the synthetic fixtures
from the repository.
"""
from __future__ import print_function
import hashlib
import os
import shutil
import sys
import tempfile
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "packages", "msbwt-modern2"))
FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")

UNIFORM_MSBWT = "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"
UNIFORM_PAYLOAD = "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e"


def sha256_file(path):
    d = hashlib.sha256()
    with open(path, "rb") as fh:
        d.update(fh.read())
    return d.hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def payload_hash(path):
    with open(path, "rb") as fh:
        data = fh.read()
    hl = ord(data[8]) + ord(data[9]) * 256
    return hashlib.sha256(data[10 + hl:]).hexdigest()


def cli(*argv):
    from MUS import CommandLineInterface
    import logging
    logger = logging.getLogger('root')
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    old_argv = sys.argv
    try:
        sys.argv = ["msbwt"] + list(argv)
        CommandLineInterface.mainRun()
    finally:
        sys.argv = old_argv


def stage(name, fn):
    try:
        fn()
    except Exception:
        import traceback
        traceback.print_exc()
        print("FAIL  %-28s" % name)
        return False
    print("PASS  %s" % name)
    return True


if __name__ == '__main__':
    results = {}

    def s(name, fn):
        results[name] = stage(name, fn)

    work = tempfile.mkdtemp(prefix="win-proc-")
    try:
        # --- uniform -p 1 ---
        for p in [1, 2, 4]:
            def build_uniform(p=p):
                out = os.path.join(work, "uni-p%d" % p)
                if os.path.exists(out):
                    shutil.rmtree(out)
                os.mkdir(out)
                cli("pp", "-u", out,
                    os.path.join(FIXTURES, "uniform-a.fastq"),
                    os.path.join(FIXTURES, "uniform-b.fastq"))
                cli("cfpp", "-p", str(p), "-u", out)
            s("uniform -p %d build" % p, build_uniform)

        def check_uniform_golden():
            msbwt = os.path.join(work, "uni-p1", "msbwt.npy")
            got = sha256_file(msbwt)
            if got != UNIFORM_MSBWT:
                raise AssertionError("msbwt.npy sha256 %s != golden" % got)
            ph = payload_hash(msbwt)
            if ph != UNIFORM_PAYLOAD:
                raise AssertionError("payload sha256 %s != golden" % ph)
        s("uniform golden == dd91d69e", check_uniform_golden)

        # --- p1 == p2 == p4 byte-identical ---
        def p1_eq_p2():
            h1 = sha256_file(os.path.join(work, "uni-p1", "msbwt.npy"))
            h2 = sha256_file(os.path.join(work, "uni-p2", "msbwt.npy"))
            h4 = sha256_file(os.path.join(work, "uni-p4", "msbwt.npy"))
            if not (h1 == h2 == h4):
                raise AssertionError("p1=%s p2=%s p4=%s" % (h1, h2, h4))
        s("uniform p1==p2==p4 byte-identical", p1_eq_p2)

        # --- nonuniform -p 1 ---
        for p in [1, 2]:
            def build_nonuni(p=p):
                out = os.path.join(work, "nonuni-p%d" % p)
                if os.path.exists(out):
                    shutil.rmtree(out)
                os.mkdir(out)
                cli("pp", out, os.path.join(FIXTURES, "nonuniform.fastq"))
                cli("cfpp", "-p", str(p), out)
            s("nonuniform -p %d build" % p, build_nonuni)

        NU_PAYLOAD = "7a97b19addd3c41a79dbd6ce5e43609766eca78a971576e1ab2b32e3df80ca03"
        def nonuni_p1_eq_p2():
            h1 = sha256_file(os.path.join(work, "nonuni-p1", "msbwt.npy"))
            h2 = sha256_file(os.path.join(work, "nonuni-p2", "msbwt.npy"))
            if h1 != h2:
                raise AssertionError("p1=%s p2=%s" % (h1, h2))
            arr = __import__('numpy').load(os.path.join(work, "nonuni-p1", "msbwt.npy"))
            ph = sha256_bytes(arr.tobytes())
            if ph != NU_PAYLOAD:
                raise AssertionError("nonuni payload %s != %s" % (ph, NU_PAYLOAD))
        s("nonuniform p1==p2 + payload", nonuni_p1_eq_p2)

    finally:
        shutil.rmtree(work, ignore_errors=True)

    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print("PROCESS-COUNT SUMMARY: %d/%d stages passed" % (passed, total))
    sys.exit(0 if passed == total else 1)
