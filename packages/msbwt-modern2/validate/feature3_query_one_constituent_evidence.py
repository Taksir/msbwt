#!/usr/bin/env python2
"""msbwt-modern2 Feature 3 evidence generator: query one constituent inside
a multi-merged MSBWT.

Runs inside the pinned Python-2.7 environment (CPython 2.7.18 / NumPy
1.16.6).  Exercises:

- the ten-source read-derived fixture with an independent suffix-order
  oracle: >=350 patterns x 10 sources, exact standalone interval identity;
- the independent naive interval-projection oracle (direct bit-array
  counting through ``unpack_interleave``);
- one merged FM search per constituent query and lazy rank-node loading;
- rank-cache round trip and reload, plus hardening probes (same-length
  replaced interleave, corrupt cache, wrong stride, legacy cache without
  identity fields);
- REAL modern2 integration: canonical uniform-a + uniform-b merge, real
  5-source balanced merge, real 4-source unbalanced chain, givenRange
  delegation, one-search instrumentation on the real BWT;
- deterministic randomized Level-3 differential (seed 20260811);
- storage/performance sanity measurements.

Any mismatch raises AssertionError with the full reproducer; the driver
script records the JSON only after every gate passes.

This file must remain valid Python 2.7 (no f-strings, no annotations).
"""

from __future__ import print_function

import itertools
import json
import os
import random
import shutil
import sys
import tempfile
import time

import numpy as np

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

PACKAGE = os.path.join(REPO, "packages", "msbwt-modern2")
# the in-tree package must win over any installed msbwt-modern2
sys.path.insert(0, PACKAGE)
sys.path.insert(0, os.path.join(PACKAGE, "tests"))
import test_source_index_py2 as f1  # noqa: E402

from MUS.MultiSourceProvenance import (  # noqa: E402
    initialize_leaf_provenance,
    load_manifest,
    merge_many_balanced,
    merge_two_with_provenance,
    unpack_interleave,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryError,
    MultiSourceQueryIndex,
)

FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")
SEED = 20260811

ROWS_FILENAME = "naive_suffix_rows.json"
ALPHABET_CODE = {"$": 0, "A": 1, "C": 2, "G": 3, "N": 4, "T": 5}

TEN_SOURCE_READS = {
    "sample00": ["ACGTAC", "GATTACA", "AAAA"],
    "sample01": ["ACGTTC", "CCCC", "TACGTA"],
    "sample02": ["GGGG", "ACACAC", "TTAC"],
    "sample03": ["TGCATG", "CATCAT", "AGGG"],
    "sample04": ["AAAAAC", "CGCG", "GTGTGT"],
    "sample05": ["TTTT", "GCGTAC", "AACCAA"],
    "sample06": ["CAGTCA", "AGAGAG", "CTTT"],
    "sample07": ["GTACGT", "CCGGA", "ATATAT"],
    "sample08": ["NACGT", "ACNGT", "GGNCC"],
    "sample09": ["TTAACC", "CGTACG", "AAGGTT"],
}


def _terminated_suffix_rows(reads):
    rows = []
    for read_id, read in enumerate(reads):
        text = read + "$"
        for pos in range(len(text)):
            rows.append({
                "suffix": text[pos:],
                "bwt": text[pos - 1] if pos > 0 else "$",
                "read_id": read_id,
                "pos": pos,
            })
    rows.sort(key=lambda row: (row["suffix"], row["read_id"], row["pos"]))
    return rows


def _save_rows(directory, rows):
    with open(os.path.join(directory, ROWS_FILENAME), "w") as fp:
        json.dump(rows, fp, separators=(",", ":"))


def _load_rows(directory):
    with open(os.path.join(directory, ROWS_FILENAME), "r") as fp:
        return json.load(fp)


