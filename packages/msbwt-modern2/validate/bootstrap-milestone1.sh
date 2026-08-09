#!/usr/bin/env bash
# msbwt-modern2 bootstrap milestone 1 validation driver.
#
# Usage:
#   validate/bootstrap-milestone1.sh --prefix /absolute/modern2/env \
#       --package /absolute/packages/msbwt-modern2 \
#       --repository /absolute/msbwt \
#       [--build] [--install] [--evidence /absolute/output.json]
#
# Gates (all must pass):
#   1. environment: CPython 2.7, Cython 3.0.x, NumPy 1.16.6, pysam 0.15.4
#   2. in-tree build of the 8 migrated extensions (Cython 3.0.12, language_level=2)
#   3. Python-2 test suite (packages/msbwt-modern2/tests)
#   4. optional: pip install into the prefix, installed CLI + slice
#   5. the uniform-multifile slice, byte-compared against the committed legacy
#      golden manifest (pre and build stages)
#   6. reader/query smoke on a disposable copy, side-effect inventory
# If --evidence is given, a JSON record of every gate is written.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: validate/bootstrap-milestone1.sh --prefix /absolute/prefix --package /absolute/package --repository /absolute/repo [--build] [--install] [--evidence /absolute/out.json]'
}

PREFIX=''
PACKAGE=''
REPOSITORY=''
DO_BUILD=0
DO_INSTALL=0
EVIDENCE=''
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=${2:?--prefix requires a value}; shift 2 ;;
        --package) PACKAGE=${2:?--package requires a value}; shift 2 ;;
        --repository) REPOSITORY=${2:?--repository requires a value}; shift 2 ;;
        --build) DO_BUILD=1; shift ;;
        --install) DO_INSTALL=1; shift ;;
        --evidence) EVIDENCE=${2:?--evidence requires a value}; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 64 ;;
    esac
