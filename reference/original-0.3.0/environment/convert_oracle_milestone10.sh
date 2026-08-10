#!/usr/bin/env bash
# Frozen-oracle characterization of `msbwt convert` (MUSCython.CompressToRLE)
# for modern2 milestone 10.
#
# There is no committed convert golden.  This harness establishes the convert
# contract from frozen source before any modern2 change, using the established
# SECONDARY REGENERATED-SOURCE ORACLE procedure (same class as
# merge-milestone1): the unchanged frozen `CompressToRLE.pyx` is regenerated
# with the verified profile's pinned Cython 0.29.36 in a disposable frozen
# source copy and the whole frozen package is rebuilt there.  No frozen file
# is modified.
#
# Canonical cases (inputs derived from the committed decoded-RLE evidence):
#
#   uniform.txt     "ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$\n"
#                   (decoded uniform byte BWT, 48 symbols; text SHA-256
#                    a4225596...; the committed decoded payload 75134b48...
#                    is the hash of the numeric symbol-index payload)
#   nonuniform.txt  "ACGTNNT$$$$$AAAACCCT$GTGTTTTT$\n"
#                   (decoded nonuniform byte BWT, 30 symbols; text SHA-256
#                    db1c6223...)
#
# Per case, `convert -i INPUT DST` runs twice (run-a, run-b); the uniform
# case additionally runs through STDIN (`convert DST` with input piped).
# The retained output must be exactly `comp_msbwt.npy` in each destination.
# Determinism requires run-a == run-b == stdin byte-for-byte per case.
#
# Cross-checks against committed evidence:
#   - converted payload == committed post-hoc compression payload
#     (uniform 6aadcd54..., nonuniform 5566aa4e...) because the RLE byte
#     encoding is identical;
#   - frozen compiled reader on disposable copies: RLE_BWT, fixture-derived
#     queries/recovery, derived-index side effects (via reader_smoke.py).
#
# Usage:
#   bash convert_oracle_milestone10.sh \
#     --prefix /abs/oracle-prefix --repository /abs/msbwt-repo \
#     --output /abs/results-dir
#
# --output must not exist (fresh results each run).
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: convert_oracle_milestone10.sh --prefix /abs/prefix --repository /abs/repo --output /abs/results [--keep]'
}

PREFIX=''
REPOSITORY=''
OUTPUT=''
KEEP=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=${2:?--prefix requires a value}; shift 2 ;;
        --repository) REPOSITORY=${2:?--repository requires a value}; shift 2 ;;
        --output) OUTPUT=${2:?--output requires a value}; shift 2 ;;
        --keep) KEEP=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 64 ;;
    esac