def make_read_derived_leaf(work, source_name, reads):
    directory = os.path.join(work, source_name)
    os.mkdir(directory)
    rows = _terminated_suffix_rows(reads)
    np.save(os.path.join(directory, "msbwt.npy"),
            np.asarray([ALPHABET_CODE[row["bwt"]] for row in rows],
                       dtype=np.uint8))
    _save_rows(directory, rows)
    initialize_leaf_provenance(directory, source_id=source_name,
                               source_name=source_name)
    return directory


def stable_suffix_merge(left_rows, right_rows):
    merged = []
    bits = []
    li = 0
    ri = 0
    while li < len(left_rows) or ri < len(right_rows):
        if ri >= len(right_rows):
            choose_right = False
        elif li >= len(left_rows):
            choose_right = True
        else:
            choose_right = right_rows[ri]["suffix"] < left_rows[li]["suffix"]
        if choose_right:
            merged.append(right_rows[ri])
            bits.append(1)
            ri += 1
        else:
            merged.append(left_rows[li])
            bits.append(0)
            li += 1
    return merged, bits


def read_derived_merge(left_dir, right_dir, output_dir, num_procs=1,
                       logger=None):
    merged_rows, bits = stable_suffix_merge(_load_rows(left_dir),
                                            _load_rows(right_dir))
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    np.save(os.path.join(output_dir, "msbwt.npy"),
            np.asarray([ALPHABET_CODE[row["bwt"]] for row in merged_rows],
                       dtype=np.uint8))
    np.save(os.path.join(output_dir, "inter0.npy"),
            f1.pack_little_endian_bits(bits))
    _save_rows(output_dir, merged_rows)


class NaiveSuffixBWT(object):
    """Independent tiny exact-search oracle over sorted suffix rows."""

    def __init__(self, directory):
        self.rows = _load_rows(directory)
        self.suffixes = [row["suffix"] for row in self.rows]
        self.search_calls = 0

    def getTotalSize(self):
        return len(self.rows)

    def findIndicesOfStr(self, seq, givenRange=None):
        self.search_calls += 1
        if isinstance(seq, bytes):
            pattern = seq.decode("ascii")
        else:
            pattern = str(seq)
        if givenRange is not None:
            raise NotImplementedError("naive fixture has no givenRange")
        return self._bisect(pattern), self._bisect(pattern + "\x7f")

    def _bisect(self, pattern):
        lo = 0
        hi = len(self.suffixes)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.suffixes[mid] < pattern:
                lo = mid + 1
            else:
                hi = mid
        return lo


def node_has_source(node, source_id):
    if node["type"] == "leaf":
        return node["source_id"] == source_id
    return node_has_source(node["left"], source_id) or node_has_source(
        node["right"], source_id)


def naive_project_interval(merged_dir, manifest, source_id, start, end):
    """Independent interval projection by direct bit-array counting."""
    node = manifest["root"]
    l = int(start)
    r = int(end)
    while node["type"] == "merge":
        bits = unpack_interleave(
            os.path.join(merged_dir, str(node["interleave"])),
            node["length"])
        if node_has_source(node["left"], source_id):
            selected = bits == 0
            node = node["left"]
        else:
            selected = bits == 1
            node = node["right"]
        l = int(np.count_nonzero(selected[:l]))
        r = int(np.count_nonzero(selected[:r]))
    return (l, r)


def max_depth(node):
    if node["type"] == "leaf":
        return 0
    return 1 + max(max_depth(node["left"]), max_depth(node["right"]))


def all_test_patterns():
    patterns = set()
    for reads in TEN_SOURCE_READS.values():
        for read in reads:
            for start in range(len(read)):
                for length in range(1, min(5, len(read) - start) + 1):
                    patterns.add(read[start:start + length])
    for length in range(1, 5):
        for chars in itertools.product("ACGT", repeat=length):
            patterns.add("".join(chars))
    patterns.update(["N", "NA", "ACN", "NG", "NN", "NNNN"])
    patterns.update(["$", "A$", "T$", "N$", "C$", "G$"])
    return sorted(patterns)


