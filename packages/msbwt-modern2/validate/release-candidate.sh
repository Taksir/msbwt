#!/usr/bin/env bash
# msbwt-modern2 release-candidate: fresh-install validation driver (WSL).
#
# Validates one artifact (sdist or wheel) installed into a COMPLETELY FRESH
# Python-2.7 prefix (bootstrap-modern2.sh-created): import resolution from
# site-packages only, the installed `msbwt` script, all 9 public CLI
# subcommands against the committed goldens, the canonical end-to-end
# workflow (pp -> cfpp -> query -> compress -> RLE query -> decompress ->
# byte query), merge -p 1/-p 2, convert, nonuniform and gzip construction,
# and filesystem/install isolation (clean environment, cwd outside the
# repository, sys.path captured).
#
# Usage:
#   bash validate/release-candidate.sh \
#     --label sdist|wheel \
#     --prefix /absolute/fresh/env/prefix \
#     --artifact /absolute/path/to/artifact \
#     --repo /absolute/msbwt \
#     --work-base /absolute/work/dir
#
# Writes <work-base>/evidence-<label>.json and <work-base>/results-<label>.txt.
set -uo pipefail

LABEL=""; PREFIX=""; ARTIFACT=""; REPO=""; WORK_BASE=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --label) LABEL=${2:?--label requires a value}; shift 2 ;;
        --prefix) PREFIX=${2:?--prefix requires a value}; shift 2 ;;
        --artifact) ARTIFACT=${2:?--artifact requires a value}; shift 2 ;;
        --repo) REPO=${2:?--repo requires a value}; shift 2 ;;
        --work-base) WORK_BASE=${2:?--work-base requires a value}; shift 2 ;;
        -h|--help) sed -n '1,20p' "$0"; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; exit 64 ;;
    esac
done
case "$LABEL:$PREFIX:$ARTIFACT:$REPO:$WORK_BASE" in
    sdist:*|wheel:*) ;;
    *) printf '--label must be sdist or wheel\n' >&2; exit 64 ;;
esac

PY="$PREFIX/bin/python"
OUT="$WORK_BASE/work-$LABEL"
RES="$WORK_BASE/results-$LABEL.txt"
rm -f "$RES"

# ---------- deterministic environment (conda toolchain activation) ----------
export PATH="$PREFIX/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=UTC PYTHONHASHSEED=0 PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME PYTHONUSERBASE
unset AR AS CC CXX CFLAGS CPPFLAGS CXXFLAGS LD LDFLAGS
unset CONDA_BUILD_SYSROOT _CONDA_PYTHON_SYSCONFIGDATA_NAME
export CONDA_PREFIX="$PREFIX"
set +u
for activation_name in activate-binutils_linux-64.sh activate-gcc_linux-64.sh activate-gxx_linux-64.sh; do
    activation_path="$PREFIX/etc/conda/activate.d/$activation_name"
    [ -f "$activation_path" ] && . "$activation_path"
done
set -u

rm -rf "$OUT"
mkdir -p "$OUT/fixtures"
cp "$REPO/compat/fixtures/synthetic/uniform-a.fastq" "$OUT/fixtures/"
cp "$REPO/compat/fixtures/synthetic/uniform-b.fastq" "$OUT/fixtures/"
cp "$REPO/compat/fixtures/synthetic/nonuniform.fastq" "$OUT/fixtures/"
cp "$REPO/compat/fixtures/synthetic/uniform-a.fastq.gz" "$OUT/fixtures/"
cp "$REPO/compat/fixtures/synthetic/nonuniform.fastq.gz" "$OUT/fixtures/"
cp "$REPO/compat/goldens/original-0.3.0/convert-milestone10/inputs/uniform.txt" "$OUT/fixtures/"
cp "$REPO/compat/goldens/original-0.3.0/convert-milestone10/inputs/nonuniform.txt" "$OUT/fixtures/"

