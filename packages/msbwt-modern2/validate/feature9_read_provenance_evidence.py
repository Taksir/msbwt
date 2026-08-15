#!/usr/bin/env python2
"""msbwt-modern2 Feature 9 evidence generator: exact read-level provenance.

Runs inside the pinned Python-2.7 environment.  Exercises:

- ten-source read-derived fixture (30 reads, 191 BWT rows):
  - every merged dollar ID resolves to the exact (source, source-local
    read, origin file/read ID) identity predicted by an INDEPENDENT oracle
    (naive suffix rows + direct interleave counting, no Feature-9 code);
  - readsContaining(P) == naive per-read overlapping counts for >=100
    patterns, duplicate identities preserved;
  - source/subset/group/where filtered read listing == independently
    filtered global result; source-prefilter LF-walk reduction probe;
  - mate links survive the balanced merge; 20-byte packed records;
  - one-sided read-provenance merge rejection before the BWT merge;
  - retrofit of a stripped merged package (BWT/provenance bytes unchanged)
    reproduces the fresh-merge read provenance exactly;
- REAL modern2 integration: leaves built from the uniform-a/uniform-b
  FASTQ fixtures (real pp/cfpp construction writing legacy about.npy),
  read provenance initialized from about.npy, real GenericMerge merges,
  then:
  - every dollar ID's source matches Holt's actual getSequenceDollarID
    LF walk and the provenance tree;
  - readsContaining(P) merged totals == merged FM counts; per-source
    filtered totals == standalone counts for >=10 patterns;
  - origin file/read IDs from about.npy survive exactly;
- deterministic randomized Level-3 differential (seed 20260811) over real
  construction + real merges;
- storage/identity sanity: record size 20 bytes, BWT unchanged by retrofit.

Any mismatch raises AssertionError; the driver records JSON only after
every gate passes.  Python 2.7 only.
"""

from __future__ import print_function

import hashlib
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
sys.path.insert(0, PACKAGE)
sys.path.insert(0, os.path.join(PACKAGE, "tests"))
import test_source_index_py2 as f1  # noqa: E402
import test_multisource_query_py2 as f3  # noqa: E402
import test_read_provenance_py2 as f9  # noqa: E402

from MUS.MultiSourceProvenance import (  # noqa: E402
    initialize_leaf_provenance,
    load_manifest,
    merge_many_balanced,
    merge_two_with_provenance,
)
from MUS.MultiSourceQuery import (  # noqa: E402
    MultiSourceBWT,
    MultiSourceQueryIndex,
)
from MUS.ReadProvenance import (  # noqa: E402
    ReadProvenanceIndex,
    initialize_leaf_read_provenance,
    initialize_leaf_read_provenance_from_about,
    read_provenance_exists,
    retrofit_read_provenance_from_leaf_dirs,
)

FIXTURES = os.path.join(REPO, "compat", "fixtures", "synthetic")
SEED = 20260811


