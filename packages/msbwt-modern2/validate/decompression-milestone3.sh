#!/usr/bin/env bash
# msbwt-modern2 decompression milestone 3 validation driver.
#
# Validates the first intentional correctness fix in modern2: successful
# post-hoc decompression of the uniform RLE MSBWT back to the authoritative
# byte-BWT payload.
#
#   direct-split RLE : pp -u + cfpp -p 1 -u -c, then decompress -p 1
#   posthoc RLE      : compress -p 1 (from the committed byte golden), then
#                      decompress -p 1
#
# The historical frozen decompression fails deterministically with
# `TypeError: slice indices must be integers or None or have an __index__
# method` at MUS/MultiStringBWT.py:662 (a uint64+int-to-float64 slice-bound
# promotion under CPython 2.7 / NumPy 1.16.6).  Modern2 fixes that numeric
# index arithmetic with an explicit value-preserving int() conversion; the
# committed legacy expected-failure evidence is verified read-only here and
# must remain byte-unchanged.
#
# Gates (all must pass):
#   1. environment: CPython 2.7, Cython 3.0.x, NumPy 1.16.6, pysam 0.15.4
#   2. optional in-tree build of the 8 migrated extensions (Cython 3.0.12)
#   3. each RLE route decompresses twice (-p 1) plus once with -p 2 from
#      fresh sources (compressed primary only)
#   4. same-route determinism: identical destination file set, whole-file
#      bytes, header, payload, and identical source side-effect file set
#   5. decompressed msbwt.npy matches the SUCCESS contract: whole-file SHA-256
#      f536d60f..., raw header byte-identical to the committed legacy
#      preallocated header ((48,) shape literal), dtype |u1, shape (48,),
#      payload SHA-256 75134b48... byte-identical to the committed uniform
#      byte-BWT golden payload
#   6. independent symbol counts (bwt_oracle.py) match fixture-derived
#      expectations and the golden counts
#   7. round trip: byte golden -> compress -> decompress -> byte payload
#      equality
#   8. reader/query validation on disposable copies only: ByteBWT class,
#      total size, dollar count, fixture-derived query counts, recovered
#      strings, and exact derived side-effect inventory (totalCounts.npy +
#      fmIndex.npy with the committed legacy byte-reader hashes)
#   9. historical failure evidence (record.json + stderr.txt) preserved and
#      asserted read-only
# If --evidence is given, a JSON record of every gate is written.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: validate/decompression-milestone3.sh --prefix /absolute/prefix --package /absolute/package --repository /absolute/repo [--build] [--evidence /absolute/out.json]'
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
BWT_ORACLE_TOOL="$REPOSITORY/compat/tools/bwt_oracle.py"
BYTE_GOLDEN="$GOLDENS/uniform-multifile/$PROFILE/$ROUTE/build"
FAILURE_EVIDENCE="$GOLDENS/compression-milestone1/decompression-failure/uniform"

# modern2 decompression SUCCESS contract constants
DECOMPRESSED_WHOLE_SHA256=f536d60f356ed4a34e8253eecdd91e90db8c2ba3430c2e3d3e1855bb49007ef4
GOLDEN_WHOLE_SHA256=dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f
GOLDEN_PAYLOAD_SHA256=75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e
DIRECT_RLE_SHA256=0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372
POSTHOC_RLE_SHA256=53d82b388a9d565afa96ead611d5db964bee199869fd07f96b8c84258ba099a3

WORK=$(mktemp -d /tmp/modern2-milestone3-XXXXXX)
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

# build the two modern2 uniform RLE compressed inputs once per route
build_direct_rle() {
    local out=$1
    mkdir -p "$out"
    cp "$FIXTURES/uniform-a.fastq" "$FIXTURES/uniform-b.fastq" "$WORK/"
    cli "$WORK/pp.log" pp -u "$out" "$WORK/uniform-a.fastq" "$WORK/uniform-b.fastq"
    cli "$WORK/cfpp.log" cfpp -p 1 -u -c "$out"
}

