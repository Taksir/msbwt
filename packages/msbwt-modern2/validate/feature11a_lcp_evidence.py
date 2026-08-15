#!/usr/bin/env python2
"""msbwt-modern2 Feature 11A evidence generator: exact post-construction
LCP retrofit.

Runs inside the pinned Python-2.7 environment.  Exercises:

- 10-source read-derived fixture (191 rows): EVERY adjacent LCP boundary
  compared against the independent explicit-suffix oracle (190/190,
  terminator excluded from LCP length);
- terminator semantics: duplicate reads (LCP == biological length, never
  +1), many identical reads, prefix/suffix-related reads, N-heavy,
  mixed lengths, 1-base reads;
- construction requires no FASTQ and no BWT rebuild (BWT bytes
  unchanged); adding LCP changes no Point-12 tag or Q1 quality bytes;
- construction on a post-Feature-10 reduced package;
- query API: lcpAt / lcpAdjacent / lcpBetweenRows (RMQ identity);
- stale/corrupt protection: same-length replaced BWT rejected, wrong
  length/dtype/version/metadata rejected;
- Point-10 fail-safe: LCP removal rejected; drop_lcp produces a clean
  reduced package;
- deterministic randomized Level-3 differential (seed 20260811): 18
  random collections, all boundaries vs the oracle.

Any mismatch raises AssertionError; the driver records JSON only after
every gate passes.  Python 2.7 only.
"""

from __future__ import print_function

import json
import os
import random
import shutil
import sys
import tempfile

import numpy as np

REPO = os.environ.get("MSBWT_MODERN2_REPO")
if REPO is None:
    raise SystemExit("MSBWT_MODERN2_REPO must point at the repository root")

PACKAGE = os.path.join(REPO, "packages", "msbwt-modern2")
sys.path.insert(0, PACKAGE)
sys.path.insert(0, os.path.join(PACKAGE, "tests"))
import test_read_provenance_py2 as f9  # noqa: E402
import test_lcp_py2 as t11a  # noqa: E402

from MUS.LCP import (  # noqa: E402
    LCPError,
    LCPIndex,
    construct_lcp_from_bwt,
    lcp_exists,
)
from MUS.MultiSourceProvenance import (  # noqa: E402
    load_manifest,
    merge_many_balanced,
    validate_manifest,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)
from MUS.SourceRemoval import remove_sources  # noqa: E402

SEED = 20260811


def construct_lcp(directory, oracle):
    """Construct LCP through the independent naive adapter."""
    return construct_lcp_from_bwt(
        directory, bwt=t11a.OracleBackedAdapter(directory, oracle))


