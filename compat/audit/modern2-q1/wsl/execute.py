#!/usr/bin/env python3
"""WSL-side executor for the modern2 quality audit Q1.

Runs the msbwt CLI (either the frozen oracle tree or the modern2 package
tree) for the audit test families and records implementation-independent
results as JSON:

  construct  -- pp + cfpp -p 1 (and -p 2 for the flagged subset)
  cffq       -- direct FASTQ wrapper: cffq -p 1 / -p 2
  gzip       -- pp + cfpp from deterministic .gz inputs
  compress   -- compress -p 1 / -p 2 + decompress -p 1 / -p 2 round trips
  merge      -- construct A, construct B, merge (frozen: -p 2 only;
                modern2: -p 1 and -p 2), plus a clean union construction
  reader     -- batched Python-2 reader probe on disposable copies
                (char-at, FM rows, queries, recovery, cache regeneration)
  permute    -- construction from permuted FASTQ record orders

Every CLI invocation logs to --work/logs/<impl>/<op>-<name>.log.  Output
directories are always created empty (the frozen CLI rejects pre-existing
non-empty output directories).  The executor never writes into the
repository tree.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from audit_core import (  # noqa: E402
    json_dump,
    json_load,
    parse_npy_v1,
    sha256_bytes,
    sha256_file,
)


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--impl", required=True, choices=("frozen", "modern2"))
    parser.add_argument("--tree", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--ops", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


class Executor(object):
    def __init__(self, args):
        self.impl = args.impl
        self.tree = args.tree
        self.python = args.python
        self.work = args.work
        self.corpus = json_load(args.corpus)
        self.ops = json_load(args.ops)
        self.fastq_dir = os.path.join(args.work, "fastqs")
        self.log_dir = os.path.join(args.work, "logs", args.impl)
        self.run_dir = os.path.join(args.work, "runs", args.impl)
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.run_dir, exist_ok=True)
        self.results = {"impl": self.impl}
        self.env = dict(os.environ)
        self.env.update({
            "PYTHONPATH": self.tree,
            "PYTHONNOUSERSITE": "1",
            "PYTHONHASHSEED": "0",
            "TZ": "UTC",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        })

    # ------------------------------------------------------------------
    def run_cli(self, name, *argv):
        """Run one CLI invocation; returns (exit_code, stdout+stderr text)."""
        log_path = os.path.join(self.log_dir, name + ".log")
        cmd = [self.python, "-B", os.path.join(self.tree, "bin", "msbwt")] + list(argv)
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.run(cmd, cwd=self.tree, env=self.env,
                                  stdout=log, stderr=subprocess.STDOUT)
        text = ""
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as log:
                text = log.read()
        except OSError:
            pass
        return proc.returncode, text

    def fresh_dir(self, *parts):
        path = os.path.join(self.run_dir, *parts)
        if os.path.exists(path):
            shutil.rmtree(path)
        os.makedirs(path)
        return path

    def record_npy(self, path):
        raw = open(path, "rb").read()
        parsed = parse_npy_v1(raw)
        return {
            "raw_sha256": sha256_bytes(raw),
            "dtype": parsed["dtype"],
            "shape": parsed["shape"],
            "payload_sha256": sha256_bytes(parsed["payload"]),
            "payload_b64": base64.b64encode(parsed["payload"]).decode("ascii"),
        }

    def fastq_for(self, name):
        return os.path.join(self.fastq_dir, name)

    def case_by_id(self, case_id):
        for case in self.corpus["cases"]:
            if case["id"] == case_id:
                return case
        raise KeyError(case_id)

    # ------------------------------------------------------------------
    # Family 1 + 8: construction (pp + cfpp)
    # ------------------------------------------------------------------
    def construct_one(self, case_id, fastq, label, do_p2):
        case = self.case_by_id(case_id)
        uniform = case["uniform"]
        out = self.fresh_dir("construct", case_id + label)
        args = ["pp"]
        if uniform:
            args.append("-u")
        args += [out, fastq]
        rc, text = self.run_cli("pp-" + case_id + label, *args)
        if rc != 0:
            return {"exit": rc, "log_tail": text[-4000:]}
        cfpp_args = ["cfpp", "-p", "1"]
        if uniform:
            cfpp_args.append("-u")
        cfpp_args.append(out)
        rc, text = self.run_cli("cfpp-" + case_id + label + "-p1", *cfpp_args)
        if rc != 0:
            return {"exit": rc, "log_tail": text[-4000:]}
        primary = self.record_npy(os.path.join(out, "msbwt.npy"))
        result = {
            "exit": 0,
            "uniform": uniform,
            "p1": primary,
            "files": sorted(os.listdir(out)),
        }
        if do_p2:
            cfpp_args = ["cfpp", "-p", "2"]
            if uniform:
                cfpp_args.append("-u")
            cfpp_args.append(out)
            rc, text = self.run_cli("cfpp-" + case_id + label + "-p2", *cfpp_args)
            if rc == 0:
                result["p2"] = self.record_npy(os.path.join(out, "msbwt.npy"))
            else:
                result["p2"] = {"exit": rc, "log_tail": text[-4000:]}
        return result

    def family_construct(self):
        ops = self.ops
        results = {}
        p2_set = set(ops.get("construct_p2", []))
        for case_id in ops.get("construct", []):
            results[case_id] = self.construct_one(
                case_id, self.fastq_for(case_id + ".fastq"), "", case_id in p2_set)
        self.results["construct"] = results

    # ------------------------------------------------------------------
    # Family 2: direct FASTQ wrapper cffq
    # ------------------------------------------------------------------
    def family_cffq(self):
        results = {}
        for case_id in self.ops.get("cffq", []):
            case = self.case_by_id(case_id)
            uniform = case["uniform"]
            for proc in ("1", "2"):
                out = self.fresh_dir("cffq", case_id, "p" + proc)
                args = ["cffq", "-p", proc]
                if uniform:
                    args.append("-u")
                args += [out, self.fastq_for(case_id + ".fastq")]
                rc, text = self.run_cli("cffq-" + case_id + "-p" + proc, *args)
                if rc != 0:
                    results.setdefault(case_id, {})["p" + proc] = {
                        "exit": rc, "log_tail": text[-4000:]}
                    continue
                entry = {"exit": 0, "files": sorted(os.listdir(out))}
                for name in ("msbwt.npy", "comp_msbwt.npy"):
                    path = os.path.join(out, name)
                    if os.path.exists(path):
                        entry[name] = self.record_npy(path)
                results.setdefault(case_id, {})["p" + proc] = entry
        self.results["cffq"] = results

    # ------------------------------------------------------------------
    # Family 3: gzip equivalence (deterministic .gz inputs)
    # ------------------------------------------------------------------
    def family_gzip(self):
        results = {}
        for case_id in self.ops.get("gzip", []):
            results[case_id] = self.construct_one(
                case_id, self.fastq_for(case_id + ".fastq.gz"), "-gz", False)
        self.results["gzip"] = results

    # ------------------------------------------------------------------
    # Family 4: compression round trips (compress/decompress -p 1/-p 2)
    # ------------------------------------------------------------------
    def family_compress(self):
        results = {}
        for case_id in self.ops.get("compress", []):
            src = os.path.join(self.run_dir, "construct", case_id)
            if not os.path.exists(os.path.join(src, "msbwt.npy")):
                continue
            entry = {}
            for proc in ("1", "2"):
                dst = self.fresh_dir("compress", case_id, "p" + proc)
                rc, text = self.run_cli("compress-" + case_id + "-p" + proc,
                                        "compress", "-p", proc, src, dst)
                if rc != 0:
                    entry["compress_p" + proc] = {"exit": rc,
                                                  "log_tail": text[-4000:]}
                    continue
                comp = {"exit": 0}
                for name in ("comp_msbwt.npy",):
                    path = os.path.join(dst, name)
                    if os.path.exists(path):
                        comp[name] = self.record_npy(path)
                comp["files"] = sorted(os.listdir(dst))
                entry["compress_p" + proc] = comp
                # decompress back to byte
                back = self.fresh_dir("decompress", case_id, "p" + proc)
                rc, text = self.run_cli("decompress-" + case_id + "-p" + proc,
                                        "decompress", "-p", proc, dst, back)
                if rc != 0:
                    entry["decompress_p" + proc] = {"exit": rc,
                                                    "log_tail": text[-4000:]}
                    continue
                decomp = {"exit": 0}
                path = os.path.join(back, "msbwt.npy")
                if os.path.exists(path):
                    decomp["msbwt.npy"] = self.record_npy(path)
                decomp["files"] = sorted(os.listdir(back))
                entry["decompress_p" + proc] = decomp
            results[case_id] = entry
        self.results["compress"] = results

    # ------------------------------------------------------------------
    # Family 7: merge stress
    # ------------------------------------------------------------------
    def family_merge(self):
        results = {}
        for pair_id in self.ops.get("merge", []):
            pair = self.ops["merge_pairs"][pair_id]
            a_fastq = self.fastq_for(pair_id + "_a.fastq")
            b_fastq = self.fastq_for(pair_id + "_b.fastq")
            u_fastq = self.fastq_for(pair_id + "_u.fastq")
            entry = {}
            # construct A, B, and the clean union
            entry["a"] = self.construct_one(pair_id + "-a", a_fastq, "-m", False)
            entry["b"] = self.construct_one(pair_id + "-b", b_fastq, "-m", False)
            entry["union_clean"] = self.construct_one(
                pair_id + "-u", u_fastq, "-m", False)
            a_dir = os.path.join(self.run_dir, "construct", pair_id + "-a-m")
            b_dir = os.path.join(self.run_dir, "construct", pair_id + "-b-m")
            if entry["a"].get("exit") or entry["b"].get("exit"):
                results[pair_id] = entry
                continue
            # frozen: merge -p 2 only (the -p 1 UnboundLocalError is the
            # preserved legacy source bug; modern2: both -p 1 and -p 2)
            procs = ("2",) if self.impl == "frozen" else ("1", "2")
            for proc in procs:
                out = self.fresh_dir("merge", pair_id, "p" + proc)
                rc, text = self.run_cli("merge-" + pair_id + "-p" + proc,
                                        "merge", "-p", proc, out, a_dir, b_dir)
                if rc != 0:
                    entry["merge_p" + proc] = {"exit": rc,
                                               "log_tail": text[-4000:]}
                    continue
                merged = {"exit": 0, "files": sorted(os.listdir(out))}
                for name in ("msbwt.npy", "inter0.npy"):
                    path = os.path.join(out, name)
                    if os.path.exists(path):
                        merged[name] = self.record_npy(path)
                entry["merge_p" + proc] = merged
            results[pair_id] = entry
        self.results["merge"] = results

    # ------------------------------------------------------------------
    # Family 8: input-order permutations
    # ------------------------------------------------------------------
    def family_permute(self):
        results = {}
        for perm in self.ops.get("permute", []):
            case_id = perm["case"]
            fastq = self.fastq_for(perm["fastq"])
            results[perm["fastq"]] = self.construct_one(
                case_id, fastq, "-perm" + str(perm["variant"]), False)
        self.results["permute"] = results

    # ------------------------------------------------------------------
    # Family 5 + 6 + 8: reader probe (batched, Python 2)
    # ------------------------------------------------------------------
    def family_reader(self):
        probe = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "reader_probe.py")
        manifest = {"dirs": [], "regen": [], "rle": []}
        for case_id in self.ops.get("reader", []):
            kind = "byte"
            if case_id in self.ops.get("reader_rle", []):
                kind = "rle"
            if kind == "rle":
                src = os.path.join(self.run_dir, "compress", case_id, "p1")
                if not os.path.exists(os.path.join(src, "comp_msbwt.npy")):
                    continue
            else:
                src = os.path.join(self.run_dir, "construct", case_id)
                if not os.path.exists(os.path.join(src, "msbwt.npy")):
                    continue
            probe_dir = self.fresh_dir("reader", case_id)
            for name in os.listdir(src):
                shutil.copy2(os.path.join(src, name), os.path.join(probe_dir, name))
            case = self.case_by_id(case_id)
            manifest["dirs"].append({
                "case": case_id,
                "dir": probe_dir,
                "kind": kind,
                "queries": case["queries"],
                "positions": case["sample_positions"],
            })
            if case_id in self.ops.get("reader_regen", []):
                manifest["regen"].append(case_id)
            if kind == "rle":
                manifest["rle"].append(case_id)
        if not manifest["dirs"]:
            self.results["reader"] = {}
            return
        manifest_path = os.path.join(self.log_dir, "reader-manifest.json")
        json_dump(manifest, manifest_path)
        out_path = os.path.join(self.log_dir, "reader-results.json")
        rc = subprocess.run([self.python, "-B", probe, "--manifest", manifest_path,
                             "--out", out_path], cwd=self.tree, env=self.env)
        if rc.returncode != 0:
            self.results["reader"] = {"probe_exit": rc.returncode}
            return
        self.results["reader"] = json_load(out_path)

    # ------------------------------------------------------------------
    def run(self):
        if "construct" in self.ops:
            self.family_construct()
        if "cffq" in self.ops:
            self.family_cffq()
        if "gzip" in self.ops:
            self.family_gzip()
        if "compress" in self.ops:
            self.family_compress()
        if "merge" in self.ops:
            self.family_merge()
        if "permute" in self.ops:
            self.family_permute()
        if "reader" in self.ops:
            self.family_reader()
        json_dump(self.results, args.out)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    Executor(args).run()
