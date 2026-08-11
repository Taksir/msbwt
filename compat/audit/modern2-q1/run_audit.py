#!/usr/bin/env python3
"""Host orchestrator for the modern2 quality audit Q1.

Flow:

1. git gates: branch must be exactly ``codex/modern2`` and the worktree
   clean (unless --skip-git-check for harness development);
2. deterministic corpus generation (audit_core) with merge pairs, query
   sets, sample positions, and the family subsets;
3. FASTQ/FASTQ.gz writing (deterministic gzip bytes);
4. provisioning of the WSL execution trees when needed (provision.sh);
5. execution of the frozen oracle and modern2 through wsl/execute.py;
6. three-way analysis (analyze_audit) and evidence/report writing under
   compat/audit/modern2-q1/evidence/<tag>/.

Run twice with identical seeds to verify the summary is byte-identical
(``--verify-run B`` compares a fresh execution with the previous evidence).

The audit never modifies production source; the repository tree is only
read (plus the evidence directory written below).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "compat" / "audit" / "modern2-q1"))

from audit_core import (  # noqa: E402
    deterministic_gzip_bytes,
    generate_corpus,
    json_dump,
    json_load,
    reverse_complement,
)
from analyze_audit import Analyzer, build_summary  # noqa: E402

WSL_DIST = "Ubuntu-26.04"
AUDIT_DIR = REPO / "compat" / "audit" / "modern2-q1"
EVIDENCE_DIR = AUDIT_DIR / "evidence"
WSL_AUDIT_HOME = "/home/mytho/.local/share/msbwt-audit-q1"
WSL_FROZEN = WSL_AUDIT_HOME + "/frozen"
WSL_MODERN2 = WSL_AUDIT_HOME + "/modern2"
WSL_ORACLE_PY = ("/home/mytho/.local/share/msbwt-oracle/environments/"
                 "python27-late-pydeps-clean/bin/python")
WSL_MODERN2_PY = "/home/mytho/.local/share/msbwt-modern2/python27-modern2/bin/python"

REQUIRED_BRANCH = "codex/modern2"


def _in_wsl() -> bool:
    try:
        with open("/proc/version", "r", encoding="utf-8", errors="replace") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:
        return False


IN_WSL = _in_wsl()

# ---------------------------------------------------------------------------
# Family subset planning (deterministic from the corpus itself)
# ---------------------------------------------------------------------------


def plan_subsets(corpus):
    cases = [c for c in corpus["cases"] if not c.get("merge_case")]
    by_id = {c["id"]: c for c in cases}
    ids = [c["id"] for c in cases]

    construct = ids
    medium = [c["id"] for c in cases if c["medium"]]
    small = [c["id"] for c in cases if not c["medium"]]
    p2 = list(medium) + [small[i] for i in range(0, len(small), 5)]

    def cap_uniform(subset_ids, limit):
        chosen = []
        uniform_seen = 0
        for case_id in subset_ids:
            if by_id[case_id]["uniform"]:
                if uniform_seen >= limit:
                    continue
                uniform_seen += 1
            chosen.append(case_id)
        return chosen

    cffq = cap_uniform([ids[i] for i in range(0, len(ids), 4)], 12)
    gzip = cap_uniform([ids[i] for i in range(0, len(ids), 5)], 8)
    compress = [ids[i] for i in range(0, len(ids), 4)][:40] + medium
    compress = sorted(set(compress))

    reader = construct
    reader_regen = [small[i] for i in range(6, min(18, len(small)))]
    reader_rle = [c for c in compress if by_id[c]["uniform"]][:5] + \
                 [c for c in compress if not by_id[c]["uniform"]][:5]

    uniform_cases = [c["id"] for c in cases if c["uniform"]]
    nonuniform_cases = [c["id"] for c in cases if not c["uniform"]]
    permute = []
    for index, case_id in enumerate(uniform_cases[:4]):
        for variant in (1, 2):
            permute.append({"case": case_id, "variant": variant,
                            "fastq": "perm_%s_v%d.fastq" % (case_id, variant)})
    for index, case_id in enumerate(nonuniform_cases[:16]):
        for variant in (1, 2, 3):
            permute.append({"case": case_id, "variant": variant,
                            "fastq": "perm_%s_v%d.fastq" % (case_id, variant)})
    return {
        "construct": construct,
        "construct_p2": p2,
        "cffq": cffq,
        "gzip": gzip,
        "compress": compress,
        "reader": reader,
        "reader_regen": reader_regen,
        "reader_rle": reader_rle,
        "permute": permute,
    }


def generate_merge_pairs(seed):
    """20 deterministic merge pairs with the required trait coverage."""
    import random
    pairs = {}
    rng = random.Random(seed * 97 + 5)
    bases = "ACGTN"

    def rand_read(length):
        return "".join(rng.choice(bases) for _ in range(length))

    traits = [
        ("unequal-sizes", True),
        ("duplicates-across", True),
        ("identical-in-both", True),
        ("prefix-sharing", True),
        ("n-containing", True),
        ("very-short", True),
        ("unequal-sizes", False),
        ("duplicates-across", False),
        ("identical-in-both", False),
        ("prefix-sharing", False),
        ("n-containing", False),
        ("very-short", False),
        ("unequal-sizes", False),
        ("duplicates-across", False),
        ("identical-in-both", False),
        ("prefix-sharing", False),
        ("n-containing", False),
        ("very-short", False),
        ("mixed-traits", False),
        ("mixed-traits", False),
    ]
    for index in range(20):
        trait, uniform = traits[index]
        a_reads = [rand_read(5) for _ in range(3)]
        b_reads = [rand_read(5) for _ in range(5)]
        if trait == "unequal-sizes":
            a_reads = [rand_read(4) for _ in range(2)]
            b_reads = [rand_read(4) for _ in range(7)]
        elif trait == "duplicates-across":
            dup = rand_read(5)
            a_reads = [dup, dup, rand_read(5)]
            b_reads = [dup, rand_read(5), rand_read(5), rand_read(5)]
        elif trait == "identical-in-both":
            same = rand_read(5)
            a_reads = [same, rand_read(5)]
            b_reads = [same, same, rand_read(5)]
        elif trait == "prefix-sharing":
            prefix = "".join(rng.choice("ACGT") for _ in range(2))
            a_reads = [prefix + rand_read(2), prefix + rand_read(3)]
            b_reads = [prefix + rand_read(2), prefix + rand_read(4),
                       rand_read(5)]
        elif trait == "n-containing":
            a_reads = [rand_read(5).replace("N", "A") + "N",
                       "NN" + rand_read(3)]
            b_reads = ["N" + rand_read(4), rand_read(5)]
        elif trait == "very-short":
            a_reads = ["A", "C"]
            b_reads = ["N", "G", "T", "A"]
        elif trait == "mixed-traits":
            a_reads = [rand_read(3), "NAC", "TT", rand_read(5)]
            b_reads = ["TT", rand_read(6), "NAC", rand_read(2), "A"]
        if uniform:
            length = rng.choice([4, 5, 6])
            a_reads = [rand_read(length) for _ in range(rng.randint(2, 4))]
            b_reads = [rand_read(length) for _ in range(rng.randint(3, 6))]
            if trait == "identical-in-both":
                same = a_reads[0]
                b_reads[0] = same
                b_reads[1] = same
        pairs["m%04d" % index] = {
            "id": "m%04d" % index,
            "category": trait,
            "uniform": uniform,
            "a_reads": a_reads,
            "b_reads": b_reads,
        }
    return pairs


def merge_cases_from_pairs(pairs):
    cases = []
    for pair_id, pair in sorted(pairs.items()):
        for role, reads in (("a", pair["a_reads"]), ("b", pair["b_reads"]),
                            ("u", pair["a_reads"] + pair["b_reads"])):
            uniform = all(len(r) == len(reads[0]) for r in reads)
            cases.append({
                "id": pair_id + "-" + role,
                "index": -1,
                "category": "merge-" + pair["category"],
                "medium": False,
                "uniform": uniform and pair["uniform"],
                "reads": reads,
                "seed": 0,
                "queries": [],
                "sample_positions": [],
                "merge_case": True,
                "merge_pair": pair_id,
                "merge_role": role,
            })
    return cases


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------


def wsl_run(args, cwd=None):
    """Run a command inside the WSL Linux environment.

    On the Windows host a disposable script file is used (``wsl.exe -e bash
    -c`` joins argv with spaces and loses quoting).  When the orchestrator
    itself runs inside WSL, ``bash`` is invoked directly.
    """
    import tempfile
    fd, script_path = tempfile.mkstemp(suffix=".sh", prefix="audit-q1-",
                                       dir=os.environ.get("TEMP"))
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("#!/usr/bin/env bash\nset -euo pipefail\n")
        handle.write(" ".join(_sh_quote(a) for a in args) + "\n")
    try:
        if IN_WSL:
            return subprocess.run(["bash", script_path],
                                  cwd=str(cwd) if cwd else None,
                                  capture_output=True, text=True, timeout=None)
        wsl_path = _windows_to_wsl_path(script_path)
        return subprocess.run(["wsl", "-d", WSL_DIST, "-e", "bash", wsl_path],
                              cwd=str(cwd) if cwd else None, capture_output=True,
                              text=True, timeout=None)
    finally:
        os.remove(script_path)


def _sh_quote(value):
    """Quote a token for bash only when needed.

    Shell control operators must stay bare (a single-quoted '&&' is a
    literal word); safe tokens are left unquoted; everything else (paths
    with spaces, wildcard-ish characters, quotes) is single-quoted.
    """
    import re
    if value in ("&&", "||", "|", ";", "&", ">", ">>", "<", "(", ")"):
        return value
    if re.fullmatch(r"[A-Za-z0-9_./:+=,@%^#-]+", value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def _windows_to_wsl_path(path):
    if path.startswith("/"):
        return path
    drive, rest = os.path.splitdrive(path)
    rest = rest.replace("\\", "/")
    return "/mnt/" + drive[0].lower() + rest


def ensure_provisioned():
    trees = wsl_run(["test", "-f", WSL_FROZEN + "/MUSCython/MSBWTGenCython.so",
                     "&&", "test", "-f", WSL_MODERN2 + "/MUSCython/MSBWTGenCython.so"])
    if trees.returncode != 0:
        print("provisioning WSL execution trees ...", flush=True)
        result = wsl_run([
            "cd", _windows_to_wsl_path(str(REPO)), "&&",
            "bash", "compat/audit/modern2-q1/wsl/provision.sh",
            "--repo", _windows_to_wsl_path(str(REPO)),
            "--work", WSL_AUDIT_HOME,
            "--oracle-python", WSL_ORACLE_PY,
            "--modern2-python", WSL_MODERN2_PY,
        ])
        if result.returncode != 0:
            print(result.stdout, result.stderr)
            raise SystemExit("provisioning failed")
        print("provisioning complete", flush=True)
    else:
        print("WSL trees already provisioned", flush=True)


def git_check():
    branch = subprocess.run(["git", "branch", "--show-current"],
                            cwd=str(REPO), capture_output=True, text=True)
    status = subprocess.run(["git", "status", "--porcelain"],
                            cwd=str(REPO), capture_output=True, text=True)
    current = branch.stdout.strip()
    if current != REQUIRED_BRANCH:
        raise SystemExit("branch is %r, expected %r" % (current, REQUIRED_BRANCH))
    if status.stdout.strip():
        raise SystemExit("worktree is not clean:\n%s" % status.stdout)
    print("git gates OK: branch=%s clean" % current, flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260810)
    parser.add_argument("--tag", default="q1")
    parser.add_argument("--small", type=int, default=150)
    parser.add_argument("--medium", type=int, default=15)
    parser.add_argument("--work", default=(
        "/tmp/opencode/audit-q1" if IN_WSL else os.path.join(
            os.environ.get("TEMP", r"C:\Users\mytho\AppData\Local\Temp"),
            "opencode", "audit-q1")))
    parser.add_argument("--skip-git-check", action="store_true")
    parser.add_argument("--skip-provision", action="store_true")
    parser.add_argument("--impls", default="frozen,modern2")
    parser.add_argument("--dry-run", action="store_true",
                        help="generate corpus/ops/fastqs only")
    parser.add_argument("--analyze-only", action="store_true",
                        help="regenerate evidence from existing WSL results "
                             "(no execution)")
    args = parser.parse_args(argv)

    if not args.skip_git_check:
        git_check()

    windows_work = Path(args.work) / args.tag
    if windows_work.exists() and not args.analyze_only:
        shutil.rmtree(windows_work)
    fastq_dir = windows_work / "fastqs"
    fastq_dir.mkdir(parents=True)

    # --- corpus + ops -------------------------------------------------
    if args.analyze_only and (windows_work / "corpus.json").exists():
        corpus = json_load(str(windows_work / "corpus.json"))
        ops = json_load(str(windows_work / "ops.json"))
        merge_pairs = ops["merge_pairs"]
    else:
        corpus = generate_corpus(args.seed, args.small, args.medium)
        merge_pairs = generate_merge_pairs(args.seed)
        merge_cases = merge_cases_from_pairs(merge_pairs)
        corpus["cases"].extend(merge_cases)
        subsets = plan_subsets(corpus)

        ops = {
            "merge_pairs": merge_pairs,
            "merge": sorted(merge_pairs),
        }
        for key in ("construct", "construct_p2", "cffq", "gzip", "compress",
                    "reader", "reader_regen", "reader_rle", "permute"):
            ops[key] = subsets[key]

        json_dump(corpus, str(windows_work / "corpus.json"))
        json_dump(ops, str(windows_work / "ops.json"))

        # --- fastqs --------------------------------------------------------
        for case in corpus["cases"]:
            if case.get("merge_case"):
                pair_id = case["merge_pair"]
                role = case["merge_role"]
                name = "%s_%s.fastq" % (pair_id, role)
            else:
                name = case["id"] + ".fastq"
            write_fastq(fastq_dir / name, case["reads"])
            if case.get("merge_case"):
                continue
            write_gzip(fastq_dir / (case["id"] + ".fastq.gz"), case["reads"])
        for perm in ops["permute"]:
            case = next(c for c in corpus["cases"] if c["id"] == perm["case"])
            permuted = list(case["reads"])
            rng = random_for_permute(args.seed, perm)
            for i in range(len(permuted)):
                j = rng.randrange(len(permuted))
                permuted[i], permuted[j] = permuted[j], permuted[i]
            if permuted == case["reads"] and len(permuted) > 1:
                permuted[0], permuted[1] = permuted[1], permuted[0]
            write_fastq(fastq_dir / perm["fastq"], permuted)
        print("corpus: %d cases (%d small, %d medium, %d merge), %d fastqs" % (
            len(corpus["cases"]), args.small, args.medium,
            sum(1 for c in corpus["cases"] if c.get("merge_case")),
            len(list(fastq_dir.iterdir()))), flush=True)

    if args.dry_run:
        print("dry-run: work written to", windows_work)
        return

    if args.analyze_only:
        print("analyze-only: reusing executed results in", windows_work, flush=True)
    else:
        # --- WSL execution -------------------------------------------------
        if not args.skip_provision:
            ensure_provisioned()

        wsl_work = WSL_AUDIT_HOME + "/run-" + args.tag
        wsl_run(["rm", "-rf", wsl_work])
        wsl_run(["mkdir", "-p", wsl_work + "/fastqs"])
        wsl_run(["cp", _windows_to_wsl_path(str(windows_work / "corpus.json")),
                 _windows_to_wsl_path(str(windows_work / "ops.json")),
                 wsl_work + "/"])
        wsl_run(["cp", "-r", _windows_to_wsl_path(str(fastq_dir)) + "/.",
                 wsl_work + "/fastqs/"])

        script_dir = _windows_to_wsl_path(str(AUDIT_DIR / "wsl"))
        for impl in args.impls.split(","):
            print("executing %s ..." % impl, flush=True)
            py = WSL_ORACLE_PY if impl == "frozen" else WSL_MODERN2_PY
            tree = WSL_FROZEN if impl == "frozen" else WSL_MODERN2
            result = wsl_run([
                "cd", script_dir, "&&",
                "python3", "execute.py",
                "--impl", impl,
                "--tree", tree,
                "--python", py,
                "--work", wsl_work,
                "--corpus", wsl_work + "/corpus.json",
                "--ops", wsl_work + "/ops.json",
                "--out", wsl_work + "/results-" + impl + ".json",
            ])
            if result.returncode != 0:
                print(result.stdout)
                print(result.stderr)
                raise SystemExit("execution failed for " + impl)
            # copy back
            wsl_run(["cp", wsl_work + "/results-" + impl + ".json",
                     _windows_to_wsl_path(str(windows_work)) + "/"])
            print("  done", flush=True)

    # --- analysis ------------------------------------------------------
    if args.analyze_only:
        # reuse the executed WSL results without re-running anything
        wsl_work = WSL_AUDIT_HOME + "/run-" + args.tag
        wsl_run(["cp", wsl_work + "/results-frozen.json",
                 _windows_to_wsl_path(str(windows_work)) + "/"])
        wsl_run(["cp", wsl_work + "/results-modern2.json",
                 _windows_to_wsl_path(str(windows_work)) + "/"])
    frozen = json_load(str(windows_work / "results-frozen.json"))
    modern2 = json_load(str(windows_work / "results-modern2.json"))
    modern2["permute_ops"] = ops["permute"]
    modern2["reader_rle_cases"] = ops["reader_rle"]
    frozen["permute_ops"] = ops["permute"]
    analyzer = Analyzer(corpus, frozen, modern2)
    results = analyzer.run()
    summary = build_summary(results, corpus)

    evidence = EVIDENCE_DIR / args.tag
    evidence.mkdir(parents=True, exist_ok=True)
    json_dump(summary, str(evidence / "summary.json"))
    json_dump(results, str(evidence / "results.json"))
    json_dump(corpus, str(evidence / "corpus.json"))
    write_report(results, summary, corpus, str(evidence / "report.txt"))
    print("evidence written to", evidence, flush=True)
    print("summary:", json.dumps(summary, sort_keys=True), flush=True)


def random_for_permute(seed, perm):
    import hashlib
    import random
    digest = hashlib.sha256(perm["fastq"].encode("ascii")).digest()
    derived = int.from_bytes(digest[:8], "little")
    return random.Random(seed * 1009 + derived)


def write_fastq(path, reads):
    lines = []
    for index, read in enumerate(reads):
        lines.append("@audit-%s-%d" % (path.stem, index))
        lines.append(read)
        lines.append("+")
        lines.append("I" * len(read))
    text = "\n".join(lines) + "\n"
    path.write_bytes(text.encode("ascii"))


def write_gzip(path, reads):
    lines = []
    for index, read in enumerate(reads):
        lines.append("@audit-%s-%d" % (path.stem, index))
        lines.append(read)
        lines.append("+")
        lines.append("I" * len(read))
    text = ("\n".join(lines) + "\n").encode("ascii")
    path.write_bytes(deterministic_gzip_bytes(text))


def write_report(results, summary, corpus, path):
    small = sum(1 for c in corpus["cases"] if not c.get("merge_case") and not c["medium"])
    medium = sum(1 for c in corpus["cases"] if not c.get("merge_case") and c["medium"])
    merge_cases = sum(1 for c in corpus["cases"] if c.get("merge_case"))
    lines = []
    lines.append("MODERN2 QUALITY AUDIT Q1 — randomized differential + invariant stress")
    lines.append("seed: %d" % corpus["seed"])
    lines.append("cases: %d (%d small, %d medium, %d merge)" % (
        len(corpus["cases"]), small, medium, merge_cases))
    lines.append("family_counts: %s" % json.dumps(summary["family_counts"]))
    lines.append("classifications: %s" % json.dumps(summary["classification_counts"]))
    lines.append("total_failures: %d" % summary["total_failures"])
    for failure in summary["failures"]:
        lines.append("FAILURE %(case)s [%(family)s] %(kind)s: %(detail)s" % failure)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