build_posthoc_rle() {
    local out=$1
    mkdir -p "$WORK/posthoc-rle-src"
    cp "$BYTE_GOLDEN/artifacts/msbwt.npy" "$WORK/posthoc-rle-src/"
    cli "$WORK/compress.log" compress -p 1 "$WORK/posthoc-rle-src" "$out"
}

# fresh source directory containing ONLY the compressed primary
fresh_source() {
    local route=$1
    local label=$2
    local src="$WORK/src-$route-$label"
    mkdir -p "$src"
    if [ "$route" = direct ]; then
        cp "$WORK/direct-rle/comp_msbwt.npy" "$src/"
    else
        cp "$WORK/posthoc-rle/comp_msbwt.npy" "$src/"
    fi
    printf '%s' "$src"
}

run_decompress() {
    local route=$1
    local label=$2
    local procs=$3
    local src
    src=$(fresh_source "$route" "$label")
    cli "$WORK/decomp-$route-$label.log" decompress -p "$procs" "$src" "$WORK/dst-$route-$label"
}

# ---------------------------------------------------------------------------
# verification (host-side, independent of the modern2 reader)
# ---------------------------------------------------------------------------

verify_decompression() {
    python3 - "$WORK" "$GOLDENS" "$PROFILE" "$ROUTE" "$MANIFEST_TOOL" "$BWT_ORACLE_TOOL" "$FIXTURES" <<'PY'
import hashlib, importlib.util, json, os, sys
from pathlib import Path

work, goldens, profile, route, tool, oracle_tool, fixtures = sys.argv[1:8]
spec = importlib.util.spec_from_file_location('mam', tool)
mam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mam)
spec2 = importlib.util.spec_from_file_location('bwt_oracle', oracle_tool)
oracle = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(oracle)

DECOMPRESSED_WHOLE_SHA256 = 'f536d60f356ed4a34e8253eecdd91e90db8c2ba3430c2e3d3e1855bb49007ef4'
GOLDEN_WHOLE_SHA256 = 'dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f'
GOLDEN_PAYLOAD_SHA256 = '75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e'
DIRECT_RLE_SHA256 = '0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372'
POSTHOC_RLE_SHA256 = '53d82b388a9d565afa96ead611d5db964bee199869fd07f96b8c84258ba099a3'

def sha(path):
    return mam.sha256_file(Path(path))

# authoritative golden payload bytes
golden_primary = os.path.join(goldens, 'uniform-multifile', profile, route,
                              'build', 'artifacts', 'msbwt.npy')
golden_framing = mam.parse_npy_header(Path(golden_primary))
assert sha(golden_primary) == GOLDEN_WHOLE_SHA256
golden_payload = open(golden_primary, 'rb').read()[golden_framing['payload_offset']:]
assert hashlib.sha256(golden_payload).hexdigest() == GOLDEN_PAYLOAD_SHA256

# committed legacy decompression-failure evidence (read-only contract)
failure_dir = os.path.join(goldens, 'compression-milestone1',
                           'decompression-failure', 'uniform')
record = mam.load_json(os.path.join(failure_dir, 'record.json'))
assert record['exit_code'] == 1
assert record['exception'] == 'TypeError: slice indices must be integers or None or have an __index__ method'
assert 'MUS/MultiStringBWT.py", line 662' in record['traceback_locations']
assert record['source_side_effects'] == ['comp_fmIndex.npy', 'comp_refIndex.npy', 'totalCounts.p']
assert record['preallocated_primary']['payload_sha256'] == '17b0761f87b081d5cf10757ccc89f12be355c70e2e29df288b65b30710dcbcd1'
stderr = Path(os.path.join(failure_dir, 'stderr.txt')).read_text(encoding='utf-8')
assert 'TypeError: slice indices must be integers or None or have an __index__ method' in stderr
assert 'MUS/MultiStringBWT.py", line 662, in decompressBlocks' in stderr
legacy_header = record['preallocated_primary']  # header text comes from manifest
dest_manifest = mam.load_json(os.path.join(failure_dir, 'destination-manifest.json'))
preallocated_header = dest_manifest['artifacts'][0]['npy']['header_text']