def run_evidence(out_path):
    report = {
        "seed": SEED,
        "mismatch_count": 0,
        "oracles": [
            "naive_suffix_rows_plus_tree_walk",
            "per_read_naive_pattern_counts",
            "legacy_about_npy",
            "real_getSequenceDollarID_lf_walk",
        ],
        "ten_source_fixture": {},
        "real_integration": {},
        "randomized": {},
        "performance": {},
        "notes": [
            "read-derived fixtures are tiny deterministic corpora; real "
            "construction uses pp/cfpp (legacy about.npy) and real merges "
            "use compiled GenericMerge through the Feature-2 adapter.",
            "read provenance is AUTHORITATIVE; read_provenance.json binds "
            "format/version/read count/source metadata and the validated "
            "msbwt_sha256 of the current BWT.",
        ],
    }

    work = tempfile.mkdtemp(prefix="f9-evidence-")
    try:
        # ---------------- ten-source read-derived fixture ----------------
        leaves, output, manifest, oracle = f9.build_merged(
            work, f9.TEN_SOURCE_READS)
        index = ReadProvenanceIndex(output)
        assert index.record_bytes() == 20
        assert index.read_count == 30
        assert index.source_index.source_count == 10

        ten = report["ten_source_fixture"]
        ten["reads"] = index.read_count
        ten["sources"] = index.source_index.source_count
        ten["record_bytes"] = index.record_bytes()

        mismatches = []
        comparisons = 0

        # every dollar ID matches the independent oracle
        for dollar_id in range(index.read_count):
            expected_source, expected_local = (
                oracle.dollar_to_identity[dollar_id])
            record = index.record(dollar_id)
            comparisons += 3
            if record["source_id"] != expected_source:
                mismatches.append(("dollar_source", dollar_id,
                                   record["source_id"], expected_source))
            if record["source_read_id"] != expected_local:
                mismatches.append(("dollar_local", dollar_id,
                                   record["source_read_id"],
                                   expected_local))
            if record["origin_read_id"] != 100 + expected_local:
                mismatches.append(("origin_read_id", dollar_id,
                                   record["origin_read_id"],
                                   100 + expected_local))

        # readsContaining vs naive per-read counts for the full pattern set
        wrapped = MultiSourceBWT(
            None, index.source_index, read_provenance=index)
        bwt = f9.OracleBWTAdapter(oracle, output, manifest)
        wrapped.bwt = bwt
        patterns = f9.pattern_set(f9.TEN_SOURCE_READS)
        ten["patterns"] = len(patterns)
        assert ten["patterns"] >= 100
        for pattern in patterns:
            result = wrapped.readsContaining(pattern)
            expected = {}
            for sid, reads in f9.TEN_SOURCE_READS.items():
                for local_id in range(len(reads)):
                    dollar_id = oracle.global_dollar[(sid, local_id)]
                    count = f9.overlapping_count(reads[local_id], pattern)
                    if count:
                        expected[dollar_id] = count
            actual = {
                rec["dollar_id"]: rec["occurrence_count"]
                for rec in result["reads"]
            }
            comparisons += 1
            if actual != expected:
                mismatches.append(("reads_containing", pattern,
                                   actual, expected))
            comparisons += 2
            if result["unique_read_count"] != len(expected):
                mismatches.append(("unique_count", pattern,
                                   result["unique_read_count"],
                                   len(expected)))
            if result["reported_occurrences"] != sum(expected.values()):
                mismatches.append(("reported", pattern,
                                   result["reported_occurrences"],
                                   sum(expected.values())))
            if result["reported_occurrences"] != result[
                    "merged_occurrences"]:
                mismatches.append(("merged_total", pattern,
                                   result["reported_occurrences"],
                                   result["merged_occurrences"]))
            # per-source filtered listing == independently filtered global
            for sid, reads in f9.TEN_SOURCE_READS.items():
                sub = wrapped.readsContaining(pattern, source=sid)
                expected_sub = {
                    d: c for d, c in expected.items()
                    if oracle.dollar_to_identity[d][0] == sid
                }
                actual_sub = {
                    rec["dollar_id"]: rec["occurrence_count"]
                    for rec in sub["reads"]
                }
                comparisons += 1
                if actual_sub != expected_sub:
                    mismatches.append(
                        ("source_filter", (pattern, sid),
                         actual_sub, expected_sub))

        # source/subset/group/where filtered == independently filtered
        global_result = wrapped.readsContaining("A")
        global_map = {
            rec["dollar_id"]: rec["occurrence_count"]
            for rec in global_result["reads"]
        }
        subset = ["sample00", "sample02", "sample09"]
        filtered = {
            d: c for d, c in global_map.items()
            if index.record(d)["source_id"] in subset
        }
        result = wrapped.readsContaining("A", sources=subset)
        actual = {
            rec["dollar_id"]: rec["occurrence_count"]
            for rec in result["reads"]
        }
        comparisons += 1
        if actual != filtered:
            mismatches.append(("subset_filter", "A", actual, filtered))
        if result["stats"]["source_prefilter_skips"] + result[
                "reported_occurrences"] != global_result[
                "merged_occurrences"]:
            mismatches.append(
                ("prefilter_conservation", "A",
                 result["stats"]["source_prefilter_skips"],
                 global_result["merged_occurrences"]))

        metadata = wrapped.source_metadata
        metadata.define_group("case", ["sample00", "sample01", "sample02"])
        metadata.set_source_metadata("sample00", cohort="case")
        metadata.set_source_metadata("sample01", cohort="case")
        metadata.set_source_metadata("sample02", cohort="case")
        metadata.set_source_metadata("sample03", cohort="control")
        group_result = wrapped.readsContaining("AC", group="case")
        where_result = wrapped.readsContaining("AC", where={"cohort": "case"})
        comparisons += 2
        if [r["dollar_id"] for r in group_result["reads"]] != [
                r["dollar_id"] for r in where_result["reads"]]:
            mismatches.append(("group_where_equality", "AC", "x", "y"))

        # mate links survive in merged dollar order
        d0 = index.find_dollar_id("sample04", 0)
        d1 = index.find_dollar_id("sample04", 1)
        comparisons += 2
        if index.mate(d0)["dollar_id"] != d1:
            mismatches.append(("mate_0", "sample04", d0, d1))
        if index.mate(d1)["dollar_id"] != d0:
            mismatches.append(("mate_1", "sample04", d1, d0))
        if index.mate(index.find_dollar_id("sample04", 2)) is not None:
            mismatches.append(("mate_unpaired", "sample04", "x", "y"))

        # one-sided merge rejection before the BWT merge
        bad_sources = f9.build_sources(
            work, {"badleaf": ["AAAA", "CC"]})
        leaf_bad = bad_sources["badleaf"]
        os.remove(os.path.join(leaf_bad, "read_provenance.npy"))
        os.remove(os.path.join(leaf_bad, "read_provenance.json"))
        called = [False]

        def should_not_run(*args, **kwargs):
            called[0] = True

        try:
            merge_two_with_provenance(
                leaves["sample00"], leaf_bad,
                os.path.join(work, "bad_merge"),
                merge_two_func=should_not_run)
            raise AssertionError("one-sided read provenance not rejected")
        except Exception as exc:
            if called[0]:
                raise AssertionError("merge ran despite one-sided provenance")
            if "only one merge input" not in str(exc):
                raise
        comparisons += 1
        ten["one_sided_rejection"] = True

        # retrofit a stripped copy; BWT and provenance.json must not change
        merged2 = os.path.join(work, "merged_stripped")
        shutil.copytree(output, merged2)
        os.remove(os.path.join(merged2, "read_provenance.npy"))
        os.remove(os.path.join(merged2, "read_provenance.json"))
        bwt_before = hashlib.sha256(open(
            os.path.join(merged2, "msbwt.npy"), "rb").read()).hexdigest()
        manifest_before = hashlib.sha256(open(
            os.path.join(merged2, "provenance.json"), "rb").read()).hexdigest()
        retrofit_read_provenance_from_leaf_dirs(
            merged2,
            {sid: leaves[sid] for sid in f9.TEN_SOURCE_READS})
        bwt_after = hashlib.sha256(open(
            os.path.join(merged2, "msbwt.npy"), "rb").read()).hexdigest()
        manifest_after = hashlib.sha256(open(
            os.path.join(merged2, "provenance.json"), "rb").read()).hexdigest()
        comparisons += 2
        if bwt_before != bwt_after or manifest_before != manifest_after:
            mismatches.append(("retrofit_bwt_unchanged", merged2,
                               bwt_before, bwt_after))
        r1 = ReadProvenanceIndex(output)
        r2 = ReadProvenanceIndex(merged2)
        for dollar_id in range(r1.read_count):
            a = r1.record(dollar_id)
            b = r2.record(dollar_id)
            for field in ("source_id", "source_read_id", "origin_file_id",
                          "origin_read_id", "mate_dollar_id"):
                comparisons += 1
                if a[field] != b[field]:
                    mismatches.append(
                        ("retrofit_record", (dollar_id, field),
                         a[field], b[field]))

        ten["comparisons"] = comparisons
        ten["mismatches"] = len(mismatches)
        assert comparisons >= 1000
        assert mismatches == []

        # ---------------- REAL modern2 integration ------------------------
        real = report["real_integration"]
        harness = f1.SourceHarness(work)
        a_dir = harness.build_fixture_source("real-a", "uniform-a.fastq")
        b_dir = harness.build_fixture_source("real-b", "uniform-b.fastq")
        initialize_leaf_provenance(a_dir, source_id="real-a",
                                   source_name="real-a")
        initialize_leaf_provenance(b_dir, source_id="real-b",
                                   source_name="real-b")
        assert os.path.exists(os.path.join(a_dir, "about.npy"))
        assert os.path.exists(os.path.join(b_dir, "about.npy"))
        initialize_leaf_read_provenance_from_about(
            a_dir, input_files=["uniform-a.fastq"])
        initialize_leaf_read_provenance_from_about(
            b_dir, input_files=["uniform-b.fastq"])
        m_dir = os.path.join(work, "real-m")
        merge_two_with_provenance(a_dir, b_dir, m_dir,
                                  merge_two_func=f3.holt_merge_two_local,
                                  num_procs=1)
        assert read_provenance_exists(m_dir)

        merged = MultiSourceBWT.load(m_dir, mmap=False)
        qindex = merged.source_index
        rindex = merged.read_provenance
        real["reads"] = rindex.read_count
        real["sources"] = 2
        real["record_bytes"] = rindex.record_bytes()
        assert rindex.record_bytes() == 20
        assert rindex.read_count > 0

        a_bwt = f1.load_standalone(a_dir)
        b_bwt = f1.load_standalone(b_dir)
        real_mismatches = []
        real_comparisons = 0

        # every dollar ID: provenance tree identity == real LF walk result
        for dollar_id in range(rindex.read_count):
            record = rindex.record(dollar_id)
            sid, local_row = qindex.locate_row_source(dollar_id)
            real_comparisons += 1
            if record["source_id"] != sid:
                real_mismatches.append(
                    ("dollar_source", dollar_id, record["source_id"], sid))
            real_comparisons += 1
            if record["source_read_id"] != local_row:
                real_mismatches.append(
                    ("dollar_local", dollar_id,
                     record["source_read_id"], local_row))

        from MUS.util import fastqIterator

        def fixture_reads(fixture_name):
            path = os.path.join(FIXTURES, fixture_name)
            reads = []
            for name, seq, comment, quality in fastqIterator(path):
                reads.append(seq)
            return reads

        reads_a = fixture_reads("uniform-a.fastq")
        reads_b = fixture_reads("uniform-b.fastq")
        origin_reads = {"real-a": reads_a, "real-b": reads_b}

        # pattern -> readsContaining merged totals == real FM counts
        queries = set(["A", "C", "G", "T", "N", "AC", "GT", "ACGT",
                       "AAAAA", "NACGT"])
        for read in reads_a + reads_b:
            for start in range(len(read)):
                for end in range(start + 1, len(read) + 1):
                    queries.add(read[start:end])
        queries = sorted(queries)
        for query in queries:
            result = merged.readsContaining(query)
            merged_count = int(merged.bwt.countOccurrencesOfSeq(query))
            real_comparisons += 2
            if result["reported_occurrences"] != merged_count:
                real_mismatches.append(
                    ("merged_total", query,
                     result["reported_occurrences"], merged_count))
            for sid, standalone in (("real-a", a_bwt), ("real-b", b_bwt)):
                sub = merged.readsContaining(query, source=sid)
                expected = int(standalone.countOccurrencesOfSeq(query))
                real_comparisons += 1
                if sub["reported_occurrences"] != expected:
                    real_mismatches.append(
                        ("source_total", (query, sid),
                         sub["reported_occurrences"], expected))
                if any(rec["source_id"] != sid for rec in sub["reads"]):
                    real_mismatches.append(
                        ("source_purity", (query, sid), "x", "y"))

        # about.npy origin file/read IDs survive the real merge
        for sid, standalone_dir in (("real-a", a_dir), ("real-b", b_dir)):
            about = np.load(os.path.join(standalone_dir, "about.npy"))
            parsed = f9_read_about(about)
            for local_id, (file_id, read_id) in enumerate(parsed):
                dollar_id = rindex.find_dollar_id(sid, local_id)
                record = rindex.record(dollar_id)
                real_comparisons += 2
                if record["origin_file_id"] != file_id:
                    real_mismatches.append(
                        ("about_file", (sid, local_id),
                         record["origin_file_id"], file_id))
                if record["origin_read_id"] != read_id:
                    real_mismatches.append(
                        ("about_read", (sid, local_id),
                         record["origin_read_id"], read_id))

        # real LF walk: row -> dollar id -> record source agrees
        total_rows = int(merged.bwt.getTotalSize())
        step = 1 if total_rows < 500 else max(1, total_rows // 100)
        for row in range(0, total_rows, step):
            dollar_id = int(merged.bwt.getSequenceDollarID(row))
            record = merged.readProvenance(dollar_id)
            sid, _ = qindex.locate_row_source(row)
            real_comparisons += 1
            if record["source_id"] != sid:
                real_mismatches.append(
                    ("lf_row_source", row, record["source_id"], sid))

        # exact read recovery: recoverString(dollar_id) must equal the
        # original FASTQ read (as a multiset over the whole source)
        for sid in ("real-a", "real-b"):
            recovered = []
            for local_id in range(len(origin_reads[sid])):
                dollar_id = rindex.find_dollar_id(sid, local_id)
                sequence = merged.bwt.recoverString(dollar_id)
                recovered.append(sequence)
                real_comparisons += 1
            recovered_sorted = sorted(recovered)
            # Holt's recoverString returns the rotation starting at '$',
            # i.e. '$' + original read.
            origin_sorted = sorted(
                ("$" + read).encode("ascii") for read in origin_reads[sid])
            real_comparisons += 1
            if recovered_sorted != origin_sorted:
                real_mismatches.append(
                    ("read_recovery", sid, recovered_sorted,
                     origin_sorted))

        # per-read occurrence counts from recovered reads for every query
        # (recovered reads are indexed by about.npy order, which is the
        # sorted-read order the BWT dollar rows follow)
        recovered_by_dollar = {}
        for sid, leaf_dir in (("real-a", a_dir), ("real-b", b_dir)):
            about = np.load(os.path.join(leaf_dir, "about.npy"))
            parsed = [(int(r[0]), int(r[1])) for r in about]
            for local_id, (_file_id, read_id) in enumerate(parsed):
                dollar_id = rindex.find_dollar_id(sid, local_id)
                recovered_by_dollar[dollar_id] = origin_reads[sid][read_id]
        for query in queries:
            result = merged.readsContaining(
                query, include_sequence=True)
            for record in result["reads"]:
                sequence = record["sequence"]
                if isinstance(sequence, bytes):
                    text = sequence.decode("ascii")
                else:
                    text = str(sequence)
                if text.startswith("$"):
                    text = text[1:]
                expected_count = f9.overlapping_count(text, query)
                real_comparisons += 1
                if record["occurrence_count"] != expected_count:
                    real_mismatches.append(
                        ("per_read_count", (query, record["dollar_id"]),
                         record["occurrence_count"], expected_count))
            # full per-read map over every dollar ID
            expected_map = {
                dollar_id: f9.overlapping_count(read, query)
                for dollar_id, read in recovered_by_dollar.items()
                if f9.overlapping_count(read, query)
            }
            actual_map = {
                rec["dollar_id"]: rec["occurrence_count"]
                for rec in result["reads"]
            }
            real_comparisons += 1
            if actual_map != expected_map:
                real_mismatches.append(
                    ("per_read_map", query, actual_map, expected_map))

        # exhaustive kmer sweep over ACGTN (lengths 1-3): merged totals
        # and per-read maps against the recovered reads
        import itertools
        kmer_queries = []
        for length in (1, 2, 3):
            for chars in itertools.product("ACGTN", repeat=length):
                kmer_queries.append("".join(chars))
        for query in kmer_queries:
            result = merged.readsContaining(query)
            expected_total = sum(
                f9.overlapping_count(read, query)
                for read in recovered_by_dollar.values())
            real_comparisons += 1
            if result["reported_occurrences"] != expected_total:
                real_mismatches.append(
                    ("kmer_total", query,
                     result["reported_occurrences"], expected_total))
            expected_map = {
                dollar_id: f9.overlapping_count(read, query)
                for dollar_id, read in recovered_by_dollar.items()
                if f9.overlapping_count(read, query)
            }
            actual_map = {
                rec["dollar_id"]: rec["occurrence_count"]
                for rec in result["reads"]
            }
            real_comparisons += 1
            if actual_map != expected_map:
                real_mismatches.append(
                    ("kmer_map", query, actual_map, expected_map))

        real["comparisons"] = real_comparisons
        real["mismatches"] = len(real_mismatches)
        assert real_mismatches == []
        assert real_comparisons > 500

        # ------------- randomized Level-3 differential --------------------
        rng = random.Random(SEED)
        random_mismatches = []
        random_comparisons = 0
        datasets = 0
        for case_index in range(3):
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
                # The nonuniform (Multimerge) preprocessing route does not
                # write about.npy, so initialize explicit records in local
                # dollar-ID order.  Dollar rows are sorted by full rotation
                # ('$'-terminated read comparison, '$' < 'A'), so record k
                # carries the INPUT index of the k-th read in that order
                # (the exact about.npy semantic).
                sorted_input = sorted(
                    range(len(reads)),
                    key=lambda i: reads[i] + "$")
                records = [
                    {"origin_file_id": 0,
                     "origin_read_id": sorted_input[k]}
                    for k in range(len(reads))
                ]
                initialize_leaf_read_provenance(leaf, records)
                leaves_r.append(leaf)
                standalone_r["rd-%d" % i] = f1.load_standalone(leaf)
            out_r = os.path.join(work, "rand-%d" % case_index)
            merge_two_with_provenance(
                leaves_r[0], leaves_r[1], out_r,
                merge_two_func=f3.holt_merge_two_local, num_procs=1)
            for i in range(2, source_count):
                merged_tmp = os.path.join(work, "rand-%d-m%d" %
                                          (case_index, i))
                merge_two_with_provenance(
                    out_r, leaves_r[i], merged_tmp,
                    merge_two_func=f3.holt_merge_two_local, num_procs=1)
                out_r = merged_tmp
            merged_r = MultiSourceBWT.load(out_r, mmap=False)
            datasets += 1
            queries_r = set(["A", "C", "G", "T", "N", "AA", "AC", "NN"])
            for reads in reads_by_source.values():
                for read in reads:
                    for start in range(len(read)):
                        for end in range(start + 1,
                                         min(len(read), start + 4) + 1):
                            queries_r.add(read[start:end])
            for query in queries_r:
                result = merged_r.readsContaining(query)
                expected_total = sum(
                    int(bwt.countOccurrencesOfSeq(query))
                    for bwt in standalone_r.values())
                random_comparisons += 1
                if result["reported_occurrences"] != expected_total:
                    random_mismatches.append({
                        "case": case_index, "query": query,
                        "actual": result["reported_occurrences"],
                        "expected": expected_total})
                for sid, standalone in standalone_r.items():
                    sub = merged_r.readsContaining(query, source=sid)
                    expected = int(standalone.countOccurrencesOfSeq(query))
                    random_comparisons += 1
                    if sub["reported_occurrences"] != expected:
                        random_mismatches.append({
                            "case": case_index, "query": query,
                            "source": sid,
                            "actual": sub["reported_occurrences"],
                            "expected": expected})
            # read-level alignment against the REAL LF walk: every dollar
            # ID must point at a read of the correct source whose recovered
            # sequence matches the read at the recorded origin position
            # (duplicate reads may share positions, so membership is the
            # exact contract here).
            rindex_r = merged_r.read_provenance
            for dollar_id in range(rindex_r.read_count):
                record = rindex_r.record(dollar_id)
                sid = record["source_id"]
                recovered = merged_r.bwt.recoverString(dollar_id)
                if isinstance(recovered, bytes):
                    text = recovered.decode("ascii")
                else:
                    text = str(recovered)
                if text.startswith("$"):
                    text = text[1:]
                origin_read_id = record["origin_read_id"]
                random_comparisons += 1
                if origin_read_id is None or origin_read_id < 0 or (
                        origin_read_id >= len(reads_by_source[sid])):
                    random_mismatches.append({
                        "case": case_index, "dollar_id": dollar_id,
                        "origin_read_id": origin_read_id,
                        "recovered": text})
                    continue
                allowed = [
                    i for i, read in enumerate(reads_by_source[sid])
                    if read == text
                ]
                random_comparisons += 1
                if origin_read_id not in allowed:
                    random_mismatches.append({
                        "case": case_index, "dollar_id": dollar_id,
                        "source": sid,
                        "origin_read_id": origin_read_id,
                        "recovered": text,
                        "allowed": allowed})
        report["randomized"] = {
            "seed": SEED,
            "datasets": datasets,
            "queries": random_comparisons,
            "mismatches": len(random_mismatches),
        }
        assert random_mismatches == []
        assert datasets == 3
        assert random_comparisons > 200

        # ------------- performance / storage sanity -----------------------
        perf = report["performance"]
        started = time.time()
        pattern = "A"
        global_result = wrapped.readsContaining(pattern)
        perf["lf_walks_without_filter"] = global_result["stats"]["lf_walks"]
        sample09_result = wrapped.readsContaining(pattern, source="sample09")
        perf["lf_walks_with_filter"] = sample09_result["stats"]["lf_walks"]
        perf["source_prefilter_skips"] = sample09_result["stats"][
            "source_prefilter_skips"]
        perf["wall_seconds"] = round(time.time() - started, 3)
        assert perf["lf_walks_with_filter"] < perf["lf_walks_without_filter"]

        report["mismatch_count"] = (
            len(mismatches) + len(real_mismatches) + len(random_mismatches))
        assert report["mismatch_count"] == 0

        with open(out_path, "w") as fp:
            json.dump(report, fp, indent=2, sort_keys=True)
            fp.write("\n")
        return report
    finally:
        shutil.rmtree(work, ignore_errors=True)


def f9_read_about(about):
    """Independent parse of legacy about.npy records."""
    names = about.dtype.names
    if names:
        f0, f1n = names[:2]
        return [(int(row[f0]), int(row[f1n])) for row in about]
    arr = np.asarray(about)
    return [(int(row[0]), int(row[1])) for row in arr]


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("usage: feature9_read_provenance_evidence.py "
                         "OUTPUT.json\n")
        return 2
    report = run_evidence(sys.argv[1])
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
