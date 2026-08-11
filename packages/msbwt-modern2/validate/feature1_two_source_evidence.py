"""Feature-1 two-source rank evidence generator (runs inside the pinned
Python-2.7 environment; invoked by validate/feature1-two-source-rank.sh).

Executes, against REAL modern2 construction + REAL GenericMerge:

- canonical fixture integration (uniform-a + uniform-b);
- the deterministic 12-class edge corpus;
- a 50-case randomized differential suite (seed 20260811);
- per-case interleave bit verification against the independent
  rotation-sort oracle (every unambiguous bit; tied blocks by per-source
  multiplicity);
- rank-cache identity/staleness probes;
- one-search-per-query instrumentation on the real merged BWT;
- givenRange legacy-semantics preservation;
- performance/memory sanity measurements.

Any source-count mismatch is dumped in full (seed, reads, query, interval,
provenance bits, expected and observed counts) and fails the run.

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import gc
import json
import os
import random
import shutil
import sys
import tempfile
import time

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

PACKAGE = os.path.join(REPO, "packages", "msbwt-modern2")
# the in-tree package must win over any installed msbwt-modern2
sys.path.insert(0, PACKAGE)
sys.path.insert(0, os.path.join(PACKAGE, "tests"))
import test_source_index_py2 as f1  # noqa: E402

from MUS.SourceIndex import (  # noqa: E402
    TwoSourceBWT,
    TwoSourceInterleaveIndex,
)

SEED = f1.SEED
RANDOM_CASES = 50

SYMBOLS = "$ACGNT"


def provenance_bits(merged, low, high):
    """Unpack the provenance bits of a merged interval [low, high)."""
    index = merged.source_index
    return [index.source_at(position) for position in range(low, high)]


def rotation_sort_bwt(reads):
    rotations = []
    for read in reads:
        terminated = read + "$"
        length = len(terminated)
        for start in range(length):
            rotations.append(terminated[start:] + terminated[:start])
    rotations.sort()
    return bytes(bytearray(SYMBOLS.index(rotation[-1]) for rotation in rotations))


def interleave_bits(merged, total_bits):
    payload = merged.source_index.packed_bits
    bits = []
    for value in payload:
        for bit_index in range(8):
            if len(bits) < total_bits:
                bits.append((int(value) >> bit_index) & 1)
    return bits


def verify_interleave_oracle(merged, reads_a, reads_b, source_a, source_b):
    """Verify provenance bits against independent oracles.

    Order-independent checks (valid for uniform AND nonuniform inputs):

    - per-symbol joint provenance counts: rows with bit 0 and symbol c must
      equal standalone A's count of c; rows with bit 1 and symbol c must
      equal standalone B's count of c (uses the merged reader's
      ``getCharAtIndex`` and ``getSymbolCount``);
    - LF-recovered read multiset from the merged BWT must equal the union
      read multiset (the merged BWT is a valid BWT of the union);
    - total zero/one bits equal the standalone BWT lengths.

    Rotation-sort block oracle (only for uniform-route inputs, where the
    merged BWT equals the rotation-sorted union): EVERY unambiguous bit must
    match the per-rotation source prediction; tied blocks (identical reads
    shared by both sources) are verified by per-source multiplicity.
    """
    total_bits = int(merged.bwt.getTotalSize())
    bits = interleave_bits(merged, total_bits)
    bwt_len_a = sum(len(read) + 1 for read in reads_a)
    bwt_len_b = sum(len(read) + 1 for read in reads_b)

    # --- per-symbol joint provenance counts --------------------------------
    joint = {}
    for symbol_index in range(6):
        joint[symbol_index] = [0, 0]
    for position in range(total_bits):
        symbol = int(merged.bwt.getCharAtIndex(position))
        joint[symbol][bits[position]] += 1
    # rows with bit 0 and symbol c == standalone A's count of c; rows with
    # bit 1 and symbol c == standalone B's count of c
    for symbol_index in range(6):
        assert joint[symbol_index][0] == int(
            source_a.getSymbolCount(symbol_index)), (
                "joint provenance disagrees with standalone A for symbol %d"
                % symbol_index)
        assert joint[symbol_index][1] == int(
            source_b.getSymbolCount(symbol_index)), (
                "joint provenance disagrees with standalone B for symbol %d"
                % symbol_index)

    # --- LF-recovered multiset ----------------------------------------------
    recovered = lf_recover_reads(merged, total_bits)
    union = sorted(reads_a + reads_b)
    assert recovered == union, (
        "LF-recovered reads %r != union %r" % (recovered, union))

    assert bits.count(0) == bwt_len_a, (bits.count(0), bwt_len_a)
    assert bits.count(1) == bwt_len_b, (bits.count(1), bwt_len_b)

    uniform_a = all(len(read) == len(reads_a[0]) for read in reads_a)
    uniform_b = all(len(read) == len(reads_b[0]) for read in reads_b)
    report = {
        "total_rows": total_bits,
        "zeros": bits.count(0),
        "ones": bits.count(1),
        "expected_zeros": bwt_len_a,
        "expected_ones": bwt_len_b,
        "joint_provenance_consistent": True,
        "lf_recovered_multiset_matches": True,
        "rotation_sort_oracle_applicable": uniform_a and uniform_b,
    }
    if not (uniform_a and uniform_b):
        # nonuniform-route BWTs use a different-but-valid ordering; the
        # source-count invariants and the checks above are the applicable
        # oracle for them
        report["exact_bits_checked"] = 0
        report["tied_rows_multiplicity_checked"] = 0
        return report

    rotations_a = []
    for read in reads_a:
        terminated = read + "$"
        for start in range(len(terminated)):
            rotations_a.append(terminated[start:] + terminated[:start])
    rotations_b = []
    for read in reads_b:
        terminated = read + "$"
        for start in range(len(terminated)):
            rotations_b.append(terminated[start:] + terminated[:start])

    from collections import Counter
    count_a = Counter(rotations_a)
    count_b = Counter(rotations_b)

    exact_checked = 0
    tied_rows = 0
    position = 0
    for rotation in sorted(set(rotations_a) | set(rotations_b)):
        block_a = count_a[rotation]
        block_b = count_b[rotation]
        block_len = block_a + block_b
        in_a = block_a > 0
        in_b = block_b > 0
        block_bits = bits[position:position + block_len]
        if in_a and in_b:
            zeros = block_bits.count(0)
            ones = len(block_bits) - zeros
            assert zeros == block_a and ones == block_b, (
                "tied block multiplicity mismatch for %r" % rotation)
            tied_rows += block_len
        elif in_a:
            assert all(bit == 0 for bit in block_bits), (
                "unique-to-A block contains a 1 bit: %r" % rotation)
            exact_checked += block_len
        elif in_b:
            assert all(bit == 1 for bit in block_bits), (
                "unique-to-B block contains a 0 bit: %r" % rotation)
            exact_checked += block_len
        position += block_len

    assert position == total_bits
    report["exact_bits_checked"] = exact_checked
    report["tied_rows_multiplicity_checked"] = tied_rows
    return report


def lf_recover_reads(merged, total_bits):
    """Recover the read multiset from the merged BWT via LF mapping."""
    counts = [int(merged.bwt.getSymbolCount(symbol))
              for symbol in range(6)]
    c_table = [0] * 6
    running = 0
    for symbol in range(6):
        c_table[symbol] = running
        running += counts[symbol]
    occ = []
    tally = [0] * 6
    for position in range(total_bits):
        tally[int(merged.bwt.getCharAtIndex(position))] += 1
        occ.append(list(tally))

    def lf(index):
        symbol = int(merged.bwt.getCharAtIndex(index))
        return c_table[symbol] + occ[index][symbol] - 1

    reads = []
    for start in range(total_bits):
        if int(merged.bwt.getCharAtIndex(start)) != 0:
            continue
        reversed_chars = []
        index = start
        while True:
            index = lf(index)
            if int(merged.bwt.getCharAtIndex(index)) == 0:
                break
            reversed_chars.append(SYMBOLS[int(merged.bwt.getCharAtIndex(index))])
        reads.append("".join(reversed(reversed_chars)))
    return sorted(reads)


def run_queries(merged, a_bwt, b_bwt, queries, label, mismatches,
                comparisons):
    for query in queries:
        expected_a = int(a_bwt.countOccurrencesOfSeq(query))
        expected_b = int(b_bwt.countOccurrencesOfSeq(query))
        legacy = int(merged.bwt.countOccurrencesOfSeq(query))
        result = merged.countOccurrencesBySource(query)
        got_a = int(result["A"])
        got_b = int(result["B"])
        comparisons += 3
        checks = (
            ("source0", got_a, expected_a),
            ("source1", got_b, expected_b),
            ("sum_vs_merged", got_a + got_b, legacy),
        )
        for kind, got, expected in checks:
            if got != expected:
                mismatches.append({
                    "case": label,
                    "query": query,
                    "kind": kind,
                    "got": got,
                    "expected": expected,
                    "interval": result["interval"],
                    "provenance_bits": provenance_bits(
                        merged, result["interval"][0], result["interval"][1]),
                    "reads_a": reads_a_for(label, mismatches),
                    "reads_b": reads_b_for(label, mismatches),
                })
    return comparisons


# read sets are tracked through the caller-provided case context
_CASE_CONTEXT = {}


def reads_a_for(label, mismatches):
    return _CASE_CONTEXT.get(label, {}).get("reads_a")


def reads_b_for(label, mismatches):
    return _CASE_CONTEXT.get(label, {}).get("reads_b")


def run_case(harness, reads_a, reads_b, queries, label, mismatches,
             comparisons):
    _CASE_CONTEXT[label] = {"reads_a": reads_a, "reads_b": reads_b}
    a_dir = harness.build_fastq_source(label + "-a", reads_a)
    b_dir = harness.build_fastq_source(label + "-b", reads_b)
    m_dir = harness.merge(label + "-m", a_dir, b_dir)
    a_bwt = f1.load_standalone(a_dir)
    b_bwt = f1.load_standalone(b_dir)
    merged = TwoSourceBWT.load(m_dir, source_names=("A", "B"))
    comparisons = run_queries(merged, a_bwt, b_bwt, queries, label,
                              mismatches, comparisons)
    interleave = verify_interleave_oracle(merged, reads_a, reads_b, a_bwt, b_bwt)
    interleave["case"] = label
    return comparisons, interleave


def main():
    work = tempfile.mkdtemp(prefix="f1-evidence-")
    report = {"seed": SEED, "random_cases": RANDOM_CASES, "cases": []}
    mismatches = []
    comparisons = 0
    harness = f1.SourceHarness(work)
    try:
        # --- canonical fixtures -------------------------------------------
        a_dir = harness.build_fixture_source("canon-a", "uniform-a.fastq")
        b_dir = harness.build_fixture_source("canon-b", "uniform-b.fastq")
        m_dir = harness.merge("canon-m", a_dir, b_dir)
        a_bwt = f1.load_standalone(a_dir)
        b_bwt = f1.load_standalone(b_dir)
        merged = TwoSourceBWT.load(m_dir, source_names=("A", "B"))
        canonical_queries = (
            list(f1.COMMITTED_QUERIES.keys())
            + [str(q) for q in f1.CANONICAL_EXTRA_QUERIES])
        _CASE_CONTEXT["canonical"] = {
            "reads_a": f1.CANONICAL_READS_A, "reads_b": f1.CANONICAL_READS_B}
        comparisons = run_queries(merged, a_bwt, b_bwt, canonical_queries,
                                  "canonical", mismatches, comparisons)
        interleave = verify_interleave_oracle(
            merged, f1.CANONICAL_READS_A, f1.CANONICAL_READS_B,
            a_bwt, b_bwt)
        interleave["case"] = "canonical"
        report["cases"].append({
            "case": "canonical",
            "queries": len(canonical_queries),
            "interleave": interleave,
            "merged_msbwt_sha256": _sha256_file(
                os.path.join(m_dir, "msbwt.npy")),
            "merged_inter0_sha256": _sha256_file(
                os.path.join(m_dir, "inter0.npy")),
        })
        report["canonical_total_rows"] = int(merged.bwt.getTotalSize())

        # --- one-search + givenRange instrumentation on the real BWT ------
        proxy = f1.CountingProxy(merged.bwt)
        wrapper = TwoSourceBWT(proxy, merged.source_index,
                               source_names=("A", "B"))
        for query in (b"ACGTN", b"A", b"$", b"TTTTT"):
            wrapper.countOccurrencesBySource(query)
        report["one_search_probe"] = {
            "queries": 4, "findIndicesOfStr_calls": proxy.search_calls}
        assert proxy.search_calls == 4

        t_interval = tuple(
            int(v) for v in merged.bwt.findIndicesOfStr(b"T"))
        gt_direct = tuple(int(v) for v in merged.bwt.findIndicesOfStr(b"GT"))
        gt_via_range = tuple(
            int(v) for v in merged.bwt.findIndicesOfStr(
                b"G", givenRange=t_interval))
        ranged = merged.countOccurrencesBySource(b"G", givenRange=t_interval)
        report["given_range_probe"] = {
            "t_interval": t_interval,
            "gt_direct": gt_direct,
            "gt_via_range": gt_via_range,
            "feature1_interval": ranged["interval"],
            "feature1_A": ranged["A"],
            "feature1_B": ranged["B"],
        }
        assert gt_via_range == gt_direct
        assert ranged["interval"] == gt_direct
        assert ranged["A"] == 3 and ranged["B"] == 1

        # --- cache staleness probes ---------------------------------------
        cache_probe_dir = os.path.join(work, "cache-probe")
        os.mkdir(cache_probe_dir)
        import numpy as np
        cache_bits = [int(i % 3 == 0) for i in range(500)]
        np.save(os.path.join(cache_probe_dir, "inter0.npy"),
                f1.pack_little_endian_bits(cache_bits))
        np.save(os.path.join(cache_probe_dir, "msbwt.npy"),
                np.zeros(len(cache_bits), dtype=np.uint8))
        cache_index = TwoSourceInterleaveIndex.from_directory(
            cache_probe_dir, use_saved_rank=False)
        cache_index.save_rank_index(cache_probe_dir)
        del cache_index
        gc.collect()
        np.save(os.path.join(cache_probe_dir, "inter0.npy"),
                f1.pack_little_endian_bits([1 - b for b in cache_bits]))
        reloaded = TwoSourceInterleaveIndex.from_directory(
            cache_probe_dir, use_saved_rank=True)
        report["cache_same_length_replaced"] = {
            "rank1_after_replace": reloaded.rank1(500),
            "expected": sum(1 - b for b in cache_bits),
            "stale_cache_detected": reloaded.rank1(500) == sum(
                1 - b for b in cache_bits),
        }
        assert report["cache_same_length_replaced"]["stale_cache_detected"]

        # --- deterministic edge corpus ------------------------------------
        for label, reads_a, reads_b in f1.EDGE_CORPUS:
            queries = f1.build_queries(reads_a, reads_b)
            comparisons, interleave = run_case(
                harness, reads_a, reads_b, queries, label, mismatches,
                comparisons)
            report["cases"].append({
                "case": label, "queries": len(queries),
                "reads_a": reads_a, "reads_b": reads_b,
                "interleave": interleave,
            })

        # --- randomized differential suite --------------------------------
        rng = random.Random(SEED)
        for case_index in range(RANDOM_CASES):
            reads_a, reads_b = f1.make_random_case(rng)
            label = "random-%02d" % case_index
            queries = f1.build_queries(reads_a, reads_b)
            comparisons, interleave = run_case(
                harness, reads_a, reads_b, queries, label, mismatches,
                comparisons)
            report["cases"].append({
                "case": label, "queries": len(queries),
                "reads_a": reads_a, "reads_b": reads_b,
                "interleave": interleave,
            })

        # --- performance/memory sanity ------------------------------------
        perf = {}
        start = time.time()
        for _ in range(2000):
            merged.source_index.rank1(24)
        perf["canonical_rank1_us"] = round(
            (time.time() - start) * 1e6 / 2000, 2)
        start = time.time()
        for _ in range(2000):
            merged.source_index.counts(6, 9)
        perf["canonical_counts_us"] = round(
            (time.time() - start) * 1e6 / 2000, 2)
        big_bits = [int(i % 7 < 3) for i in range(1 << 20)]
        big_packed = f1.pack_little_endian_bits(big_bits)
        big_index = TwoSourceInterleaveIndex(big_packed, total_bits=1 << 20)
        start = time.time()
        for position in range(0, 1 << 20, 4096):
            big_index.rank1(position)
        perf["one_megabit_rank1_ns_per_query"] = round(
            (time.time() - start) * 1e9 / 256, 2)
        perf["rank_prefix_bytes_for_1Mbits"] = int(
            big_index.rank_prefix.nbytes)
        report["performance"] = perf
    finally:
        shutil.rmtree(work, ignore_errors=True)

    report["source_pairs"] = len(report["cases"])
    report["query_comparisons"] = comparisons
    report["total_queries"] = sum(case["queries"] for case in report["cases"])
    report["randomized_source_pairs"] = RANDOM_CASES
    report["edge_source_pairs"] = len(f1.EDGE_CORPUS)
    report["mismatch_count"] = len(mismatches)
    if mismatches:
        with open("/tmp/feature1-mismatches.json", "w") as handle:
            json.dump(mismatches, handle, indent=2, sort_keys=True)
        raise SystemExit(
            "FEATURE-1 MISMATCHES: %d (dumped to /tmp/feature1-mismatches.json)"
            % len(mismatches))
    payload = json.dumps(report, indent=2, sort_keys=True)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as handle:
            handle.write(payload + "\n")
    else:
        print(payload)
    print("FEATURE-1 EVIDENCE OK: %d source pairs, %d comparisons, "
          "0 mismatches" % (report["source_pairs"],
                            report["query_comparisons"]))


def _sha256_file(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
