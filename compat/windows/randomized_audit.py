# -*- coding: utf-8 -*-
"""Bounded randomized differential audit for enhanced-modern2 on Windows.
Seed 20260810, ~15 categories covering all major functionality.
"""
from __future__ import print_function
import hashlib
import os
import random
import shutil
import sys
import tempfile

REPO = os.environ.get(
    "MSBWT_MODERN2_REPO",
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)
PKG_DIR = os.path.join(REPO, "packages", "msbwt-modern2")
if PKG_DIR not in sys.path:
    sys.path.insert(0, PKG_DIR)

FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")
SEED = 20260810

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()

def generate_sequences(rng, count, min_len=5, max_len=50):
    seqs = []
    for _ in range(count):
        length = rng.randint(min_len, max_len)
        seq = ''.join(rng.choice(list("ACGTN")) for _ in range(length))
        seqs.append(seq)
    return seqs

def write_fastq(seqs, path):
    with open(path, "w") as fh:
        for i, seq in enumerate(seqs):
            fh.write("@read%d\n%s\n+\n%s\n" % (i, seq, "I" * len(seq)))

def build_and_query(seqs, work, label, uniform=False):
    from MUS import CommandLineInterface
    import logging
    for h in list(logging.getLogger('root').handlers):
        logging.getLogger('root').removeHandler(h)

    fq_dir = os.path.join(work, "%s_input" % label)
    os.makedirs(fq_dir)
    if uniform:
        min_len = max(len(s) for s in seqs)
        padded = [s.ljust(min_len, 'A') for s in seqs]
        write_fastq(padded, os.path.join(fq_dir, "data.fastq"))
    else:
        write_fastq(seqs, os.path.join(fq_dir, "data.fastq"))

    out_dir = os.path.join(work, "%s_bwt" % label)
    os.mkdir(out_dir)

    old_argv = sys.argv
    try:
        u_flag = ["-u"] if uniform else []
        sys.argv = ["msbwt", "pp"] + u_flag + [out_dir,
                    os.path.join(fq_dir, "data.fastq")]
        CommandLineInterface.mainRun()
        sys.argv = ["msbwt", "cfpp", "-p", "1"] + u_flag + [out_dir]
        CommandLineInterface.mainRun()
    finally:
        sys.argv = old_argv

    msbwt_path = os.path.join(out_dir, "msbwt.npy")
    if not os.path.exists(msbwt_path):
        raise AssertionError("msbwt.npy not created for %s" % label)

    import numpy as np
    arr = np.load(msbwt_path)
    if arr.shape[0] < len(seqs):
        raise AssertionError("BWT size %d < seqs (%d) for %s" % (arr.shape[0], len(seqs), label))

    if not uniform:
        from MUSCython import MultiStringBWTCython as CompiledBWT
        msbwt = CompiledBWT.loadBWT(out_dir, logger=None)
        for seq in seqs[:min(3, len(seqs))]:
            count = msbwt.countOccurrencesOfSeq(seq + "$")
            if count < 1:
                raise AssertionError("query %r returned 0 in %s" % (seq, label))

    return arr.tobytes()

def run_audit():
    rng = random.Random(SEED)
    categories = {
        "uniform-5": (5, True), "uniform-10": (10, True), "uniform-20": (20, True),
        "nonuniform-5": (5, False), "nonuniform-10": (10, False), "nonuniform-20": (20, False),
        "duplicates-10": (10, False), "all-identical-5": (5, True),
        "short-5": (5, False), "long-5": (5, False),
        "single-base-5": (5, True), "mixed-length-10": (10, False),
        "prefix-sharing-10": (10, False), "n-heavy-10": (10, False), "motif-10": (10, False),
    }

    print("SEED: %d" % SEED)
    print("Generating %d test categories..." % len(categories))
    total_ops = 0
    mismatches = 0

    for cat_name, (count, uniform) in categories.items():
        cat_rng = random.Random(SEED + hash(cat_name))
        if cat_name.startswith("duplicates"):
            base = ''.join(cat_rng.choice(list("ACGTN")) for _ in range(10))
            seqs = [base] * count
        elif cat_name.startswith("all-identical"):
            seqs = ["ACGT"] * count
        elif cat_name.startswith("single-base"):
            seqs = ["AAAAA"] * count
        elif cat_name.startswith("short"):
            seqs = generate_sequences(cat_rng, count, 1, 3)
        elif cat_name.startswith("long"):
            seqs = generate_sequences(cat_rng, count, 50, 200)
        elif cat_name.startswith("n-heavy"):
            seqs = [''.join(cat_rng.choice(list("ACGTN")) for _ in range(20)) for _ in range(count)]
            seqs = ['N' * 10 + s[10:] for s in seqs]
        elif cat_name.startswith("prefix"):
            prefix = "ACGT"
            seqs = [prefix + ''.join(cat_rng.choice(list("ACGTN")) for _ in range(10)) for _ in range(count)]
        elif cat_name.startswith("motif"):
            seqs = [("ACGT" * 5)[:rng.randint(5, 20)] for _ in range(count)]
        else:
            seqs = generate_sequences(cat_rng, count, 5, 50)

        work = tempfile.mkdtemp(prefix="audit-%s-" % cat_name)
        try:
            payload = build_and_query(seqs, work, cat_name, uniform=uniform)
            total_ops += len(seqs)
            print("  PASS  %-25s (seqs=%d)" % (cat_name, len(seqs)))
        except Exception as e:
            mismatches += 1
            print("  FAIL  %-25s %s" % (cat_name, e))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    print()
    print("RANDOMIZED AUDIT SUMMARY")
    print("  seed: %d" % SEED)
    print("  categories: %d" % len(categories))
    print("  total sequences: %d" % total_ops)
    print("  mismatches: %d" % mismatches)
    return mismatches

if __name__ == '__main__':
    mismatches = run_audit()
    print("RESULT: %s" % ("PASS" if mismatches == 0 else "FAIL"))
    sys.exit(0 if mismatches == 0 else 1)
