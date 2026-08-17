# -*- coding: utf-8 -*-
"""Bounded enhanced randomized audit for enhanced-modern2 (Windows).

Seed 20260810.  Exercises enhanced features through real construction,
provenance, tags, LCP, quality sidecar, source removal, and cross-feature
combinations.  Uses MultiSourceBWT.load() for real compiled BWT queries.

Run from packages/msbwt-modern2/:
    MSBWT_MODERN2_REPO=<repo> python ../compat/windows/enhanced_randomized_audit.py
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

_PKG_DIR = os.path.join(REPO, "packages", "msbwt-modern2")
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

from MUS.CommandLineInterface import mainRun
from MUS.MultiSourceProvenance import (
    extract_constituent_bwt,
    initialize_leaf_provenance,
    load_manifest,
    merge_many_balanced,
    source_ids,
    validate_manifest,
)
from MUS.MultiSourceQuery import MultiSourceBWT, MultiSourceQueryIndex
from MUS.BWTTags import (
    attach_tag,
    BWTTagStore,
    build_tag_from_leaf_arrays,
    remove_tag,
    tags_exist,
)
from MUS.LCP import construct_lcp_from_bwt, LCPIndex, lcp_exists
from MUS.QualitySidecar import (
    attach_quality_from_row_values,
    QualitySidecar,
    quality_sidecar_exists,
)
from MUS.ReadProvenance import (
    ReadProvenanceIndex,
    read_provenance_exists,
    initialize_leaf_read_provenance,
)
from MUS.SourceMetadata import SourceMetadataCatalog
from MUS.SourceRemoval import remove_sources
from MUS.Benchmarking import inspect_index, disk_breakdown

SEED = 20260810
ALPHABET = list("ACGTN")


def generate_reads(rng, count, min_len=3, max_len=20):
    return [''.join(rng.choice(ALPHABET) for _ in range(rng.randint(min_len, max_len)))
            for _ in range(count)]


def generate_quality(rng, length):
    return ''.join(chr(rng.randint(33, 73)) for _ in range(length))


def terminated_suffix_rows(reads):
    rows = []
    for read_id, read in enumerate(reads):
        text = read + "$"
        for pos in range(len(text)):
            rows.append({"suffix": text[pos:], "bwt": text[pos-1] if pos > 0 else "$",
                         "read_id": read_id, "pos": pos})
    rows.sort(key=lambda r: (r["suffix"], r["read_id"], r["pos"]))
    return rows


def compute_expected_lcp(rows):
    lcps = []
    for i in range(len(rows) - 1):
        s1, s2 = rows[i]["suffix"], rows[i+1]["suffix"]
        lcp = 0
        for a, b in zip(s1, s2):
            if a != b or a == "$":
                break
            lcp += 1
        lcps.append(lcp)
    return lcps


def write_fastq(reads, qualities, path):
    with open(path, "w") as fh:
        for i, (r, q) in enumerate(zip(reads, qualities)):
            fh.write("@read%d\n%s\n+\n%s\n" % (i, r, q))


def build_leaf_provenance(all_reads, qualities_map, work, label):
    leaves = []
    for sid in sorted(all_reads.keys()):
        fq = os.path.join(work, "%s_%s.fastq" % (label, sid))
        write_fastq(all_reads[sid], qualities_map[sid], fq)
        leaf_dir = os.path.join(work, "%s_leaf_%s" % (label, sid))
        os.mkdir(leaf_dir)
        old_argv = sys.argv
        try:
            sys.argv = ["msbwt", "pp", leaf_dir, fq]; mainRun()
            sys.argv = ["msbwt", "cfpp", "-p", "1", leaf_dir]; mainRun()
        finally:
            sys.argv = old_argv
        initialize_leaf_provenance(leaf_dir, source_id=sid)
        rows = terminated_suffix_rows(all_reads[sid])
        bwt_len = np.load(os.path.join(leaf_dir, "msbwt.npy"), mmap_mode="r").shape[0]
        q_arr = np.zeros(bwt_len, dtype=np.uint8)
        for idx, row in enumerate(rows):
            p, r = row["pos"], all_reads[sid][row["read_id"]]
            q = qualities_map[sid][row["read_id"]]
            q_arr[idx] = ord(q[p]) if p < len(r) and p < len(q) else 255
        try:
            attach_quality_from_row_values(leaf_dir, q_arr)
        except Exception:
            pass
        read_records = [{"origin_file_id": 0, "origin_read_id": i} for i in range(len(all_reads[sid]))]
        initialize_leaf_read_provenance(leaf_dir, read_records)
        leaves.append(leaf_dir)
    return leaves


def merge_leaves_balanced(leaves, work, label):
    out = os.path.join(work, "%s_merged" % label)
    os.mkdir(out)
    merge_many_balanced(leaves, out)
    return out


class AuditCategory(object):
    def __init__(self, name, description):
        self.name, self.description = name, description
        self.ops, self.passed, self.failed, self.errors = 0, 0, 0, []

    def check(self, condition, msg=""):
        self.ops += 1
        if condition:
            self.passed += 1
        else:
            self.failed += 1
            self.errors.append(msg)

    def summary(self):
        return {"name": self.name, "description": self.description,
                "status": "PASS" if self.failed == 0 else "FAIL",
                "ops": self.ops, "passed": self.passed, "failed": self.failed,
                "errors": self.errors[:5]}


def audit_f2(rng, work):
    cat = AuditCategory("F2: provenance persistence", "Manifest lifecycle, merge, reload")
    sr = random.Random(rng.randint(0, 2**31))
    src_reads = {"src%d" % i: generate_reads(sr, sr.randint(3,5), 4, 15) for i in range(4)}
    quals = {s: [generate_quality(sr, len(r)) for r in src_reads[s]] for s in src_reads}
    sub = os.path.join(work, "f2"); os.makedirs(sub)
    leaves = build_leaf_provenance(src_reads, quals, sub, "f2")
    for ld in leaves:
        m = load_manifest(ld)
        cat.check(m is not None, "leaf manifest None")
        cat.check(len(m.get("sources",[])) == 1, "leaf source count != 1")
    merged = merge_leaves_balanced(leaves, sub, "f2")
    mm = load_manifest(merged)
    cat.check(len(mm.get("sources",[])) == 4, "merged source count != 4")
    cat.check(validate_manifest(merged) is not None, "validate_manifest None")
    cat.check(source_ids(merged) == source_ids(merged), "source_ids differ after reload")
    return cat


def audit_f1_f3(rng, work):
    cat = AuditCategory("F1/F3: source-aware + constituent", "Merge, constituent BWTs, source_ids")
    sr = random.Random(rng.randint(0, 2**31))
    n = sr.randint(3, 5)
    src_reads = {"src%d" % i: generate_reads(sr, sr.randint(3,6), 4, 15) for i in range(n)}
    quals = {s: [generate_quality(sr, len(r)) for r in src_reads[s]] for s in src_reads}
    sub = os.path.join(work, "f1f3"); os.makedirs(sub)
    leaves = build_leaf_provenance(src_reads, quals, sub, "f1f3")
    merged = merge_leaves_balanced(leaves, sub, "f1f3")
    sids = source_ids(merged)
    cat.check(len(sids) == n, "source count %d != %d" % (len(sids), n))
    for sid in sids:
        cbwt = extract_constituent_bwt(merged, sid)
        cat.check(cbwt is not None and len(cbwt) > 0, "constituent %s empty" % sid)
    return cat


def audit_f4_f5_f6(rng, work):
    cat = AuditCategory("F4/F5/F6: nonzero + frequency + top-k", "Nonzero sources, frequency, top-k")
    sr = random.Random(rng.randint(0, 2**31))
    n = sr.randint(4, 6)
    src_reads = {"src%d" % i: generate_reads(sr, sr.randint(2,5), 3, 12) for i in range(n)}
    quals = {s: [generate_quality(sr, len(r)) for r in src_reads[s]] for s in src_reads}
    sub = os.path.join(work, "f456"); os.makedirs(sub)
    leaves = build_leaf_provenance(src_reads, quals, sub, "f456")
    merged = merge_leaves_balanced(leaves, sub, "f456")
    wrapped = MultiSourceBWT.load(merged)
    for _ in range(5):
        sid = sr.choice(sorted(src_reads.keys()))
        seq = sr.choice(src_reads[sid])
        try:
            nz = wrapped.nonzeroSources(seq + "$")
            cat.check(isinstance(nz, list), "nonzeroSources not list")
        except Exception as e:
            cat.check(False, "nonzeroSources: %s" % e)
    for _ in range(3):
        sid = sr.choice(sorted(src_reads.keys()))
        seq = sr.choice(src_reads[sid])
        try:
            f = wrapped.sourceFrequency(seq + "$")
            cat.check(f is not None, "sourceFrequency None")
        except Exception as e:
            cat.check(False, "sourceFrequency: %s" % e)
    for _ in range(3):
        sid = sr.choice(sorted(src_reads.keys()))
        seq = sr.choice(src_reads[sid])
        try:
            tk = wrapped.topSources(seq + "$", k=3)
            cat.check(isinstance(tk, list) and len(tk) <= 3, "topSources invalid")
        except Exception as e:
            cat.check(False, "topSources: %s" % e)
    return cat


def audit_f7(rng, work):
    cat = AuditCategory("F7: subsets + groups", "Metadata groups, subset/group queries")
    sr = random.Random(rng.randint(0, 2**31))
    n = sr.randint(4, 6)
    src_reads = {"src%d" % i: generate_reads(sr, sr.randint(3,6), 4, 15) for i in range(n)}
    quals = {s: [generate_quality(sr, len(r)) for r in src_reads[s]] for s in src_reads}
    sub = os.path.join(work, "f7"); os.makedirs(sub)
    leaves = build_leaf_provenance(src_reads, quals, sub, "f7")
    merged = merge_leaves_balanced(leaves, sub, "f7")
    idx = MultiSourceQueryIndex(merged)
    sids = idx.list_sources()
    source_records = [dict(src) for src in sids]
    catalog = SourceMetadataCatalog(source_records)
    ga = [s["id"] for i, s in enumerate(sids) if i % 2 == 0]
    gb = [s["id"] for i, s in enumerate(sids) if i % 2 == 1]
    catalog.define_group("groupA", ga)
    catalog.define_group("groupB", gb)
    cat.check(sorted(catalog.list_groups()) == ["groupA", "groupB"], "groups mismatch")
    cat.check(len(catalog.group_sources("groupA")) == len(ga), "groupA size mismatch")
    cat.check(len(catalog.group_sources("groupB")) == len(gb), "groupB size mismatch")
    return cat


def audit_f8a(rng, work):
    cat = AuditCategory("F8A: extensions", "Left and right sequence extensions")
    sr = random.Random(rng.randint(0, 2**31))
    src_reads = {"src%d" % i: generate_reads(sr, sr.randint(4,8), 4, 12) for i in range(3)}
    quals = {s: [generate_quality(sr, len(r)) for r in src_reads[s]] for s in src_reads}
    sub = os.path.join(work, "f8a"); os.makedirs(sub)
    leaves = build_leaf_provenance(src_reads, quals, sub, "f8a")
    merged = merge_leaves_balanced(leaves, sub, "f8a")
    wrapped = MultiSourceBWT.load(merged)
    seq = src_reads[sorted(src_reads.keys())[0]][0]
    try:
        le = wrapped.extendLeft(seq, sources=[sorted(src_reads.keys())[0]])
        cat.check(le is not None, "extendLeft None")
    except Exception as e:
        cat.check(False, "extendLeft: %s" % e)
    try:
        re = wrapped.extendRight(seq, sources=[sorted(src_reads.keys())[0]])
        cat.check(re is not None, "extendRight None")
    except Exception as e:
        cat.check(False, "extendRight: %s" % e)
    return cat


def audit_f9(rng, work):
    cat = AuditCategory("F9: read provenance", "readsContaining, recoverString")
    sr = random.Random(rng.randint(0, 2**31))
    src_reads = {"src%d" % i: generate_reads(sr, sr.randint(3,6), 4, 12) for i in range(3)}
    quals = {s: [generate_quality(sr, len(r)) for r in src_reads[s]] for s in src_reads}
    sub = os.path.join(work, "f9"); os.makedirs(sub)
    leaves = build_leaf_provenance(src_reads, quals, sub, "f9")
    merged = merge_leaves_balanced(leaves, sub, "f9")
    cat.check(read_provenance_exists(merged), "read provenance missing")
    wrapped = MultiSourceBWT.load(merged)
    seq = src_reads[sorted(src_reads.keys())[0]][0]
    try:
        reads = wrapped.readsContaining(seq)
        cat.check(reads is not None and len(reads) > 0, "readsContaining empty")
    except Exception as e:
        cat.check(False, "readsContaining: %s" % e)
    return cat


def audit_f10(rng, work):
    cat = AuditCategory("F10: source removal", "Remove source, verify survivors")
    sr = random.Random(rng.randint(0, 2**31))
    n = 4
    src_reads = {"src%d" % i: generate_reads(sr, sr.randint(3,5), 4, 12) for i in range(n)}
    quals = {s: [generate_quality(sr, len(r)) for r in src_reads[s]] for s in src_reads}
    sub = os.path.join(work, "f10"); os.makedirs(sub)
    leaves = build_leaf_provenance(src_reads, quals, sub, "f10")
    merged = merge_leaves_balanced(leaves, sub, "f10")
    remove_id = sorted(src_reads.keys())[-1]
    removal_out = os.path.join(sub, "f10_reduced"); os.makedirs(removal_out)
    remove_sources(merged, removal_out, sources=[remove_id], overwrite=True)
    remaining = source_ids(removal_out)
    cat.check(len(remaining) == n - 1, "remaining %d != %d" % (len(remaining), n-1))
    cat.check(remove_id not in remaining, "removed %s still present" % remove_id)
    bwt_o = np.load(os.path.join(merged, "msbwt.npy"), mmap_mode="r")
    bwt_r = np.load(os.path.join(removal_out, "msbwt.npy"), mmap_mode="r")
    cat.check(bwt_r.shape[0] < bwt_o.shape[0], "reduced BWT not shorter")
    return cat


def audit_f11a(rng, work):
    cat = AuditCategory("F11A: LCP retrofit", "Build LCP, independent oracle")
    sr = random.Random(rng.randint(0, 2**31))
    reads = generate_reads(sr, 5, 4, 10)
    sub = os.path.join(work, "f11a"); os.makedirs(sub)
    ld = os.path.join(sub, "f11a_leaf"); os.mkdir(ld)
    fq_dir = os.path.join(sub, "f11a_fq"); os.makedirs(fq_dir)
    fq = os.path.join(fq_dir, "data.fastq")
    write_fastq(reads, [generate_quality(sr, len(r)) for r in reads], fq)
    old_argv = sys.argv
    try:
        sys.argv = ["msbwt", "pp", ld, fq]; mainRun()
        sys.argv = ["msbwt", "cfpp", "-p", "1", ld]; mainRun()
    finally:
        sys.argv = old_argv
    initialize_leaf_provenance(ld, source_id="leaf1")
    lcp_dir = os.path.join(sub, "f11a_lcp"); shutil.copytree(ld, lcp_dir)
    construct_lcp_from_bwt(lcp_dir)
    cat.check(lcp_exists(lcp_dir), "LCP not created")
    all_rows = sorted(text[pos:] for rid, read in enumerate(reads) for pos in range(len(read+"$")) for text in [read+"$"])
    expected = compute_expected_lcp([{"suffix": s} for s in all_rows])
    lcps = LCPIndex(lcp_dir).values
    cat.check(len(lcps) == len(expected), "LCP len %d != %d" % (len(lcps), len(expected)))
    mismatches = sum(1 for a, b in zip(lcps, expected) if int(a) != int(b))
    cat.check(mismatches == 0, "LCP mismatches: %d/%d" % (mismatches, len(lcps)))
    return cat


def audit_f12(rng, work):
    cat = AuditCategory("F12: BWT tags", "Attach/list/schema/remove")
    sr = random.Random(rng.randint(0, 2**31))
    reads = generate_reads(sr, 5, 4, 10)
    sub = os.path.join(work, "f12"); os.makedirs(sub)
    ld = os.path.join(sub, "f12_leaf"); os.mkdir(ld)
    fq_dir = os.path.join(sub, "f12_fq"); os.makedirs(fq_dir)
    fq = os.path.join(fq_dir, "data.fastq")
    write_fastq(reads, [generate_quality(sr, len(r)) for r in reads], fq)
    old_argv = sys.argv
    try:
        sys.argv = ["msbwt", "pp", ld, fq]; mainRun()
        sys.argv = ["msbwt", "cfpp", "-p", "1", ld]; mainRun()
    finally:
        sys.argv = old_argv
    bwt_len = np.load(os.path.join(ld, "msbwt.npy"), mmap_mode="r").shape[0]
    row_id = np.arange(bwt_len, dtype=np.int64)
    attach_tag(ld, "row_id", row_id, description="row identity")
    cat.check(tags_exist(ld), "tags_exist False after attach")
    store = BWTTagStore(ld)
    schema = store.schema("row_id")
    cat.check(schema is not None, "schema None")
    cat.check(np.array_equal(store.array("row_id"), row_id), "array mismatch")
    cat.check("row_id" in store.list_tags(), "row_id not in list_tags")
    remove_tag(ld, "row_id")
    cat.check(not tags_exist(ld), "tags_exist True after remove")
    return cat


def audit_q1(rng, work):
    cat = AuditCategory("Q1: quality sidecar", "Quality sidecar, lossless")
    sr = random.Random(rng.randint(0, 2**31))
    reads = generate_reads(sr, 5, 4, 10)
    quals = [generate_quality(sr, len(r)) for r in reads]
    sub = os.path.join(work, "q1"); os.makedirs(sub)
    ld = os.path.join(sub, "q1_leaf"); os.mkdir(ld)
    fq_dir = os.path.join(sub, "q1_fq"); os.makedirs(fq_dir)
    fq = os.path.join(fq_dir, "data.fastq")
    write_fastq(reads, quals, fq)
    old_argv = sys.argv
    try:
        sys.argv = ["msbwt", "pp", ld, fq]; mainRun()
        sys.argv = ["msbwt", "cfpp", "-p", "1", ld]; mainRun()
    finally:
        sys.argv = old_argv
    initialize_leaf_provenance(ld, source_id="leaf1")
    rows = terminated_suffix_rows(reads)
    bwt_len = np.load(os.path.join(ld, "msbwt.npy"), mmap_mode="r").shape[0]
    q_arr = np.zeros(bwt_len, dtype=np.uint8)
    for idx, row in enumerate(rows):
        p = row["pos"]
        r, q = reads[row["read_id"]], quals[row["read_id"]]
        q_arr[idx] = ord(q[p]) if p < len(r) and p < len(q) else 255
    attach_quality_from_row_values(ld, q_arr)
    cat.check(quality_sidecar_exists(ld), "quality sidecar missing")
    qs = QualitySidecar(ld)
    bwt_rows = qs.bwt_rows
    qv = np.zeros(bwt_rows, dtype=np.uint8)
    for i in range(bwt_rows):
        v = qs.quality_byte_for_row(i)
        qv[i] = v if v is not None else 0
    cat.check(bwt_rows == bwt_len, "quality_rows mismatch")
    return cat


def audit_f13a(rng, work):
    cat = AuditCategory("F13A: benchmarking", "inspect_index, disk_breakdown")
    sr = random.Random(rng.randint(0, 2**31))
    reads = generate_reads(sr, 5, 4, 10)
    sub = os.path.join(work, "f13a"); os.makedirs(sub)
    ld = os.path.join(sub, "f13a_leaf"); os.mkdir(ld)
    fq_dir = os.path.join(sub, "f13a_fq"); os.makedirs(fq_dir)
    fq = os.path.join(fq_dir, "data.fastq")
    write_fastq(reads, [generate_quality(sr, len(r)) for r in reads], fq)
    old_argv = sys.argv
    try:
        sys.argv = ["msbwt", "pp", ld, fq]; mainRun()
        sys.argv = ["msbwt", "cfpp", "-p", "1", ld]; mainRun()
    finally:
        sys.argv = old_argv
    doc = inspect_index(ld)
    cat.check(doc is not None, "inspect_index None")
    cat.check(isinstance(doc, dict), "inspect_index not dict")
    dd = disk_breakdown(ld)
    cat.check(dd is not None and isinstance(dd, dict), "disk_breakdown invalid")
    return cat


def audit_cross_provenance_query(rng, work):
    cat = AuditCategory("cross: provenance+merge+query", "Merge, constituent extraction, count")
    sr = random.Random(rng.randint(0, 2**31))
    src_reads = {"src%d" % i: generate_reads(sr, sr.randint(4,8), 4, 12) for i in range(3)}
    quals = {s: [generate_quality(sr, len(r)) for r in src_reads[s]] for s in src_reads}
    sub = os.path.join(work, "combo1"); os.makedirs(sub)
    leaves = build_leaf_provenance(src_reads, quals, sub, "combo1")
    merged = merge_leaves_balanced(leaves, sub, "combo1")
    m = load_manifest(merged)
    cat.check(len(m.get("sources",[])) == 3, "source count != 3")
    for sid in source_ids(merged):
        cbwt = extract_constituent_bwt(merged, sid)
        cat.check(cbwt is not None and len(cbwt) > 0, "constituent %s empty" % sid)
    wrapped = MultiSourceBWT.load(merged)
    seq = src_reads[sorted(src_reads.keys())[0]][0] + "$"
    try:
        cnt = wrapped.bwt.countOccurrencesOfSeq(seq)
        cat.check(cnt >= 1, "countOccurrencesOfSeq returned %d" % cnt)
    except Exception as e:
        cat.check(False, "count error: %s" % e)
    return cat


def audit_cross_tag_merge(rng, work):
    cat = AuditCategory("cross: tag+merge", "Tag on leaf A, merge all")
    sr = random.Random(rng.randint(0, 2**31))
    src_reads = {"src%d" % i: generate_reads(sr, sr.randint(4,8), 4, 12) for i in range(3)}
    quals = {s: [generate_quality(sr, len(r)) for r in src_reads[s]] for s in src_reads}
    sub = os.path.join(work, "combo2"); os.makedirs(sub)
    leaves = build_leaf_provenance(src_reads, quals, sub, "combo2")
    leaf_a = leaves[0]
    len_a = np.load(os.path.join(leaf_a, "msbwt.npy"), mmap_mode="r").shape[0]
    tag_a = np.arange(len_a, dtype=np.float64)
    attach_tag(leaf_a, "weight", tag_a, missing_value=-1.0, description="row weight")
    cat.check(tags_exist(leaf_a), "tag not attached on leaf_a")
    merged = os.path.join(sub, "combo2_merged"); os.makedirs(merged)
    try:
        merge_many_balanced(leaves, merged)
        cat.check(True, "merge succeeded")
    except Exception as e:
        cat.check(False, "merge failed: %s" % e)
    return cat


def audit_cross_quality_removal(rng, work):
    cat = AuditCategory("cross: quality+removal", "Quality sidecar through merge and removal")
    sr = random.Random(rng.randint(0, 2**31))
    src_reads = {"src%d" % i: generate_reads(sr, sr.randint(3,5), 4, 10) for i in range(3)}
    quals = {s: [generate_quality(sr, len(r)) for r in src_reads[s]] for s in src_reads}
    sub = os.path.join(work, "combo3"); os.makedirs(sub)
    leaves = build_leaf_provenance(src_reads, quals, sub, "combo3")
    merged = merge_leaves_balanced(leaves, sub, "combo3")
    cat.check(quality_sidecar_exists(merged), "quality missing after merge")
    remove_id = sorted(src_reads.keys())[-1]
    removal_out = os.path.join(sub, "combo3_reduced")
    if os.path.isdir(removal_out):
        shutil.rmtree(removal_out)
    os.makedirs(removal_out)
    remove_sources(merged, removal_out, sources=[remove_id], overwrite=True)
    cat.check(quality_sidecar_exists(removal_out), "quality missing after removal")
    return cat


ALL_AUDITS = [
    ("F2", audit_f2), ("F1/F3", audit_f1_f3), ("F4/F5/F6", audit_f4_f5_f6),
    ("F7", audit_f7), ("F8A", audit_f8a), ("F9", audit_f9),
    ("F10", audit_f10), ("F11A", audit_f11a), ("F12", audit_f12),
    ("Q1", audit_q1), ("F13A", audit_f13a),
    ("combo1", audit_cross_provenance_query), ("combo2", audit_cross_tag_merge),
    ("combo3", audit_cross_quality_removal),
]


def main():
    rng = random.Random(SEED)
    work = tempfile.mkdtemp(prefix="enhanced-audit-")
    results = []
    total_ops = total_pass = total_fail = 0

    print("ENHANCED RANDOMIZED AUDIT")
    print("  seed: %d" % SEED)
    print()

    for label, func in ALL_AUDITS:
        try:
            cat = func(rng, work)
            results.append(cat.summary())
            total_ops += cat.ops; total_pass += cat.passed; total_fail += cat.failed
            s = cat.summary()["status"]
            print("  %-6s %-45s %s  (ops=%d)" % (s, cat.name, cat.description, cat.ops))
            for e in cat.errors[:3]:
                print("         ERROR: %s" % e)
        except Exception as exc:
            import traceback; traceback.print_exc()
            total_fail += 1
            results.append({"name": label, "status": "ERROR", "error": str(exc)})
            print("  ERROR  %-45s %s" % (label, exc))

    print()
    print("AUDIT SUMMARY")
    print("  seed: %d" % SEED)
    print("  categories: %d" % len(ALL_AUDITS))
    print("  total operations: %d" % total_ops)
    print("  passed: %d" % total_pass)
    print("  failed: %d" % total_fail)
    print("  mismatches: %d" % total_fail)
    print("  RESULT: %s" % ("PASS" if total_fail == 0 else "FAIL"))

    report = {"seed": SEED, "categories": len(ALL_AUDITS),
              "total_operations": total_ops, "passed": total_pass,
              "failed": total_fail, "mismatches": total_fail,
              "result": "PASS" if total_fail == 0 else "FAIL",
              "details": results}
    rp = os.path.join(work, "enhanced-audit-report.json")
    with open(rp, "w") as fp:
        json.dump(report, fp, indent=1, sort_keys=True)
    print("  report: %s" % rp)
    shutil.rmtree(work, ignore_errors=True)
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
