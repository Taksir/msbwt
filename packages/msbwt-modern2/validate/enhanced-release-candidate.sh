#!/usr/bin/env bash
# enhanced-modern2 release-candidate: fresh-install validation driver (WSL).
#
# Validates the enhanced-modern2 distribution end-to-end from its build
# artifacts:
#
#   1. build sdist + wheel from a disposable copy of the package tree in
#      the pinned Python-2.7 build prefix;
#   2. record artifact names / sizes / SHA-256 / wheel tag and audit the
#      archive contents (enhanced modules, tools package, generated C,
#      no tests/evidence/environment/validate);
#   3. bootstrap TWO brand-new Python-2.7 prefixes (bootstrap-modern2.sh,
#      hash-verified micromamba) and install one artifact each;
#   4. prove every import (MUS, MUSCython, tools) resolves from
#      site-packages with no repository path on sys.path;
#   5. run the legacy release-candidate.sh fresh-install gate (all 9 CLI
#      commands, committed goldens, isolation) against each install;
#   6. run the enhanced installed-distribution gate
#      (validate/enhanced_installed_gate.py) against each install;
#   7. run every enhanced console script (--help + real operations on the
#      gate's fixture package);
#   8. write evidence/enhanced-release-candidate.json.
#
# Usage:
#   bash validate/enhanced-release-candidate.sh \
#     --repo /absolute/msbwt \
#     --build-prefix /absolute/python27-modern2-prefix \
#     --micromamba /absolute/micromamba-2.8.1 \
#     --work-base /absolute/work/dir \
#     [--prefix-sdist /absolute/fresh-A] \
#     [--prefix-wheel /absolute/fresh-B] \
#     [--keep-prefixes]
#
# When --prefix-sdist / --prefix-wheel are omitted (or --keep-prefixes is
# not given), the driver bootstraps fresh prefixes itself.
set -uo pipefail

REPO=""; BUILD_PREFIX=""; MICROMAMBA=""; WORK_BASE=""
PREFIX_SDIST=""; PREFIX_WHEEL=""; KEEP_PREFIXES=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --repo) REPO=${2:?--repo requires a value}; shift 2 ;;
        --build-prefix) BUILD_PREFIX=${2:?--build-prefix requires a value}; shift 2 ;;
        --micromamba) MICROMAMBA=${2:?--micromamba requires a value}; shift 2 ;;
        --work-base) WORK_BASE=${2:?--work-base requires a value}; shift 2 ;;
        --prefix-sdist) PREFIX_SDIST=${2:?--prefix-sdist requires a value}; shift 2 ;;
        --prefix-wheel) PREFIX_WHEEL=${2:?--prefix-wheel requires a value}; shift 2 ;;
        --keep-prefixes) KEEP_PREFIXES=1 ;;
        -h|--help) sed -n '1,40p' "$0"; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; exit 64 ;;
    esac
done
for arg in "$REPO" "$BUILD_PREFIX" "$MICROMAMBA" "$WORK_BASE"; do
    [ -n "$arg" ] || { printf 'All of --repo --build-prefix --micromamba --work-base are required\n' >&2; exit 64; }
