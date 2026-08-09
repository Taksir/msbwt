#!/usr/bin/env bash
# msbwt-modern2 compression milestone 2 validation driver.
#
# Validates the first RLE/compression slice of msbwt-modern2 against the
# committed legacy route-specific goldens:
#
#   direct-split : pp -u + cfpp -p 1 -u -c   -> uniform-direct-split
#   direct-wrapper: cffq -p 1 -u -c          -> uniform-direct-wrapper
#   posthoc      : compress -p 1             -> uniform-compress-posthoc
#
# Gates (all must pass):
#   1. environment: CPython 2.7, Cython 3.0.x, NumPy 1.16.6, pysam 0.15.4
#   2. optional in-tree build of the 8 migrated extensions (Cython 3.0.12)
#   3. each route runs twice (-p 1) plus once with -p 2
#   4. same-route determinism: identical retained file sets and whole-file
#      bytes across run-a, run-b, and run-p2
#   5. whole-file SHA-256, raw NPY header (including the historical (22L,) vs
#      (22,) shape literal distinction), dtype, shape, and payload SHA-256
#      match the committed route-specific golden manifest
#   6. host-side safe RLE decoding (no NumPy/pickle) matches the committed
#      decoded-rle.json for each route; cross-route payload equality
#   7. reader/query validation on disposable copies only: RLE_BWT class,
#      total size, dollar count, fixture-derived query counts, recovered
#      strings, and exact derived side-effect inventory
# If --evidence is given, a JSON record of every gate is written.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: validate/compression-milestone2.sh --prefix /absolute/prefix --package /absolute/package --repository /absolute/repo [--build] [--evidence /absolute/out.json]'
}

PREFIX=''
PACKAGE=''
REPOSITORY=''
DO_BUILD=0
EVIDENCE=''
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=${2:?--prefix requires a value}; shift 2 ;;
        --package) PACKAGE=${2:?--package requires a value}; shift 2 ;;
        --repository) REPOSITORY=${2:?--repository requires a value}; shift 2 ;;
        --build) DO_BUILD=1; shift ;;
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
GOLDENS="$REPOSITORY/compat/goldens/original-0.3.0"
PROFILE=py27-late-05a7d6d83862
ROUTE=pyx-historical-cython
FIXTURES="$REPOSITORY/compat/fixtures/synthetic"
MANIFEST_TOOL="$REPOSITORY/compat/tools/artifact_manifest.py"
BYTE_GOLDEN="$GOLDENS/uniform-multifile/$PROFILE/$ROUTE/build"

WORK=$(mktemp -d /tmp/modern2-milestone2-XXXXXX)
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