def build_fixture(work, source_reads, name="merged10"):
    leaves = []
    standalone = {}
    for source_name, reads in source_reads.items():
        leaf = make_read_derived_leaf(work, source_name, reads)
        leaves.append(leaf)
        standalone[source_name] = NaiveSuffixBWT(leaf)
    output = os.path.join(work, name)
    work_dir = os.path.join(work, name + "_work")
    manifest = merge_many_balanced(
        leaves, output, merge_two_func=read_derived_merge,
        work_dir=work_dir, keep_work=True)
    merged = NaiveSuffixBWT(output)
    return output, manifest, merged, standalone


def holt_merge_two_local(left_dir, right_dir, output_dir, num_procs=1,
                         logger=None):
    from MUS.MultiSourceProvenance import holt_merge_two
    return holt_merge_two(left_dir, right_dir, output_dir,
                          num_procs=num_procs, logger=logger)


class Harness(object):
    """In-process CLI harness building real modern2 MSBWTs and merges."""

    def __init__(self, work):
        self.work = work

    def cli(self, *argv):
        from MUS import CommandLineInterface
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt"] + list(argv)
            CommandLineInterface.mainRun()
        finally:
            sys.argv = old_argv

    def build_fastq_source(self, name, reads):
        fastq = os.path.join(self.work, name + ".fastq")
        with open(fastq, "w") as handle:
            for index, read in enumerate(reads):
                handle.write("@read%d\n" % index)
                handle.write(read + "\n")
                handle.write("+\n")
                handle.write("I" * len(read) + "\n")
        out = os.path.join(self.work, name)
        os.mkdir(out)
        uniform = all(len(read) == len(reads[0]) for read in reads)
        if uniform:
            self.cli("pp", "-u", out, fastq)
            self.cli("cfpp", "-p", "1", "-u", out)
        else:
            self.cli("pp", out, fastq)
            self.cli("cfpp", "-p", "1", out)
        return out

    def build_fixture_source(self, name, fixture_name):
        out = os.path.join(self.work, name)
        os.mkdir(out)
        self.cli("pp", "-u", out, os.path.join(FIXTURES, fixture_name))
        self.cli("cfpp", "-p", "1", "-u", out)
        return out

    def merge(self, name, in_a, in_b):
        out = os.path.join(self.work, name)
        self.cli("merge", "-p", "1", out, in_a, in_b)
        return out