done
if [ -z "$PREFIX" ] || [ -z "$PACKAGE" ] || [ -z "$REPOSITORY" ]; then usage >&2; exit 64; fi
case "$PREFIX:$PACKAGE:$REPOSITORY" in /*:/*:/*) ;; *) printf 'All paths must be absolute Linux paths.\n' >&2; exit 64;; esac
if [ ! -x "$PREFIX/bin/python" ]; then printf 'Python not found in prefix: %s\n' "$PREFIX" >&2; exit 66; fi
if [ ! -d "$PACKAGE" ] || [ ! -d "$REPOSITORY" ]; then printf 'Package or repository directory not found.\n' >&2; exit 66; fi
for tool in python3 sha256sum; do command -v "$tool" >/dev/null 2>&1 || { printf 'Missing required tool: %s\n' "$tool" >&2; exit 69; }; done

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
GOLDEN="$REPOSITORY/compat/goldens/original-0.3.0/uniform-multifile/py27-late-05a7d6d83862/pyx-historical-cython"
FIXTURES="$REPOSITORY/compat/fixtures/synthetic"
MANIFEST_TOOL="$REPOSITORY/compat/tools/artifact_manifest.py"

WORK=$(mktemp -d /tmp/modern2-validate-XXXXXX)
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

gate_build() {
    (cd "$PACKAGE" && "$PREFIX/bin/python" setup.py build_ext --inplace)
    for name in AlignmentUtil BasicBWT ByteBWTCython LZW_BWTCython \
                MSBWTCompGenCython MSBWTGenCython MultiStringBWTCython RLE_BWTCython; do
        test -f "$PACKAGE/MUSCython/$name.so" || { printf 'Missing built module: %s\n' "$name" >&2; exit 70; }
    done
    printf 'gate_build OK\n'
}

gate_py2_tests() {
    (cd "$PACKAGE" && "$PREFIX/bin/python" -B -m unittest discover -s tests -v)
}

gate_slice() {
    mkdir -p "$WORK/out"
    cp "$FIXTURES/uniform-a.fastq" "$FIXTURES/uniform-b.fastq" "$WORK/"
    (cd "$PACKAGE" && "$PREFIX/bin/python" -c 'from MUS import CommandLineInterface; CommandLineInterface.mainRun()' \
        pp -u "$WORK/out" "$WORK/uniform-a.fastq" "$WORK/uniform-b.fastq") > "$WORK/pp.log" 2>&1
    cp -r "$WORK/out" "$WORK/pre-snapshot"
    (cd "$PACKAGE" && "$PREFIX/bin/python" -c 'from MUS import CommandLineInterface; CommandLineInterface.mainRun()' \
        cfpp -p 1 -u "$WORK/out") > "$WORK/cfpp.log" 2>&1

    python3 "$MANIFEST_TOOL" verify \
        --artifact-dir "$WORK/pre-snapshot" \
        --manifest "$GOLDEN/pre/manifest.json" \
        --output "$WORK/pre-verify.json"
    python3 "$MANIFEST_TOOL" verify \
        --artifact-dir "$WORK/out" \
        --manifest "$GOLDEN/build/manifest.json" \
        --output "$WORK/build-verify.json"
    python3 - "$WORK/build-verify.json" <<'PY'
import json, sys
check = json.load(open(sys.argv[1]))
assert check['matches'] is True, check
assert check['added'] == [] and check['removed'] == [] and check['changed'] == []
print('gate_slice manifest match OK')
PY

    cp -r "$WORK/out" "$WORK/reader-copy"
    (cd "$PACKAGE" && "$PREFIX/bin/python" - "$WORK/reader-copy" <<'PY'
import json, os, sys
from MUSCython import MultiStringBWTCython as CompiledBWT
d = sys.argv[1]
msbwt = CompiledBWT.loadBWT(d, logger=None)
assert type(msbwt).__module__ + '.' + type(msbwt).__name__ == 'MUSCython.ByteBWTCython.ByteBWT'
assert msbwt.getTotalSize() == 48
expected = [('AAAAA', 1), ('ACGTN', 3), ('CCCCC', 1), ('AGCTA', 0)]
for kmer, count in expected:
    assert msbwt.countOccurrencesOfSeq(kmer) == count, (kmer, msbwt.countOccurrencesOfSeq(kmer))
side_effects = sorted(os.listdir(d))
assert side_effects == sorted(['about.npy', 'fmIndex.npy', 'msbwt.npy', 'offsets.npy',
    'seqs.npy.0.npy', 'seqs.npy.1.npy', 'seqs.npy.2.npy', 'seqs.npy.3.npy',
    'seqs.npy.4.npy', 'seqs.npy.5.npy', 'totalCounts.npy']), side_effects
json.dump({'class': 'MUSCython.ByteBWTCython.ByteBWT', 'total_size': 48,
           'counts': dict(expected), 'side_effects': side_effects},
          open(sys.argv[1] + '.reader.json', 'w'))
print('gate_slice reader OK')
PY
)

    primary="$WORK/out/msbwt.npy"
    python3 - "$primary" <<'PY'
import hashlib, json, sys
data = open(sys.argv[1], 'rb').read()
assert hashlib.sha256(data).hexdigest() == 'dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f'
header_len = data[8] + data[9] * 256
header = data[10:10 + header_len].decode('ascii')
assert "'shape': (48L,)" in header
assert "'descr': '|u1'" in header
payload = hashlib.sha256(data[10 + header_len:]).hexdigest()
assert payload == '75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e', payload
json.dump({'sha256': hashlib.sha256(data).hexdigest(), 'dtype': '|u1', 'shape': '(48L,)',
           'header_len': header_len, 'payload_sha256': payload}, open(sys.argv[1] + '.primary.json', 'w'))
print('gate_slice primary OK')
PY
}

gate_install() {
    (cd "$PACKAGE" && "$PREFIX/bin/python" -m pip install --isolated --disable-pip-version-check \
        --no-deps --no-build-isolation --force-reinstall .) > "$WORK/pip-install.log" 2>&1
    "$PREFIX/bin/msbwt" -V > "$WORK/msbwt-version.txt" 2>&1
    grep -q '0.3.0 in MSBWT 0.3.0' "$WORK/msbwt-version.txt"
    mkdir -p "$WORK/installed-out"
    "$PREFIX/bin/msbwt" pp -u "$WORK/installed-out" "$WORK/uniform-a.fastq" "$WORK/uniform-b.fastq" > /dev/null 2>&1
    "$PREFIX/bin/msbwt" cfpp -p 1 -u "$WORK/installed-out" > /dev/null 2>&1
    python3 - "$WORK/installed-out/msbwt.npy" <<'PY'
import hashlib, sys
assert hashlib.sha256(open(sys.argv[1], 'rb').read()).hexdigest() == 'dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f'
print('gate_install OK')
PY
}

gate_env
record environment "$("$PREFIX/bin/python" -c 'import json, sys; sys.stdout.write(json.dumps({"python": sys.version.split()[0], "cython": __import__("Cython").__version__, "numpy": __import__("numpy").__version__, "pysam": __import__("pysam").__version__, "cc": __import__("os").environ.get("CC", "")}))')"
[ "$DO_BUILD" -eq 1 ] && gate_build
if [ "$DO_BUILD" -eq 1 ]; then
    record build "{\"status\": \"ok\", \"modules\": 8, \"cython\": \"3.0.12\", \"language_level\": 2}"
else
    record build "{\"status\": \"skipped\"}"
fi
gate_py2_tests
record py2_tests "{\"status\": \"ok\"}"
gate_slice
record slice "{\"status\": \"ok\", \"case\": \"uniform-multifile\", \"pre_match\": true, \"build_match\": true}"
if [ "$DO_INSTALL" -eq 1 ]; then
    gate_install
    record install "{\"status\": \"ok\"}"
fi
record final "{\"status\": \"passed\", \"branch\": \"codex/modern2\"}"

if [ -n "$EVIDENCE" ]; then
    cp "$RESULT_FILE" "$EVIDENCE"
    printf 'Evidence written to %s\n' "$EVIDENCE"
fi
printf 'OK modern2 bootstrap milestone 1 validation passed.\n'
