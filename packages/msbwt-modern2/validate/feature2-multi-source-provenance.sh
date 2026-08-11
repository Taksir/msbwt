#!/usr/bin/env bash
# msbwt-modern2 Feature 2 validation driver: persistent multi-source
# provenance / source indexing.
#
# Validates the additive pure-Python layer MUS/MultiSourceProvenance.py over:
#   - REAL modern2 construction (pp + cfpp) of many standalone source BWTs
#   - REAL GenericMerge.mergeTwoMSBWTs two-way merges composed into
#     multi-stage trees (balanced merge_many_balanced and unbalanced chains)
#   - the persisted provenance manifest + interleave store
#   - an independent rotation-sort provenance oracle
#   - the Feature-1 compatibility contract (row- and query-level agreement
#     with MUS.SourceIndex for two sources)
#   - corruption/staleness detection and atomic writes
#
# Gates (all must pass):
#   1. environment: CPython 2.7, Cython 3.0.x, NumPy 1.16.6, pysam 0.15.4
#   2. all modern2 Python-2 tests green (includes the Feature-2 suite)
#   3. fixture hashes (uniform-a.fastq, uniform-b.fastq)
#   4. canonical Feature-1 compatibility: every merged row's Feature-2
#      provenance equals Feature-1's inter0.npy interpretation, and every
#      canonical query splits identically per source
#   5. multi-stage provenance: 3-source chain, 4-source balanced,
#      4-source unbalanced, 5-source balanced, 10-source balanced; every
#      original source BWT recovered bit-for-bit; independent rotation
#      oracle exact on unambiguous rows, tied rows by per-source
#      multiplicity; per-symbol joint provenance + LF-recovered multiset
#      consistent
#   6. deterministic 3-source edge corpus (12 classes)
#   7. randomized suite: 40 datasets (3-8 sources) + 4 explicit 10-source
#      datasets, seed 20260811; zero mismatches
#   8. corruption/staleness probes all detected (same-length replaced BWT,
#      copied manifest, same-length same-count replaced interleave,
#      truncated manifest, wrong version, wrong-dtype interleave, missing
#      interleave, BWT-length mismatch)
#   9. atomic-write probe (no .tmp leftovers, deterministic bytes)
#  10. performance/storage sanity measurements
# If --evidence is given, a JSON record of every gate is written.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: validate/feature2-multi-source-provenance.sh --prefix /absolute/prefix --package /absolute/package --repository /absolute/repo [--evidence /absolute/out.json]'
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

WORK=$(mktemp -d /tmp/modern2-feature2-XXXXXX)
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
    # the evidence generator runs the canonical case, Feature-1
    # compatibility, multi-stage merge cases (3/4/5/10 sources, balanced and
    # unbalanced trees), the 3-source edge corpus, the 40-dataset randomized
    # suite + 4 explicit 10-source datasets, corruption/staleness probes,
    # the atomic-write probe, and performance sanity; any mismatch fails with
    # a full dump.
    (cd "$PACKAGE" && "$PREFIX/bin/python" -B \
        validate/feature2_multi_source_evidence.py "$WORK/evidence.json")
    python3 - "$WORK" <<'PY'
import json, os, sys
work = sys.argv[1]
data = json.load(open(os.path.join(work, 'evidence.json')))
assert data['mismatch_count'] == 0, data['mismatch_count']
assert data['randomized_datasets'] == 40, data['randomized_datasets']
assert data['explicit_ten_source_datasets'] == 4, data['explicit_ten_source_datasets']
assert data['seed'] == 20260811, data['seed']
assert data['ten_source_fixture']['source_count'] == 10
assert data['ten_source_fixture']['extraction_mismatches'] == 0
assert data['ten_source_fixture']['reload_ok']
assert data['ten_source_fixture']['depth'] == 4
assert data['ten_source_fixture']['exact_rows_checked'] > 0, \
    data['ten_source_fixture']
assert data['feature1_compatibility']['row_mismatches'] == 0
assert data['feature1_compatibility']['query_mismatches'] == 0
assert data['feature1_compatibility']['rows_compared'] == 48
assert data['feature1_compatibility']['queries_compared'] >= 49
for probe, detected in data['corruption_probes'].items():
    assert detected, probe
assert data['atomic_write_probe']['deterministic_bytes']
assert data['atomic_write_probe']['no_tmp_leftovers']
cases = {case['case']: case for case in data['deterministic_cases']}
for name in ('canonical-two-source', 'three-source-chain',
             'four-source-balanced', 'four-source-unbalanced',
             'five-source-balanced', 'ten-source-balanced'):
    assert cases[name]['extraction_mismatches'] == 0, name
    assert cases[name]['reload_ok'], name
canonical = cases['canonical-two-source']
assert canonical['exact_rows_checked'] > 0, canonical
assert canonical['tied_rows_multiplicity_checked'] > 0, canonical
assert len(data['edge_corpus']) == 12, len(data['edge_corpus'])
assert data['dataset_mismatches'] == 0
assert data['case_mismatches'] == 0
assert data['edge_mismatches'] == 0
print('run_evidence OK')
PY
}

gate_env
record environment "$("$PREFIX/bin/python" -c 'import json, sys; sys.stdout.write(json.dumps({"python": sys.version.split()[0], "cython": __import__("Cython").__version__, "numpy": __import__("numpy").__version__, "pysam": __import__("pysam").__version__, "cc": __import__("os").environ.get("CC", "")}))')"
STARTING_COMMIT=$(git -C "$REPOSITORY" rev-parse --short HEAD)
record starting_commit "\"$STARTING_COMMIT\""
gate_py2_tests
record py2_tests '{"status": "ok", "suite": "packages/msbwt-modern2 tests, including Feature-2"}'
gate_fixtures
record fixtures "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/fixtures.json")"
run_evidence
record evidence "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/evidence.json")"
record final '{"branch": "enhanced-modern2", "milestone": "enhanced-modern2-feature2-multi-source-provenance", "feature": "Feature 2: Persistent Multi-Source Provenance / Source Indexing", "status": "passed"}'
if [ -n "$EVIDENCE" ]; then cp "$RESULT_FILE" "$EVIDENCE"; printf 'Evidence written to %s\n' "$EVIDENCE"; fi
printf 'feature2-multi-source-provenance OK\n'