done
case "$REPO:$BUILD_PREFIX:$MICROMAMBA:$WORK_BASE" in
    /*:/*:/*:/*) ;;
    *) printf 'All paths must be absolute Linux paths.\n' >&2; exit 64 ;;
esac
if [ ! -x "$BUILD_PREFIX/bin/python" ]; then
    printf 'Build prefix python not found: %s\n' "$BUILD_PREFIX" >&2; exit 66
fi
if [ ! -x "$MICROMAMBA" ]; then
    printf 'micromamba is not executable: %s\n' "$MICROMAMBA" >&2; exit 66
fi
for tool in python3 git sha256sum unzip tar; do
    command -v "$tool" >/dev/null 2>&1 || { printf 'Missing required tool: %s\n' "$tool" >&2; exit 69; }
done

PACKAGE="$REPO/packages/msbwt-modern2"
EVIDENCE_OUT="$PACKAGE/evidence/enhanced-release-candidate.json"
mkdir -p "$WORK_BASE"
RES="$WORK_BASE/results.txt"
rm -f "$RES"
ok() { echo "PASS: $1" | tee -a "$RES"; }
fail() { echo "FAIL: $1" | tee -a "$RES"; }
sha() { sha256sum "$1" | cut -d' ' -f1; }

# ---------------------------------------------------------------------------
# pinned build-prefix environment activation (conda toolchain)
# ---------------------------------------------------------------------------
activate_prefix() {
    local prefix="$1"
    export PATH="$prefix/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    export LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=UTC PYTHONHASHSEED=0 PYTHONNOUSERSITE=1
    export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
    unset PYTHONPATH PYTHONHOME PYTHONUSERBASE
    export PIP_CONFIG_FILE=/dev/null
    unset AR AS CC CXX CFLAGS CPPFLAGS CXXFLAGS LD LDFLAGS
    unset CONDA_BUILD_SYSROOT _CONDA_PYTHON_SYSCONFIGDATA_NAME
    export CONDA_PREFIX="$prefix"
    set +u
    for activation_name in activate-binutils_linux-64.sh activate-gcc_linux-64.sh activate-gxx_linux-64.sh; do
        activation_path="$prefix/etc/conda/activate.d/$activation_name"
        [ -f "$activation_path" ] && . "$activation_path"
    done
    set -u
    if [ -z "${CC:-}" ]; then
        printf 'Compiler activation failed in %s: CC is empty.\n' "$prefix" >&2
        exit 69
    fi
}

gate_build_env() {
    "$BUILD_PREFIX/bin/python" - <<'PY'
import sys
assert sys.version_info[:2] == (2, 7)
import Cython, numpy
assert Cython.__version__.startswith('3.0.'), Cython.__version__
assert numpy.__version__ == '1.16.6', numpy.__version__
print('gate_build_env OK')
PY
}

# ---------------------------------------------------------------------------
# 1. build artifacts from a disposable copy
# ---------------------------------------------------------------------------
BUILD_DIR=$(mktemp -d /tmp/msbwt-relbuild-XXXXXX)
BUILD_PKG="$BUILD_DIR/package"
mkdir -p "$BUILD_PKG"
cp -a "$PACKAGE/." "$BUILD_PKG/"
rm -rf "$BUILD_PKG/build" "$BUILD_PKG/dist" "$BUILD_PKG/*.egg-info"
find "$BUILD_PKG" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$BUILD_PKG" -name '*.so' -type f -delete
find "$BUILD_PKG" -name '*.pyc' -type f -delete

activate_prefix "$BUILD_PREFIX"
(cd "$BUILD_PKG" && "$BUILD_PREFIX/bin/python" -B setup.py sdist > "$WORK_BASE/build-sdist.log" 2>&1) \
    && ok "sdist build" || fail "sdist build"
(cd "$BUILD_PKG" && "$BUILD_PREFIX/bin/python" -B setup.py bdist_wheel > "$WORK_BASE/build-wheel.log" 2>&1) \
    && ok "wheel build" || fail "wheel build"

SDIST=$(ls "$BUILD_PKG"/dist/msbwt-modern2-*.tar.gz 2>/dev/null | head -1)
WHEEL=$(ls "$BUILD_PKG"/dist/msbwt_modern2-*.whl 2>/dev/null | head -1)
if [ -z "$SDIST" ] || [ -z "$WHEEL" ]; then
    printf 'Artifacts were not produced (sdist=%s wheel=%s)\n' "$SDIST" "$WHEEL" >&2
    exit 71
fi
SDIST_NAME=$(basename "$SDIST")
WHEEL_NAME=$(basename "$WHEEL")
SDIST_SHA=$(sha "$SDIST")
WHEEL_SHA=$(sha "$WHEEL")
SDIST_SIZE=$(stat -c %s "$SDIST")
WHEEL_SIZE=$(stat -c %s "$WHEEL")
echo "sdist: $SDIST_NAME $SDIST_SIZE bytes sha256=$SDIST_SHA" | tee -a "$RES"
echo "wheel: $WHEEL_NAME $WHEEL_SIZE bytes sha256=$WHEEL_SHA" | tee -a "$RES"

# ---------------------------------------------------------------------------
# 2. archive content audits
# ---------------------------------------------------------------------------
tar -tzf "$SDIST" > "$WORK_BASE/sdist-contents.txt"
unzip -l "$WHEEL" > "$WORK_BASE/wheel-contents.txt"

python3 - "$WORK_BASE" <<'PY'
import json, os, re, sys
work = sys.argv[1]
sdist = open(os.path.join(work, "sdist-contents.txt")).read()
wheel = open(os.path.join(work, "wheel-contents.txt")).read()
missing = []
required_sdist = [
    "MUS/BackendContract.py", "MUS/Benchmarking.py", "MUS/BWTTags.py",
    "MUS/LCP.py", "MUS/MultiSourceProvenance.py", "MUS/MultiSourceQuery.py",
    "MUS/QualitySidecar.py", "MUS/ReadProvenance.py", "MUS/SourceIndex.py",
    "MUS/SourceMetadata.py", "MUS/SourceRemoval.py",
    "tools/__init__.py", "tools/bwt_tags.py", "tools/lcp.py",
    "tools/quality_sidecar.py", "tools/remove_sources.py",
    "tools/retrofit_read_provenance.py", "tools/benchmark_index.py",
    "MUSCython/GenericMerge.pyx", "MUSCython/GenericMerge.c",
    "MUSCython/BasicBWT.pxd", "bin/msbwt", "setup.py", "MANIFEST.in",
    "LICENSE", "AUTHORS", "README.md", "PKG-INFO",
]
for rel in required_sdist:
    if ("msbwt-modern2-0.3.0/" + rel) not in sdist:
        missing.append("sdist:" + rel)
for banned in ("tests/", "evidence/", "environment/", "validate/"):
    if re.search(r"msbwt-modern2-0.3.0/%s" % banned, sdist):
        missing.append("sdist-banned:" + banned)
required_wheel = [
    "MUS/BackendContract.py", "MUS/MultiSourceQuery.py", "MUS/LCP.py",
    "tools/__init__.py", "tools/bwt_tags.py", "tools/benchmark_index.py",
    "MUSCython/BasicBWT.pxd", "MUSCython/LCPGen.py",
]
for rel in required_wheel:
    if rel not in wheel:
        missing.append("wheel:" + rel)
for name in ("AlignmentUtil", "BasicBWT", "ByteBWTCython", "CompressToRLE",
             "GenericMerge", "LZW_BWTCython", "MSBWTCompGenCython",
             "MSBWTGenCython", "MultiStringBWTCython", "MultimergeCython",
             "RLE_BWTCython"):
    if ("MUSCython/%s.so" % name) not in wheel:
        missing.append("wheel-so:" + name)
for script in ("msbwt", "msbwt-bwt-tags", "msbwt-lcp",
               "msbwt-quality-sidecar", "msbwt-remove-sources",
               "msbwt-retrofit-read-provenance", "msbwt-benchmark-index"):
    if not re.search(r"\.data/scripts/%s$" % re.escape(script), wheel):
        missing.append("wheel-script:" + script)
if re.search(r"\.pyx|\.c\b", wheel):
    missing.append("wheel-ships-sources")
json.dump({"missing": missing}, open(os.path.join(work, "content-audit.json"), "w"),
          indent=1, sort_keys=True)
print("missing: %d" % len(missing))
for item in missing:
    print("MISSING: %s" % item)
PY
AUDIT_RESULT=$(python3 - "$WORK_BASE" <<'PY'
import json, os, sys
work = sys.argv[1]
audit = json.load(open(os.path.join(work, "content-audit.json")))
print("FAIL" if audit["missing"] else "PASS")
PY
)
if [ "$AUDIT_RESULT" = "PASS" ]; then
    ok "artifact content audit (sdist + wheel)"
else
    fail "artifact content audit (sdist + wheel)"
fi

# ---------------------------------------------------------------------------
# 3. fresh prefixes
# ---------------------------------------------------------------------------
bootstrap_prefix() {
    local label="$1"
    local target="${2:-}"
    if [ "$KEEP_PREFIXES" = "1" ] && [ -n "$target" ] && [ -x "$target/bin/python" ]; then
        echo "reusing existing prefix $target"
        return 0
    fi
    if [ -z "$target" ]; then
        target="$WORK_BASE/prefix-$label"
    fi
    if [ -e "$target" ]; then
        printf 'Refusing to bootstrap over existing prefix: %s\n' "$target" >&2
        exit 73
    fi
    bash "$PACKAGE/environment/bootstrap-modern2.sh" \
        --micromamba "$MICROMAMBA" --prefix "$target" \
        > "$WORK_BASE/bootstrap-$label.log" 2>&1 \
        || { printf 'bootstrap-%s failed\n' "$label" >&2; tail -30 "$WORK_BASE/bootstrap-$label.log" >&2; exit 1; }
}

if [ -n "$PREFIX_SDIST" ]; then
    SDIST_PREFIX="$PREFIX_SDIST"
else
    SDIST_PREFIX="$WORK_BASE/prefix-sdist"
    bootstrap_prefix sdist "$SDIST_PREFIX"
fi
if [ -n "$PREFIX_WHEEL" ]; then
    WHEEL_PREFIX="$PREFIX_WHEEL"
else
    WHEEL_PREFIX="$WORK_BASE/prefix-wheel"
    bootstrap_prefix wheel "$WHEEL_PREFIX"
fi

# ---------------------------------------------------------------------------
# per-install validation: wheel then sdist
# ---------------------------------------------------------------------------
INSTALLS="wheel:${WHEEL_PREFIX}:${WHEEL} sdist:${SDIST_PREFIX}:${SDIST}"
for entry in $INSTALLS; do
    LABEL=${entry%%:*}
    REST=${entry#*:}
    PREFIX=${REST%%:*}
    ARTIFACT=${REST#*:}
    echo "=== validating $LABEL install into $PREFIX ===" | tee -a "$RES"

    # 3a. install
    "$PREFIX/bin/python" -m pip install --isolated --disable-pip-version-check \
        --no-cache-dir --no-deps "$ARTIFACT" > "$WORK_BASE/install-$LABEL.log" 2>&1 \
        || { fail "pip install $LABEL"; tail -20 "$WORK_BASE/install-$LABEL.log"; }
    "$PREFIX/bin/python" -c "import Cython, numpy, pysam" \
        && ok "pinned runtime imports in $LABEL prefix" \
        || fail "pinned runtime imports in $LABEL prefix"

    # 3b. import report: MUS/MUSCython/tools from site-packages only
    mkdir -p "$WORK_BASE/import-$LABEL"
    (cd "$WORK_BASE/import-$LABEL" && "$PREFIX/bin/python" -B - "$REPO" <<'PY'
import json, os, re, sys
repo = os.path.abspath(sys.argv[1])
res = {"repo_root": repo, "sys_path_leaks": []}
for probe in sys.path:
    if probe.startswith("/mnt/") or (repo and os.path.abspath(probe).startswith(repo)):
        res["sys_path_leaks"].append(probe)
res["modules"] = {}
mods = ["MUS", "MUSCython", "tools"]
mods += ["MUS.CommandLineInterface", "MUS.util",
         "MUS.MultiSourceProvenance", "MUS.MultiSourceQuery",
         "MUS.ReadProvenance", "MUS.SourceRemoval", "MUS.BWTTags",
         "MUS.QualitySidecar", "MUS.LCP", "MUS.Benchmarking",
         "MUS.BackendContract", "MUS.SourceIndex", "MUS.SourceMetadata",
         "MUSCython.AlignmentUtil", "MUSCython.BasicBWT",
         "MUSCython.CompressToRLE", "MUSCython.GenericMerge",
         "MUSCython.MultiStringBWTCython", "MUSCython.RLE_BWTCython",
         "tools.bwt_tags", "tools.lcp", "tools.quality_sidecar",
         "tools.remove_sources", "tools.retrofit_read_provenance",
         "tools.benchmark_index"]
for name in mods:
    try:
        mod = __import__(name, fromlist=["*"])
        res["modules"][name] = {"ok": True, "__file__": mod.__file__}
    except Exception as exc:
        res["modules"][name] = {"ok": False, "error": repr(exc)}
print(json.dumps(res, indent=1, sort_keys=True))
PY
) > "$WORK_BASE/import-$LABEL/report.json" 2>&1
python3 - "$LABEL" "$RES" "$WORK_BASE" <<'PY'
import json, os, re, sys
label, res_path, work = sys.argv[1:]
report = json.load(open(os.path.join(work, "import-%s" % label, "report.json")))
bad = [k for k, v in report["modules"].items() if not v.get("ok")]
paths = [v["__file__"] for v in report["modules"].values()
         if v.get("__file__")]
not_site = [p for p in paths if "site-packages" not in p]
with open(res_path, "a") as handle:
    if not bad and not not_site and not report["sys_path_leaks"]:
        handle.write("PASS: %s imports all from site-packages (%d modules)\n"
                     % (label, len(report["modules"])))
    else:
        handle.write("FAIL: %s import report (bad=%s not-site=%s leaks=%s)\n"
                     % (label, bad, not_site, report["sys_path_leaks"]))
for name, info in sorted(report["modules"].items()):
    if info.get("__file__"):
        print("%s %s" % (name, info["__file__"]))
PY

    # 3c. legacy fresh-install gate (all 9 CLI commands + goldens)
    bash "$PACKAGE/validate/release-candidate.sh" \
        --label "$LABEL" --prefix "$PREFIX" --artifact "$ARTIFACT" \
        --repo "$REPO" --work-base "$WORK_BASE" \
        > "$WORK_BASE/legacy-$LABEL.log" 2>&1 \
        && ok "legacy release-candidate gate ($LABEL)" \
        || fail "legacy release-candidate gate ($LABEL)"

    # 3d. enhanced installed-distribution gate
    GATE_DIR="$WORK_BASE/gate-$LABEL"
    mkdir -p "$GATE_DIR"
    cp "$PACKAGE/validate/enhanced_installed_gate.py" "$GATE_DIR/"
    (cd "$GATE_DIR" && "$PREFIX/bin/python" -B \
        enhanced_installed_gate.py gate-report.json fixture "$REPO") \
        > "$WORK_BASE/gate-$LABEL.log" 2>&1 \
        && ok "enhanced installed gate ($LABEL)" \
        || { fail "enhanced installed gate ($LABEL)"; tail -40 "$WORK_BASE/gate-$LABEL.log"; }

    # 3e. enhanced console scripts: --help + real operations
    M10="$GATE_DIR/fixture/merged10"
    RED="$GATE_DIR/fixture/reduced"
    LEAVES="$GATE_DIR/fixture/leaves"
    for script in msbwt-bwt-tags msbwt-lcp msbwt-quality-sidecar \
                  msbwt-remove-sources msbwt-retrofit-read-provenance \
                  msbwt-benchmark-index; do
        "$PREFIX/bin/$script" --help > "$WORK_BASE/help-$LABEL-$script.txt" 2>&1 \
            && ok "console script --help ($LABEL $script)" \
            || fail "console script --help ($LABEL $script)"
    done
    "$PREFIX/bin/msbwt-bwt-tags" list --input "$M10" \
        > "$WORK_BASE/tool-$LABEL-bwt-tags-list.json" 2>&1 \
        && grep -q '"row_id"' "$WORK_BASE/tool-$LABEL-bwt-tags-list.json" \
        && ok "msbwt-bwt-tags list ($LABEL)" \
        || fail "msbwt-bwt-tags list ($LABEL)"
    "$PREFIX/bin/msbwt-bwt-tags" validate --input "$M10" \
        > "$WORK_BASE/tool-$LABEL-bwt-tags-validate.json" 2>&1 \
        && grep -q '"valid": true' "$WORK_BASE/tool-$LABEL-bwt-tags-validate.json" \
        && ok "msbwt-bwt-tags validate ($LABEL)" \
        || fail "msbwt-bwt-tags validate ($LABEL)"
    "$PREFIX/bin/msbwt-lcp" validate --input "$M10" \
        > "$WORK_BASE/tool-$LABEL-lcp-validate.json" 2>&1 \
        && grep -q '"valid": true' "$WORK_BASE/tool-$LABEL-lcp-validate.json" \
        && ok "msbwt-lcp validate ($LABEL)" \
        || fail "msbwt-lcp validate ($LABEL)"
    "$PREFIX/bin/msbwt-quality-sidecar" validate --input "$M10" \
        > "$WORK_BASE/tool-$LABEL-quality-validate.json" 2>&1 \
        && grep -q '"valid": true' "$WORK_BASE/tool-$LABEL-quality-validate.json" \
        && ok "msbwt-quality-sidecar validate ($LABEL)" \
        || fail "msbwt-quality-sidecar validate ($LABEL)"
    "$PREFIX/bin/msbwt-remove-sources" --input "$M10" \
        --output "$GATE_DIR/fixture/tools-reduced" \
        --remove sample00,sample02,sample09 --drop-lcp \
        > "$WORK_BASE/tool-$LABEL-remove.json" 2>&1 \
        && grep -q '"read_provenance_preserved": true' "$WORK_BASE/tool-$LABEL-remove.json" \
        && ok "msbwt-remove-sources ($LABEL)" \
        || fail "msbwt-remove-sources ($LABEL)"
    "$PREFIX/bin/msbwt-quality-sidecar" validate \
        --input "$GATE_DIR/fixture/tools-reduced" \
        > "$WORK_BASE/tool-$LABEL-quality-reduced.json" 2>&1 \
        && grep -q '"valid": true' "$WORK_BASE/tool-$LABEL-quality-reduced.json" \
        && ok "quality sidecar valid after removal ($LABEL)" \
        || fail "quality sidecar valid after removal ($LABEL)"
    SOURCE_ARGS=""
    for sid in sample00 sample01 sample02 sample03 sample04 sample05 \
               sample06 sample07 sample08 sample09; do
        SOURCE_ARGS="$SOURCE_ARGS --source $sid=$LEAVES/$sid"
    done
    # shellcheck disable=SC2086
    "$PREFIX/bin/msbwt-retrofit-read-provenance" --merged "$M10" \
        $SOURCE_ARGS --overwrite \
        > "$WORK_BASE/tool-$LABEL-retrofit.txt" 2>&1 \
        && grep -q "read provenance written" "$WORK_BASE/tool-$LABEL-retrofit.txt" \
        && ok "msbwt-retrofit-read-provenance ($LABEL)" \
        || fail "msbwt-retrofit-read-provenance ($LABEL)"
    "$PREFIX/bin/msbwt-benchmark-index" inspect --input "$M10" \
        --output "$WORK_BASE/tool-$LABEL-bench.json" \
        > "$WORK_BASE/tool-$LABEL-bench-inspect.log" 2>&1 \
        && grep -q '"N": 191' "$WORK_BASE/tool-$LABEL-bench.json" \
        && ok "msbwt-benchmark-index inspect ($LABEL)" \
        || fail "msbwt-benchmark-index inspect ($LABEL)"
    "$PREFIX/bin/msbwt-benchmark-index" contract \
        --output "$WORK_BASE/tool-$LABEL-contract.json" \
        > /dev/null 2>&1 \
        && grep -q '"contract_version"' "$WORK_BASE/tool-$LABEL-contract.json" \
        && ok "msbwt-benchmark-index contract ($LABEL)" \
        || fail "msbwt-benchmark-index contract ($LABEL)"
done

# ---------------------------------------------------------------------------
# summary + evidence
# ---------------------------------------------------------------------------
echo "=== enhanced release-candidate summary ==="
if grep -q "^FAIL" "$RES"; then
    echo "FAILURES:"; grep "^FAIL" "$RES"
    RESULT="FAIL"
else
    RESULT="PASS"
fi
STARTING_COMMIT=$(git -C "$REPO" rev-parse --short HEAD)
BRANCH=$(git -C "$REPO" branch --show-current)
python3 - "$RESULT" "$RES" "$WORK_BASE" "$SDIST_NAME" "$SDIST_SHA" \
    "$SDIST_SIZE" "$WHEEL_NAME" "$WHEEL_SHA" "$WHEEL_SIZE" \
    "$STARTING_COMMIT" "$BRANCH" "$REPO" "$EVIDENCE_OUT" <<'PY'
import json, os, re, sys
(result, res_path, work, sdist_name, sdist_sha, sdist_size,
 wheel_name, wheel_sha, wheel_size, commit, branch, repo,
 evidence_out) = sys.argv[1:]
entries = []
for ln in open(res_path).read().strip().splitlines():
    m = re.match(r"^(PASS|FAIL): (.*)$", ln)
    if m:
        entries.append({"status": m.group(1), "check": m.group(2)})
artifact = re.match(r"^sdist: (\S+) (\d+) bytes sha256=(\S+)$",
                    open(res_path).read(), re.M)
wheel_m = re.match(r"^wheel: (\S+) (\d+) bytes sha256=(\S+)$",
                   open(res_path).read(), re.M)

def import_report(label):
    try:
        return json.load(open(os.path.join(
            work, "import-%s" % label, "report.json")))
    except Exception:
        return {}

def gate_report(label):
    try:
        return json.load(open(os.path.join(
            work, "gate-%s" % label, "gate-report.json")))
    except Exception:
        return {}

evidence = {
    "format": "msbwt-modern2-enhanced-release-candidate-evidence-v1",
    "distribution": "msbwt-modern2",
    "version": "0.3.0",
    "branch": branch,
    "commit": commit,
    "status": "release-candidate",
    "result": result,
    "checks": entries,
    "n_pass": sum(1 for e in entries if e["status"] == "PASS"),
    "n_fail": sum(1 for e in entries if e["status"] == "FAIL"),
    "build": {
        "environment": "pinned python27-modern2 prefix (bootstrap-modern2.sh)",
        "commands": ["python setup.py sdist", "python setup.py bdist_wheel"],
        "disposable_copy": True,
        "cython_policy": "exactly 3.0.12, language_level=2; generated C committed",
    },
    "sdist": {
        "filename": sdist_name,
        "sha256": sdist_sha,
        "size": int(sdist_size),
    },
    "wheel": {
        "filename": wheel_name,
        "sha256": wheel_sha,
        "size": int(wheel_size),
        "tag": wheel_name.split("-", 2)[2].rsplit(".whl", 1)[0],
    },
    "install_environments": [],
    "legacy_gate": {},
    "enhanced_gate": {},
    "tools": {},
    "release_blockers": [],
}
for label in ("wheel", "sdist"):
    rep = import_report(label)
    gate = gate_report(label)
    evidence["install_environments"].append({
        "id": "fresh-prefix (%s install)" % label,
        "artifact_installed": sdist_name if label == "sdist" else wheel_name,
        "imports": {
            "module_failures": [
                k for k, v in rep.get("modules", {}).items()
                if not v.get("ok")
            ],
            "not_site_packages": [
                v.get("__file__") for v in rep.get("modules", {}).values()
                if v.get("__file__") and "site-packages" not in v.get("__file__", "")
            ],
            "sys_path_leaks": rep.get("sys_path_leaks", []),
        },
    })
    evidence["enhanced_gate"][label] = {
        "mismatch_count": gate.get("mismatch_count"),
        "integrated_comparisons": gate.get("integrated_package", {}).get("comparisons"),
        "reduced_comparisons": gate.get("reduced_package", {}).get("comparisons"),
        "integrated_N": gate.get("benchmark", {}).get("integrated_N"),
        "reduced_N": gate.get("benchmark", {}).get("reduced_N"),
        "rebuild_payload_equal": gate.get("reduced_package", {}).get("rebuild_payload_equal"),
        "rebuild_whole_file_equal": gate.get("reduced_package", {}).get("rebuild_whole_file_equal"),
    }
os.makedirs(os.path.dirname(evidence_out), exist_ok=True)
json.dump(evidence, open(evidence_out, "w"), indent=1, sort_keys=True)
print("evidence written to %s" % evidence_out)
print("RESULT: %s" % result)
PY
if [ "$RESULT" = "FAIL" ]; then exit 1; fi
exit 0
