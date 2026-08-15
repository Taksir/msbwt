#!/usr/bin/env bash
# enhanced-modern2 final integration gate.
#
# Builds ONE integrated multi-source package carrying every verified
# enhanced feature layer (provenance, read provenance, metadata groups,
# BWT-aligned tags, Q1 quality, Feature-11A LCP), exercises each
# feature's semantics against the independent fixture oracles, derives a
# Feature-10 source-removed package and verifies the supported semantics
# there, then runs Feature-13A benchmark/accounting on both packages.
#
# Gates:
#   1. environment: CPython 2.7, Cython 3.0.x, NumPy 1.16.6, pysam 0.15.4
#   2. integration gate script: zero mismatches
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: validate/enhanced-integration-gate.sh --prefix /absolute/prefix --package /absolute/package --repository /absolute/repo [--evidence /absolute/out.json]'
}

PREFIX=''
PACKAGE=''
REPOSITORY=''
EVIDENCE=''
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=${2:?--prefix requires a value}; shift 2 ;;
        --package) PACKAGE=${2:?--package requires a value}; shift 2 ;;
        --repository) REPOSITORY=${2:?--repository requires a value}; shift 2 ;;
        --evidence) EVIDENCE=${2:?--evidence requires a value}; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 64 ;;
    esac
done
if [ -z "$PREFIX" ] || [ -z "$PACKAGE" ] || [ -z "$REPOSITORY" ]; then usage >&2; exit 64; fi
case "$PREFIX:$PACKAGE:$REPOSITORY" in /*:/*:/*) ;; *) printf 'All paths must be absolute Linux paths.\n' >&2; exit 64;; esac
if [ ! -x "$PREFIX/bin/python" ]; then printf 'Python not found in prefix: %s\n' "$PREFIX" >&2; exit 66; fi
if [ ! -d "$PACKAGE" ] || [ ! -d "$REPOSITORY" ]; then printf 'Package or repository directory not found.\n' >&2; exit 66; fi
for tool in python3 git; do command -v "$tool" >/dev/null 2>&1 || { printf 'Missing required tool: %s\n' "$tool" >&2; exit 69; }; done

export PATH="$PREFIX/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export TZ=UTC
export PYTHONHASHSEED=0
export PYTHONNOUSERSITE=1
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
unset PYTHONHOME PYTHONPATH PYTHONUSERBASE
export PIP_CONFIG_FILE=/dev/null
unset AR AS CC CXX CFLAGS CPPFLAGS CXXFLAGS LD LDFLAGS
unset CONDA_BUILD_SYSROOT _CONDA_PYTHON_SYSCONFIGDATA_NAME
export CONDA_PREFIX="$PREFIX"
set +u
for activation_name in activate-binutils_linux-64.sh activate-gcc_linux-64.sh activate-gxx_linux-64.sh; do
    activation_path="$PREFIX/etc/conda/activate.d/$activation_name"
    [ -f "$activation_path" ] && . "$activation_path"
done
set -u
if [ -z "${CC:-}" ]; then printf 'Compiler activation failed: CC is empty.\n' >&2; exit 69; fi

export MSBWT_MODERN2_REPO="$REPOSITORY"

WORK=$(mktemp -d /tmp/enhanced-integration-XXXXXX)
trap 'rm -rf "$WORK"' EXIT
RESULT_FILE="$WORK/result.json"
echo '{}' > "$RESULT_FILE"

record() {
    python3 - "$RESULT_FILE" "$1" "$2" <<'PY'
import json, sys
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(path))
data[key] = json.loads(value)
json.dump(data, open(path, 'w'), indent=2, sort_keys=True)
PY
}

gate_env() {
    "$PREFIX/bin/python" - <<'PY'
import sys
assert sys.version_info[:2] == (2, 7)
import Cython, numpy, pysam
assert Cython.__version__.startswith('3.0.'), Cython.__version__
assert numpy.__version__ == '1.16.6'
assert pysam.__version__ == '0.15.4'
print('gate_env OK')
PY
}

run_gate() {
    (cd "$PACKAGE" && "$PREFIX/bin/python" -B \
        validate/enhanced_integration_gate.py "$WORK/gate.json")
    python3 - "$WORK" <<'PY'
import json, os, sys
work = sys.argv[1]
data = json.load(open(os.path.join(work, 'gate.json')))
assert data['mismatch_count'] == 0, data['mismatch_count']
assert data['seed'] == 20260811, data['seed']
integrated = data['integrated_package']
assert integrated['comparisons'] > 200
assert integrated['mismatches'] == 0
reduced = data['reduced_package']
assert reduced['read_count'] == 21
assert reduced['lcp_absent']
assert reduced['comparisons'] > 100
assert reduced['mismatches'] == 0
bench = data['benchmark']
assert bench['integrated_N'] == 191
assert bench['reduced_N'] == 133
assert bench['integrated_lcp_available']
assert not bench['reduced_lcp_available']
print('run_gate OK')
PY
}

gate_env
record environment "$("$PREFIX/bin/python" -c 'import json, sys; sys.stdout.write(json.dumps({"python": sys.version.split()[0], "cython": __import__("Cython").__version__, "numpy": __import__("numpy").__version__, "pysam": __import__("pysam").__version__, "cc": __import__("os").environ.get("CC", "")}))')"
STARTING_COMMIT=$(git -C "$REPOSITORY" rev-parse --short HEAD)
record starting_commit "\"$STARTING_COMMIT\""
run_gate
record gate "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/gate.json")"
record final '{"branch": "enhanced-modern2", "milestone": "enhanced-modern2-final-integration-gate", "feature": "Final integration gate: all enhanced features in one package + source removal + 13A accounting", "status": "passed"}'
if [ -n "$EVIDENCE" ]; then cp "$RESULT_FILE" "$EVIDENCE"; printf 'Evidence written to %s\n' "$EVIDENCE"; fi
printf 'enhanced-integration-gate OK\n'