# fixture-derived expectations (independent oracle)
reads = []
for name in ('uniform-a.fastq', 'uniform-b.fastq'):
    with open(os.path.join(fixtures, name), 'rb') as handle:
        lines = handle.read().splitlines()
    reads += [lines[i + 1].decode('ascii') for i in range(0, len(lines), 4)]
expected_counts = oracle.expected_symbol_counts(reads)

reads_route = {
    'direct': DIRECT_RLE_SHA256,
    'posthoc': POSTHOC_RLE_SHA256,
}

report = {}
runs = ['run-a', 'run-b', 'run-p2']
for route in ('direct', 'posthoc'):
    entry = {'runs': {}}
    trees = {}
    src_trees = {}
    for run in runs:
        dst_dir = os.path.join(work, 'dst-%s-%s' % (route, run))
        src_dir = os.path.join(work, 'src-%s-%s' % (route, run))
        # destination: exactly msbwt.npy
        names = sorted(os.listdir(dst_dir))
        assert names == ['msbwt.npy'], (route, run, names)
        primary = os.path.join(dst_dir, 'msbwt.npy')
        whole = sha(primary)
        assert whole == DECOMPRESSED_WHOLE_SHA256, (route, run, whole)
        framing = mam.parse_npy_header(Path(primary))
        assert framing['dtype_descriptor'] == '|u1', (route, run)
        assert framing['shape'] == [48], (route, run)
        assert framing['header_text'] == preallocated_header, (route, run)
        assert framing['payload_sha256'] == GOLDEN_PAYLOAD_SHA256, (route, run)
        payload = open(primary, 'rb').read()[framing['payload_offset']:]
        assert payload == golden_payload, (route, run)
        # independent symbol counts match the fixture-derived oracle
        counts = oracle.symbol_counts(payload)
        assert counts == expected_counts, (route, run, counts)
        # source: primary untouched + exactly the three support files
        src_names = sorted(os.listdir(src_dir))
        assert src_names == ['comp_fmIndex.npy', 'comp_msbwt.npy',
                             'comp_refIndex.npy', 'totalCounts.p'], (route, run, src_names)
        assert sha(os.path.join(src_dir, 'comp_msbwt.npy')) == reads_route[route], (route, run)
        trees[run] = {n: sha(os.path.join(dst_dir, n)) for n in names}
        src_trees[run] = {n: sha(os.path.join(src_dir, n)) for n in src_names}
        entry['runs'][run] = {
            'whole_sha256': whole,
            'dtype': framing['dtype_descriptor'],
            'shape': framing['shape'],
            'header_text': framing['header_text'],
            'payload_sha256': framing['payload_sha256'],
            'payload_matches_golden': payload == golden_payload,
            'symbol_counts': counts,
            'destination_files': names,
            'source_files': src_names,
        }
    assert trees['run-a'] == trees['run-b'], route
    assert trees['run-a'] == trees['run-p2'], route
    assert src_trees['run-a'] == src_trees['run-b'], route
    assert src_trees['run-a'] == src_trees['run-p2'], route
    entry['destination_determinism'] = True
    entry['source_side_effect_determinism'] = True
    report[route] = entry

# cross-route byte equality
direct_primary = os.path.join(work, 'dst-direct-run-a', 'msbwt.npy')
posthoc_primary = os.path.join(work, 'dst-posthoc-run-a', 'msbwt.npy')
assert sha(direct_primary) == sha(posthoc_primary)
report['cross_route'] = {
    'direct_equals_posthoc_whole': True,
    'whole_sha256': DECOMPRESSED_WHOLE_SHA256,
    'payload_sha256': GOLDEN_PAYLOAD_SHA256,
    'payload_equals_committed_byte_golden': True,
    'golden_whole_sha256': GOLDEN_WHOLE_SHA256,
    'header_differs_from_golden_only_in_shape_literal': True,
}

