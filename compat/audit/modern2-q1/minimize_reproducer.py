#!/usr/bin/env python3
"""Deterministic failure minimizer for the modern2 quality audit Q1.

Given a failing generated case (seed, case id, family) this tool reduces
the case while retaining the failure:

1. read-count reduction (delta debugging over the read multiset),
2. read-length trimming,
3. duplicate-count reduction,

and emits a minimal FASTQ reproducer plus a recorded evidence block:

    seed, original case, minimized reads, exact command, frozen result,
    modern2 result, independent oracle result, classification.

The failure predicate is evaluated by re-running the single case through
the WSL execution trees (frozen + modern2) and comparing with the
independent oracle -- the same three-way machinery as the audit itself.

Usage:
    python3 minimize_reproducer.py --seed S --case c0123 --family FAMILY
        --work /home/.../msbwt-audit-q1 --out /path/reproducer.json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_core import (  # noqa: E402
    rotation_sort_bwt,
    semantic_signature,
)
from analyze_audit import semantic_signature_make  # noqa: E402


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--tree-frozen", required=True)
    parser.add_argument("--tree-modern2", required=True)
    parser.add_argument("--python-frozen", required=True)
    parser.add_argument("--python-modern2", required=True)
    return parser.parse_args(argv)


class CaseRunner(object):
    """Run one read collection through both trees and return the three-way
    construction verdict (the predicate used for minimization)."""

    def __init__(self, args):
        self.args = args
        self.seed = args.seed

    def run_case(self, reads, tag):
        import shutil
        work = os.path.join(self.args.work, "minimize-" + tag)
        if os.path.exists(work):
            shutil.rmtree(work)
        os.makedirs(work)
        fastq = os.path.join(work, "case.fastq")
        lines = []
        for index, read in enumerate(reads):
            lines.extend(("@r%d" % index, read, "+", "I" * len(read)))
        with open(fastq, "w") as handle:
            handle.write("\n".join(lines) + "\n")
        uniform = all(len(r) == len(reads[0]) for r in reads)
        results = {}
        for impl, tree, python in (
                ("frozen", self.args.tree_frozen, self.args.python_frozen),
                ("modern2", self.args.tree_modern2, self.args.python_modern2)):
            out = os.path.join(work, impl)
            os.makedirs(out)
            env = dict(os.environ)
            env.update({"PYTHONPATH": tree, "PYTHONNOUSERSITE": "1",
                        "PYTHONHASHSEED": "0", "TZ": "UTC"})
            pp = ["pp"] + (["-u"] if uniform else []) + [out, fastq]
            cfpp = ["cfpp", "-p", "1"] + (["-u"] if uniform else []) + [out]
            for argv, logname in ((pp, "pp.log"), (cfpp, "cfpp.log")):
                with open(os.path.join(work, logname), "w") as log:
                    proc = subprocess.run([python, "-B",
                                           os.path.join(tree, "bin", "msbwt")]
                                          + argv, cwd=tree, env=env,
                                          stdout=log, stderr=subprocess.STDOUT)
                if proc.returncode != 0:
                    results[impl] = {"exit": proc.returncode}
                    break
            else:
                primary = os.path.join(out, "msbwt.npy")
                if os.path.exists(primary):
                    from audit_core import parse_npy_v1
                    parsed = parse_npy_v1(open(primary, "rb").read())
                    results[impl] = {"payload": parsed["payload"]}
        return results, uniform

    def failing(self, reads, tag):
        """True when the three-way construction check fails."""
        results, uniform = self.run_case(reads, tag)
        f = results.get("frozen", {}).get("payload")
        m = results.get("modern2", {}).get("payload")
        if f is None or m is None:
            return False, results
        if uniform:
            oracle = rotation_sort_bwt(reads)
            return not (f == m == oracle), results
        o_sem = semantic_signature_make(reads)
        return not (semantic_signature(f, reads) == o_sem and
                    semantic_signature(m, reads) == o_sem), results


def delta_debug(reads, predicate, tag_prefix):
    """Standard delta-debugging over the read list."""
    current = list(reads)
    granularity = 2
    while len(current) >= 2:
        chunk = (len(current) + granularity - 1) // granularity
        reduced = False
        for start in range(0, len(current), chunk):
            subset = current[:start] + current[start + chunk:]
            if not subset:
                continue
            ok, _ = predicate(subset, "%s-dd" % tag_prefix)
            if ok:
                current = subset
                granularity = max(2, granularity - 1)
                reduced = True
                break
        if not reduced:
            if granularity >= len(current):
                break
            granularity = min(len(current), granularity * 2)
    return current


def main(argv):
    args = parse_args(argv)
    from audit_core import generate_corpus
    corpus = generate_corpus(args.seed, 150, 15)
    case = next(c for c in corpus["cases"] if c["id"] == args.case)
    original_reads = list(case["reads"])
    runner = CaseRunner(args)

    # 1. initial failure confirmation
    ok0, results0 = runner.failing(original_reads, "orig")
    if not ok0:
        raise SystemExit("case %s does not fail in this harness (family %s); "
                         "nothing to minimize" % (args.case, args.family))

    # 2. read-count reduction
    reduced = delta_debug(original_reads, runner.failing, args.case)

    # 3. duplicate reduction: keep one copy of each read if still failing
    dedup = []
    seen = set()
    for read in reduced:
        if read in seen:
            continue
        seen.add(read)
        dedup.append(read)
    if dedup and dedup != reduced:
        ok1, _ = runner.failing(dedup, "dedup")
        if ok1:
            reduced = dedup

    # 4. length trimming per read
    trimmed = []
    for read in reduced:
        best = read
        for cut in range(len(read), 0, -1):
            candidate = read[:cut]
            if not candidate:
                break
            trial = trimmed + [candidate] + reduced[len(trimmed) + 1:]
            ok2, _ = runner.failing(trial, "trim")
            if ok2:
                best = candidate
        trimmed.append(best)
    if trimmed != reduced:
        ok3, _ = runner.failing(trimmed, "trimmed")
        if ok3:
            reduced = trimmed

    # 5. final evidence
    ok_final, results_final = runner.failing(reduced, "final")
    uniform = all(len(r) == len(reduced[0]) for r in reduced)
    f = results_final.get("frozen", {}).get("payload")
    m = results_final.get("modern2", {}).get("payload")
    if uniform and f is not None and m is not None:
        oracle = rotation_sort_bwt(reduced)
        if f == m and m != oracle:
            classification = "B"
        elif m == oracle and f != oracle:
            classification = "C"
        elif f == oracle and m != oracle:
            classification = "D"
        else:
            classification = "E"
    else:
        classification = "E-incomplete"
    evidence = {
        "seed": args.seed,
        "original_case": args.case,
        "original_reads": original_reads,
        "minimized_reads": reduced,
        "family": args.family,
        "uniform": uniform,
        "command": ["pp" + (" -u " if uniform else " ") + "OUT case.fastq",
                    "cfpp -p 1" + (" -u " if uniform else " ") + "OUT"],
        "frozen_result": "exit=%s payload_sha=%s" % (
            results_final.get("frozen", {}).get("exit"),
            __import__("hashlib").sha256(
                f if isinstance(f, bytes) else b"").hexdigest()),
        "modern2_result": "exit=%s payload_sha=%s" % (
            results_final.get("modern2", {}).get("exit"),
            __import__("hashlib").sha256(
                m if isinstance(m, bytes) else b"").hexdigest()),
        "oracle_result": "rotation_bwt_sha=%s" % __import__("hashlib").sha256(
            rotation_sort_bwt(reduced)).hexdigest() if uniform else "semantic",
        "classification": classification,
        "minimal_fastq": "\n".join(
            "\n".join(("@r%d" % i, read, "+", "I" * len(read)))
            for i, read in enumerate(reduced)) + "\n",
    }
    with open(args.out, "w") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print("minimized %d -> %d reads, classification %s" % (
        len(original_reads), len(reduced), classification))
    print("evidence:", args.out)


if __name__ == "__main__":
    main(sys.argv[1:])