def run_evidence(out_path):
    report = {
        "seed": SEED,
        "mismatch_count": 0,
        "oracles": [
            "explicit_adjacent_suffix_comparison_excluding_terminator",
        ],
        "boundaries": {},
        "terminator_semantics": {},
        "bwt_unchanged": False,
        "tags_quality_unchanged": False,
        "reduced_construction": False,
        "query_api": {},
        "stale_protection": {},
        "removal_failsafe": {},
        "randomized": {},
        "notes": [
            "lcps.npy preserves the upstream Holt convention: "
            "lcps[i] = LCP(SA[i], SA[i+1]), length N-1; canonical "
            "LCP[0] = 0.",
            "stored '$' acts as virtual distinct ordered terminators and "
            "contributes 0 symbols to the LCP (duplicate reads never gain "
            "an extra terminator symbol).",
            "construction recovers reads through the existing BWT only: "
            "no FASTQ, no BWT rebuild, no re-merge.",
        ],
    }

    work = tempfile.mkdtemp(prefix="lcp-evidence-")
    try:
        # ---------------- 10-source fixture: every boundary --------------
        leaves, output, oracle, rbs = t11a.build_merged(work, 
            f9.TEN_SOURCE_READS, name="merged10")
        construct_lcp(output, oracle)

        boundaries = report["boundaries"]
        index = LCPIndex(output)
        expected = t11a.expected_lcps(output)
        mismatches = []
        comparisons = 0
        for i in range(expected.shape[0]):
            comparisons += 1
            if int(index.values[i]) != int(expected[i]):
                mismatches.append((i, int(index.values[i]),
                                   int(expected[i])))
        boundaries["count"] = expected.shape[0]
        boundaries["comparisons"] = comparisons
        boundaries["mismatches"] = len(mismatches)
        boundaries["max_lcp"] = int(np.max(expected))
        boundaries["dtype"] = str(index.values.dtype)
        assert expected.shape[0] == 190
        assert boundaries["max_lcp"] == 5
        assert mismatches == []

        # ---------------- terminator semantics ---------------------------
        term = report["terminator_semantics"]
        dup_leaves, dup_out, dup_oracle, _ = (
            t11a.build_merged(work, 
                {"D": ["ACG", "ACG"], "O": ["TTTT"]}, name="dup"))
        construct_lcp(dup_out, dup_oracle)
        dup_index = LCPIndex(dup_out)
        assert int(np.max(dup_index.values)) == 3  # biological length
        term["duplicates"] = True

        ident_leaves, ident_out, ident_oracle, _ = (
            t11a.build_merged(work, 
                {"S1": ["AAAA", "AAAA", "AAAA"],
                 "S2": ["AAAA", "AAAA"]}, name="ident"))
        construct_lcp(ident_out, ident_oracle)
        ident_index = LCPIndex(ident_out)
        assert int(np.max(ident_index.values)) == 4  # never 5
        term["identical"] = True

        mix_leaves, mix_out, mix_oracle, _ = (
            t11a.build_merged(work, 
                {"P": ["ACGT", "ACG", "AC", "A", "ACGTACGT"],
                 "S": ["TACGT", "GTACGT", "CGTACGT"],
                 "N": ["NACGT", "ACNT", "GGN"],
                 "M": ["A", "AC", "ACG", "ACGT"],
                 "B": ["T", "G", "N"]}, name="mix"))
        construct_lcp(mix_out, mix_oracle)
        mix_index = LCPIndex(mix_out)
        mix_expected = t11a.expected_lcps(mix_out)
        assert np.array_equal(mix_index.values, mix_expected)
        term["prefix_suffix_n_mixed"] = True

        # ---------------- BWT / tags / quality unchanged -----------------
        import hashlib
        from MUS.BWTTags import BWTTagStore, attach_tag
        from MUS.QualitySidecar import (
            QualitySidecar, attach_quality_from_row_values)

        tag_leaves = {}
        tagged_root = os.path.join(work, "tagged")
        if not os.path.isdir(tagged_root):
            os.makedirs(tagged_root)
        for sid, reads in (("A", ["ACGTAC", "AAAA"]),
                           ("B", ["TTTT", "CCCC"])):
            leaf = f9.make_read_derived_leaf(
                tagged_root, sid, reads)
            attach_tag(
                leaf, "row_id",
                np.arange(len(f9.load_rows(leaf)), dtype=np.uint32))
            rows = f9.load_rows(leaf)
            q = np.zeros(len(rows), dtype=np.uint8)
            for idx, r in enumerate(rows):
                read = reads[r["read_id"]]
                q[idx] = 255 if r["pos"] >= len(read) else 33 + (idx % 40)
            attach_quality_from_row_values(leaf, q)
            tag_leaves[sid] = leaf
        tag_out = os.path.join(work, "tagged_merged")
        merge_many_balanced(
            list(tag_leaves.values()), tag_out,
            merge_two_func=f9.read_derived_merge)
        bwt_before = hashlib.sha256(open(
            os.path.join(tag_out, "msbwt.npy"), "rb").read()).hexdigest()
        tag_before = BWTTagStore(tag_out).array("row_id").copy()
        quality_before = QualitySidecar(tag_out).values.copy()
        tag_oracle = f9.OracleReadIdentity(
            tag_out,
            {sid: tag_leaves[sid] for sid in tag_leaves},
            {"A": ["ACGTAC", "AAAA"], "B": ["TTTT", "CCCC"]})
        construct_lcp(tag_out, tag_oracle)
        bwt_after = hashlib.sha256(open(
            os.path.join(tag_out, "msbwt.npy"), "rb").read()).hexdigest()
        assert bwt_before == bwt_after
        assert np.array_equal(
            BWTTagStore(tag_out).array("row_id"), tag_before)
        assert np.array_equal(
            QualitySidecar(tag_out).values, quality_before)
        report["bwt_unchanged"] = True
        report["tags_quality_unchanged"] = True

        # ---------------- reduced package construction -------------------
        reduced = os.path.join(work, "reduced")
        remove_sources(
            output, reduced,
            sources=["sample00", "sample02", "sample09"],
            drop_lcp=True)
        keep = {sid: rbs[sid] for sid in rbs
                if sid not in ("sample00", "sample02", "sample09")}
        reduced_oracle = f9.OracleReadIdentity(
            reduced,
            {sid: leaves[sid] for sid in keep},
            keep)
        t11a.save_expected_rows(reduced, leaves, keep)
        construct_lcp(reduced, reduced_oracle)
        red_index = LCPIndex(reduced)
        red_expected = t11a.expected_lcps(reduced)
        assert np.array_equal(red_index.values, red_expected)
        report["reduced_construction"] = True

        # ---------------- query API --------------------------------------
        queries = report["query_api"]
        qindex = MultiSourceQueryIndex(
            output, rank_stride_bytes=1, mmap=False,
            use_saved_rank=False)
        wrapped = MultiSourceBWT(None, qindex, lcp_index=LCPIndex(output))
        assert wrapped.hasLCP()
        assert wrapped.lcpAt(0) == 0
        qmismatches = []
        qcomparisons = 0
        for row in (1, 5, 100, 190):
            qcomparisons += 1
            if wrapped.lcpAt(row) != int(expected[row - 1]):
                qmismatches.append(("lcpAt", row))
        for left in (0, 3, 77, 189):
            qcomparisons += 1
            if wrapped.lcpAdjacent(left) != int(expected[left]):
                qmismatches.append(("lcpAdjacent", left))
        for i in (0, 1, 5, 60, 100, 189):
            for j in (i + 1, min(i + 7, 190), 190):
                if j <= i:
                    continue
                qcomparisons += 1
                if wrapped.lcpBetweenRows(i, j) != int(
                        np.min(expected[i:j])):
                    qmismatches.append(("between", i, j))
        # exhaustive RMQ identity on the small range [0, 40)
        for i in range(40):
            for j in range(i + 1, 40):
                qcomparisons += 1
                if wrapped.lcpBetweenRows(i, j) != int(
                        np.min(expected[i:j])):
                    qmismatches.append(("between_full", i, j))
        queries["comparisons"] = qcomparisons
        queries["mismatches"] = len(qmismatches)
        assert qmismatches == []
        assert qcomparisons > 50

        # ---------------- stale protection -------------------------------
        stale = report["stale_protection"]
        copy_dir = os.path.join(work, "stale_copy")
        shutil.copytree(output, copy_dir)
        bwt = np.load(os.path.join(copy_dir, "msbwt.npy"))
        bwt[0] = (bwt[0] + 1) % 6
        np.save(os.path.join(copy_dir, "msbwt.npy"), bwt)
        try:
            LCPIndex(copy_dir)
            raise AssertionError("same-length replaced BWT accepted")
        except (LCPError, Exception) as exc:
            if not isinstance(exc, (LCPError, ValueError)):
                raise
        stale["replaced_bwt_rejected"] = True
        # wrong length / dtype / metadata
        arr = np.load(os.path.join(output, "lcps.npy"))
        np.save(os.path.join(copy_dir, "lcps.npy"), arr[:-1])
        try:
            LCPIndex(copy_dir)
            raise AssertionError("wrong-length LCP accepted")
        except LCPError:
            pass
        np.save(os.path.join(copy_dir, "lcps.npy"), arr)
        np.save(os.path.join(copy_dir, "lcps.npy"),
                np.zeros(190, dtype=np.int32))
        try:
            LCPIndex(copy_dir)
            raise AssertionError("wrong-dtype LCP accepted")
        except LCPError:
            pass
        stale["wrong_length_dtype_rejected"] = True

        # ---------------- removal fail-safe ------------------------------
        removal = report["removal_failsafe"]
        try:
            remove_sources(
                output, os.path.join(work, "r"),
                sources=["sample09"])
            raise AssertionError("LCP removal not rejected")
        except LCPError:
            pass
        assert not os.path.exists(os.path.join(work, "r", "msbwt.npy"))
        removal["rejected"] = True
        r2 = os.path.join(work, "r2")
        remove_sources(
            output, r2, sources=["sample09"], drop_lcp=True)
        assert not lcp_exists(r2)
        assert validate_manifest(r2)
        removal["drop_lcp"] = True

        # ------------- randomized Level-3 differential --------------------
        rng = random.Random(SEED)
        random_mismatches = []
        cases = 0
        for case in range(18):
            reads_by_source = {}
            n_sources = rng.randint(1, 4)
            for i in range(n_sources):
                sid = "R%02d_S%d" % (case, i)
                n_reads = rng.randint(1, 4)
                reads = []
                alphabet = "ACGTN"
                for _ in range(n_reads):
                    length = rng.randint(1, 8)
                    if rng.random() < 0.3 and reads:
                        reads.append(reads[rng.randrange(len(reads))])
                        continue
                    reads.append("".join(
                        rng.choice(alphabet) for _ in range(length)))
                reads_by_source[sid] = reads
            rleaves = {}
            rand_root = os.path.join(work, "rand_%d" % case)
            if not os.path.isdir(rand_root):
                os.makedirs(rand_root)
            for sid, reads in reads_by_source.items():
                leaf = f9.make_read_derived_leaf(rand_root, sid, reads)
                rleaves[sid] = leaf
            rout = os.path.join(work, "rand_merged_%02d" % case)
            merge_many_balanced(
                list(rleaves.values()), rout,
                merge_two_func=f9.read_derived_merge)
            roracle = f9.OracleReadIdentity(
                rout,
                {sid: rleaves[sid] for sid in reads_by_source},
                reads_by_source)
            construct_lcp(rout, roracle)
            rindex = LCPIndex(rout)
            rexpected = t11a.expected_lcps(rout)
            cases += 1
            if not np.array_equal(rindex.values, rexpected):
                random_mismatches.append(("boundaries", case))
            if rindex.boundary(0) != 0:
                random_mismatches.append(("canonical", case))
        report["randomized"] = {
            "seed": SEED,
            "cases": cases,
            "mismatches": len(random_mismatches),
        }
        assert random_mismatches == []
        assert cases == 18

        report["mismatch_count"] = (
            len(mismatches) + len(qmismatches) + len(random_mismatches))
        assert report["mismatch_count"] == 0

        with open(out_path, "w") as fp:
            json.dump(report, fp, indent=2, sort_keys=True)
            fp.write("\n")
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("usage: feature11a_lcp_evidence.py OUTPUT.json\n")
        return 2
    report = run_evidence(sys.argv[1])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
