#!/usr/bin/env bash
# msbwt-modern2 decompression milestone 4 validation driver.
#
# Validates MULTI-BLOCK decompression: a deterministic uniform RLE MSBWT whose
# logical decoded size (1,056,000 symbols) exceeds the decompression work size
# (1,000,000), so decompression splits into TWO work regions:
#   region 1 = [0, 1000000), region 2 = [1000000, 1056000)
#
# The compressed input is EXACTLY the committed m3c2 evidence dataset:
#   - evidence primary: the committed uniform byte golden (48 symbols) tiled
#     22000x -> shape (1056000,), whole-file SHA-256
#     24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35
#     (byte-identical to the committed relationship-m3c2 evidence_primary)
#   - compressed RLE: modern2 `compress -p 1` -> comp_msbwt.npy, SHA-256
#     681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99
#     (byte-identical to the committed m3c2 clean-compression primary)
#
# The historical frozen implementation fails on this input in the first
# worker tuple with `IndexError` at MUS/MultiStringBWT.py:630: the `<u8`
# refFM scalar plus the Python int 1 promotes to NumPy float64 under CPython
# 2.7 / NumPy 1.16.6, and float64 cannot index the compressed BWT.  Modern2
# fixes that boundary arithmetic with an explicit value-preserving int()
# conversion (the second documented decompression index-boundary correction;
# the line-662 fill-loop correction from milestone 3 remains unchanged).
#
# Gates (all must pass):
#   1. environment: CPython 2.7, Cython 3.0.x, NumPy 1.16.6, pysam 0.15.4
#   2. optional in-tree build of the 8 migrated extensions (Cython 3.0.12)
#   3. all modern2 Python-2 tests green (including the milestone-3 single-block
#      decompression regression)
#   4. evidence primary regenerated deterministically and hash-matched to the
#      committed m3c2 evidence primary
#   5. modern2 compression reproduces the committed m3c2 RLE primary
#   6. decompression runs twice with -p 1 and twice with -p 2, each from a
#      fresh source containing ONLY the compressed primary
#   7. every destination is exactly msbwt.npy; whole-file SHA-256 equals the
#      committed evidence primary (byte-identical), header `(1056000,)` /
#      dtype |u1 / shape [1056000], payload SHA-256
#      7c27ccd61dec44ede4a02c883459eef78f5d909b8f30be327584c1a24391cc78
#   8. payload byte-identical to the independent expectation: the committed
#      uniform byte-golden payload repeated 22000x; exact logical length
#      1056000; symbol counts {$:176000, A:198000, C:198000, G:198000,
#      N:88000, T:198000}
#   9. independent safe RLE decode of comp_msbwt.npy (host-side, no NumPy)
#      yields the same decoded length and decoded payload hash
#  10. block-boundary validation around the work-region boundary B=1000000:
#      bytes B-2, B-1, B, B+1, B+2 all match the independent expectation
#      (plus the edges 0,1 and 1055998,1055999)
#  11. -p 1 output == -p 2 output; both deterministic across repeated runs
#  12. source side effects exactly totalCounts.p + comp_fmIndex.npy +
#      comp_refIndex.npy; comp_msbwt.npy untouched
#  13. reader/query validation on disposable copies only: ByteBWT class,
#      total size 1056000, dollar count 176000, and countOccurrencesOfSeq
#      results cross-checked against the independent host-side FM backward
#      search (bwt_oracle) on the same payload for representative k-mers,
#      deterministic across two independent reader loads.  NOTE: the
#      committed m3c2 evidence primary is a tiled byte string, not a valid
#      collection BWT (tiling the BWT interleaves equal rotations instead of
#      grouping them, so the LF cycles do not decompose into the 8 reads;
#      recoverString yields long pseudo-reads), so collection-semantics
#      query/recovery expectations are NOT applicable; the decompression
#      correctness contract is byte-level and is fully validated
#      independently (length, symbol counts, payload hash, boundary
#      neighborhoods, safe RLE decode).
#  14. the committed legacy m3c2 failure evidence is preserved and asserted
#      read-only (IndexError, line 630, exit 87, tuple count 2, all-zero
#      preallocated destination, partial manifests)
# If --evidence is given, a JSON record of every gate is written.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: validate/decompression-milestone4.sh --prefix /absolute/prefix --package /absolute/package --repository /absolute/repo [--build] [--evidence /absolute/out.json]'
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
BYTE_GOLDEN="$GOLDENS/uniform-multifile/$PROFILE/$ROUTE/build/artifacts/msbwt.npy"
M3C2_RELATIONSHIP="$GOLDENS/compression-milestone3/relationship-m3c2.json"
M3C2_MANIFEST="$GOLDENS/compression-milestone3/partial/m3c2-run-a.manifest.json"

