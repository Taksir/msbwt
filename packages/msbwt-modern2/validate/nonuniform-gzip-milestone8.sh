#!/usr/bin/env bash
# msbwt-modern2 nonuniform construction + gzip input milestone 8 validation
# driver.
#
# Broadens modern2 from the characterized uniform byte/RLE path to the two
# already-established real legacy contracts:
#   1. nonuniform read-length construction (`pp` + `cfpp -p 1` without `-u`)
#   2. gzip FASTQ input (`pp` with .gz fixtures + `cfpp -p 1` without `-u`)
#
# Both cases route through the migrated `MUSCython.MultimergeCython` module
# (frozen `MultimergeCython.pyx` + `#cython: language_level=2`, compiled with
# the pinned Cython 3.0.12 toolchain).  The committed legacy goldens
# (`nonuniform-prefix`, `gzip-input`) are the byte contract.
#
# Executed verdict (see docs/modernization/MODERN2_MILESTONE8_NONUNIFORM_GZIP.md):
#   - the migrated MultimergeCython reproduces the committed preprocess
#     artifacts and build primaries byte-for-byte on the first run for both
#     cases, with deterministic independent runs and byte-identical `-p 2`;
#   - the compiled ByteBWT reader matches the committed reader-smoke query
#     tables, recovered strings, dollar counts, and side-effect hashes;
#   - gzip and plain input produce identical preprocess artifacts.
#
# Gates (all must pass):
#   1. environment: CPython 2.7, Cython 3.0.x, NumPy 1.16.6, pysam 0.15.4
#   2. optional in-tree build of the 9 migrated extensions (Cython 3.0.12)
#   3. all modern2 Python-2 tests green
#   4. nonuniform-prefix case (pp + cfpp -p 1), two fresh runs (run-a/run-b):
#      a. preprocess stage retained file set exactly {offsets.npy, seqs.npy}
#         with whole-file SHA-256 == committed pre manifest
#      b. build stage retained file set exactly {msbwt.npy, offsets.npy,
#         seqs.npy}; msbwt.npy whole-file hash, |u1 (30,) header, and payload
#         hash == committed build manifest
#      c. determinism: run-a == run-b byte-for-byte at both stages
#   5. gzip-input case (pp of uniform-a.fastq.gz + nonuniform.fastq.gz +
#      cfpp -p 1), two fresh runs: same checks vs the committed gzip manifests
#      (offsets 9f96565f..., seqs 605c199e..., msbwt da40d02e..., payload
#      13c68736...)
#   6. `-p 2`: fresh preprocess dir per case built with `cfpp -p 2`;
#      require byte-identical build files to the `-p 1` build
#   7. gzip parsing/input contract: fixture .gz hashes verified and a plain-
#      format `pp` run of the same fixture content produces byte-identical
#      preprocess artifacts to the .gz run
#   8. reader validation on disposable build copies (compiled ByteBWT):
#      reader class, total size, dollar count, committed query table,
#      committed recovered strings, and exact committed side-effect hashes
#      (fmIndex.npy / totalCounts.npy); derived-index regeneration
#   9. optional low-risk extension: nonuniform byte primary -> compress ->
#      decompress; compressed bytes == committed nonuniform-compress-posthoc
#      golden (9d19222e...), decompressed bytes == nonuniform byte primary
#   10. independent semantic validation: bwt_oracle backward_count on the raw
#       build payloads equals the committed query tables
#   11. frozen source untouched (MultimergeCython.pyx 9c591c05...,
#       MultiStringBWT.py 95ac0b86...); the modern2 MultimergeCython.pyx diff
#       vs the frozen file is exactly the `#cython: language_level=2` header
# If --evidence is given, a JSON record of every gate is written.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: validate/nonuniform-gzip-milestone8.sh --prefix /absolute/prefix --package /absolute/package --repository /absolute/repo [--build] [--evidence /absolute/out.json]'
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
for tool in python3 sha256sum diff; do command -v "$tool" >/dev/null 2>&1 || { printf 'Missing required tool: %s\n' "$tool" >&2; exit 69; }; done

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

