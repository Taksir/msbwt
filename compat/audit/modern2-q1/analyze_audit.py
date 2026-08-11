#!/usr/bin/env python3
"""Three-way differential analysis for the modern2 quality audit Q1.

Consumes the raw results JSON written by ``wsl/execute.py`` for the frozen
oracle and modern2 implementations plus the generated corpus, and produces:

- per-case classification A/B/C/D/E on the strongest correct invariant
  (byte payload for uniform inputs, where the historical ordering is
  uniquely determined; canonical semantic signature -- symbol totals,
  sorted backward-search counts, sorted LF recovery multiset -- for
  nonuniform inputs, where the historical ordering has a documented
  representation nuance);
- p1/p2 process-count, gzip, cffq, compression round trip, merge,
  reader/FM/query/recovery, permutation and cache-regeneration checks;
- a deterministic summary (JSON) and a human-readable report.

No production code is modified; every mismatch is recorded with the exact
case id and category.
"""

from __future__ import annotations

import base64
import json
from collections import Counter
from typing import Any, Dict, List, Optional

from audit_core import (
    SYMBOLS,
    backward_counts_many,
    decode_rle,
    expected_substring_counts,
    expected_symbol_counts,
    fm_rank_row,
    lf_recover_reads,
    rotation_sort_bwt,
    substring_count_in_reads,
)


def payload_from(entry: Optional[Dict[str, Any]]) -> Optional[bytes]:
    if not entry or "payload_b64" not in entry:
        return None
    return base64.b64decode(entry["payload_b64"])


def semantic_signature(payload: bytes, reads: List[str]) -> Dict[str, Any]:
    """Ordering-independent canonical semantics of a collection BWT."""
    counts = expected_symbol_counts(reads)
    expected = expected_substring_counts(reads)
    backward = backward_counts_many(payload, sorted(expected))
    recovered = lf_recover_reads(payload)
    return {
        "symbol_counts": counts,
        "backward_counts": backward,
        "recovered_sorted": recovered,
    }


def semantic_matches(signature: Dict[str, Any], reads: List[str]) -> bool:
    return signature == semantic_signature_make(reads)


def semantic_signature_make(reads: List[str]) -> Dict[str, Any]:
    """The oracle's expected semantic signature for a read multiset."""
    counts = expected_symbol_counts(reads)
    expected = expected_substring_counts(reads)
    return {
        "symbol_counts": counts,
        "backward_counts": dict(sorted(expected.items())),
        "recovered_sorted": sorted(reads),
    }


def classify3(frozen: Optional[Any], modern2: Optional[Any],
              oracle: Optional[Any]) -> str:
    if frozen is not None and modern2 is not None and oracle is not None:
        if frozen == modern2 and modern2 == oracle:
            return "A"
        if frozen == modern2:
            return "B"
        if modern2 == oracle:
            return "C"
        if frozen == oracle:
            return "D"
        return "E"
    return "E-incomplete"