ok() { echo "PASS: $1" | tee -a "$RES"; }
fail() { echo "FAIL: $1" | tee -a "$RES"; }
sha() { sha256sum "$1" | cut -d' ' -f1; }
expect_sha() {
    local got; got=$(sha "$2" 2>/dev/null) || { fail "$1: missing $2"; return; }
    if [ "$got" = "$3" ]; then ok "$1 ($got)"; else fail "$1: got $got want $3"; fi
}

# ---------- install ----------------------------------------------------------
"$PY" -m pip install --isolated --disable-pip-version-check --no-cache-dir \
    --no-deps "$ARTIFACT" > "$WORK_BASE/install-$LABEL.log" 2>&1 \
    || { fail "pip install of $ARTIFACT"; echo "log tail:"; tail -20 "$WORK_BASE/install-$LABEL.log"; }
"$PY" -c "import Cython, numpy, pysam" \
    && ok "pinned runtime imports (Cython/numpy/pysam) in fresh prefix"

# ---------- import resolution from site-packages ----------------------------
cd "$OUT"
"$PY" -B - "$LABEL" <<'PY' > "$OUT/import-report-$LABEL.json" 2>&1
import json, sys
label = sys.argv[1]
res = {"sys.path": sys.path[:]}
for pkg in ("MUS", "MUSCython"):
    try:
        mod = __import__(pkg, fromlist=["*"])
        res[pkg] = {"ok": True, "__file__": mod.__file__}
    except Exception as exc:
        res[pkg] = {"ok": False, "error": repr(exc)}
res["modules"] = {}
for name in ["MUS.CommandLineInterface", "MUS.MSBWTGen", "MUS.MultiStringBWT",
             "MUS.TranscriptBuilder", "MUS.util",
             "MUSCython.AlignmentUtil", "MUSCython.BasicBWT",
             "MUSCython.ByteBWTCython", "MUSCython.CompressToRLE",
             "MUSCython.GenericMerge", "MUSCython.LZW_BWTCython",
             "MUSCython.MSBWTCompGenCython", "MUSCython.MSBWTGenCython",
             "MUSCython.MultiStringBWTCython", "MUSCython.MultimergeCython",
             "MUSCython.RLE_BWTCython", "MUSCython.LCPGen"]:
    try:
        mod = __import__(name, fromlist=["*"])
        res["modules"][name] = {"ok": True, "__file__": mod.__file__}
    except Exception as exc:
        res["modules"][name] = {"ok": False, "error": repr(exc)}
print(json.dumps(res, indent=1, sort_keys=True))
PY
python3 - "$LABEL" "$PREFIX" "$RES" "$OUT" <<'PY'
import json, os, re, sys
label, prefix, res_path, out = sys.argv[1:]
report = json.load(open(os.path.join(out, "import-report-%s.json" % label)))
mus = report.get("MUS", {}); cyn = report.get("MUSCython", {})
print("MUS.__file__ =", mus.get("__file__"))
print("MUSCython.__file__ =", cyn.get("__file__"))
bad = [k for k, v in report.get("modules", {}).items() if not v.get("ok")]
print("module failures:", bad if bad else "none")
with open(res_path, "a") as handle:
    if mus.get("ok") and cyn.get("ok") and not bad:
        handle.write("PASS: all imports resolve from site-packages\n")
    else:
        handle.write("FAIL: import resolution (%s)\n" % bad)
    if any("/mnt/" in p for p in report.get("sys.path", [])):
        handle.write("FAIL: sys.path leaks repository paths\n")
    else:
        handle.write("PASS: sys.path contains no repository paths\n")
PY

# ---------- installed CLI presence ------------------------------------------
MSBWT="$PREFIX/bin/msbwt"
"$MSBWT" -V > "$OUT/version.txt" 2>&1 && ok "installed msbwt -V" || fail "installed msbwt -V"
"$MSBWT" -h > "$OUT/help.txt" 2>&1 && ok "installed msbwt -h" || fail "installed msbwt -h"