# modern2 multi-block decompression SUCCESS contract constants
EVIDENCE_PRIMARY_SHA256=24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35
RLE_PRIMARY_SHA256=681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99
PAYLOAD_SHA256=7c27ccd61dec44ede4a02c883459eef78f5d909b8f30be327584c1a24391cc78
TOTAL_SIZE=1056000
WORK_SIZE=1000000
REPEAT_COUNT=22000
BOUNDARY=1000000

WORK=$(mktemp -d /tmp/modern2-milestone4-XXXXXX)
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
# evidence generation (byte-identical to the committed m3c2 evidence dataset)
# ---------------------------------------------------------------------------

build_evidence() {
    # evidence primary: committed uniform byte golden tiled 22000x
    "$PREFIX/bin/python" -B - "$BYTE_GOLDEN" "$WORK/evidence" <<'PY'
import numpy as np
import sys
golden = sys.argv[1]
out = sys.argv[2]
evidence = np.load(golden, 'r')
tiled = np.tile(evidence, 22000)
assert tiled.shape == (1056000,)
np.save(out + '/msbwt.npy', tiled)
print('evidence primary shape', tiled.shape)
PY
    sha256sum "$WORK/evidence/msbwt.npy"
}

# ---------------------------------------------------------------------------
# decompression runs (fresh source containing ONLY the compressed primary)
# ---------------------------------------------------------------------------