class Analyzer(object):
    def __init__(self, corpus: Dict[str, Any], frozen: Dict[str, Any],
                 modern2: Dict[str, Any]):
        self.corpus = corpus
        self.cases = {case["id"]: case for case in corpus["cases"]}
        self.frozen = frozen
        self.modern2 = modern2
        self.results: Dict[str, Any] = {
            "construction": {},
            "process_count": {},
            "gzip": {},
            "cffq": {},
            "compress": {},
            "merge": {},
            "reader": {},
            "permute": {},
            "classifications": {},
            "failures": [],
        }
        self.counts: Dict[str, int] = {}
        self.family_counts: Dict[str, int] = {}

    def bump(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1

    def family_bump(self, family: str) -> None:
        self.family_counts[family] = self.family_counts.get(family, 0) + 1

    def record_failure(self, case_id: str, family: str, detail: str,
                       kind: str = "observation") -> None:
        self.results["failures"].append({
            "case": case_id,
            "family": family,
            "kind": kind,
            "detail": detail,
        })

    # ------------------------------------------------------------------
    def analyze_construction(self) -> None:
        constructs = {}
        for case_id, case in sorted(self.cases.items()):
            if case.get("merge_case"):
                continue
            f = self.frozen.get("construct", {}).get(case_id, {})
            m = self.modern2.get("construct", {}).get(case_id, {})
            if f.get("exit") == 0 and m.get("exit") == 0:
                constructs[case_id] = (f, m)
            else:
                self.record_failure(case_id, "construction",
                                    "exit codes frozen=%s modern2=%s" % (
                                        f.get("exit"), m.get("exit")),
                                    kind="harness")
        for case_id in sorted(constructs):
            f, m = constructs[case_id]
            case = self.cases[case_id]
            reads = case["reads"]
            oracle_payload = rotation_sort_bwt(reads)
            fp = payload_from(f.get("p1"))
            mp = payload_from(m.get("p1"))
            entry: Dict[str, Any] = {
                "category": case["category"],
                "uniform": case["uniform"],
            }
            self.family_bump("construction")
            if case["uniform"]:
                entry["byte_3way"] = classify3(fp, mp, oracle_payload)
                entry["byte_frozen_vs_modern2"] = fp == mp
                entry["byte_frozen_vs_oracle"] = fp == oracle_payload
                entry["byte_modern2_vs_oracle"] = mp == oracle_payload
                entry["classification"] = entry["byte_3way"]
            else:
                f_sem = semantic_signature(fp, reads)
                m_sem = semantic_signature(mp, reads)
                o_sem = semantic_signature_make(reads)
                entry["semantic_frozen_ok"] = f_sem == o_sem
                entry["semantic_modern2_ok"] = m_sem == o_sem
                entry["semantic_frozen_vs_modern2"] = f_sem == m_sem
                entry["classification"] = classify3(f_sem, m_sem, o_sem)
            self.bump("classification_" + entry["classification"])
            entry["classification"] = entry["classification"]
            self.results["construction"][case_id] = entry
            # p1 vs p2 process-count invariance
            pc: Dict[str, Any] = {}
            for impl, data in (("frozen", f), ("modern2", m)):
                p1 = payload_from(data.get("p1"))
                p2_entry = data.get("p2")
                if isinstance(p2_entry, dict) and p2_entry.get("exit") == 0:
                    p2 = payload_from(p2_entry)
                    pc[impl] = p1 == p2
                    if p1 != p2:
                        self.record_failure(case_id, "process_count",
                                            "%s p1 payload differs from p2" % impl)
                elif isinstance(p2_entry, dict):
                    pc[impl] = "failed:" + str(p2_entry.get("exit"))
                else:
                    pc[impl] = "not-run"
            if pc:
                self.results["process_count"][case_id] = pc
                self.family_bump("process_count")

    # ------------------------------------------------------------------
    def analyze_gzip(self) -> None:
        for case_id, case in sorted(self.cases.items()):
            if case.get("merge_case"):
                continue
            plain = self.frozen.get("construct", {}).get(case_id, {})
            gz_f = self.frozen.get("gzip", {}).get(case_id, {})
            gz_m = self.modern2.get("gzip", {}).get(case_id, {})
            if not gz_f and not gz_m:
                continue
            self.family_bump("gzip")
            f_ok = (gz_f.get("exit") == 0
                    and payload_from(gz_f.get("p1")) == payload_from(plain.get("p1")))
            m_ok = (gz_m.get("exit") == 0
                    and payload_from(gz_m.get("p1")) == payload_from(plain.get("p1")))
            fp = payload_from(gz_f.get("p1"))
            mp = payload_from(gz_m.get("p1"))
            oracle_payload = rotation_sort_bwt(case["reads"])
            entry = {
                "frozen_gz_equals_plain": f_ok,
                "modern2_gz_equals_plain": m_ok,
                "classification": classify3(
                    fp if case["uniform"] else (fp == oracle_payload),
                    mp if case["uniform"] else (mp == oracle_payload),
                    oracle_payload if case["uniform"] else True),
            }
            if case["uniform"]:
                entry["gz_3way_bytes"] = classify3(fp, mp, oracle_payload)
                entry["classification"] = entry["gz_3way_bytes"]
            else:
                f_sem = semantic_signature(fp, case["reads"])
                m_sem = semantic_signature(mp, case["reads"])
                o_sem = semantic_signature_make(case["reads"])
                entry["gz_3way_semantics"] = classify3(f_sem, m_sem, o_sem)
                entry["classification"] = entry["gz_3way_semantics"]
            self.bump("classification_" + entry["classification"])
            self.results["gzip"][case_id] = entry
            if not (f_ok and m_ok):
                self.record_failure(case_id, "gzip",
                                    "gzip-vs-plain mismatch frozen=%s modern2=%s" % (
                                        f_ok, m_ok))

    # ------------------------------------------------------------------
    def analyze_cffq(self) -> None:
        for case_id, case in sorted(self.cases.items()):
            if case.get("merge_case"):
                continue
            f = self.frozen.get("cffq", {}).get(case_id, {})
            m = self.modern2.get("cffq", {}).get(case_id, {})
            if not f and not m:
                continue
            self.family_bump("cffq")
            plain_f = payload_from(self.frozen.get("construct", {}).get(case_id, {}).get("p1"))
            plain_m = payload_from(self.modern2.get("construct", {}).get(case_id, {}).get("p1"))
            entry: Dict[str, Any] = {"category": case["category"]}
            for proc in ("p1", "p2"):
                f_c = f.get(proc, {})
                m_c = m.get(proc, {})
                if isinstance(f_c, dict) and f_c.get("exit") == 0 and "msbwt.npy" in f_c:
                    f_cffq = payload_from(f_c["msbwt.npy"])
                    entry["frozen_%s_eq_construct" % proc] = f_cffq == plain_f
                if isinstance(m_c, dict) and m_c.get("exit") == 0 and "msbwt.npy" in m_c:
                    m_cffq = payload_from(m_c["msbwt.npy"])
                    entry["modern2_%s_eq_construct" % proc] = m_cffq == plain_m
            fp = payload_from(f.get("p1", {}).get("msbwt.npy", {})) if f.get("p1", {}).get("exit") == 0 else None
            mp = payload_from(m.get("p1", {}).get("msbwt.npy", {})) if m.get("p1", {}).get("exit") == 0 else None
            if case["uniform"]:
                oracle = rotation_sort_bwt(case["reads"])
                entry["classification"] = classify3(fp, mp, oracle)
            else:
                f_sem = semantic_signature(fp, case["reads"])
                m_sem = semantic_signature(mp, case["reads"])
                o_sem = semantic_signature_make(case["reads"])
                entry["classification"] = classify3(f_sem, m_sem, o_sem)
            self.bump("classification_" + entry["classification"])
            self.results["cffq"][case_id] = entry

    # ------------------------------------------------------------------
    def analyze_compress(self) -> None:
        for case_id, case in sorted(self.cases.items()):
            if case.get("merge_case"):
                continue
            f = self.frozen.get("compress", {}).get(case_id, {})
            m = self.modern2.get("compress", {}).get(case_id, {})
            if not f and not m:
                continue
            self.family_bump("compress")
            original = payload_from(
                self.frozen.get("construct", {}).get(case_id, {}).get("p1"))
            if original is None:
                original = payload_from(
                    self.modern2.get("construct", {}).get(case_id, {}).get("p1"))
            entry: Dict[str, Any] = {}
            for proc in ("1", "2"):
                for impl, data in (("frozen", f), ("modern2", m)):
                    comp = data.get("compress_p" + proc)
                    decomp = data.get("decompress_p" + proc)
                    comp_ok = (isinstance(comp, dict) and comp.get("exit") == 0
                               and "comp_msbwt.npy" in comp)
                    if comp_ok:
                        rle = payload_from(comp["comp_msbwt.npy"])
                        _, decoded = decode_rle(rle)
                        entry["%s_p%s_decode_ok" % (impl, proc)] = bytes(decoded) == original
                        entry["%s_p%s_compress_exit" % (impl, proc)] = 0
                    else:
                        entry["%s_p%s_compress_exit" % (impl, proc)] = (
                            comp.get("exit") if isinstance(comp, dict) else "missing")
                    if isinstance(decomp, dict) and decomp.get("exit") == 0:
                        back = payload_from(decomp.get("msbwt.npy"))
                        entry["%s_p%s_roundtrip_ok" % (impl, proc)] = back == original
                        entry["%s_p%s_decompress_exit" % (impl, proc)] = 0
                    else:
                        entry["%s_p%s_decompress_exit" % (impl, proc)] = (
                            decomp.get("exit") if isinstance(decomp, dict) else "missing")
                        if impl == "frozen" and isinstance(decomp, dict):
                            # DOCUMENTED LEGACY CONTRACT (tracker #1 /
                            # COMPATIBILITY.md entry 1): frozen decompression
                            # deterministically raises the uint64/int float64
                            # slice TypeError at MultiStringBWT.py:662.  A
                            # matching failure is the EXPECTED result; a
                            # different failure would be a new finding.
                            log = decomp.get("log_tail", "")
                            entry["%s_p%s_decompress_expected_failure" % (impl, proc)] = (
                                decomp.get("exit") == 1
                                and "TypeError: slice indices must be integers or None or have an __index__ method" in log)
                        else:
                            entry["%s_p%s_decompress_expected_failure" % (impl, proc)] = False
                        entry["%s_p%s_roundtrip_ok" % (impl, proc)] = False
            if f.get("compress_p1") and f.get("compress_p2"):
                c1 = payload_from(f["compress_p1"].get("comp_msbwt.npy", {}))
                c2 = payload_from(f["compress_p2"].get("comp_msbwt.npy", {}))
                entry["frozen_p1_eq_p2"] = c1 == c2
            if m.get("compress_p1") and m.get("compress_p2"):
                c1 = payload_from(m["compress_p1"].get("comp_msbwt.npy", {}))
                c2 = payload_from(m["compress_p2"].get("comp_msbwt.npy", {}))
                entry["modern2_p1_eq_p2"] = c1 == c2
            ok = all(entry.get(k) is True for k in entry
                     if k.endswith("_ok") or k.endswith("_eq_p2"))
            self.results["compress"][case_id] = entry
            if not ok:
                bad = [k for k, v in entry.items() if v is False]
                # the frozen decompression failure is a documented contract;
                # only genuinely failed checks are findings
                findings = [k for k in bad
                            if not k.startswith("frozen_p") or
                            not k.endswith("_roundtrip_ok")]
                if findings:
                    self.record_failure(case_id, "compress", "failed checks: %s" % findings)
            # the documented frozen decompression failure contract must hold
            for key in sorted(entry):
                if key.startswith("frozen_p") and key.endswith("decompress_expected_failure"):
                    self.family_bump("frozen_decompress_contract")
                    if not entry[key]:
                        self.record_failure(case_id, "compress",
                                            "%s did not match the documented contract" % key)

    # ------------------------------------------------------------------
    def analyze_merge(self) -> None:
        for pair_id, pair in sorted(self.ops_merge_pairs().items()):
            f = self.frozen.get("merge", {}).get(pair_id, {})
            m = self.modern2.get("merge", {}).get(pair_id, {})
            if not f and not m:
                continue
            self.family_bump("merge")
            reads = pair["a_reads"] + pair["b_reads"]
            clean_f = payload_from(f.get("union_clean", {}).get("p1"))
            clean_m = payload_from(m.get("union_clean", {}).get("p1"))
            entry: Dict[str, Any] = {"category": pair["category"],
                                     "uniform": pair["uniform"]}
            f_merges = {}
            m_merges = {}
            for proc in ("p1", "p2"):
                fp = payload_from(f.get("merge_" + proc, {}).get("msbwt.npy"))
                mp = payload_from(m.get("merge_" + proc, {}).get("msbwt.npy"))
                if fp is not None:
                    f_merges[proc] = fp
                    entry["frozen_%s_eq_clean" % proc] = fp == clean_f
                if mp is not None:
                    m_merges[proc] = mp
                    entry["modern2_%s_eq_clean" % proc] = mp == clean_m
            if pair["uniform"]:
                oracle = rotation_sort_bwt(reads)
                fp = f_merges.get("p2") or f_merges.get("p1")
                mp = m_merges.get("p2") or m_merges.get("p1")
                entry["classification"] = classify3(fp, mp, oracle)
            else:
                f_sem = (f_merges and semantic_signature(
                    f_merges["p2" if "p2" in f_merges else "p1"], reads))
                m_sem = (m_merges and semantic_signature(
                    m_merges["p2" if "p2" in m_merges else "p1"], reads))
                o_sem = semantic_signature_make(reads)
                if f_sem and m_sem:
                    entry["classification"] = classify3(f_sem, m_sem, o_sem)
                else:
                    entry["classification"] = "E-incomplete"
            if "p1" in m_merges and "p2" in m_merges:
                entry["modern2_p1_eq_p2"] = m_merges["p1"] == m_merges["p2"]
            if len(f_merges) == 2:
                entry["frozen_p1_eq_p2"] = f_merges["p1"] == f_merges["p2"]
            if pair["uniform"]:
                if clean_f != clean_m or (clean_f is not None and clean_f != rotation_sort_bwt(reads)):
                    self.record_failure(pair_id, "merge",
                                        "clean union mismatch frozen/modern2/oracle")
            self.bump("classification_" + entry["classification"])
            self.results["merge"][pair_id] = entry

    def ops_merge_pairs(self) -> Dict[str, Any]:
        # merge pair read lists come from the corpus merge_case entries
        pairs: Dict[str, Any] = {}
        for case_id, case in self.cases.items():
            if case.get("merge_pair"):
                pair_id = case["merge_pair"]
                role = case["merge_role"]
                pairs.setdefault(pair_id, {"a_reads": [], "b_reads": [],
                                           "category": case["category"],
                                           "uniform": case["uniform"]})
                if role == "a":
                    pairs[pair_id]["a_reads"] = case["reads"]
                elif role == "b":
                    pairs[pair_id]["b_reads"] = case["reads"]
                elif role == "u":
                    pairs[pair_id]["u_reads"] = case["reads"]
        return pairs

    # ------------------------------------------------------------------
    def analyze_reader(self) -> None:
        f_reader = self.frozen.get("reader", {})
        m_reader = self.modern2.get("reader", {})
        if not isinstance(f_reader, dict):
            f_reader = {}
        if not isinstance(m_reader, dict):
            m_reader = {}
        for case_id in sorted(set(f_reader) | set(m_reader)):
            case = self.cases[case_id]
            entry: Dict[str, Any] = {}
            self.family_bump("reader")
            f_r = f_reader.get(case_id, {})
            m_r = m_reader.get(case_id, {})
            original = payload_from(
                self.frozen.get("construct", {}).get(case_id, {}).get("p1"))
            if original is None:
                original = payload_from(
                    self.modern2.get("construct", {}).get(case_id, {}).get("p1"))
            if original is not None:
                for impl, data in (("frozen", f_r), ("modern2", m_r)):
                    if data.get("load_error"):
                        entry[impl + "_load_error"] = data["load_error"]
                        continue
                    ok = True
                    detail = []
                    for position, value in data.get("char_at", {}).items():
                        if value == original[int(position)]:
                            continue
                        ok = False
                        detail.append("char@%s" % position)
                    for position, row in data.get("fm_at", {}).items():
                        if row == fm_rank_row(original, int(position)):
                            continue
                        ok = False
                        detail.append("fm@%s" % position)
                    for query, value in data.get("queries", {}).items():
                        if isinstance(value, dict):
                            ok = False
                            detail.append("query-error:%s" % query)
                            continue
                        expected = substring_count_in_reads(case["reads"], query)
                        if value == expected:
                            continue
                        ok = False
                        detail.append("query:%s=%s!=%s" % (query, value, expected))
                    recovered = [s for s in data.get("recovery", [])
                                 if not isinstance(s, dict)]
                    expected_recovery = sorted(r + "$" for r in case["reads"])
                    if sorted(recovered) != expected_recovery:
                        ok = False
                        detail.append("recovery-multiset")
                    entry[impl + "_ok"] = ok
                    entry[impl + "_detail"] = detail
                    if data.get("regen"):
                        regen_ok = data["regen"].get("identical") is True
                        entry[impl + "_regen_ok"] = regen_ok
                        if not regen_ok:
                            ok = False
                            detail.append("regen")
                    if not ok:
                        self.record_failure(case_id, "reader",
                                            "%s: %s" % (impl, detail))
            self.results["reader"][case_id] = entry
        # cross-encoding RLE vs byte reader comparison
        for case_id in sorted(set(f_reader) | set(m_reader)):
            case = self.cases[case_id]
            entry = self.results["reader"][case_id]
            if case_id not in self.ops_reader_rle():
                continue
            self.family_bump("reader_rle_cross")
            byte_q = m_reader.get(case_id, {}).get("queries", {})
            rle_q = self.modern2.get("reader", {}).get(case_id, {}).get("queries", {})
            if byte_q and rle_q:
                same = all(byte_q.get(q) == rle_q.get(q) for q in byte_q)
                entry["byte_vs_rle_queries_same"] = same
                if not same:
                    self.record_failure(case_id, "reader",
                                        "byte-vs-RLE query mismatch")

    def ops_reader_rle(self) -> List[str]:
        return self.modern2.get("reader_rle_cases", [])

    # ------------------------------------------------------------------
    def analyze_permute(self) -> None:
        # permute results live under frozen/modern2 "permute" keyed by fastq
        f_p = self.frozen.get("permute", {})
        m_p = self.modern2.get("permute", {})
        permute_ops = self.modern2.get("permute_ops", [])
        for perm in permute_ops:
            fastq = perm["fastq"]
            case_id = perm["case"]
            case = self.cases[case_id]
            self.family_bump("permute")
            base_f = payload_from(self.frozen.get("construct", {}).get(case_id, {}).get("p1"))
            base_m = payload_from(self.modern2.get("construct", {}).get(case_id, {}).get("p1"))
            pf = payload_from(f_p.get(fastq, {}).get("p1"))
            pm = payload_from(m_p.get(fastq, {}).get("p1"))
            entry: Dict[str, Any] = {}
            if case["uniform"]:
                entry["frozen_perm_eq_base"] = pf == base_f
                entry["modern2_perm_eq_base"] = pm == base_m
            else:
                f_ok = (pf is not None and semantic_signature(pf, case["reads"])
                        == semantic_signature_make(case["reads"]))
                m_ok = (pm is not None and semantic_signature(pm, case["reads"])
                        == semantic_signature_make(case["reads"]))
                entry["frozen_perm_semantic_ok"] = f_ok
                entry["modern2_perm_semantic_ok"] = m_ok
            self.results["permute"][fastq] = entry
            if not all(v is True for v in entry.values()):
                self.record_failure(case_id, "permute",
                                    "%s: %s" % (fastq, entry))

    # ------------------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        self.analyze_construction()
        self.analyze_gzip()
        self.analyze_cffq()
        self.analyze_compress()
        self.analyze_merge()
        self.analyze_reader()
        self.analyze_permute()
        classification_counts = {k: v for k, v in sorted(self.counts.items())
                                 if k.startswith("classification_")}
        self.results["classification_counts"] = classification_counts
        self.results["family_counts"] = dict(sorted(self.family_counts.items()))
        self.results["total_failures"] = len(self.results["failures"])
        return self.results


def build_summary(results: Dict[str, Any], corpus: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic summary used for the double-run equality gate."""
    return {
        "seed": corpus["seed"],
        "family_counts": results["family_counts"],
        "classification_counts": results["classification_counts"],
        "total_failures": results["total_failures"],
        "failures": sorted(
            [{"case": f["case"], "family": f["family"], "kind": f["kind"],
              "detail": f["detail"]} for f in results["failures"]],
            key=lambda f: (f["case"], f["family"])),
    }
