# -*- coding: utf-8 -*-
"""Native Windows smoke gate for msbwt-modern2.

Stages: imports, uniform build vs committed golden hash, query, compression,
decompression, merge, nonuniform build.  Prints a summary line per stage.

IMPORTANT: on Windows, multiprocessing uses spawn, so every CLI invocation
must happen under the ``if __name__ == '__main__':`` guard (the same idiom
required by the installed ``msbwt`` script and ``python -m
MUS.CommandLineInterface``).
"""
from __future__ import print_function
import hashlib
import logging
import os
import shutil
import sys
import tempfile
import traceback

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = os.path.join(REPO, "packages", "msbwt-modern2")
FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")

sys.path.insert(0, PKG)

UNIFORM_MSBWT_SHA256 = "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"
UNIFORM_PAYLOAD_SHA256 = "75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e"
EXPECTED_QUERIES = [("ACGTN", 3), ("AAAAA", 1), ("CCCCC", 1), ("AGCTA", 0)]
NU_PAYLOAD_SHA256 = "7a97b19addd3c41a79dbd6ce5e43609766eca78a971576e1ab2b32e3df80ca03"


def sha256_file(path):
    d = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                return d.hexdigest()
            d.update(b)


def cli(*argv):
    from MUS import CommandLineInterface
    # reset the module-level logger so repeated in-process invocations do not
    # accumulate StreamHandlers (each CLI call re-registers one)
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
    except Exception as exc:
        traceback.print_exc()
        print("FAIL  %-28s %s: %s" % (name, type(exc).__name__, exc))
        return False
    print("PASS  %s" % name)
    return True