# ---------- CLI matrix + canonical workflow (all 9 subcommands) --------------
F="$OUT/fixtures"
G_UNIFORM="dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"
G_POSTHOC="53d82b388a9d565afa96ead611d5db964bee199869fd07f96b8c84258ba099a3"
G_DECOMP="f536d60f356ed4a34e8253eecdd91e90db8c2ba3430c2e3d3e1855bb49007ef4"
G_CONV_U="121ffb41838b696ed0c543345794f8dad36525373e4d7427de8a45d298ec009b"
G_CONV_N="5fb45204712b0177803104d27a8170f11c159ed4f666c1b2521bc8fc614c7517"
G_NONUNI="da28963ca3726568dd7a26eccea35f107bd4cb8b295c909de628374db38dd4b2"
G_GZIP="da40d02ef42d4cf61d7b4814a2bc2c44c48f3516a53d6111a19bf2fdba8ff33b"

"$MSBWT" pp -u "$OUT/pp48" "$F/uniform-a.fastq" "$F/uniform-b.fastq" >> "$WORK_BASE/install-$LABEL.log" 2>&1 \
    && ok "pp (uniform)" || fail "pp (uniform)"
"$MSBWT" cfpp -p 1 -u "$OUT/pp48" >> "$WORK_BASE/install-$LABEL.log" 2>&1 \
    && ok "cfpp -p 1" || fail "cfpp -p 1"
expect_sha "cfpp -p 1 primary (uniform 48 golden)" "$OUT/pp48/msbwt.npy" "$G_UNIFORM"
"$MSBWT" cfpp -p 2 -u "$OUT/pp48" >> "$WORK_BASE/install-$LABEL.log" 2>&1 \
    && ok "cfpp -p 2" || fail "cfpp -p 2"
expect_sha "cfpp -p 2 primary (uniform 48 golden)" "$OUT/pp48/msbwt.npy" "$G_UNIFORM"
"$MSBWT" cffq -p 1 -u "$OUT/cffq48" "$F/uniform-a.fastq" "$F/uniform-b.fastq" >> "$WORK_BASE/install-$LABEL.log" 2>&1 \
    && ok "cffq -p 1" || fail "cffq -p 1"
expect_sha "cffq -p 1 primary (uniform 48 golden)" "$OUT/cffq48/msbwt.npy" "$G_UNIFORM"

Q=$("$MSBWT" query "$OUT/pp48" ACGTN 2>/dev/null | tail -1)
[ "$Q" = "3" ] && ok "query ACGTN=3" || fail "query ACGTN got '$Q'"
Q=$("$MSBWT" query "$OUT/pp48" AAAAA 2>/dev/null | tail -1)
[ "$Q" = "1" ] && ok "query AAAAA=1" || fail "query AAAAA got '$Q'"
Q=$("$MSBWT" query "$OUT/pp48" AGCTA 2>/dev/null | tail -1)
[ "$Q" = "0" ] && ok "query AGCTA=0" || fail "query AGCTA got '$Q'"

printf 'ACGTN\nAAAAA\nAGCTA\nAA\n' > "$OUT/kmers.txt"
"$MSBWT" massquery "$OUT/pp48" "$OUT/kmers.txt" "$OUT/mass.csv" >> "$WORK_BASE/install-$LABEL.log" 2>&1 \
    && ok "massquery" || fail "massquery"