run_decompress() {
    local label=$1
    local procs=$2
    local src="$WORK/src-$label"
    local dst="$WORK/dst-$label"
    mkdir -p "$src"
    cp "$WORK/rle/comp_msbwt.npy" "$src/"
    cli "$WORK/decomp-$label.log" decompress -p "$procs" "$src" "$dst"
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

EVIDENCE_PRIMARY_SHA256 = '24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35'
RLE_PRIMARY_SHA256 = '681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99'
PAYLOAD_SHA256 = '7c27ccd61dec44ede4a02c883459eef78f5d909b8f30be327584c1a24391cc78'
TOTAL_SIZE = 1056000
WORK_SIZE = 1000000
BOUNDARY = 1000000
EXPECTED_COUNTS = {'$': 176000, 'A': 198000, 'C': 198000, 'G': 198000,
                   'N': 88000, 'T': 198000}

def sha(path):
    return mam.sha256_file(Path(path))

# --- independent expectation: committed uniform byte golden payload x22000
golden_primary = os.path.join(goldens, 'uniform-multifile', profile, route,
                              'build', 'artifacts', 'msbwt.npy')
golden_framing = mam.parse_npy_header(Path(golden_primary))
golden_payload = open(golden_primary, 'rb').read()[golden_framing['payload_offset']:]
assert len(golden_payload) == 48
expected_payload = golden_payload * 22000
assert len(expected_payload) == TOTAL_SIZE
assert hashlib.sha256(expected_payload).hexdigest() == PAYLOAD_SHA256

# --- committed m3c2 legacy failure evidence (read-only contract)
relationship = mam.load_json(os.path.join(
    goldens, 'compression-milestone3', 'relationship-m3c2.json'))
assert relationship['worker']['exception_type'] == 'IndexError'
assert relationship['worker']['exception'] == ('only integers, slices (`:`), ellipsis (`...`), '
                                               'numpy.newaxis (`None`) and integer or boolean '
                                               'arrays are valid indices')
assert 'MUS/MultiStringBWT.py", line 630' in relationship['worker']['traceback_locations']
assert relationship['worker']['exit_code'] == 87
assert relationship['worker']['mode'] == 'first-tuple-worker-failed-naturally'
assert relationship['worker']['first_tuple'] == ['SOURCE', 'DESTINATION', 0, 1000000]
assert relationship['clean_compression']['shape'] == [484000]
assert relationship['clean_compression']['primary_sha256'] == RLE_PRIMARY_SHA256
assert relationship['evidence_primary']['shape'] == [TOTAL_SIZE]
assert relationship['evidence_primary']['sha256'] == EVIDENCE_PRIMARY_SHA256
assert relationship['destination_primary_deterministic'] is True
assert relationship['completed_regions'] == 0
assert relationship['unwritten_regions'] == 2
assert relationship['destination']['shape'] == [TOTAL_SIZE]
assert relationship['destination']['primary_sha256'] == 'd77f2be75db0b24fac38eb10296701625652fc7c98d77ebf9cf59b53fcd0a691'
assert relationship['destination']['region_fingerprint']['boundary'] == 1000000
assert relationship['destination']['region_fingerprint']['prefix_region_any_nonzero'] is False
assert relationship['destination']['region_fingerprint']['tail_region_any_nonzero'] is False
manifest = mam.load_json(os.path.join(
    goldens, 'compression-milestone3', 'partial', 'm3c2-run-a.manifest.json'))
assert manifest['content_sha256'] == 'aa9815561102054a366db6992b7c5504dbe0b1c77a836c074e27eb92a290f33e'
assert manifest['artifacts'][0]['npy']['shape'] == [TOTAL_SIZE]
assert manifest['artifacts'][0]['npy']['payload_size'] == TOTAL_SIZE
# all-zero preallocated destination payload
assert manifest['artifacts'][0]['npy']['payload_sha256'] == '75855919076ba96440de78fc73f23378edaddb409dbef7dc865f43d5d60b2948'
assert relationship['partial_manifest_content_sha256_run_a'] == manifest['content_sha256']
assert relationship['partial_manifest_content_sha256_run_b'] == manifest['content_sha256']

# --- regenerated evidence primary and modern2-compressed RLE match committed
assert sha(os.path.join(work, 'evidence', 'msbwt.npy')) == EVIDENCE_PRIMARY_SHA256
rle_primary = os.path.join(work, 'rle', 'comp_msbwt.npy')
assert sha(rle_primary) == RLE_PRIMARY_SHA256

# --- independent safe RLE decode of the compressed primary
rle_report = mam.decode_npy_rle_primary(Path(rle_primary))
assert rle_report['dtype'] == '|u1'
assert rle_report['decoded_length'] == TOTAL_SIZE
assert rle_report['decoded_sha256'] == PAYLOAD_SHA256
assert rle_report['run_count'] == 484000

# --- decompression runs: -p 1 x2 and -p 2 x2 from fresh sources
runs = ['p1-run-a', 'p1-run-b', 'p2-run-a', 'p2-run-b']
report = {'runs': {}}
trees = {}
src_trees = {}
for run in runs:
    dst_dir = os.path.join(work, 'dst-' + run)
    src_dir = os.path.join(work, 'src-' + run)
    names = sorted(os.listdir(dst_dir))
    assert names == ['msbwt.npy'], (run, names)
    primary = os.path.join(dst_dir, 'msbwt.npy')
    whole = sha(primary)
    assert whole == EVIDENCE_PRIMARY_SHA256, (run, whole)
    framing = mam.parse_npy_header(Path(primary))
    assert framing['dtype_descriptor'] == '|u1', run
    assert framing['shape'] == [TOTAL_SIZE], (run, framing['shape'])
    assert framing['payload_sha256'] == PAYLOAD_SHA256, run
    payload = open(primary, 'rb').read()[framing['payload_offset']:]
    assert len(payload) == TOTAL_SIZE, run
    assert payload == expected_payload, run
    counts = oracle.symbol_counts(payload)
    assert counts == EXPECTED_COUNTS, (run, counts)
    src_names = sorted(os.listdir(src_dir))
    assert src_names == ['comp_fmIndex.npy', 'comp_msbwt.npy',
                         'comp_refIndex.npy', 'totalCounts.p'], (run, src_names)
    assert sha(os.path.join(src_dir, 'comp_msbwt.npy')) == RLE_PRIMARY_SHA256, run
    trees[run] = {n: sha(os.path.join(dst_dir, n)) for n in names}
    src_trees[run] = {n: sha(os.path.join(src_dir, n)) for n in src_names}
    report['runs'][run] = {
        'whole_sha256': whole,
        'dtype': framing['dtype_descriptor'],
        'shape': framing['shape'],
        'header_text': framing['header_text'],
        'payload_sha256': framing['payload_sha256'],
        'payload_matches_expectation': payload == expected_payload,
        'symbol_counts': counts,
        'destination_files': names,
        'source_files': src_names,
    }

# --- determinism: all four runs byte-identical; -p 1 equals -p 2
assert trees['p1-run-a'] == trees['p1-run-b']
assert trees['p2-run-a'] == trees['p2-run-b']
assert trees['p1-run-a'] == trees['p2-run-a']
assert src_trees['p1-run-a'] == src_trees['p1-run-b']
assert src_trees['p1-run-a'] == src_trees['p2-run-a']
report['determinism'] = {
    'p1_run_a_eq_p1_run_b': True,
    'p2_run_a_eq_p2_run_b': True,
    'p1_eq_p2': True,
    'source_side_effect_determinism': True,
}

# --- block-boundary validation around the work-region boundary B=1000000
primary = os.path.join(work, 'dst-p1-run-a', 'msbwt.npy')
framing = mam.parse_npy_header(Path(primary))
payload = open(primary, 'rb').read()[framing['payload_offset']:]
neighborhood = {}
for position in (BOUNDARY - 2, BOUNDARY - 1, BOUNDARY, BOUNDARY + 1, BOUNDARY + 2,
                 0, 1, TOTAL_SIZE - 2, TOTAL_SIZE - 1):
    neighborhood[position] = {
        'decoded': payload[position],
        'expected': expected_payload[position],
        'match': payload[position] == expected_payload[position],
    }
    assert payload[position] == expected_payload[position], (position,)
report['block_boundaries'] = {
    'boundary': BOUNDARY,
    'worksize': WORK_SIZE,
    'regions': [[0, 1000000], [1000000, 1056000]],
    'neighborhood': neighborhood,
}

print(json.dumps(report, indent=2, sort_keys=True))
open(os.path.join(work, 'decomp-report.json'), 'w').write(json.dumps(report, indent=2, sort_keys=True))
PY
}