cli() {
    # run one CLI command under the modern2 package; logs to the work area
    local log=$1
    shift
    (cd "$PACKAGE" && "$PREFIX/bin/python" -c 'from MUS import CommandLineInterface; CommandLineInterface.mainRun()' "$@") > "$log" 2>&1
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

# ---------------------------------------------------------------------------
# route execution
# ---------------------------------------------------------------------------

run_direct_split() {
    local out=$1
    local procs=$2
    mkdir -p "$out"
    cp "$FIXTURES/uniform-a.fastq" "$FIXTURES/uniform-b.fastq" "$WORK/"
    cli "$WORK/pp.log" pp -u "$out" "$WORK/uniform-a.fastq" "$WORK/uniform-b.fastq"
    cli "$WORK/cfpp.log" cfpp -p "$procs" -u -c "$out"
}

run_direct_wrapper() {
    local out=$1
    local procs=$2
    mkdir -p "$WORK/wrapper-work"
    cp "$FIXTURES/uniform-a.fastq" "$FIXTURES/uniform-b.fastq" "$WORK/wrapper-work/"
    cli "$WORK/cffq.log" cffq -p "$procs" -u -c "$out" \
        "$WORK/wrapper-work/uniform-a.fastq" "$WORK/wrapper-work/uniform-b.fastq"
}

run_posthoc() {
    local out=$1
    local procs=$2
    # source is the committed uniform byte BWT (authoritative legacy bytes)
    mkdir -p "$WORK/posthoc-src"
    cp "$BYTE_GOLDEN/artifacts/msbwt.npy" "$WORK/posthoc-src/"
    cli "$WORK/compress.log" compress -p "$procs" "$WORK/posthoc-src" "$out"
}

# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------

verify_routes() {
    python3 - "$WORK" "$GOLDENS" "$PROFILE" "$ROUTE" "$MANIFEST_TOOL" <<'PY'
import hashlib, importlib.util, json, os, subprocess, sys
from pathlib import Path

work, goldens, profile, route, tool = sys.argv[1:6]
spec = importlib.util.spec_from_file_location('mam', tool)
mam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mam)

def sha(path):
    return mam.sha256_file(Path(path))

EXPECTED = {
    'direct-split': {
        'golden': 'uniform-direct-split',
        'shape_literal': '(22L,)',
        'whole_sha256': '0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372',
        'payload_sha256': '6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb',
    },
    'direct-wrapper': {
        'golden': 'uniform-direct-wrapper',
        'shape_literal': '(22L,)',
        'whole_sha256': '0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372',
        'payload_sha256': '6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb',
    },
    'posthoc': {
        'golden': 'uniform-compress-posthoc',
        'shape_literal': '(22,)',
        'whole_sha256': '53d82b388a9d565afa96ead611d5db964bee199869fd07f96b8c84258ba099a3',
        'payload_sha256': '6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb',
    },
}
DECODED_SHA256 = '75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e'
DECODED_BWT = 'ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$'

def dir_tree_hash(root):
    entries = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            entries.append((name, sha(path)))
        else:
            raise AssertionError('unexpected non-file entry: ' + path)
    return entries

report = {}
for route_key, config in EXPECTED.items():
    golden_dir = os.path.join(goldens, config['golden'], profile, route)
    entry = {'golden': config['golden']}
    runs = ['run-a', 'run-b', 'run-p2']
    trees = {}
    for run in runs:
        artifact_dir = os.path.join(work, route_key, run)
        trees[run] = dir_tree_hash(artifact_dir)
        primary = os.path.join(artifact_dir, 'comp_msbwt.npy')
        whole = sha(primary)
        assert whole == config['whole_sha256'], (route_key, run, whole)
        entry[run + '_whole_sha256'] = whole

    assert trees['run-a'] == trees['run-b'], (route_key, 'run-a != run-b')
    assert trees['run-a'] == trees['run-p2'], (route_key, 'run-a != run-p2')
    entry['run_a_equals_run_b'] = True
    entry['run_a_equals_run_p2'] = True

    # manifest byte comparison against the committed route golden
    expected_manifest = mam.load_json(os.path.join(golden_dir, 'manifest.json'))
    actual_manifest = mam.inventory_directory(os.path.join(work, route_key, 'run-a'))
    comparison = mam.compare_manifest(expected_manifest, actual_manifest)
    assert comparison['matches'] is True, (route_key, comparison)
    assert comparison['added'] == [] and comparison['removed'] == [] and comparison['changed'] == []
    entry['golden_manifest_match'] = True

    # raw NPY header / dtype / shape / payload checks on run-a
    primary = os.path.join(work, route_key, 'run-a', 'comp_msbwt.npy')
    decoded = mam.decode_npy_rle_primary(primary)
    assert decoded['dtype'] == '|u1', (route_key, decoded['dtype'])
    assert decoded['shape'] == [22], (route_key, decoded['shape'])
    assert decoded['shape_literal'] == config['shape_literal'], (route_key, decoded['shape_literal'])
    assert decoded['payload_sha256'] == config['payload_sha256'], (route_key, decoded['payload_sha256'])
    assert decoded['run_count'] == 22, (route_key, decoded['run_count'])
    assert decoded['decoded_length'] == 48, (route_key, decoded['decoded_length'])
    assert decoded['decoded_sha256'] == DECODED_SHA256, (route_key, decoded['decoded_sha256'])
    assert decoded['decoded_bwt'] == DECODED_BWT, (route_key, decoded['decoded_bwt'])
    # committed decoded-rle.json identity
    committed = mam.load_json(os.path.join(golden_dir, 'decoded-rle.json'))
    for key in ('runs', 'run_count', 'decoded_length', 'decoded_sha256', 'decoded_bwt',
                'dtype', 'header_text', 'payload_sha256', 'payload_size'):
        assert decoded[key] == committed[key], (route_key, key)
    entry.update({
        'dtype': decoded['dtype'],
        'shape': decoded['shape'],
        'shape_literal': decoded['shape_literal'],
        'header_text': decoded['header_text'],
        'payload_sha256': decoded['payload_sha256'],
        'payload_size': decoded['payload_size'],
        'run_count': decoded['run_count'],
        'decoded_length': decoded['decoded_length'],
        'decoded_sha256': decoded['decoded_sha256'],
        'decoded_bwt': decoded['decoded_bwt'],
        'committed_decoded_rle_match': True,
    })
    report[route_key] = entry

# cross-route payload equality (all three primaries share the identical payload)
payloads = set()
for route_key, config in EXPECTED.items():
    primary = os.path.join(work, route_key, 'run-a', 'comp_msbwt.npy')
    payloads.add(mam.decode_npy_rle_primary(primary)['payload_sha256'])
assert len(payloads) == 1, payloads
report['cross_route'] = {
    'payload_equal': True,
    'payload_sha256': sorted(payloads)[0],
    'decoded_sha256': DECODED_SHA256,
    'decoded_bwt': DECODED_BWT,
    'direct_shape_literal': '(22L,)',
    'posthoc_shape_literal': '(22,)',
    'direct_equals_wrapper_whole': (
        sha(os.path.join(work, 'direct-split', 'run-a', 'comp_msbwt.npy'))
        == sha(os.path.join(work, 'direct-wrapper', 'run-a', 'comp_msbwt.npy'))),
}
# decoded BWT equals the committed byte-BWT primary payload
byte_manifest = mam.load_json(os.path.join(goldens, 'uniform-multifile', profile, route, 'build', 'manifest.json'))
byte_entry = next(e for e in byte_manifest['artifacts'] if e['path'] == 'msbwt.npy')
assert byte_entry['npy']['payload_sha256'] == DECODED_SHA256
report['decoded_matches_committed_byte_primary'] = True

print(json.dumps(report, indent=2, sort_keys=True))
open(os.path.join(work, 'route-report.json'), 'w').write(json.dumps(report, indent=2, sort_keys=True))
PY
}