def run_evidence(out_path):
    report = {
        "seed": SEED,
        "mismatch_count": 0,
        "oracles": [
            "standalone_bwt",
            "naive_project_interval",
        ],
        "ten_source_fixture": {},
        "cache_hardening_probes": {},
        "real_integration": {},
        "randomized": {},
        "performance": {},
        "notes": [
            "read-derived fixtures are tiny deterministic corpora, not "
            "compiled Holt/McMillan replacements; real merges use the "
            "compiled GenericMerge through the Feature-2 adapter.",
        ],
    }

    work = tempfile.mkdtemp(prefix="f3-evidence-")
    try:
        harness = Harness(work)

        # ---------------- ten-source read-derived fixture ----------------
        leaves = []
        standalone = {}
        for source_name, reads in TEN_SOURCE_READS.items():
            leaf = make_read_derived_leaf(work, source_name, reads)
            leaves.append(leaf)
            standalone[source_name] = NaiveSuffixBWT(leaf)
        output = os.path.join(work, "merged10")
        work_dir = os.path.join(work, "work10")
        manifest = merge_many_balanced(
            leaves, output, merge_two_func=read_derived_merge,
            work_dir=work_dir, keep_work=True)
        merged = NaiveSuffixBWT(output)
        index = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False, use_saved_rank=False)
        wrapped = MultiSourceBWT(merged, index)

        ten = report["ten_source_fixture"]
        ten["source_count"] = len(standalone)
        ten["depth"] = max_depth(manifest["root"])
        assert len(standalone) == 10
        assert ten["depth"] <= 4

        patterns = all_test_patterns()
        ten["patterns"] = len(patterns)
        assert ten["patterns"] >= 350

        interval_comparisons = 0
        naive_comparisons = 0
        mismatches = []
        for pattern in patterns:
            merged_interval = merged.findIndicesOfStr(pattern)
            for source_name, oracle in standalone.items():
                expected = oracle.findIndicesOfStr(pattern)
                actual = index.project_interval(
                    source_name, merged_interval[0], merged_interval[1])
                interval_comparisons += 1
                if actual != expected:
                    mismatches.append(
                        (pattern, source_name, merged_interval, expected,
                         actual))
                naive = naive_project_interval(
                    output, manifest, source_name, merged_interval[0],
                    merged_interval[1])
                naive_comparisons += 1
                if naive != expected:
                    mismatches.append(
                        ("naive", pattern, source_name, naive, expected))
        ten["interval_comparisons"] = interval_comparisons
        ten["naive_comparisons"] = naive_comparisons
        ten["mismatches"] = len(mismatches)
        assert interval_comparisons >= 3500
        assert mismatches == []

        # rich query fields + one search per query
        before = merged.search_calls
        rich = wrapped.querySource("ACGT", "sample07")
        assert merged.search_calls == before + 1
        expected = standalone["sample07"].findIndicesOfStr("ACGT")
        assert rich["source_interval"] == expected
        assert rich["count"] == expected[1] - expected[0]
        assert rich["present"] == (rich["count"] > 0)
        assert rich["merged_count"] == (
            rich["merged_interval"][1] - rich["merged_interval"][0])
        assert rich["path_depth"] == len(index.source_path("sample07"))
        ten["one_search_probe"] = True
        ten["rich_query_probe"] = True

        # lazy loading
        fresh = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False, use_saved_rank=False)
        assert fresh.loaded_rank_node_count == 0
        source = "sample09"
        depth = len(fresh.source_path(source))
        fresh.project_interval(source,
                               *merged.findIndicesOfStr("CGT"))
        assert fresh.loaded_rank_node_count == depth
        assert fresh.loaded_rank_node_count < 9
        ten["lazy_loading_probe"] = True

        # rank cache round trip + reload
        cached = MultiSourceQueryIndex(
            output, rank_stride_bytes=2, mmap=False, use_saved_rank=False)
        interval = merged.findIndicesOfStr("AC")
        expected_cached = cached.project_interval("sample04", *interval)
        cached.save_loaded_rank_indexes()
        reloaded = MultiSourceQueryIndex(
            output, rank_stride_bytes=2, mmap=False, use_saved_rank=True)
        assert reloaded.project_interval("sample04", *interval) == (
            expected_cached)
        ten["rank_cache_round_trip"] = True

        # --------------- cache hardening probes (derived data) ------------
        probes = report["cache_hardening_probes"]

        # same-length replaced interleave at an internal node with a valid
        # updated manifest: the stale cache must not be reused
        work2 = os.path.join(work, "hardening")
        os.mkdir(work2)
        reads_eq = {"s0": ["ACGTAC"], "s1": ["ACGTAC"],
                    "s2": ["ACGTAC"], "s3": ["ACGTAC"]}
        h_output, h_manifest, h_merged, _ = build_fixture(
            work2, reads_eq, name="equal4")
        h_index = MultiSourceQueryIndex(
            h_output, rank_stride_bytes=1, mmap=False, use_saved_rank=False)
        probe_patterns = ("A", "C", "G", "T", "AC", "CG", "GT", "AA",
                          "ACGT", "ACGTAC")
        h_old = {}
        h_intervals = {}
        for pattern in probe_patterns:
            interval = h_merged.findIndicesOfStr(pattern)
            h_intervals[pattern] = interval
            for sid in ("s0", "s3"):
                h_old[(pattern, sid)] = h_index.project_interval(
                    sid, *interval)
        h_index.save_loaded_rank_indexes()
        node = h_manifest["root"]
        inter_path = os.path.join(h_output, str(node["interleave"]))
        bits = list(unpack_interleave(inter_path, node["length"]))
        rng = random.Random(20260811)
        rng.shuffle(bits)
        replaced = f1.pack_little_endian_bits(bits)
        np.save(inter_path, replaced)
        new_manifest = json.loads(json.dumps(h_manifest))
        new_manifest["root"]["interleave_sha256"] = _array_sha256_hex(
            replaced)
        with open(os.path.join(h_output, "provenance.json"), "w") as fp:
            json.dump(new_manifest, fp, indent=2, sort_keys=True)
            fp.write("\n")
        load_manifest(h_output)
        h_reloaded = MultiSourceQueryIndex(
            h_output, rank_stride_bytes=1, mmap=False, use_saved_rank=True)
        detected = False
        for pattern in probe_patterns:
            interval = h_intervals[pattern]
            for sid in ("s0", "s3"):
                got = h_reloaded.project_interval(sid, *interval)
                if (got != h_old[(pattern, sid)] and got ==
                        naive_project_interval(
                            h_output, load_manifest(h_output), sid,
                            interval[0], interval[1])):
                    detected = True
        probes["stale_same_length_replaced_interleave_detected"] = detected
        assert detected

        # corrupt cache
        h_interval = h_merged.findIndicesOfStr("ACGT")
        h_index2 = MultiSourceQueryIndex(
            h_output, rank_stride_bytes=1, mmap=False, use_saved_rank=False)
        h_expected = h_index2.project_interval("s0", *h_interval)
        h_index2.save_loaded_rank_indexes()
        rank_dir = os.path.join(h_output, "provenance", "ranks")
        cache_file = os.path.join(rank_dir, os.listdir(rank_dir)[0])
        with open(cache_file, "wb") as fp:
            fp.write(b"not a zip")
        h_reloaded2 = MultiSourceQueryIndex(
            h_output, rank_stride_bytes=1, mmap=False, use_saved_rank=True)
        assert h_reloaded2.project_interval("s0", *h_interval) == (
            h_expected)
        probes["corrupt_cache_rebuilt"] = True

        # wrong stride
        h_index3 = MultiSourceQueryIndex(
            h_output, rank_stride_bytes=1, mmap=False, use_saved_rank=False)
        h_index3.project_interval("s0", *h_interval)
        h_index3.save_loaded_rank_indexes()
        saved = np.load(cache_file)
        np.savez(cache_file,
                 rank_prefix=saved["rank_prefix"],
                 total_bits=saved["total_bits"],
                 rank_stride_bytes=np.asarray([999], dtype=np.uint64),
                 interleave_sha256=saved["interleave_sha256"],
                 interleave_total_ones=saved["interleave_total_ones"])
        h_reloaded3 = MultiSourceQueryIndex(
            h_output, rank_stride_bytes=1, mmap=False, use_saved_rank=True)
        assert h_reloaded3.project_interval("s0", *h_interval) == (
            h_expected)
        probes["wrong_stride_cache_rebuilt"] = True

        # legacy cache without identity fields
        h_index4 = MultiSourceQueryIndex(
            h_output, rank_stride_bytes=1, mmap=False, use_saved_rank=False)
        h_index4.project_interval("s0", *h_interval)
        h_index4.save_loaded_rank_indexes()
        saved2 = np.load(cache_file)
        np.savez(cache_file,
                 rank_prefix=saved2["rank_prefix"],
                 total_bits=saved2["total_bits"],
                 rank_stride_bytes=saved2["rank_stride_bytes"])
        h_reloaded4 = MultiSourceQueryIndex(
            h_output, rank_stride_bytes=1, mmap=False, use_saved_rank=True)
        assert h_reloaded4.project_interval("s0", *h_interval) == (
            h_expected)
        probes["legacy_cache_without_identity_rebuilt"] = True

        # ------------- REAL modern2 integration ---------------------------
        real = report["real_integration"]

        a_dir = harness.build_fixture_source("real-a", "uniform-a.fastq")
        b_dir = harness.build_fixture_source("real-b", "uniform-b.fastq")
        initialize_leaf_provenance(a_dir, source_id="real-a",
                                   source_name="real-a")
        initialize_leaf_provenance(b_dir, source_id="real-b",
                                   source_name="real-b")
        m_dir = os.path.join(work, "real-m")
        merge_two_with_provenance(a_dir, b_dir, m_dir,
                                  merge_two_func=holt_merge_two_local,
                                  num_procs=1)
        a_bwt = f1.load_standalone(a_dir)
        b_bwt = f1.load_standalone(b_dir)
        real_merged = MultiSourceBWT.load(m_dir, mmap=False)

        queries = f1.build_queries(f1.CANONICAL_READS_A,
                                   f1.CANONICAL_READS_B)
        queries.extend([b"$", b"A$", b"T$", b"ACGTN$"])
        real_mismatches = []
        real_queries = 0
        for query in queries:
            expected_a = int(a_bwt.countOccurrencesOfSeq(query))
            expected_b = int(b_bwt.countOccurrencesOfSeq(query))
            legacy = int(real_merged.bwt.countOccurrencesOfSeq(query))
            got_a = real_merged.countOccurrencesForSource(query, "real-a")
            got_b = real_merged.countOccurrencesForSource(query, "real-b")
            real_queries += 2
            if (got_a, got_b) != (expected_a, expected_b):
                real_mismatches.append((query, got_a, got_b, expected_a,
                                        expected_b))
            if got_a + got_b != legacy:
                real_mismatches.append(("sum", query, got_a + got_b, legacy))
            interval_a = tuple(int(v) for v in a_bwt.findIndicesOfStr(query))
            proj_a = real_merged.findIndicesForSource(query, "real-a")
            if proj_a != interval_a:
                real_mismatches.append(("interval", query, proj_a,
                                        interval_a))
        for query, expected_total in f1.COMMITTED_QUERIES.items():
            assert int(real_merged.bwt.countOccurrencesOfSeq(query)) == (
                expected_total)
        real["canonical_two_source"] = {
            "queries": real_queries,
            "mismatches": len(real_mismatches),
        }
        assert real_mismatches == []
        assert real_queries > 100

        # real 5-source balanced merge
        rng = random.Random(SEED + 7)
        leaves5 = []
        standalone5 = {}
        for i in range(5):
            reads = f1.make_random_case(rng)[0]
            leaf = harness.build_fastq_source("real5-%d" % i, reads)
            initialize_leaf_provenance(leaf, source_id="r5-%d" % i,
                                       source_name="r5-%d" % i)
            leaves5.append(leaf)
            standalone5["r5-%d" % i] = f1.load_standalone(leaf)
        out5 = os.path.join(work, "real5")
        m5 = merge_many_balanced(
            leaves5, out5, merge_two_func=holt_merge_two_local, num_procs=1)
        assert max_depth(m5["root"]) <= 3
        merged5 = MultiSourceBWT.load(out5, mmap=False)
        q5 = ["A", "C", "G", "T", "N", "AC", "GT", "NA", "NN", "AAA",
              "ACGT", "TTA", "CGTAC", "$"]
        five_mismatches = []
        five_queries = 0
        for query in q5:
            for sid in ("r5-%d" % i for i in range(5)):
                expected = int(standalone5[sid].countOccurrencesOfSeq(query))
                got = merged5.countOccurrencesForSource(query, sid)
                five_queries += 1
                if got != expected:
                    five_mismatches.append((query, sid, got, expected))
                expected_interval = tuple(
                    int(v) for v in standalone5[sid].findIndicesOfStr(query))
                proj = merged5.findIndicesForSource(query, sid)
                if proj != expected_interval:
                    five_mismatches.append(("interval", query, sid, proj,
                                            expected_interval))
        real["five_source_balanced"] = {
            "queries": five_queries,
            "mismatches": len(five_mismatches),
        }
        assert five_mismatches == []

        # real 4-source unbalanced chain
        rng = random.Random(SEED + 8)
        leaves4 = []
        standalone4 = {}
        for i in range(4):
            reads = f1.make_random_case(rng)[0]
            leaf = harness.build_fastq_source("real4-%d" % i, reads)
            initialize_leaf_provenance(leaf, source_id="r4-%d" % i,
                                       source_name="r4-%d" % i)
            leaves4.append(leaf)
            standalone4["r4-%d" % i] = f1.load_standalone(leaf)
        current = leaves4[0]
        for i, leaf in enumerate(leaves4[1:], start=1):
            out = os.path.join(work, "real4-chain-%d" % i)
            merge_two_with_provenance(current, leaf, out,
                                      merge_two_func=holt_merge_two_local,
                                      num_procs=1)
            current = out
        merged4 = MultiSourceBWT.load(current, mmap=False)
        q4 = ["A", "T", "N", "AC", "GT", "NN", "ACGT", "$", "NA", "TAC"]
        four_mismatches = []
        four_queries = 0
        for query in q4:
            for sid in ("r4-%d" % i for i in range(4)):
                expected = int(standalone4[sid].countOccurrencesOfSeq(query))
                got = merged4.countOccurrencesForSource(query, sid)
                four_queries += 1
                if got != expected:
                    four_mismatches.append((query, sid, got, expected))
        real["four_source_unbalanced_chain"] = {
            "queries": four_queries,
            "mismatches": len(four_mismatches),
        }
        assert four_mismatches == []

        # givenRange delegation
        t_interval = tuple(int(v) for v in real_merged.bwt.findIndicesOfStr(
            b"T"))
        direct_gt = tuple(int(v) for v in real_merged.bwt.findIndicesOfStr(
            b"GT"))
        via_range = real_merged.findIndicesOfStr(b"G", givenRange=t_interval)
        assert via_range == direct_gt
        via_range_src = real_merged.findIndicesForSource(
            b"G", "real-a", givenRange=t_interval)
        assert via_range_src == tuple(
            int(v) for v in a_bwt.findIndicesOfStr(b"GT"))
        real["given_range_delegation"] = True

        # one merged search per query on the real BWT
        proxy = f1.CountingProxy(real_merged.bwt)
        wrapped_real = MultiSourceBWT(
            proxy, MultiSourceQueryIndex(m_dir, mmap=False))
        for query in (b"ACGTN", b"A", b"$", b"TTTTT"):
            wrapped_real.countOccurrencesForSource(query, "real-a")
            wrapped_real.querySource(query, "real-b")
        assert proxy.search_calls == 8
        real["one_search_per_query_real"] = True

        # ------------- randomized Level-3 differential --------------------
        rng = random.Random(SEED)
        random_mismatches = []
        random_queries = 0
        datasets = 0
        for case_index in range(6):
            source_count = rng.randint(2, 4)
            leaves_r = []
            standalone_r = {}
            reads_by_source = {}
            for i in range(source_count):
                reads = f1.make_random_case(rng)[0]
                reads_by_source["rd-%d" % i] = reads
                leaf = harness.build_fastq_source(
                    "rand-%d-%d" % (case_index, i), reads)
                initialize_leaf_provenance(leaf, source_id="rd-%d" % i,
                                           source_name="rd-%d" % i)
                leaves_r.append(leaf)
                standalone_r["rd-%d" % i] = f1.load_standalone(leaf)
            out_r = os.path.join(work, "rand-%d" % case_index)
            manifest_r = merge_many_balanced(
                leaves_r, out_r, merge_two_func=holt_merge_two_local,
                num_procs=1)
            merged_r = MultiSourceBWT.load(out_r, mmap=False)
            datasets += 1
            queries_r = set(["A", "C", "G", "T", "N", "$", "AA", "AC",
                             "NN", "A$", "T$"])
            for reads in reads_by_source.values():
                for read in reads:
                    for start in range(len(read)):
                        for end in range(start + 1, len(read) + 1):
                            queries_r.add(read[start:end])
            for query in queries_r:
                merged_interval = tuple(
                    int(v) for v in merged_r.bwt.findIndicesOfStr(query))
                for sid in reads_by_source:
                    expected = int(standalone_r[sid].countOccurrencesOfSeq(
                        query))
                    got = merged_r.countOccurrencesForSource(query, sid)
                    random_queries += 1
                    if got != expected:
                        random_mismatches.append({
                            "case": case_index, "query": query, "sid": sid,
                            "got": got, "expected": expected,
                            "reads_by_source": reads_by_source})
                    expected_interval = tuple(
                        int(v) for v in standalone_r[sid].findIndicesOfStr(
                            query))
                    proj = merged_r.findIndicesForSource(query, sid)
                    if proj != expected_interval:
                        random_mismatches.append({
                            "case": case_index, "query": query, "sid": sid,
                            "kind": "interval", "proj": proj,
                            "expected": expected_interval,
                            "reads_by_source": reads_by_source})
                    naive = naive_project_interval(
                        out_r, manifest_r, sid, merged_interval[0],
                        merged_interval[1])
                    if naive != expected_interval:
                        random_mismatches.append({
                            "case": case_index, "query": query, "sid": sid,
                            "kind": "naive", "naive": naive,
                            "expected": expected_interval,
                            "reads_by_source": reads_by_source})
        report["randomized"] = {
            "seed": SEED,
            "datasets": datasets,
            "queries": random_queries,
            "mismatches": len(random_mismatches),
        }
        assert random_mismatches == []
        assert datasets == 6
        assert random_queries > 500

        # ------------- performance / storage sanity -----------------------
        perf = report["performance"]
        started = time.time()
        steps = 0
        nodes = 0
        probe_index = MultiSourceQueryIndex(
            output, rank_stride_bytes=64, mmap=True, use_saved_rank=False)
        for _ in range(20):
            pattern = patterns[_ * 13 % len(patterns)]
            merged_interval = merged.findIndicesOfStr(pattern)
            for sid in list(standalone)[:3]:
                probe_index.project_interval(
                    sid, merged_interval[0], merged_interval[1])
        steps = 20 * 3
        nodes = probe_index.loaded_rank_node_count
        perf["projection_steps_total"] = steps
        perf["rank_nodes_touched"] = nodes
        perf["wall_seconds"] = round(time.time() - started, 3)
        perf["storage_bytes_rank_cache"] = sum(
            os.path.getsize(os.path.join(
                output, "provenance", "ranks", name))
            for name in os.listdir(os.path.join(
                output, "provenance", "ranks"))
            if name.endswith(".npz"))
        assert nodes > 0

        # summary
        report["real_queries"] = (
            real_queries + five_queries + four_queries)
        report["mismatch_count"] = (
            len(mismatches) + len(real_mismatches) + len(five_mismatches)
            + len(four_mismatches) + len(random_mismatches))
        assert report["mismatch_count"] == 0

        with open(out_path, "w") as fp:
            json.dump(report, fp, indent=2, sort_keys=True)
            fp.write("\n")
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _array_sha256_hex(array):
    import hashlib
    return hashlib.sha256(
        np.ascontiguousarray(array).tobytes()).hexdigest()


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("usage: feature3_query_one_constituent_evidence.py "
                         "OUTPUT.json\n")
        return 2
    report = run_evidence(sys.argv[1])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