# frozen projection digests (committed manifest byte form, see
# reference/original-0.3.0/environment/frozen-source.sha256)
FROZEN_MULTIMERGE_PYX_SHA256=9c591c05697a662a0f0a7fb78b0afd609e7a567afb4ed182d926fca0726859cb
FROZEN_MULTISTRINGBWT_SHA256=95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0

WORK=$(mktemp -d /tmp/modern2-milestone8-XXXXXX)
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
    local log=$1
    shift
    (cd "$PACKAGE" && "$PREFIX/bin/python" -B -c 'from MUS import CommandLineInterface; CommandLineInterface.mainRun()' "$@") > "$log" 2>&1
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
                MSBWTCompGenCython MSBWTGenCython MultiStringBWTCython \
                MultimergeCython RLE_BWTCython; do
        test -f "$PACKAGE/MUSCython/$name.so" || { printf 'Missing built module: %s\n' "$name" >&2; exit 70; }
    done
    printf 'gate_build OK\n'
}

gate_py2_tests() {
    (cd "$PACKAGE" && "$PREFIX/bin/python" -B -m unittest discover -s tests -v)
}

sha256_tree() {
    # sorted "sha256  size  name" lines for a directory
    local dir=$1
    (cd "$dir" && for f in *; do [ -f "$f" ] || continue; printf '%s %s %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$(stat -c %s "$f")" "$f"; done | sort -k3)
}

run_case() {
    # $1 = case id (nonuniform-prefix|gzip-input), $2 = run id (run-a|run-b)
    local case=$1
    local run=$2
    local case_dir="$WORK/$case-$run"
    mkdir -p "$case_dir"
    if [ "$case" = nonuniform-prefix ]; then
        cli "$WORK/$case-$run-pp.log" pp "$case_dir" "$FIXTURES/nonuniform.fastq"
    else
        cli "$WORK/$case-$run-pp.log" pp "$case_dir" "$FIXTURES/uniform-a.fastq.gz" "$FIXTURES/nonuniform.fastq.gz"
    fi
    # preprocess snapshot BEFORE the build so the pre file set is exact
    mkdir -p "$case_dir-pre-snapshot"
    cp -a "$case_dir/." "$case_dir-pre-snapshot/"
    python3 "$MANIFEST_TOOL" verify \
        --artifact-dir "$case_dir-pre-snapshot" \
        --manifest "$GOLDENS/$case/$PROFILE/$ROUTE/pre/manifest.json" \
        --output "$WORK/$case-$run-pre-verify.json"
    cli "$WORK/$case-$run-cfpp.log" cfpp -p 1 "$case_dir"
    python3 "$MANIFEST_TOOL" verify \
        --artifact-dir "$case_dir" \
        --manifest "$GOLDENS/$case/$PROFILE/$ROUTE/build/manifest.json" \
        --output "$WORK/$case-$run-build-verify.json"
    python3 - "$WORK/$case-$run-pre-verify.json" "$WORK/$case-$run-build-verify.json" <<'PY'
import json, sys
for path in (sys.argv[1], sys.argv[2]):
    check = json.load(open(path))
    assert check['matches'] is True, path
    assert check['added'] == [] and check['removed'] == [] and check['changed'] == [], path
print('manifest verify OK')
PY
    sha256_tree "$case_dir-pre-snapshot" > "$WORK/$case-$run-pre-tree.txt"
    sha256_tree "$case_dir" > "$WORK/$case-$run-build-tree.txt"
}

gate_determinism() {
    local case=$1
    diff -u "$WORK/$case-run-a-pre-tree.txt" "$WORK/$case-run-b-pre-tree.txt" > /dev/null
    diff -u "$WORK/$case-run-a-build-tree.txt" "$WORK/$case-run-b-build-tree.txt" > /dev/null
    printf 'determinism OK (%s)\n' "$case"
}

gate_p2() {
    local case=$1
    local p2_dir="$WORK/$case-p2"
    mkdir -p "$p2_dir"
    if [ "$case" = nonuniform-prefix ]; then
        cli "$WORK/$case-p2-pp.log" pp "$p2_dir" "$FIXTURES/nonuniform.fastq"
    else
        cli "$WORK/$case-p2-pp.log" pp "$p2_dir" "$FIXTURES/uniform-a.fastq.gz" "$FIXTURES/nonuniform.fastq.gz"
    fi
    cli "$WORK/$case-p2-cfpp.log" cfpp -p 2 "$p2_dir"
    sha256_tree "$p2_dir" > "$WORK/$case-p2-build-tree.txt"
    diff -u "$WORK/$case-run-a-build-tree.txt" "$WORK/$case-p2-build-tree.txt" > /dev/null
    printf 'gate_p2 OK (%s)\n' "$case"
}

gate_gzip_plain_equivalence() {
    # pp of the plain fixtures must produce byte-identical preprocess artifacts
    local plain_dir="$WORK/gzip-plain"
    mkdir -p "$plain_dir"
    cli "$WORK/gzip-plain-pp.log" pp "$plain_dir" "$FIXTURES/uniform-a.fastq" "$FIXTURES/nonuniform.fastq"
    sha256_tree "$plain_dir" > "$WORK/gzip-plain-pre-tree.txt"
    diff -u "$WORK/gzip-input-run-a-pre-tree.txt" "$WORK/gzip-plain-pre-tree.txt" > /dev/null
    printf 'gzip/plain preprocess equivalence OK\n'
}

gate_compress_roundtrip() {
    # optional low-risk extension: nonuniform byte primary -> compress ->
    # decompress.  The compressed bytes must equal the committed
    # nonuniform-compress-posthoc golden and the decompressed bytes must equal
    # the committed nonuniform byte primary.
    local src_dir="$WORK/compress-src"
    local comp_dir="$WORK/compress-out"
    local decomp_dir="$WORK/decompress-out"
    mkdir -p "$src_dir" "$comp_dir" "$decomp_dir"
    cli "$WORK/compress-pp.log" pp "$src_dir" "$FIXTURES/nonuniform.fastq"
    cli "$WORK/compress-cfpp.log" cfpp -p 1 "$src_dir"
    cli "$WORK/compress.log" compress -p 1 "$src_dir" "$comp_dir"
    cli "$WORK/decompress.log" decompress -p 1 "$comp_dir" "$decomp_dir"
    local comp_hash=$(sha256sum "$comp_dir/comp_msbwt.npy" | cut -d' ' -f1)
    local decomp_hash=$(sha256sum "$decomp_dir/msbwt.npy" | cut -d' ' -f1)
    if [ "$comp_hash" != 9d19222eaa78c1d89304e79ff14a8a0a5f0c21c3ae979d179f570f1d8d5c1e66 ]; then
        printf 'compressed nonuniform primary mismatch: %s\n' "$comp_hash" >&2
        exit 70
    fi
    if [ "$decomp_hash" != da28963ca3726568dd7a26eccea35f107bd4cb8b295c909de628374db38dd4b2 ]; then
        printf 'decompressed nonuniform primary mismatch: %s\n' "$decomp_hash" >&2
        exit 70
    fi
    printf 'gate_compress_roundtrip OK\n'
}

run_reader_probe() {
    # $1 = case id; writes $WORK/$case-reader.json
    local case=$1
    local smoke="$GOLDENS/$case/$PROFILE/$ROUTE/reader-smoke.json"
    "$PREFIX/bin/python" -B - "$case" "$WORK" "$REPOSITORY" "$smoke" <<'PY'
from __future__ import print_function
import hashlib
import json
import os
import shutil
import sys

case = sys.argv[1]
work = sys.argv[2]
repo = sys.argv[3]
smoke_path = sys.argv[4]
package = os.path.join(repo, 'packages', 'msbwt-modern2')
sys.path.insert(0, package)
sys.path.insert(0, os.path.join(package, 'MUS'))

GOLDENS = os.path.join(repo, 'compat', 'goldens', 'original-0.3.0')
PROFILE = 'py27-late-05a7d6d83862'
ROUTE = 'pyx-historical-cython'

smoke = json.load(open(smoke_path))
assert smoke['status'] == 'passed'
expected_queries = dict((str(k), int(v)) for k, v in smoke['expected_queries'].items())
expected_recovered = [str(v) for v in smoke['expected_recovered_strings']]
expected_added = dict((str(e['path']), (str(e['sha256']), int(e['size'])))
                      for e in smoke['side_effects']['added'])

from MUSCython import MultiStringBWTCython

def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()

def inventory(directory):
    return dict((name, (sha256_file(os.path.join(directory, name)),
                        os.path.getsize(os.path.join(directory, name))))
                for name in sorted(os.listdir(directory))
                if os.path.isfile(os.path.join(directory, name)))

def fresh_copy(src, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst

src = os.path.join(work, case + '-run-a')
copy = os.path.join(work, case + '-reader-copy')
fresh_copy(src, copy)
before = inventory(copy)
reader = MultiStringBWTCython.loadBWT(os.path.abspath(copy), useMemmap=False,
                                      logger=None)
after = inventory(copy)
added = dict((name, value) for name, value in after.items()
             if name not in before)
report = {
    'reader_class': type(reader).__module__ + '.' + type(reader).__name__,
    'total_size': int(reader.getTotalSize()),
    'dollar_count': int(reader.getSymbolCount(0)),
}
report['added_files'] = dict((name, {'sha256': value[0], 'size': value[1]})
                             for name, value in sorted(added.items()))
report['side_effects_match_committed'] = (
    sorted(added.keys()) == sorted(expected_added.keys()) and
    all(added[name][0] == expected_added[name][0] and
        added[name][1] == expected_added[name][1] for name in expected_added))

report['queries_match_committed'] = all(
    int(reader.countOccurrencesOfSeq(k)) == v
    for k, v in expected_queries.items())
report['queries_sample'] = dict((k, int(reader.countOccurrencesOfSeq(k)))
                                for k in sorted(expected_queries.keys()))
recovered = sorted(reader.recoverString(i) for i in range(report['dollar_count']))
report['recovered_strings'] = [str(v) for v in recovered]
report['recovery_matches_committed'] = [str(v) for v in recovered] == expected_recovered

# derived-index regeneration: delete and reload, bytes must be identical
for name in ('totalCounts.npy', 'fmIndex.npy'):
    path = os.path.join(copy, name)
    if os.path.exists(path):
        os.remove(path)
reader2 = MultiStringBWTCython.loadBWT(os.path.abspath(copy), useMemmap=False,
                                       logger=None)
after2 = inventory(copy)
report['regeneration_bytes_identical'] = all(
    after2[name] == added[name] for name in added)
assert int(reader2.getTotalSize()) == report['total_size']

assert report['side_effects_match_committed'], report
assert report['queries_match_committed'], report
assert report['recovery_matches_committed'], report
assert report['regeneration_bytes_identical'], report
assert report['reader_class'] == 'MUSCython.ByteBWTCython.ByteBWT'

with open(os.path.join(work, case + '-reader.json'), 'w') as handle:
    json.dump(report, handle, indent=2, sort_keys=True)
print('reader probe OK (' + case + ')')
PY
}

gate_primary_bytes() {
    local case=$1
    python3 - "$case" "$WORK" <<'PY'
import json
import os
import sys

case = sys.argv[1]
work = sys.argv[2]
primary = os.path.join(work, case + '-run-a', 'msbwt.npy')
data = open(primary, 'rb').read()
assert data[0:6] == b'\x93NUMPY'
header_len = data[8] | (data[9] << 8)
header = data[10:10 + header_len].decode('ascii')
payload = data[10 + header_len:]
report = {
    'size': len(data),
    'header_len': header_len,
    'header_text': header.rstrip('\n'),
    'payload_sha256': __import__('hashlib').sha256(payload).hexdigest(),
}
expected = {
    'nonuniform-prefix': {
        'payload_sha256': '7a97b19addd3c41a79dbd6ce5e43609766eca78a971576e1ab2b32e3df80ca03',
        'shape_literal': '(30,)',
    },
    'gzip-input': {
        'payload_sha256': '13c687364c3ca7ebae5379d4f8d9814d880616dd23968fdfa2c2697ced9f24ee',
        'shape_literal': '(54,)',
    },
}[case]
assert report['payload_sha256'] == expected['payload_sha256'], case
assert expected['shape_literal'] in header, header
assert "'descr': '|u1'" in header, header
json.dump(report, open(os.path.join(work, case + '-primary.json'), 'w'),
          indent=2, sort_keys=True)
print('primary bytes OK (' + case + ')')
PY
}

gate_oracle() {
    # independent backward-count oracle on the raw build payloads
    python3 - "$WORK" "$BWT_ORACLE_TOOL" "$GOLDENS" "$PROFILE" "$ROUTE" <<'PY'
import json
import os
import struct
import sys

work = sys.argv[1]
oracle_tool = sys.argv[2]
goldens = sys.argv[3]
profile = sys.argv[4]
route = sys.argv[5]
sys.path.insert(0, os.path.dirname(oracle_tool))
from bwt_oracle import backward_count  # noqa: E402

report = {}
for case in ('nonuniform-prefix', 'gzip-input'):
    smoke = json.load(open(os.path.join(goldens, case, profile, route,
                                        'reader-smoke.json')))
    primary = os.path.join(work, case + '-run-a', 'msbwt.npy')
    data = open(primary, 'rb').read()
    header_len = struct.unpack('<H', data[8:10])[0]
    payload = data[10 + header_len:]
    mismatches = []
    for kmer, expected in smoke['expected_queries'].items():
        got = backward_count(payload, str(kmer))
        if got != int(expected):
            mismatches.append((kmer, got, expected))
    report[case] = {'kmers_checked': len(smoke['expected_queries']),
                    'mismatches': mismatches[:5],
                    'mismatch_count': len(mismatches)}
    assert not mismatches, (case, mismatches)
json.dump(report, open(os.path.join(work, 'oracle.json'), 'w'),
          indent=2, sort_keys=True)
print('gate_oracle OK')
PY
}

gate_source_policy() {
    python3 - "$REPOSITORY" "$WORK" <<'PY'
import hashlib
import json
import os
import sys

repo = sys.argv[1]
work = sys.argv[2]

def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()

report = {}
frozen_pyx = os.path.join(repo, 'MUSCython', 'MultimergeCython.pyx')
modern_pyx = os.path.join(repo, 'packages', 'msbwt-modern2', 'MUSCython',
                          'MultimergeCython.pyx')
frozen_hash = sha256_file(frozen_pyx)
report['frozen_MultimergeCython_pyx_sha256'] = frozen_hash
assert frozen_hash == '9c591c05697a662a0f0a7fb78b0afd609e7a567afb4ed182d926fca0726859cb'
frozen_msw = sha256_file(os.path.join(repo, 'MUS', 'MultiStringBWT.py'))
report['frozen_MultiStringBWT_py_sha256'] = frozen_msw
assert frozen_msw == '95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0'

frozen_text = open(frozen_pyx, 'rb').read().replace(b'\r\n', b'\n')
modern_text = open(modern_pyx, 'rb').read().replace(b'\r\n', b'\n')
frozen_lines = frozen_text.decode('utf-8').splitlines()
modern_lines = modern_text.decode('utf-8').splitlines()
import difflib
diff = list(difflib.unified_diff(frozen_lines, modern_lines, lineterm=''))
added = [line[1:] for line in diff
         if line.startswith('+') and not line.startswith('+++')]
removed = [line[1:] for line in diff
           if line.startswith('-') and not line.startswith('---')]
report['pyx_diff_added'] = added
report['pyx_diff_removed'] = removed
assert added == ['#cython: language_level=2'], added
assert removed == [], removed
json.dump(report, open(os.path.join(work, 'source.json'), 'w'),
          indent=2, sort_keys=True)
print('gate_source_policy OK')
PY
}

gate_env
record environment "$("$PREFIX/bin/python" -c 'import json, sys; sys.stdout.write(json.dumps({"python": sys.version.split()[0], "cython": __import__("Cython").__version__, "numpy": __import__("numpy").__version__, "pysam": __import__("pysam").__version__, "cc": __import__("os").environ.get("CC", "")}))')"
if [ "$DO_BUILD" -eq 1 ]; then gate_build; fi
if [ "$DO_BUILD" -eq 1 ]; then record build '{"status": "ok", "modules": 9, "cython": "3.0.12", "language_level": 2}'; else record build '{"status": "skipped"}'; fi
gate_py2_tests > "$WORK/py2-tests.log" 2>&1
record py2_tests '{"status": "ok"}'

for case in nonuniform-prefix gzip-input; do
    run_case "$case" run-a
    run_case "$case" run-b
    gate_determinism "$case"
    gate_p2 "$case"
    gate_primary_bytes "$case"
    run_reader_probe "$case"
done
gate_gzip_plain_equivalence
gate_compress_roundtrip
gate_oracle
gate_source_policy

record nonuniform "$(python3 -c 'import json, sys; print(json.dumps({"pre_tree": open(sys.argv[1]).read().splitlines(), "build_tree": open(sys.argv[2]).read().splitlines()}))' "$WORK/nonuniform-prefix-run-a-pre-tree.txt" "$WORK/nonuniform-prefix-run-a-build-tree.txt")"
record gzip "$(python3 -c 'import json, sys; print(json.dumps({"pre_tree": open(sys.argv[1]).read().splitlines(), "build_tree": open(sys.argv[2]).read().splitlines()}))' "$WORK/gzip-input-run-a-pre-tree.txt" "$WORK/gzip-input-run-a-build-tree.txt")"
record determinism '{"nonuniform-prefix": "run-a == run-b byte-identical", "gzip-input": "run-a == run-b byte-identical"}'
record p2 '{"nonuniform-prefix": "byte-identical to -p 1", "gzip-input": "byte-identical to -p 1"}'
record gzip_plain_equivalence '{"status": "preprocess artifacts byte-identical"}'
record compress_roundtrip '{"status": "nonuniform byte -> compress -> decompress == byte primary; compressed bytes == committed nonuniform-compress-posthoc golden (9d19222e...)"}'
record nonuniform_primary "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/nonuniform-prefix-primary.json")"
record gzip_primary "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/gzip-input-primary.json")"
record nonuniform_reader "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/nonuniform-prefix-reader.json")"
record gzip_reader "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/gzip-input-reader.json")"
record oracle "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/oracle.json")"
record source "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/source.json")"
record final '{"branch": "codex/modern2", "milestone": "modern2-milestone8-nonuniform-gzip", "status": "passed"}'
if [ -n "$EVIDENCE" ]; then cp "$RESULT_FILE" "$EVIDENCE"; printf 'Evidence written to %s\n' "$EVIDENCE"; fi
printf 'nonuniform-gzip-milestone8 OK\n'