verify_reader() {
    local dir=$1
    local label=$2
    (cd "$PACKAGE" && "$PREFIX/bin/python" - "$dir" "$FIXTURES" "$label" <<'PY'
import hashlib, json, os, sys
d = sys.argv[1]
fixtures = sys.argv[2]
label = sys.argv[3]

def read_fastq_sequences(path):
    with open(path, 'rb') as handle:
        lines = handle.read().splitlines()
    sequences = []
    for index in range(0, len(lines), 4):
        sequences.append(lines[index + 1])
    return sequences

def all_fixture_substrings(sequences):
    queries = set()
    for sequence in sequences:
        for start in range(len(sequence)):
            for end in range(start + 1, len(sequence) + 1):
                queries.add(sequence[start:end])
    longest = max(len(sequence) for sequence in sequences)
    queries.add(b'A' * (longest + 1))
    return sorted(queries)

def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        while True:
            block = handle.read(1 << 20)
            if not block:
                return digest.hexdigest()
            digest.update(block)

def inventory(root):
    result = {}
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            result[name] = {'sha256': sha256_file(path), 'size': os.path.getsize(path)}
    return result

sequences = read_fastq_sequences(os.path.join(fixtures, 'uniform-a.fastq'))
sequences += read_fastq_sequences(os.path.join(fixtures, 'uniform-b.fastq'))
queries = all_fixture_substrings(sequences)
expected_queries = {q.decode('ascii'): sum(
    1 for seq in sequences for off in range(0, len(seq) - len(q) + 1)
    if seq[off:off + len(q)] == q) for q in queries}
expected_recovered = sorted(b'$' + seq for seq in sequences)

from MUSCython import MultiStringBWTCython
before = inventory(d)
reader = MultiStringBWTCython.loadBWT(os.path.abspath(d), useMemmap=False)
actual_queries = {q.decode('ascii'): int(reader.countOccurrencesOfSeq(q)) for q in queries}
dollar_count = int(reader.getSymbolCount(0))
recovered = sorted(reader.recoverString(index) for index in range(dollar_count))
after = inventory(d)

assert type(reader).__module__ + '.' + type(reader).__name__ == 'MUSCython.RLE_BWTCython.RLE_BWT'
assert int(reader.getTotalSize()) == 48
assert actual_queries == expected_queries, label
assert recovered == expected_recovered, label
assert dollar_count == 8, label

added = {name: value for name, value in after.items() if name not in before}
expected_side_effects = {
    'comp_fmIndex.npy': 'f6565545114d769fbe6ba6010ce125c8690256f2d97562ceb65064b38d48c881',
    'comp_refIndex.npy': '30c0c0f336e69b86ee3da30f0f4ce1d9a138d503845c586e993ff31e8003fee1',
    'totalCounts.npy': 'ea104b616fe89d7b786acdff7ca0db61f6339a59c31fbf0fff066ad7384c1c2b',
}
assert sorted(added) == sorted(expected_side_effects), (label, sorted(added))
for name, digest in expected_side_effects.items():
    assert added[name]['sha256'] == digest, (label, name)

result = {
    'reader_class': 'MUSCython.RLE_BWTCython.RLE_BWT',
    'total_size': 48,
    'dollar_count': dollar_count,
    'queries_match': True,
    'recovered_match': True,
    'side_effects': {
        'added': [{'path': name, 'sha256': value['sha256'], 'size': value['size']}
                  for name, value in sorted(added.items())],
        'changed': [],
        'removed': [],
    },
}
open(os.path.join(d, '..', 'reader-' + label + '.json'), 'w').write(json.dumps(result, indent=2, sort_keys=True))
print('reader OK ' + label)
PY
)
}