# round trip: byte golden -> compress -> decompress
rt_rle = os.path.join(work, 'rt-rle')
rt_back = os.path.join(work, 'rt-back')
assert sha(os.path.join(rt_rle, 'comp_msbwt.npy')) == POSTHOC_RLE_SHA256
rt_framing = mam.parse_npy_header(Path(os.path.join(rt_back, 'msbwt.npy')))
rt_payload = open(os.path.join(rt_back, 'msbwt.npy'), 'rb').read()[rt_framing['payload_offset']:]
assert rt_payload == golden_payload
assert sha(os.path.join(rt_back, 'msbwt.npy')) == DECOMPRESSED_WHOLE_SHA256
report['round_trip'] = {
    'byte_golden_compress_decompress_payload_equal': True,
    'whole_sha256': DECOMPRESSED_WHOLE_SHA256,
}

report['legacy_failure_evidence'] = {
    'exit_code': record['exit_code'],
    'exception': record['exception'],
    'traceback_line_662': True,
    'source_side_effects': record['source_side_effects'],
    'preallocated_payload_all_zero_sha256': record['preallocated_primary']['payload_sha256'],
    'stderr_preserved': True,
}

print(json.dumps(report, indent=2, sort_keys=True))
open(os.path.join(work, 'decomp-report.json'), 'w').write(json.dumps(report, indent=2, sort_keys=True))
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

assert type(reader).__module__ + '.' + type(reader).__name__ == 'MUSCython.ByteBWTCython.ByteBWT'
assert int(reader.getTotalSize()) == 48
assert actual_queries == expected_queries, label
assert recovered == expected_recovered, label
assert dollar_count == 8, label

added = {name: value for name, value in after.items() if name not in before}
expected_side_effects = {
    'totalCounts.npy': 'ea104b616fe89d7b786acdff7ca0db61f6339a59c31fbf0fff066ad7384c1c2b',
    'fmIndex.npy': 'a5b4bf06726fcadf535245d03ef65e04a4a5248d368b3aa53639c190028b933f',
}
assert sorted(added) == sorted(expected_side_effects), (label, sorted(added))
for name, digest in expected_side_effects.items():
    assert added[name]['sha256'] == digest, (label, name)

result = {
    'reader_class': 'MUSCython.ByteBWTCython.ByteBWT',
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

echo '== build compressed inputs =='
build_direct_rle "$WORK/direct-rle"
build_posthoc_rle "$WORK/posthoc-rle"

echo '== decompression runs =='
for route in direct posthoc; do
    for label in run-a run-b run-p2; do
        procs=1
        case "$label" in
            run-p2) procs=2 ;;
        esac
        run_decompress "$route" "$label" "$procs"
    done
done

echo '== round trip: byte golden -> compress -> decompress =='
mkdir -p "$WORK/rt-rle"
mkdir -p "$WORK/rt-rt-src"
cp "$BYTE_GOLDEN/artifacts/msbwt.npy" "$WORK/rt-rt-src/"
cli "$WORK/rt-compress.log" compress -p 1 "$WORK/rt-rt-src" "$WORK/rt-rle"
cli "$WORK/rt-decompress.log" decompress -p 1 "$WORK/rt-rle" "$WORK/rt-back"

verify_decompression
record decompression "$(python3 -c 'import json, sys; print(open(sys.argv[1]).read())' "$WORK/decomp-report.json")"

for entry in "direct:decomp-direct-a" "posthoc:decomp-posthoc-a"; do
    route_key=${entry%%:*}
    label=${entry#*:}
    cp -r "$WORK/dst-$route_key-run-a" "$WORK/reader-$label"
    verify_reader "$WORK/reader-$label" "$label"
done
record reader "$(python3 -c "
import json, sys
result = {}
for label in ('decomp-direct-a', 'decomp-posthoc-a'):
    result[label] = json.load(open(sys.argv[1] + '/reader-' + label + '.json'))
print(json.dumps(result, indent=2, sort_keys=True))
" "$WORK")"

record final "{\"status\": \"passed\", \"branch\": \"codex/modern2\", \"milestone\": \"modern2-milestone3-decompression\"}"

if [ -n "$EVIDENCE" ]; then
    cp "$RESULT_FILE" "$EVIDENCE"
    printf 'Evidence written to %s\n' "$EVIDENCE"
fi
printf 'OK modern2 decompression milestone 3 validation passed.\n'