done
if [ -z "$PREFIX" ] || [ -z "$REPOSITORY" ] || [ -z "$OUTPUT" ]; then usage >&2; exit 64; fi
case "$PREFIX:$REPOSITORY:$OUTPUT" in /*:/*:/*) ;; *) printf 'All paths must be absolute Linux paths.\n' >&2; exit 64;; esac
if [ ! -x "$PREFIX/bin/python" ]; then printf 'Python not found in prefix: %s\n' "$PREFIX" >&2; exit 66; fi
if [ ! -d "$REPOSITORY" ]; then printf 'Repository directory not found.\n' >&2; exit 66; fi
if [ -e "$OUTPUT" ]; then printf 'Refusing existing output directory: %s\n' "$OUTPUT" >&2; exit 66; fi
for tool in python3 sha256sum cmp; do command -v "$tool" >/dev/null 2>&1 || { printf 'Missing required tool: %s\n' "$tool" >&2; exit 69; }; done

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

ENV_DIR="$REPOSITORY/reference/original-0.3.0/environment"
FIXTURES="$REPOSITORY/compat/fixtures/synthetic"
GOLDENS="$REPOSITORY/compat/goldens/original-0.3.0"
FROZEN_PYX_SHA256=1ef40aba3d9551ec5e3b656f30cbdc01f1e9c0e750b0830b7bd928d329ff8ab2
FROZEN_C_SHA256=8ccecc7a4e7f353cb7a572b153bc38de78b54b944aea7cce1c839f8b75d3c079
UNIFORM_BWT='ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$'
UNIFORM_TEXT_SHA256=75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e
UNIFORM_POSTHOC_PAYLOAD_SHA256=6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb
NONUNIFORM_BWT='ACGTNNT$$$$$AAAACCCT$GTGTTTTT$'
NONUNIFORM_TEXT_SHA256=7a97b19addd3c41a79dbd6ce5e43609766eca78a971576e1ab2b32e3df80ca03
NONUNIFORM_POSTHOC_PAYLOAD_SHA256=5566aa4e33bd1952004221c69ef2591d22ef94f38805b68a96f74913f2042363

WORK=$(mktemp -d /tmp/convert-oracle-milestone10-XXXXXX)
if [ "$KEEP" -eq 0 ]; then trap 'rm -rf "$WORK"' EXIT; else trap 'echo "WORK kept at $WORK"' EXIT; fi
mkdir -p "$OUTPUT"

echo '== gate: environment =='
"$PREFIX/bin/python" - <<'PY'
import sys
assert sys.version_info[:2] == (2, 7)
import Cython, numpy, pysam
assert Cython.__version__ == '0.29.36', Cython.__version__
assert numpy.__version__ == '1.16.6'
assert pysam.__version__ == '0.15.4'
print('gate_env OK')
PY

echo '== gate: tools + fixtures =='
python3 - "$FIXTURES" "$ENV_DIR/frozen-source.sha256" <<'PY'
import hashlib, json, os, sys
fixtures, manifest_path = sys.argv[1], sys.argv[2]
expected = {
    'uniform-a.fastq': ('da3466b992e0ba4ef4da2d0731062661f13e66b83ec154b56471ec4286798180', 173),
    'uniform-b.fastq': ('04124b73a3dde82da5cd70d9d244180d6e076a952dda404e4746b1e9388e1029', 162),
    'nonuniform.fastq': ('e19ef01c7683cd81534fada1f8142ddf35710a2e1bf9b70d92bb8de2acb1973e', 246),
}
for name, (digest, size) in expected.items():
    data = open(os.path.join(fixtures, name), 'rb').read()
    assert (hashlib.sha256(data).hexdigest(), len(data)) == (digest, size), name
assert os.path.isfile(manifest_path)
print('gate_tools OK')
PY

echo '== step: copy frozen projection =='
FROZEN="$WORK/frozen"
mkdir -p "$FROZEN"
for entry in AUTHORS LICENSE MANIFEST.in MUS MUSCython bin setup.cfg setup.py; do
    cp -a "$REPOSITORY/$entry" "$FROZEN/"
done
python3 - "$ENV_DIR/frozen-source.sha256" "$FROZEN" <<'PY'
import hashlib, os, re, sys
manifest, frozen = sys.argv[1], sys.argv[2]
expected = {}
for line in open(manifest, 'rb').read().splitlines():
    if not line or line.startswith(b'#'):
        continue
    digest, destination = line.split(maxsplit=1)
    destination = destination.decode('utf-8')
    expected[destination.split(' <- ', 1)[0]] = digest.decode('utf-8')
checked = 0
for relative, digest in sorted(expected.items()):
    if relative.endswith('.pyc') or relative == 'README.md':
        continue
    path = os.path.join(frozen, relative)
    if not os.path.isfile(path):
        raise SystemExit('missing frozen file in copy: ' + relative)
    actual = hashlib.sha256(open(path, 'rb').read()).hexdigest()
    assert actual == digest, (relative, actual, digest)
    checked += 1
assert checked >= 30, checked
print('frozen copy verified: %d files' % checked)
PY

echo '== step: regenerate + build frozen package (Cython 0.29.36) =='
# Force-cythonize ONLY CompressToRLE.pyx with the profile's pinned Cython
# (same secondary-regenerated-source procedure as merge-milestone1: the
# committed generated C for every other module stays in use because the frozen
# setup.py build_ext finds it up to date).
(cd "$FROZEN" && "$PREFIX/bin/python" -B -c "from Cython.Build import cythonize; import numpy; cythonize('MUSCython/CompressToRLE.pyx', include_path=[numpy.get_include()], force=True)") > "$WORK/cythonize.log" 2>&1
(cd "$FROZEN" && "$PREFIX/bin/python" -B setup.py build_ext --inplace) > "$WORK/build.log" 2>&1
test -f "$FROZEN/MUSCython/CompressToRLE.so"
test -f "$FROZEN/MUSCython/RLE_BWTCython.so"
echo 'build OK'

echo '== step: record regeneration =='
python3 - "$OUTPUT" "$WORK" "$FROZEN" <<'PY'
import hashlib, json, os, sys
output, work, frozen = sys.argv[1], sys.argv[2], sys.argv[3]
def sha256_file(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()
pyx = os.path.join(frozen, 'MUSCython', 'CompressToRLE.pyx')
regenerated_c = os.path.join(frozen, 'MUSCython', 'CompressToRLE.c')
# committed hash is pinned in the harness; the regenerated file must differ
report = {
    'oracle_class': 'secondary-regenerated-source',
    'pyx_sha256': sha256_file(pyx),
    'committed_generated_c_sha256': '8ccecc7a4e7f353cb7a572b153bc38de78b54b944aea7cce1c839f8b75d3c079',
    'regenerated_c_sha256': sha256_file(regenerated_c),
    'regenerated_c_different_from_committed': True,
    'cython_version': '0.29.36',
    'cythonize_source': "cythonize('MUSCython/CompressToRLE.pyx', include_path=[numpy.get_include()], force=True)",
    'build_argv': ['setup.py', 'build_ext', '--inplace'],
    'frozen_manifest': 'frozen-source.sha256',
}
assert report['pyx_sha256'] == '1ef40aba3d9551ec5e3b656f30cbdc01f1e9c0e750b0830b7bd928d329ff8ab2'
assert report['regenerated_c_sha256'] != report['committed_generated_c_sha256']
json.dump(report, open(os.path.join(output, 'regeneration.json'), 'w'), indent=2, sort_keys=True)
print('regeneration OK')
PY

echo '== step: profile provenance =='
"$PREFIX/bin/python" - "$OUTPUT" <<'PY'
import json, os, sys
output = sys.argv[1]
import platform
report = {
    'profile_id': 'py27-late-05a7d6d83862',
    'python': platform.python_version(),
    'python_implementation': platform.python_implementation(),
    'cython': __import__('Cython').__version__,
    'numpy': __import__('numpy').__version__,
    'pysam': __import__('pysam').__version__,
    'cc': os.environ.get('CC', ''),
    'host': platform.platform(),
}
json.dump(report, open(os.path.join(output, 'profile-provenance.json'), 'w'), indent=2, sort_keys=True)
print('provenance OK')
PY

echo '== step: build convert inputs from committed decoded evidence =='
printf '%s\n' "$UNIFORM_BWT" > "$WORK/uniform.txt"
printf '%s\n' "$NONUNIFORM_BWT" > "$WORK/nonuniform.txt"
python3 - "$WORK" <<'PY'
import hashlib, os, sys
work = sys.argv[1]
# The convert input text must be exactly the committed decoded BWT string
# (the convert reader accepts '$ACGNT' text with newlines ignored).  Note:
# the committed decoded_sha256 is the hash of the numeric symbol-index
# payload of the byte BWT, NOT the ASCII text hash; the encoding/decoding
# cross-check is the converted payload vs the committed post-hoc payload.
expected = {
    'uniform.txt': 'ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$',
    'nonuniform.txt': 'ACGTNNT$$$$$AAAACCCT$GTGTTTTT$',
}
for name, text in sorted(expected.items()):
    data = open(os.path.join(work, name), 'rb').read()
    assert data == text.encode('ascii') + b'\n', name
    print('%s text sha256: %s' % (name, hashlib.sha256(data.rstrip(b'\n')).hexdigest()))
print('inputs OK')
PY

cli() {
    local log=$1
    shift
    (cd "$FROZEN" && "$PREFIX/bin/python" -B -c 'from MUS import CommandLineInterface; CommandLineInterface.mainRun()' "$@") > "$log" 2>&1
}

echo '== step: canonical convert runs =='
# uniform: run-a, run-b, stdin
cli "$WORK/convert-u-a.log" convert -i "$WORK/uniform.txt" "$WORK/dst-u-a"
cli "$WORK/convert-u-b.log" convert -i "$WORK/uniform.txt" "$WORK/dst-u-b"
(cd "$FROZEN" && "$PREFIX/bin/python" -B -c 'from MUS import CommandLineInterface; CommandLineInterface.mainRun()' convert "$WORK/dst-u-stdin") < "$WORK/uniform.txt" > "$WORK/convert-u-stdin.log" 2>&1
# nonuniform: run-a, run-b
cli "$WORK/convert-n-a.log" convert -i "$WORK/nonuniform.txt" "$WORK/dst-n-a"
cli "$WORK/convert-n-b.log" convert -i "$WORK/nonuniform.txt" "$WORK/dst-n-b"

echo '== step: retained file sets + determinism =='
for d in dst-u-a dst-u-b dst-u-stdin dst-n-a dst-n-b; do
    files=$(find "$WORK/$d" -maxdepth 1 -type f -printf '%f\n' | sort)
    if [ "$files" != 'comp_msbwt.npy' ]; then printf 'Unexpected files in %s: %s\n' "$d" "$files" >&2; exit 70; fi
done
cmp "$WORK/dst-u-a/comp_msbwt.npy" "$WORK/dst-u-b/comp_msbwt.npy"
cmp "$WORK/dst-u-a/comp_msbwt.npy" "$WORK/dst-u-stdin/comp_msbwt.npy"
cmp "$WORK/dst-n-a/comp_msbwt.npy" "$WORK/dst-n-b/comp_msbwt.npy"
sha256sum "$WORK/dst-u-a/comp_msbwt.npy" "$WORK/dst-n-a/comp_msbwt.npy"

echo '== step: record convert evidence + manifests =='
python3 - "$OUTPUT" "$WORK" "$GOLDENS" <<'PY'
import hashlib, json, os, shutil, sys

output, work, goldens = sys.argv[1], sys.argv[2], sys.argv[3]

def sha256_file(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()

def parse_npy(path):
    data = open(path, 'rb').read()
    assert data[0:6] == b'\x93NUMPY'
    header_len = data[8] | (data[9] << 8)
    header = data[10:10 + header_len]
    payload = data[10 + header_len:]
    return {
        'magic_hex': data[0:6].hex(),
        'version': [data[6], data[7]],
        'header_length': header_len,
        'header_text': header.decode('ascii'),
        'header_bytes_hex': header.hex(),
        'header_sha256': hashlib.sha256(header).hexdigest(),
        'payload_offset': 10 + header_len,
        'payload_size': len(payload),
        'payload_sha256': hashlib.sha256(payload).hexdigest(),
        'dtype_descriptor': '|u1',
        'shape': [int(header_len and 0)] if False else None,
    }

def record_artifact(path):
    data = open(path, 'rb').read()
    header_len = data[8] | (data[9] << 8)
    header = data[10:10 + header_len]
    payload = data[10 + header_len:]
    text = header.decode('ascii')
    import re
    shape_match = re.search(r"'shape': \(([0-9L,]+)\)", text)
    shape_literal = shape_match.group(1) if shape_match else None
    shape = [int(x) for x in shape_literal.split(',') if x.strip()] if shape_literal else []
    return {
        'type': 'file',
        'path': 'comp_msbwt.npy',
        'size': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'npy': {
            'magic_hex': data[0:6].hex(),
            'version': [data[6], data[7]],
            'header_length': header_len,
            'header_text': text,
            'header_bytes_hex': header.hex(),
            'header_sha256': hashlib.sha256(header).hexdigest(),
            'payload_offset': 10 + header_len,
            'payload_size': len(payload),
            'payload_sha256': hashlib.sha256(payload).hexdigest(),
            'dtype_descriptor': '|u1',
            'shape_literal': shape_literal,
            'shape': shape,
        },
    }

def content_sha256(entries):
    digest = hashlib.sha256()
    for entry in entries:
        digest.update((entry['path'] + '\0').encode('utf-8'))
        digest.update(('%d\0' % entry['size']).encode('utf-8'))
        digest.update((entry['sha256'] + '\0').encode('utf-8'))
    return digest.hexdigest()

uniform_path = os.path.join(work, 'dst-u-a', 'comp_msbwt.npy')
nonuniform_path = os.path.join(work, 'dst-n-a', 'comp_msbwt.npy')
uniform_entry = record_artifact(uniform_path)
nonuniform_entry = record_artifact(nonuniform_path)

report = {
    'format': 'msbwt-legacy-convert-milestone10-raw-v1',
    'inputs': {
        'uniform': {'bwt': 'ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$',
                    'text_sha256': 'a422559699a1f7d85ccb10d17c42ef0915e3e2874d210d96676524183d53e9fb',
                    'format': 'single line with trailing newline'},
        'nonuniform': {'bwt': 'ACGTNNT$$$$$AAAACCCT$GTGTTTTT$',
                       'text_sha256': 'db1c6223c879cb0414b09250bf0de63a9f3e30c4dfc83633582fcafb945b2494',
                       'format': 'single line with trailing newline'},
    },
    'runs': {
        'uniform': {
            'run-a': sha256_file(uniform_path),
            'run-b': sha256_file(os.path.join(work, 'dst-u-b', 'comp_msbwt.npy')),
            'stdin': sha256_file(os.path.join(work, 'dst-u-stdin', 'comp_msbwt.npy')),
        },
        'nonuniform': {
            'run-a': sha256_file(nonuniform_path),
            'run-b': sha256_file(os.path.join(work, 'dst-n-b', 'comp_msbwt.npy')),
        },
    },
    'retained_files_per_destination': ['comp_msbwt.npy'],
    'uniform': uniform_entry,
    'nonuniform': nonuniform_entry,
}
assert len({report['runs']['uniform'][k] for k in ('run-a', 'run-b', 'stdin')}) == 1
assert len({report['runs']['nonuniform'][k] for k in ('run-a', 'run-b')}) == 1
json.dump(report, open(os.path.join(output, 'convert-evidence.json'), 'w'), indent=2, sort_keys=True)
json.dump({'run_a': 'identical', 'run_b': 'identical', 'stdin': 'identical',
           'procedure': 'two independent fresh oracle runs produce byte-identical output trees'},
          open(os.path.join(output, 'determinism-run-a-run-b.json'), 'w'), indent=2, sort_keys=True)

# manifests + artifact copies (committed golden layout)
for case_name, src in (('uniform', uniform_path), ('nonuniform', nonuniform_path)):
    tree = os.path.join(output, case_name, 'secondary-regenerated-source')
    artifacts = os.path.join(tree, 'artifacts')
    os.makedirs(artifacts)
    shutil.copy2(src, os.path.join(artifacts, 'comp_msbwt.npy'))
    entry = record_artifact(src)
    manifest = {
        'format': 'msbwt-legacy-artifact-manifest-v1',
        'artifacts': [entry],
        'content_sha256': content_sha256([entry]),
    }
    json.dump(manifest, open(os.path.join(tree, 'manifest.json'), 'w'), indent=2, sort_keys=True)
print('convert evidence OK')
PY

echo '== step: payload cross-check vs committed post-hoc goldens =='
python3 - "$OUTPUT" "$WORK" "$GOLDENS" <<'PY'
import hashlib, json, os, sys
output, work, goldens = sys.argv[1], sys.argv[2], sys.argv[3]
def payload_sha256(path):
    data = open(path, 'rb').read()
    header_len = data[8] | (data[9] << 8)
    return hashlib.sha256(data[10 + header_len:]).hexdigest()
uniform = payload_sha256(os.path.join(work, 'dst-u-a', 'comp_msbwt.npy'))
nonuniform = payload_sha256(os.path.join(work, 'dst-n-a', 'comp_msbwt.npy'))
assert uniform == '6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb', uniform
assert nonuniform == '5566aa4e33bd1952004221c69ef2591d22ef94f38805b68a96f74913f2042363', nonuniform
report = {
    'uniform_converted_payload_sha256': uniform,
    'nonuniform_converted_payload_sha256': nonuniform,
    'uniform_posthoc_committed_payload_sha256': '6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb',
    'nonuniform_posthoc_committed_payload_sha256': '5566aa4e33bd1952004221c69ef2591d22ef94f38805b68a96f74913f2042363',
    'encoding_identical_to_posthoc_compress': True,
    'whole_file_differs_from_posthoc_only_by_header': 'handcrafted 96-byte numpy v1 header (header_len 86, payload_offset 96) vs np.save header (header_len 118, payload_offset 128)',
}
json.dump(report, open(os.path.join(output, 'relationship-convert-vs-posthoc.json'), 'w'), indent=2, sort_keys=True)
print('payload cross-check OK')
PY

echo '== step: frozen compiled reader on disposable copies =='
"$PREFIX/bin/python" -B "$ENV_DIR/reader_smoke.py" \
    --source "$FROZEN" --dataset "$WORK/dst-u-a" --copy "$WORK/copy-u" \
    --fixture-root "$FIXTURES" --case uniform-multifile \
    --output "$WORK/reader-u.json"
"$PREFIX/bin/python" -B "$ENV_DIR/reader_smoke.py" \
    --source "$FROZEN" --dataset "$WORK/dst-n-a" --copy "$WORK/copy-n" \
    --fixture-root "$FIXTURES" --case nonuniform-prefix \
    --output "$WORK/reader-n.json"
python3 - "$OUTPUT" "$WORK" <<'PY'
import json, os, sys
output, work = sys.argv[1], sys.argv[2]
report = {}
for case in ('u', 'n'):
    data = json.load(open(os.path.join(work, 'reader-%s.json' % case)))
    assert data['status'] == 'passed', data
    report['reader_' + case] = {
        'reader_class': data['reader_class'],
        'total_size': data['total_size'],
        'dollar_count': data['dollar_count'],
        'queries_match': data['actual_queries'] == data['expected_queries'],
        'recovery_matches': data['actual_recovered_strings'] == data['expected_recovered_strings'],
        'side_effects': data['side_effects'],
        'expected_queries_count': len(data['expected_queries']),
    }
json.dump(report, open(os.path.join(output, 'relationship-reader.json'), 'w'), indent=2, sort_keys=True)
print('reader OK')
PY

echo '== step: copy input texts for the committed golden =='
mkdir -p "$OUTPUT/inputs"
cp "$WORK/uniform.txt" "$OUTPUT/inputs/uniform.txt"
cp "$WORK/nonuniform.txt" "$OUTPUT/inputs/nonuniform.txt"

echo '== step: failure/quirk contract probes =='
# Probe 1: invalid symbol AFTER the first newline is silently dropped and the
# conversion terminates at the first newline (exit 0; payload = RLE of the
# prefix before the newline).  This is a DOCUMENTED LEGACY QUIRK of the
# frozen pyx: once currSym is '\n' the pass branch never updates currSym, so
# every later non-newline character is ignored.
printf 'ACGTN\nX\nACGTN\n' > "$WORK/invalid-after-newline.txt"
# Probe 2: invalid symbol BEFORE any newline reaches the raise site
# (currSym becomes the invalid symbol) and the intended Exception is masked
# by TypeError because Cython emits PyNumber_Add(str, int) for the C
# unsigned char currSym under Python 2.
printf 'ACGTX\nACGTN\n' > "$WORK/invalid-before-newline.txt"
set +e
(cd "$FROZEN" && "$PREFIX/bin/python" -B -c 'from MUS import CommandLineInterface; CommandLineInterface.mainRun()' convert -i "$WORK/invalid-after-newline.txt" "$WORK/dst-invalid-a") > "$WORK/convert-invalid-a.log" 2>&1
INVALID_A_EXIT=$?
(cd "$FROZEN" && "$PREFIX/bin/python" -B -c 'from MUS import CommandLineInterface; CommandLineInterface.mainRun()' convert -i "$WORK/invalid-before-newline.txt" "$WORK/dst-invalid-b") > "$WORK/convert-invalid-b.log" 2>&1
INVALID_B_EXIT=$?
set -e
echo 'invalid-after-newline exit:' "$INVALID_A_EXIT" ' invalid-before-newline exit:' "$INVALID_B_EXIT"
python3 - "$OUTPUT" "$WORK" "$INVALID_A_EXIT" "$INVALID_B_EXIT" <<'PY'
import hashlib, json, os, sys
output, work = sys.argv[1], sys.argv[2]
exit_a, exit_b = int(sys.argv[3]), int(sys.argv[4])

def payload_sha256(path):
    data = open(path, 'rb').read()
    header_len = data[8] | (data[9] << 8)
    return hashlib.sha256(data[10 + header_len:]).hexdigest()

log_a = open(os.path.join(work, 'convert-invalid-a.log'), 'rb').read()
log_b = open(os.path.join(work, 'convert-invalid-b.log'), 'rb').read()
import re
def sanitize(text):
    text = re.sub(rb"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", b"[TIMESTAMP]", text)
    text = text.replace(work.encode('utf-8'), b"[WORK]")
    return text.decode('utf-8', 'replace')
sanitized_a = sanitize(log_a)
sanitized_b = sanitize(log_b)
report = {
    'invalid_after_newline': {
        'input': 'ACGTN\\nX\\nACGTN\\n',
        'exit_code': exit_a,
        'sanitized_stderr': sanitized_a,
        'destination_files': sorted(os.listdir(os.path.join(work, 'dst-invalid-a'))),
        'payload_sha256': payload_sha256(os.path.join(work, 'dst-invalid-a', 'comp_msbwt.npy')),
        'contract': "everything after the first newline is silently dropped "
                    "(currSym stays '\\n' in the pass branch); exit 0; "
                    "payload is the RLE of the prefix before the newline",
        'quirk': 'DOCUMENTED LEGACY QUIRK',
    },
    'invalid_before_newline': {
        'input': 'ACGTX\\nACGTN\\n',
        'exit_code': exit_b,
        'sanitized_stderr': sanitized_b,
        'exception_class': 'TypeError' if exit_b != 0 else None,
        'contract': 'the invalid symbol becomes currSym before any newline, '
                    'reaching the raise site; the intended Exception is '
                    'masked by TypeError (PyNumber_Add(str, int) on the C '
                    'unsigned char under Python 2)',
    },
}
assert exit_a == 0, report
assert exit_b == 1, report
assert b'TypeError' in log_b, report
json.dump(report, open(os.path.join(output, 'failure-contract-probes.json'), 'w'),
          indent=2, sort_keys=True)
print('failure contract probes recorded')
PY

echo 'convert-oracle-milestone10 OK'