gate_env
record environment "$("$PREFIX/bin/python" -c 'import json, sys; sys.stdout.write(json.dumps({"python": sys.version.split()[0], "cython": __import__("Cython").__version__, "numpy": __import__("numpy").__version__, "pysam": __import__("pysam").__version__, "cc": __import__("os").environ.get("CC", "")}))')"
if [ "$DO_BUILD" -eq 1 ]; then
    gate_build
    record build "{\"status\": \"ok\", \"modules\": 8, \"cython\": \"3.0.12\", \"language_level\": 2}"
else
    record build "{\"status\": \"skipped\"}"
fi
gate_py2_tests
record py2_tests "{\"status\": \"ok\"}"

for route_key in direct-split direct-wrapper posthoc; do
    for run in run-a run-b run-p2; do
        procs=1
        case "$run" in
            run-p2) procs=2 ;;
        esac
        out="$WORK/$route_key/$run"
        case "$route_key" in
            direct-split) run_direct_split "$out" "$procs" ;;
            direct-wrapper) run_direct_wrapper "$out" "$procs" ;;
            posthoc) run_posthoc "$out" "$procs" ;;
        esac
    done
done

verify_routes
record routes "$(python3 -c 'import json, sys; print(open(sys.argv[1]).read())' "$WORK/route-report.json")"

for entry in "direct-split:direct-a" "direct-wrapper:direct-wrapper-a" "posthoc:posthoc-a"; do
    route_key=${entry%%:*}
    label=${entry#*:}
    cp -r "$WORK/$route_key/run-a" "$WORK/reader-$label"
    verify_reader "$WORK/reader-$label" "$label"
done
record reader "$(python3 -c "
import json, sys
result = {}
for label in ('direct-a', 'direct-wrapper-a', 'posthoc-a'):
    result[label] = json.load(open(sys.argv[1] + '/reader-' + label + '.json'))
print(json.dumps(result, indent=2, sort_keys=True))
" "$WORK")"

record final "{\"status\": \"passed\", \"branch\": \"codex/modern2\", \"milestone\": \"modern2-milestone2-compression\"}"

if [ -n "$EVIDENCE" ]; then
    cp "$RESULT_FILE" "$EVIDENCE"
    printf 'Evidence written to %s\n' "$EVIDENCE"
fi
printf 'OK modern2 compression milestone 2 validation passed.\n'