def main():
    results = {}

    def s(name, fn):
        results[name] = stage(name, fn)

    # --- imports ---------------------------------------------------------
    def imports():
        import MUS
        import MUSCython
        from MUS import CommandLineInterface
        from MUSCython import (BasicBWT, ByteBWTCython, GenericMerge,
                               MultimergeCython, RLE_BWTCython, MSBWTGenCython,
                               MSBWTCompGenCython, MultiStringBWTCython,
                               CompressToRLE, AlignmentUtil, LZW_BWTCython)
        import MUS.MultiStringBWT

    s("import MUS/MUSCython/CLI", imports)

    work = tempfile.mkdtemp(prefix="win-smoke-")
    try:
        out = os.path.join(work, "out")
        os.mkdir(out)
        for f in ("uniform-a.fastq", "uniform-b.fastq", "nonuniform.fastq"):
            shutil.copy(os.path.join(FIXTURES, f), work)

        # --- uniform construction vs golden ------------------------------
        def uniform_build():
            cli("pp", "-u", out,
                os.path.join(work, "uniform-a.fastq"),
                os.path.join(work, "uniform-b.fastq"))
            cli("cfpp", "-p", "1", "-u", out)

        s("uniform pp+cfpp", uniform_build)

        def golden_hash():
            got = sha256_file(os.path.join(out, "msbwt.npy"))
            if got != UNIFORM_MSBWT_SHA256:
                raise AssertionError(
                    "msbwt.npy sha256 %s != golden %s" % (got, UNIFORM_MSBWT_SHA256))
            data = open(os.path.join(out, "msbwt.npy"), "rb").read()
            header_len = ord(data[8]) + ord(data[9]) * 256
            payload = data[10 + header_len:]
            got_p = hashlib.sha256(payload).hexdigest()
            if got_p != UNIFORM_PAYLOAD_SHA256:
                raise AssertionError(
                    "payload sha256 %s != golden %s" % (got_p, UNIFORM_PAYLOAD_SHA256))

        s("uniform msbwt.npy == golden bytes", golden_hash)

        # --- query --------------------------------------------------------
        def queries():
            from MUSCython import MultiStringBWTCython as CompiledBWT
            msbwt = CompiledBWT.loadBWT(out, logger=None)
            if msbwt.getTotalSize() != 48:
                raise AssertionError("total size %s != 48" % msbwt.getTotalSize())
            for kmer, expected in EXPECTED_QUERIES:
                got = msbwt.countOccurrencesOfSeq(kmer)
                if got != expected:
                    raise AssertionError(
                        "query %s: got %s expected %s" % (kmer, got, expected))

        s("reader + queries (ACGTN=3 AAAAA=1 CCCCC=1 AGCTA=0)", queries)

        # --- compression (post-hoc) --------------------------------------
        comp_dir = os.path.join(work, "comp")  # dstDir must not pre-exist
        comp_src = os.path.join(work, "comp-src")
        shutil.copytree(out, comp_src)

        def compress():
            cli("compress", comp_src, comp_dir)

        s("compress", compress)

        def compressed_query():
            from MUSCython import MultiStringBWTCython as CompiledBWT
            msbwt = CompiledBWT.loadBWT(comp_dir, logger=None)
            if msbwt.getTotalSize() != 48:
                raise AssertionError(
                    "compressed total %s != 48" % msbwt.getTotalSize())
            for kmer, expected in EXPECTED_QUERIES:
                got = msbwt.countOccurrencesOfSeq(kmer)
                if got != expected:
                    raise AssertionError(
                        "compressed query %s: %s != %s" % (kmer, got, expected))

        s("compressed BWT query parity", compressed_query)

        # --- decompression ------------------------------------------------
        dec_dir = os.path.join(work, "dec")

        def decompress():
            cli("decompress", comp_dir, dec_dir)

        s("decompress", decompress)

        def decompressed_compare():
            # the modern2 decompression output contract (release-candidate.json:
            # decompress_modern2_contract) is f536d60f..., NOT the uniform
            # primary golden; decompressed msbwt.npy is a rewritten artifact.
            got = sha256_file(os.path.join(dec_dir, "msbwt.npy"))
            if got != "f536d60f356ed4a34e8253eecdd91e90db8c2ba3430c2e3d3e1855bb49007ef4":
                raise AssertionError(
                    "decompressed sha256 %s != modern2 contract f536d60f..." % got)

        s("decompressed msbwt.npy == modern2 contract", decompressed_compare)

        # --- merge ---------------------------------------------------------
        merge_out = os.path.join(work, "merge")

        def merge():
            a_out = os.path.join(work, "a")
            b_out = os.path.join(work, "b")
            for d, f in ((a_out, "uniform-a.fastq"), (b_out, "uniform-b.fastq")):
                os.mkdir(d)
                cli("pp", "-u", d, os.path.join(work, f))
                cli("cfpp", "-p", "1", "-u", d)
            cli("merge", "-p", "2", merge_out, a_out, b_out)

        s("merge -p 2 (two uniform BWTs)", merge)

        def merged_query():
            from MUSCython import MultiStringBWTCython as CompiledBWT
            msbwt = CompiledBWT.loadBWT(merge_out, logger=None)
            if msbwt.getTotalSize() != 48:
                raise AssertionError(
                    "merged total %s != 48" % msbwt.getTotalSize())
            for kmer, expected in EXPECTED_QUERIES:
                got = msbwt.countOccurrencesOfSeq(kmer)
                if got != expected:
                    raise AssertionError(
                        "merged query %s: %s != %s" % (kmer, got, expected))
            got = sha256_file(os.path.join(merge_out, "msbwt.npy"))
            if got != UNIFORM_MSBWT_SHA256:
                raise AssertionError(
                    "merged msbwt.npy sha256 %s != golden" % got)

        s("merged BWT == golden + queries", merged_query)

        # --- nonuniform ----------------------------------------------------
        nu_out = os.path.join(work, "nu")

        def nonuniform():
            cli("pp", nu_out, os.path.join(work, "nonuniform.fastq"))
            cli("cfpp", "-p", "1", nu_out)

        s("nonuniform pp+cfpp", nonuniform)

        def nonuniform_compare():
            from MUSCython import MultiStringBWTCython as CompiledBWT
            msbwt = CompiledBWT.loadBWT(nu_out, logger=None)
            if msbwt.getTotalSize() != 30:
                raise AssertionError(
                    "nonuniform total %s != 30" % msbwt.getTotalSize())
            arr = np.load(os.path.join(nu_out, "msbwt.npy"))
            got = hashlib.sha256(arr.tobytes()).hexdigest()
            if got != NU_PAYLOAD_SHA256:
                raise AssertionError(
                    "nonuniform payload sha256 %s != %s" % (got, NU_PAYLOAD_SHA256))

        s("nonuniform payload == golden payload", nonuniform_compare)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    passed = sum(1 for v in results.values() if v)
    print("SMOKE SUMMARY: %d/%d stages passed" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