[ "$(cat "$OUT/mass.csv")" = "k-mer,counts
ACGTN,3
AAAAA,1
AGCTA,0
AA,4" ] && ok "massquery CSV contract" || fail "massquery CSV contract"

"$MSBWT" compress -p 1 "$OUT/pp48" "$OUT/comp48" >> "$WORK_BASE/install-$LABEL.log" 2>&1 \
    && ok "compress -p 1" || fail "compress -p 1"
expect_sha "compress posthoc primary (golden)" "$OUT/comp48/comp_msbwt.npy" "$G_POSTHOC"
"$MSBWT" decompress -p 1 "$OUT/comp48" "$OUT/decomp48" >> "$WORK_BASE/install-$LABEL.log" 2>&1 \
    && ok "decompress -p 1" || fail "decompress -p 1"
expect_sha "decompress primary (modern2 contract)" "$OUT/decomp48/msbwt.npy" "$G_DECOMP"
Q=$("$MSBWT" query "$OUT/comp48" ACGTN 2>/dev/null | tail -1)
[ "$Q" = "3" ] && ok "RLE reader query ACGTN=3" || fail "RLE reader query got '$Q'"
Q=$("$MSBWT" query "$OUT/decomp48" ACGTN 2>/dev/null | tail -1)
[ "$Q" = "3" ] && ok "decompressed byte reader query ACGTN=3" || fail "decompressed query got '$Q'"

"$MSBWT" pp -u "$OUT/A" "$F/uniform-a.fastq" >> "$WORK_BASE/install-$LABEL.log" 2>&1
"$MSBWT" cfpp -p 1 -u "$OUT/A" >> "$WORK_BASE/install-$LABEL.log" 2>&1
"$MSBWT" pp -u "$OUT/B" "$F/uniform-b.fastq" >> "$WORK_BASE/install-$LABEL.log" 2>&1
"$MSBWT" cfpp -p 1 -u "$OUT/B" >> "$WORK_BASE/install-$LABEL.log" 2>&1
"$MSBWT" merge -p 1 "$OUT/merged1" "$OUT/A" "$OUT/B" >> "$WORK_BASE/install-$LABEL.log" 2>&1 \
    && ok "merge -p 1" || fail "merge -p 1"
expect_sha "merge -p 1 primary (uniform 48 golden)" "$OUT/merged1/msbwt.npy" "$G_UNIFORM"
"$MSBWT" merge -p 2 "$OUT/merged2" "$OUT/A" "$OUT/B" >> "$WORK_BASE/install-$LABEL.log" 2>&1 \
    && ok "merge -p 2" || fail "merge -p 2"
expect_sha "merge -p 2 primary (uniform 48 golden)" "$OUT/merged2/msbwt.npy" "$G_UNIFORM"

"$MSBWT" convert -i "$F/uniform.txt" "$OUT/conv48" >> "$WORK_BASE/install-$LABEL.log" 2>&1 \
    && ok "convert (uniform)" || fail "convert (uniform)"
expect_sha "convert uniform primary (golden)" "$OUT/conv48/comp_msbwt.npy" "$G_CONV_U"
"$MSBWT" convert -i "$F/nonuniform.txt" "$OUT/conv30" >> "$WORK_BASE/install-$LABEL.log" 2>&1 \
    && ok "convert (nonuniform)" || fail "convert (nonuniform)"
expect_sha "convert nonuniform primary (golden)" "$OUT/conv30/comp_msbwt.npy" "$G_CONV_N"

"$MSBWT" pp "$OUT/pp30" "$F/nonuniform.fastq" >> "$WORK_BASE/install-$LABEL.log" 2>&1
"$MSBWT" cfpp -p 1 "$OUT/pp30" >> "$WORK_BASE/install-$LABEL.log" 2>&1
expect_sha "cfpp nonuniform 30 primary (golden)" "$OUT/pp30/msbwt.npy" "$G_NONUNI"
"$MSBWT" pp "$OUT/ppgz" "$F/uniform-a.fastq.gz" "$F/nonuniform.fastq.gz" >> "$WORK_BASE/install-$LABEL.log" 2>&1
"$MSBWT" cfpp -p 1 "$OUT/ppgz" >> "$WORK_BASE/install-$LABEL.log" 2>&1
expect_sha "cfpp gzip 54 primary (golden)" "$OUT/ppgz/msbwt.npy" "$G_GZIP"

# ---------- filesystem/install isolation -------------------------------------
ISO="$OUT/isolation"; mkdir -p "$ISO/run"
env -i HOME="$HOME" PATH="$PREFIX/bin:/usr/bin:/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    TZ=UTC PYTHONNOUSERSITE=1 "$PY" -B - > "$ISO/syspath.txt" 2>&1 <<'PY'
import sys
print("\n".join(sys.path))
import MUS, MUSCython
print("MUS=%s" % MUS.__file__)
print("MUSCython=%s" % MUSCython.__file__)
print("imports-ok")
PY
grep -q "imports-ok" "$ISO/syspath.txt" && ok "isolated import from site-packages" \
    || fail "isolated import"
if grep -q "/mnt/" "$ISO/syspath.txt"; then fail "isolated sys.path leaks repository"; else ok "isolated sys.path clean"; fi
cd "$ISO/run"
env -i HOME="$HOME" PATH="$PREFIX/bin:/usr/bin:/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    TZ=UTC PYTHONNOUSERSITE=1 "$MSBWT" -V > version.txt 2>&1 \
    && ok "isolated msbwt -V" || fail "isolated msbwt -V"
env -i HOME="$HOME" PATH="$PREFIX/bin:/usr/bin:/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    TZ=UTC PYTHONNOUSERSITE=1 "$MSBWT" pp -u "$ISO/run/pp48" "$F/uniform-a.fastq" "$F/uniform-b.fastq" >> "$WORK_BASE/install-$LABEL.log" 2>&1
env -i HOME="$HOME" PATH="$PREFIX/bin:/usr/bin:/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    TZ=UTC PYTHONNOUSERSITE=1 "$MSBWT" cfpp -p 1 -u "$ISO/run/pp48" >> "$WORK_BASE/install-$LABEL.log" 2>&1
expect_sha "isolated workflow primary (uniform 48 golden)" "$ISO/run/pp48/msbwt.npy" "$G_UNIFORM"

# ---------- summary + evidence ------------------------------------------------
echo "=== $LABEL summary ==="
if grep -q "^FAIL" "$RES"; then
    echo "FAILURES:"; grep "^FAIL" "$RES"
    echo "RESULT: FAIL"; RESULT="FAIL"
else
    echo "RESULT: ALL-PASS"; RESULT="PASS"
fi
python3 - "$LABEL" "$RESULT" "$RES" "$OUT" "$PREFIX" "$ARTIFACT" "$WORK_BASE" <<'PY'
import json, os, re, sys
label, result, res_path, out, prefix, artifact, work_base = sys.argv[1:]
entries = []
for ln in open(res_path).read().strip().splitlines():
    m = re.match(r"^(PASS|FAIL): (.*)$", ln)
    if m:
        entries.append({"status": m.group(1), "check": m.group(2)})
report = json.load(open(os.path.join(out, "import-report-%s.json" % label)))
def rel(p):
    if p.startswith(prefix):
        return "<prefix>" + p[len(prefix):]
    return p
evidence = {
    "format": "msbwt-modern2-release-install-evidence-v1",
    "install_source": label,
    "artifact": artifact,
    "result": result,
    "checks": entries,
    "n_pass": sum(1 for e in entries if e["status"] == "PASS"),
    "n_fail": sum(1 for e in entries if e["status"] == "FAIL"),
    "imports": {
        "MUS.__file__": rel(report["MUS"]["__file__"]),
        "MUSCython.__file__": rel(report["MUSCython"]["__file__"]),
        "module_failures": [k for k, v in report["modules"].items() if not v["ok"]],
        "sys_path_prefix_only": all(not p.startswith("/mnt/")
                                    for p in report["sys.path"]),
    },
}
json.dump(evidence, open(os.path.join(work_base, "evidence-%s.json" % label), "w"),
          indent=1, sort_keys=True)
print("evidence written")
PY
