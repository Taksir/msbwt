#!/usr/bin/env bash
# msbwt-modern2 Feature 10 validation driver: source removal / unmerge
# without FASTQ rebuild.
#
# Validates the Feature-10 layer (MUS/SourceRemoval + MUS/ReadProvenance
# filter_read_provenance) over:
#   - the ten-source read-derived fixture: reduced msbwt.npy BYTE-FOR-BYTE
#     equal to an independent suffix sort of the retained reads for 6+
#     removal shapes; retained constituents recover to their standalone
#     BWTs; single-source collapse to a leaf package byte-identical to the
#     standalone; read provenance filtered with mate remapping; metadata
#     group/predicate removal; input bytes unchanged; no stale rank
#     caches
#   - REAL modern2 construction (pp + cfpp with legacy about.npy) and REAL
#     GenericMerge merges: reduced counts == retained standalone counts;
#     retain-one byte equality; about-based read provenance survival
#   - deterministic randomized Level-3 differential (seed 20260811)
#
# Gates (all must pass):
#   1. environment: CPython 2.7, Cython 3.0.x, NumPy 1.16.6, pysam 0.15.4
#   2. all modern2 Python-2 tests green (includes the Feature-10 suite)
#   3. fixture hashes (uniform-a.fastq, uniform-b.fastq)
#   4. evidence generator: zero mismatches
# If --evidence is given, a JSON record of every gate is written.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: validate/feature10-source-removal.sh --prefix /absolute/prefix --package /absolute/package --repository /absolute/repo [--evidence /absolute/out.json]'
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
for tool in python3 sha256sum git; do command -v "$tool" >/dev/null 2>&1 || { printf 'Missing required tool: %s\n' "$tool" >&2; exit 69; }; done

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
FIXTURES="$REPOSITORY/compat/fixtures/synthetic"

WORK=$(mktemp -d /tmp/modern2-feature10-XXXXXX)
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

gate_py2_tests() {
    (cd "$PACKAGE" && "$PREFIX/bin/python" -B -m unittest discover -s tests) > "$WORK/py2-tests.log" 2>&1
    printf 'gate_py2_tests OK\n'
}

gate_fixtures() {
    python3 - "$FIXTURES" "$WORK" <<'PY'
import hashlib, json, os, sys
fixtures = sys.argv[1]
work = sys.argv[2]
expected = {
    'uniform-a.fastq': ('da3466b992e0ba4ef4da2d0731062661f13e66b83ec154b56471ec4286798180', 173),
    'uniform-b.fastq': ('04124b73a3dde82da5cd70d9d244180d6e076a952dda404e4746b1e9388e1029', 162),
}
report = {}
for name, (digest, size) in expected.items():
    path = os.path.join(fixtures, name)
    data = open(path, 'rb').read()
    actual = (hashlib.sha256(data).hexdigest(), len(data))
    assert actual == (digest, size), (name, actual)
    report[name] = {'sha256': digest, 'size': size}
json.dump(report, open(os.path.join(work, 'fixtures.json'), 'w'), indent=2, sort_keys=True)
print('gate_fixtures OK')
PY
}

run_evidence() {
    (cd "$PACKAGE" && "$PREFIX/bin/python" -B \
        validate/feature10_source_removal_evidence.py "$WORK/evidence.json")
    python3 - "$WORK" <<'PY'
import json, os, sys
work = sys.argv[1]
data = json.load(open(os.path.join(work, 'evidence.json')))
assert data['mismatch_count'] == 0, data['mismatch_count']
assert data['seed'] == 20260811, data['seed']
shapes = data['byte_equality']
assert shapes['shapes'] >= 6
assert shapes['mismatches'] == 0
assert data['single_source_leaf']
rp = data['read_provenance']
assert rp['read_count'] == rp['expected_read_count']
assert rp['mates_remapped']
meta = data['metadata']
assert meta['group_removal'] and meta['predicate_removal']
real = data['real_integration']
assert real['mismatches'] == 0
assert real['comparisons'] > 100
rand = data['randomized']
assert rand['seed'] == 20260811
assert rand['cases'] == 18
assert rand['mismatches'] == 0
print('run_evidence OK')
PY
}

gate_env
record environment "$("$PREFIX/bin/python" -c 'import json, sys; sys.stdout.write(json.dumps({"python": sys.version.split()[0], "cython": __import__("Cython").__version__, "numpy": __import__("numpy").__version__, "pysam": __import__("pysam").__version__, "cc": __import__("os").environ.get("CC", "")}))')"
STARTING_COMMIT=$(git -C "$REPOSITORY" rev-parse --short HEAD)
record starting_commit "\"$STARTING_COMMIT\""
gate_py2_tests
record py2_tests '{"status": "ok", "suite": "packages/msbwt-modern2 tests, including Feature-10"}'
gate_fixtures
record fixtures "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/fixtures.json")"
run_evidence
record evidence "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/evidence.json")"
record final '{"branch": "enhanced-modern2", "milestone": "enhanced-modern2-feature10-source-removal", "feature": "Feature 10: Source Removal / Unmerge Without FASTQ Rebuild", "status": "passed"}'
if [ -n "$EVIDENCE" ]; then cp "$RESULT_FILE" "$EVIDENCE"; printf 'Evidence written to %s\n' "$EVIDENCE"; fi
printf 'feature10-source-removal OK\n'