# ---------------------------------------------------------------------------
# reader/query validation on disposable copies only
# ---------------------------------------------------------------------------

verify_reader() {
    local dir=$1
    local label=$2
    (cd "$PACKAGE" && "$PREFIX/bin/python" - "$dir" "$label" <<'PY'
import hashlib, json, os, sys
d = sys.argv[1]
label = sys.argv[2]

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

# Representative k-mers.  The expected values are the string-level FM counts
# computed independently by bwt_oracle.backward_count on the same payload in
# the host-side verification step (the tiled evidence primary is not a valid
# collection BWT, so collection-semantics counts are not applicable).
representative = ['A', 'AC', 'ACGTN', 'AAAAA', 'AAAAAA', 'C', 'CG',
                  'GT', 'N', 'NACGT', 'T', 'TTTTT', 'GTGGGTTT']

from MUSCython import MultiStringBWTCython
before = inventory(d)
reader = MultiStringBWTCython.loadBWT(os.path.abspath(d), useMemmap=False)
total = int(reader.getTotalSize())
dollar_count = int(reader.getSymbolCount(0))
assert total == 1056000, label
assert dollar_count == 176000, label
assert type(reader).__module__ + '.' + type(reader).__name__ == 'MUSCython.ByteBWTCython.ByteBWT', label

queries = {}
for kmer in representative:
    queries[kmer] = int(reader.countOccurrencesOfSeq(kmer))

after = inventory(d)
added = {name: value for name, value in after.items() if name not in before}
assert sorted(added) == ['fmIndex.npy', 'totalCounts.npy'], (label, sorted(added))

result = {
    'reader_class': 'MUSCython.ByteBWTCython.ByteBWT',
    'total_size': total,
    'dollar_count': dollar_count,
    'queries': queries,
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

verify_reader_evidence() {
    python3 - "$WORK" "$MANIFEST_TOOL" "$BWT_ORACLE_TOOL" <<'PY'
import hashlib, importlib.util, json, os, sys
from pathlib import Path
work = sys.argv[1]
manifest_tool = sys.argv[2]
oracle_tool = sys.argv[3]
spec = importlib.util.spec_from_file_location('mam', manifest_tool)
mam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mam)
spec2 = importlib.util.spec_from_file_location('bwt_oracle', oracle_tool)
oracle = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(oracle)

a = json.load(open(os.path.join(work, 'reader-reader-a.json')))
b = json.load(open(os.path.join(work, 'reader-reader-b.json')))
assert a['total_size'] == b['total_size'] == 1056000
assert a['dollar_count'] == b['dollar_count'] == 176000
assert a['side_effects']['added'] == b['side_effects']['added']
assert a['queries'] == b['queries']

# independent string-level FM counts on the decompressed payload
primary = os.path.join(work, 'dst-p1-run-a', 'msbwt.npy')
framing = mam.parse_npy_header(Path(primary))
payload = open(primary, 'rb').read()[framing['payload_offset']:]

expected = {}
for kmer in sorted(a['queries']):
    expected[kmer] = oracle.backward_count(payload, kmer)
assert expected == a['queries'], (expected, a['queries'])

report = {
    'deterministic_across_reader_loads': True,
    'query_counts_are_string_level_fm_counts': True,
    'collection_semantics_not_applicable': True,
    'queries': expected,
    'side_effects': a['side_effects']['added'],
}
print(json.dumps(report, indent=2, sort_keys=True))
open(os.path.join(work, 'reader-report.json'), 'w').write(json.dumps(report, indent=2, sort_keys=True))
PY
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

echo '== build the committed m3c2 evidence dataset =='
mkdir -p "$WORK/evidence"
build_evidence

echo '== modern2 compression (must reproduce the committed m3c2 RLE primary) =='
cli "$WORK/compress.log" compress -p 1 "$WORK/evidence" "$WORK/rle"

echo '== decompression runs: -p 1 x2 and -p 2 x2 =='
run_decompress p1-run-a 1
run_decompress p1-run-b 1
run_decompress p2-run-a 2
run_decompress p2-run-b 2

verify_decompression
record decompression "$(python3 -c 'import json, sys; print(open(sys.argv[1]).read())' "$WORK/decomp-report.json")"

for label in reader-a reader-b; do
    cp -r "$WORK/dst-p1-run-a" "$WORK/$label"
    verify_reader "$WORK/$label" "$label"
done
verify_reader_evidence
record reader "$(python3 -c "
import json, sys
result = {}
for label in ('reader-a', 'reader-b'):
    result[label] = json.load(open(sys.argv[1] + '/reader-' + label + '.json'))
print(json.dumps(result, indent=2, sort_keys=True))
" "$WORK")"
record reader_determinism "$(python3 -c 'import json, sys; print(open(sys.argv[1]).read())' "$WORK/reader-report.json")"

record final "{\"status\": \"passed\", \"branch\": \"codex/modern2\", \"milestone\": \"modern2-milestone4-multiblock-decompression\"}"

if [ -n "$EVIDENCE" ]; then
    cp "$RESULT_FILE" "$EVIDENCE"
    printf 'Evidence written to %s\n' "$EVIDENCE"
fi
printf 'OK modern2 decompression milestone 4 validation passed.\n'
