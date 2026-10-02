#!/usr/bin/env python
"""Architecture-checkpoint screen: 2BWT companion vs FMD index.

Builds a deterministic SYNTHETIC cohort (no real data is used or implied):
a random reference with planted repeat families, per-sample SNPs, and
reads sampled from both strands with substitution errors.  Then builds the
forward index, its reversed companion (2BWT), and an FMD index, and
reports storage, BWT runs, construction time, and bidirectional extension
cost.  Results are written as JSON.

Usage (from the repository root, compiled extensions built in place):

    PYTHONPATH=packages/msbwt-modern3 python compat/screens/fmd_vs_2bwt.py \
        --out compat/screens/results/fmd_vs_2bwt.json

Run it as a script file: Multimerge uses multiprocessing, and Python 3.14
defaults to the forkserver start method on Linux.
"""

import argparse
import hashlib
import json
import logging
import os
import platform
import random
import shutil
import sys
import tempfile
import time

import numpy as np


def make_cohort(seed, genome_length, samples, coverage, read_length,
                error_rate, snp_rate, repeat_families, repeat_copies):
    rng = random.Random(seed)
    genome = [rng.choice("ACGT") for _ in range(genome_length)]
    for _ in range(repeat_families):
        unit = [rng.choice("ACGT") for _ in range(rng.randint(150, 400))]
        for _ in range(repeat_copies):
            start = rng.randrange(0, genome_length - len(unit))
            genome[start:start + len(unit)] = unit
    genome = "".join(genome)
    complement = str.maketrans("ACGT", "TGCA")
    reads = []
    reads_per_sample = genome_length * coverage // read_length
    for _ in range(samples):
        haplotype = list(genome)
        for i in range(genome_length):
            if rng.random() < snp_rate:
                haplotype[i] = rng.choice("ACGT".replace(haplotype[i], ""))
        haplotype = "".join(haplotype)
        for _ in range(reads_per_sample):
            start = rng.randrange(0, genome_length - read_length)
            read = list(haplotype[start:start + read_length])
            for i in range(read_length):
                if rng.random() < error_rate:
                    read[i] = rng.choice("ACGT".replace(read[i], ""))
            read = "".join(read)
            if rng.random() < 0.5:
                read = read[::-1].translate(complement)
            reads.append(read)
    return reads


def runs(rows):
    rows = np.asarray(rows)
    return int(1 + np.count_nonzero(rows[1:] != rows[:-1])) if rows.size else 0


def index_stats(directory):
    rows = np.load(os.path.join(directory, "msbwt.npy"), mmap_mode="r")
    n = int(rows.shape[0])
    r = runs(rows)
    return {
        "rows": n,
        "msbwt_bytes": os.path.getsize(os.path.join(directory, "msbwt.npy")),
        "runs": r,
        "runs_per_row": r / float(n),
        "mean_run_length": n / float(r),
    }


def time_extensions(index, patterns, rng, steps):
    """Mean seconds per extend_*_all over random growth paths."""
    calls = 0
    started = time.perf_counter()
    for pattern in patterns:
        state = index.empty_pattern()
        i = j = len(pattern) // 2
        for _ in range(min(steps, len(pattern))):
            if (rng.random() < 0.5 and i > 0) or j == len(pattern):
                i -= 1
                state = index.extend_left_all(state)[pattern[i:i + 1]]
            else:
                state = index.extend_right_all(state)[pattern[j:j + 1]]
                j += 1
            calls += 1
    return (time.perf_counter() - started) / max(1, calls), calls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=20261002)
    parser.add_argument("--genome-length", type=int, default=20000)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--coverage", type=int, default=5)
    parser.add_argument("--read-length", type=int, default=100)
    parser.add_argument("--error-rate", type=float, default=0.005)
    parser.add_argument("--snp-rate", type=float, default=0.002)
    parser.add_argument("--repeat-families", type=int, default=5)
    parser.add_argument("--repeat-copies", type=int, default=6)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--work", default=None)
    args = parser.parse_args()

    from MUSCython import MultimergeCython
    from MUS import Bidirectional as bd

    logger = logging.getLogger("fmd-screen")
    work = args.work or tempfile.mkdtemp(prefix="fmd-screen-")
    os.makedirs(work, exist_ok=True)
    try:
        reads = make_cohort(
            args.seed, args.genome_length, args.samples, args.coverage,
            args.read_length, args.error_rate, args.snp_rate,
            args.repeat_families, args.repeat_copies)
        digest = hashlib.sha256("\n".join(reads).encode()).hexdigest()

        forward = os.path.join(work, "forward")
        os.makedirs(forward)
        t0 = time.perf_counter()
        MultimergeCython.createMSBWTFromSeqs(
            [r + "$" for r in reads], forward, 1, False, logger)
        t_forward = time.perf_counter() - t0

        companion = os.path.join(work, "companion")
        t0 = time.perf_counter()
        bd.build_reverse_companion(forward, companion)
        t_companion = time.perf_counter() - t0

        fmd = os.path.join(work, "fmd")
        t0 = time.perf_counter()
        bd.build_fmd_index(forward, fmd)
        t_fmd = time.perf_counter() - t0

        two = bd.BidirectionalIndex.load(forward, companion, mmap=False)
        one = bd.BidirectionalIndex.load_fmd(fmd, mmap=False)
        rng = random.Random(args.seed + 1)
        patterns = []
        for _ in range(args.queries):
            read = rng.choice(reads).encode()
            start = rng.randrange(0, len(read) - 31)
            patterns.append(read[start:start + 31])
        for pattern in patterns[:50]:
            assert two.search(pattern) is not None
            assert one.search(pattern).size >= two.search(pattern).size
        sec_two, calls_two = time_extensions(two, patterns, random.Random(7),
                                             31)
        sec_one, calls_one = time_extensions(one, patterns, random.Random(7),
                                             31)

        f_stats = index_stats(forward)
        c_stats = index_stats(companion)
        m_stats = index_stats(fmd)
        result = {
            "screen": "fmd-vs-2bwt",
            "data": "SYNTHETIC cohort; not a biological measurement",
            "parameters": vars(args),
            "reads": len(reads),
            "reads_sha256": digest,
            "forward": f_stats,
            "companion_2bwt": c_stats,
            "fmd": m_stats,
            "totals": {
                "2bwt_rows": f_stats["rows"] + c_stats["rows"],
                "2bwt_runs": f_stats["runs"] + c_stats["runs"],
                "fmd_rows": m_stats["rows"],
                "fmd_runs": m_stats["runs"],
                "fmd_plus_forward_rows": m_stats["rows"] + f_stats["rows"],
                "fmd_plus_forward_runs": m_stats["runs"] + f_stats["runs"],
            },
            "construction_seconds": {
                "forward": t_forward,
                "companion_2bwt": t_companion,
                "fmd": t_fmd,
            },
            "extension_seconds_per_call": {
                "2bwt": sec_two,
                "fmd": sec_one,
                "calls_each": calls_two,
            },
            "platform": {
                "python": sys.version.split()[0],
                "numpy": np.__version__,
                "machine": platform.machine(),
                "system": platform.system(),
            },
            "caveats": [
                "uncompressed byte BWTs; run counts are the input to any "
                "future RLBWT/move backend, not a measured compressed size",
                "single-process construction; timings from one run, warm "
                "cache, shared cloud container",
                "extension cost uses the Python prototype over the compiled "
                "FM index; both sides use the same code path",
            ],
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as fp:
            json.dump(result, fp, indent=2, sort_keys=True)
            fp.write("\n")
        print(json.dumps(result["totals"], indent=2))
    finally:
        if args.work is None:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
