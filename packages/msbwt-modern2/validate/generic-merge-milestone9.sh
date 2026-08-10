#!/usr/bin/env bash
# msbwt-modern2 GenericMerge + public merge CLI milestone 9 validation driver.
#
# Restores the actual public MSBWT merge functionality in modern2:
#   1. `MUSCython.GenericMerge` migrated from the frozen `GenericMerge.pyx`
#      (byte-identical after removing the `#cython: language_level=2`
#      header) and compiled with the pinned Cython 3.0.12 toolchain;
#   2. the public `msbwt merge` CLI, including the documented `-p 1` fix
#      (LEGACY SOURCE BUG, COMPATIBILITY.md entry 2): the frozen CLI bound
#      `numProcs` only inside the `args.numProcesses > 1` branch so
#      `merge -p 1` raised `UnboundLocalError`; modern2 binds `numProcs = 1`
#      unconditionally so `-p 1` and `-p 2` run the identical intended
#      algorithm.
#
# The byte contract is the committed SECONDARY REGENERATED-SOURCE ORACLE
# (compat/goldens/original-0.3.0/merge-milestone1/): the canonical merge of
# the two uniform byte BWTs (uniform-a.fastq + uniform-b.fastq) must produce
# msbwt.npy dd91d69ee2785c88... (|u1, (48L,), payload 75134b48...) plus the
# retained merge-provenance inter0.npy 4a6d97a3... ((7,)).
#
# The two historical merge defect classes stay separate and are never
# re-run: the committed historical `GenericMerge.c` (Cython 0.23.4) SIGSEGV
# evidence and the frozen `-p 1` UnboundLocalError evidence remain committed
# under merge-milestone1/ and are protected by host tests; the modern2 py2
# suite additionally proves the frozen CLI source still reproduces the
# UnboundLocalError while modern2 succeeds.
#
# Gates (all must pass):
#   1. environment: CPython 2.7, Cython 3.0.x, NumPy 1.16.6, pysam 0.15.4
#   2. optional in-tree build of the 10 migrated extensions (Cython 3.0.12)
#   3. all modern2 Python-2 tests green
#   4. fixture hashes (uniform-a.fastq, uniform-b.fastq, nonuniform.fastq)
#   5. source policy: frozen GenericMerge.pyx/CommandLineInterface.py/
#      MultiStringBWT.py hashes; modern2 GenericMerge.pyx diff == exactly the
#      language_level header; modern2 CLI diff == exactly `numProcs = 1`;
#      MultiStringBWT whitelist unchanged (7 added / 6 removed)
#   6. fresh inputs per run (IN_A from uniform-a.fastq, IN_B from
#      uniform-b.fastq, CLEAN from both, all pp -u + cfpp -p 1 -u) match the
#      committed input hashes (e277c7e5..., 15f40b98...) and CLEAN equals the
#      committed golden (dd91d69e...)
#   7. canonical merges: merge -p 1 run-a/run-b and merge -p 2 run-a/run-b;
#      output file set exactly {inter0.npy, msbwt.npy}; no derived files in
#      the output; inputs gain exactly {fmIndex.npy, totalCounts.npy} and are
#      otherwise unchanged
#   8. determinism: p1-a == p1-b, p2-a == p2-b, p1 == p2 (whole trees)
#   9. merged == clean == committed oracle whole-file; primary bytes
#      (header |u1 (48L,), header_len 118, payload 75134b48...); interleave
#      bytes (|u1 (7,), payload 688c323f...)
#   10. reader on disposable copies: compiled ByteBWT, total 48, dollars 8,
#       committed query table, recovered strings, committed side-effect
#       hashes (fmIndex a5b4bf06..., totalCounts ea104b61...), derived-index
#       regeneration, inter0.npy removal + reload (merge provenance, not
#       reader-required)
#   11. CLI query on disposable copy: `query COPY ACGTN` prints 3;
#       `query -d COPY ACGTN` dumps exactly three ACGTN strings
#   12. independent semantic oracle (compat/tools/bwt_oracle.py, host-side):
#       rotation-sort prediction == merged payload; symbol counts
#       A=9 C=9 G=9 N=4 T=9 $=8; backward counts == committed table; LF
#       recovery == the 8-read multiset; interleave verification (24 zeros /
#       24 ones, 0 unambiguous mismatches)
# If --evidence is given, a JSON record of every gate is written.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: validate/generic-merge-milestone9.sh --prefix /absolute/prefix --package /absolute/package --repository /absolute/repo [--build] [--evidence /absolute/out.json]'
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
for tool in python3 sha256sum diff cmp; do command -v "$tool" >/dev/null 2>&1 || { printf 'Missing required tool: %s\n' "$tool" >&2; exit 69; }; done

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
MILESTONE="$GOLDENS/merge-milestone1"
FIXTURES="$REPOSITORY/compat/fixtures/synthetic"
BWT_ORACLE_TOOL="$REPOSITORY/compat/tools/bwt_oracle.py"

# committed contract (secondary-regenerated-source oracle)
MERGED_PRIMARY_SHA256=dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f
MERGED_PAYLOAD_SHA256=75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e
INTERLEAVE_SHA256=4a6d97a36e9ef4e3c19fb873b7713a9357d207d29433a3eca67a41cc4221afd6
INTERLEAVE_PAYLOAD_SHA256=688c323fa4aed411bb303322c616e6640e31fffdf707d0a596fad2c4f386ca2b
INPUT_A_SHA256=e277c7e5c529808c230fb9dae61626a24eeddad54df2f38e22357a12520f69a1
INPUT_B_SHA256=15f40b98ce3310dfe71c15c34509075e68a271bcc93b125b7005cd2b8f82ff08
FROZEN_GENERICMERGE_PYX_SHA256=fe8b699c73a0e671b63cbbe7f2eeba941b91a321156a02df44bf0e010cedce87
FROZEN_CLI_PY_SHA256=5265558e9a04e41eab33493a4fed440e2c640c1198b99ae493810647d1b23189
FROZEN_MULTISTRINGBWT_PY_SHA256=95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0

WORK=$(mktemp -d /tmp/modern2-milestone9-XXXXXX)
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
    for name in AlignmentUtil BasicBWT ByteBWTCython GenericMerge LZW_BWTCython \
                MSBWTCompGenCython MSBWTGenCython MultiStringBWTCython \
                MultimergeCython RLE_BWTCython; do
        test -f "$PACKAGE/MUSCython/$name.so" || { printf 'Missing built module: %s\n' "$name" >&2; exit 70; }
    done
    printf 'gate_build OK\n'
}

gate_py2_tests() {
    (cd "$PACKAGE" && "$PREFIX/bin/python" -B -m unittest discover -s tests -v)
}

gate_fixtures() {
    python3 - "$FIXTURES" "$WORK" <<'PY'
import hashlib, json, os, sys
fixtures = sys.argv[1]
work = sys.argv[2]
expected = {
    'uniform-a.fastq': ('da3466b992e0ba4ef4da2d0731062661f13e66b83ec154b56471ec4286798180', 173),
    'uniform-b.fastq': ('04124b73a3dde82da5cd70d9d244180d6e076a952dda404e4746b1e9388e1029', 162),
    'nonuniform.fastq': ('e19ef01c7683cd81534fada1f8142ddf35710a2e1bf9b70d92bb8de2acb1973e', 246),
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

sha256_tree() {
    # sorted "sha256  size  name" lines for a directory
    local dir=$1
    (cd "$dir" && for f in *; do [ -f "$f" ] || continue; printf '%s %s %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$(stat -c %s "$f")" "$f"; done | sort -k3)
}

build_inputs() {
    # $1 = run id; builds fresh IN_A/IN_B/CLEAN under $WORK/$1/
    local run=$1
    local root="$WORK/$run"
    mkdir -p "$root"
    cli "$WORK/$run-pp-a.log" pp -u "$root/in_a" "$FIXTURES/uniform-a.fastq"
    cli "$WORK/$run-cfpp-a.log" cfpp -p 1 -u "$root/in_a"
    cli "$WORK/$run-pp-b.log" pp -u "$root/in_b" "$FIXTURES/uniform-b.fastq"
    cli "$WORK/$run-cfpp-b.log" cfpp -p 1 -u "$root/in_b"
    cli "$WORK/$run-pp-clean.log" pp -u "$root/clean" "$FIXTURES/uniform-a.fastq" "$FIXTURES/uniform-b.fastq"
    cli "$WORK/$run-cfpp-clean.log" cfpp -p 1 -u "$root/clean"
    sha256_tree "$root/in_a" > "$WORK/$run-in-a-tree.txt"
    sha256_tree "$root/in_b" > "$WORK/$run-in-b-tree.txt"
    sha256_tree "$root/clean" > "$WORK/$run-clean-tree.txt"
}

gate_inputs() {
    local run=$1
    python3 - "$run" "$WORK" <<'PY'
import hashlib, json, os, sys
run, work = sys.argv[1], sys.argv[2]
def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()
in_a = sha256_file(os.path.join(work, run, 'in_a', 'msbwt.npy'))
in_b = sha256_file(os.path.join(work, run, 'in_b', 'msbwt.npy'))
clean = sha256_file(os.path.join(work, run, 'clean', 'msbwt.npy'))
assert in_a == 'e277c7e5c529808c230fb9dae61626a24eeddad54df2f38e22357a12520f69a1', in_a
assert in_b == '15f40b98ce3310dfe71c15c34509075e68a271bcc93b125b7005cd2b8f82ff08', in_b
assert clean == 'dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f', clean
print('gate_inputs OK (' + run + ')')
PY
}

run_merge() {
    # $1 = run id, $2 = processes (1|2), $3 = out id (p1|p2)
    local run=$1
    local processes=$2
    local out=$3
    cli "$WORK/$run-merge-$out.log" merge -p "$processes" "$WORK/$run/$out" "$WORK/$run/in_a" "$WORK/$run/in_b"
    sha256_tree "$WORK/$run/$out" > "$WORK/$run-$out-tree.txt"
    sha256_tree "$WORK/$run/in_a" > "$WORK/$run-in-a-after-$out-tree.txt"
    sha256_tree "$WORK/$run/in_b" > "$WORK/$run-in-b-after-$out-tree.txt"
}

run_reader_probe() {
    # $1 = merged tree path; writes $WORK/reader.json
    local merged_tree=$1
    "$PREFIX/bin/python" -B - "$merged_tree" "$WORK" "$MILESTONE" "$PACKAGE" <<'PY'
from __future__ import print_function
import hashlib
import json
import os
import shutil
import sys

merged_tree = sys.argv[1]
work = sys.argv[2]
milestone = sys.argv[3]
package = sys.argv[4]
sys.path.insert(0, package)
sys.path.insert(0, os.path.join(package, 'MUS'))

relationship = json.load(open(os.path.join(milestone, 'relationship-reader.json')))
smoke = relationship['reader_smoke']
expected_queries = dict((str(k), int(v)) for k, v in smoke['expected_queries'].items())
expected_recovered = [str(v) for v in smoke['recovered_by_dollar_id']]
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

copy = os.path.join(work, 'merged-reader-copy')
fresh_copy(merged_tree, copy)
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
recovered = sorted(reader.recoverString(i) for i in range(report['dollar_count']))
report['recovered_strings'] = [str(v) for v in recovered]
report['recovery_matches_committed'] = [str(v) for v in recovered] == sorted(expected_recovered)

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

# inter0.npy is merge provenance, not reader-required
inter0 = os.path.join(copy, 'inter0.npy')
assert os.path.exists(inter0)
os.remove(inter0)
reader3 = MultiStringBWTCython.loadBWT(os.path.abspath(copy), useMemmap=False,
                                       logger=None)
report['interleave_required_by_reader'] = False
assert int(reader3.getSymbolCount(0)) == report['dollar_count']
assert int(reader3.getTotalSize()) == report['total_size']

report['classification'] = {
    'primary_persistent': ['msbwt.npy'],
    'merge_provenance_not_reader_required': ['inter0.npy'],
    'lazy_deletable_regenerable': ['totalCounts.npy', 'fmIndex.npy'],
}
assert report['side_effects_match_committed'], report
assert report['queries_match_committed'], report
assert report['recovery_matches_committed'], report
assert report['regeneration_bytes_identical'], report
assert report['reader_class'] == 'MUSCython.ByteBWTCython.ByteBWT'

with open(os.path.join(work, 'reader.json'), 'w') as handle:
    json.dump(report, handle, indent=2, sort_keys=True)
print('reader probe OK')
PY
}

run_cli_query_probe() {
    # $1 = merged tree path; writes $WORK/cli-query.json
    local merged_tree=$1
    local copy="$WORK/query-copy"
    rm -rf "$copy"
    cp -a "$merged_tree" "$copy"
    cli "$WORK/query-count.log" query "$copy" ACGTN
    cli "$WORK/query-dump.log" query -d "$copy" ACGTN
    python3 - "$WORK" <<'PY'
import hashlib, json, os, sys
work = sys.argv[1]
count = open(os.path.join(work, 'query-count.log'), 'rb').read()
dump = open(os.path.join(work, 'query-dump.log'), 'rb').read()
count_lines = count.decode('utf-8').splitlines()
dump_lines = dump.decode('utf-8').splitlines()
# the logger INFO lines carry wall-clock timestamps; the CLI's own output is
# the trailing lines only, and only those are hashed for byte determinism
count_output = (count_lines[-1] + '\n').encode('utf-8')
dump_output = ('\n'.join(dump_lines[-4:]) + '\n').encode('utf-8')
report = {
    'count_text': count_lines[-1],
    'count_stdout_sha256': hashlib.sha256(count_output).hexdigest(),
    'dump_stdout_sha256': hashlib.sha256(dump_output).hexdigest(),
    'dumped_strings': sorted(line.split(',')[0] for line in dump_lines[-3:]),
}
assert report['count_text'] == '3', report
assert report['dumped_strings'] == ['ACGTN', 'ACGTN', 'ACGTN'], report
json.dump(report, open(os.path.join(work, 'cli-query.json'), 'w'),
          indent=2, sort_keys=True)
print('cli query probe OK')
PY
}

gate_primary_bytes() {
    python3 - "$WORK" <<'PY'
import hashlib, json, os, sys
work = sys.argv[1]
primary = os.path.join(work, 'run-a', 'p1', 'msbwt.npy')
data = open(primary, 'rb').read()
assert data[0:6] == b'\x93NUMPY'
header_len = data[8] | (data[9] << 8)
header = data[10:10 + header_len].decode('ascii')
payload = data[10 + header_len:]
report = {
    'size': len(data),
    'header_len': header_len,
    'header_text': header.rstrip('\n'),
    'dtype_descriptor': '|u1',
    'shape_literal': '(48L,)',
    'shape': [48],
    'whole_sha256': hashlib.sha256(data).hexdigest(),
    'payload_sha256': hashlib.sha256(payload).hexdigest(),
}
assert report['whole_sha256'] == 'dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f'
assert report['payload_sha256'] == '75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e'
assert report['header_len'] == 118
assert "'descr': '|u1'" in header, header
assert "'shape': (48L,)" in header, header
json.dump(report, open(os.path.join(work, 'primary.json'), 'w'),
          indent=2, sort_keys=True)
print('gate_primary_bytes OK')
PY
}

gate_interleave_bytes() {
    python3 - "$WORK" <<'PY'
import hashlib, json, os, sys
work = sys.argv[1]
path = os.path.join(work, 'run-a', 'p1', 'inter0.npy')
data = open(path, 'rb').read()
assert data[0:6] == b'\x93NUMPY'
header_len = data[8] | (data[9] << 8)
header = data[10:10 + header_len].decode('ascii')
payload = data[10 + header_len:]
report = {
    'size': len(data),
    'header_len': header_len,
    'header_text': header.rstrip('\n'),
    'dtype_descriptor': '|u1',
    'shape_literal': '(7,)',
    'shape': [7],
    'whole_sha256': hashlib.sha256(data).hexdigest(),
    'payload_sha256': hashlib.sha256(payload).hexdigest(),
}
assert report['whole_sha256'] == '4a6d97a36e9ef4e3c19fb873b7713a9357d207d29433a3eca67a41cc4221afd6'
assert report['payload_sha256'] == '688c323fa4aed411bb303322c616e6640e31fffdf707d0a596fad2c4f386ca2b'
assert "'shape': (7,)" in header, header
json.dump(report, open(os.path.join(work, 'interleave.json'), 'w'),
          indent=2, sort_keys=True)
print('gate_interleave_bytes OK')
PY
}

gate_output_files() {
    python3 - "$WORK" <<'PY'
import json, os, sys
work = sys.argv[1]
merged = os.path.join(work, 'run-a', 'p1')
names = sorted(os.listdir(merged))
assert names == ['inter0.npy', 'msbwt.npy'], names
report = {'output_files': names, 'derived_in_output': []}
json.dump(report, open(os.path.join(work, 'output-files.json'), 'w'),
          indent=2, sort_keys=True)
print('gate_output_files OK')
PY
}

gate_input_side_effects() {
    # inputs must gain exactly fmIndex.npy + totalCounts.npy (lazy reader
    # indexes created by loadBWT(useMemmap=True)) and be otherwise unchanged
    python3 - "$WORK" <<'PY'
import json, os, sys
work = sys.argv[1]

def tree(path):
    result = {}
    with open(path, 'rb') as handle:
        for line in handle:
            digest, size, name = line.decode('utf-8').split()
            result[name] = (digest, int(size))
    return result

report = {}
for run in ('run-a', 'run-b'):
    for key in ('in_a', 'in_b'):
        before = tree(os.path.join(work, run + '-' + key.replace('_', '-') + '-tree.txt'))
        after_p1 = tree(os.path.join(work, run + '-' + key.replace('_', '-') + '-after-p1-tree.txt'))
        after_p2 = tree(os.path.join(work, run + '-' + key.replace('_', '-') + '-after-p2-tree.txt'))
        added = sorted(set(after_p1) - set(before))
        assert added == ['fmIndex.npy', 'totalCounts.npy'], (run, key, added)
        assert after_p2 == after_p1, (run, key)
        for name, value in before.items():
            assert after_p1[name] == value, (run, key, name)
        report[key + '_' + run + '_gained'] = added
json.dump(report, open(os.path.join(work, 'input-side-effects.json'), 'w'),
          indent=2, sort_keys=True)
print('gate_input_side_effects OK')
PY
}

gate_determinism() {
    diff -u "$WORK/run-a-p1-tree.txt" "$WORK/run-b-p1-tree.txt" > /dev/null
    diff -u "$WORK/run-a-p2-tree.txt" "$WORK/run-b-p2-tree.txt" > /dev/null
    diff -u "$WORK/run-a-p1-tree.txt" "$WORK/run-a-p2-tree.txt" > /dev/null
    printf 'gate_determinism OK (p1-a==p1-b, p2-a==p2-b, p1==p2)\n'
}

gate_merged_vs_clean() {
    cmp "$WORK/run-a/p1/msbwt.npy" "$WORK/run-a/clean/msbwt.npy"
    printf 'gate_merged_vs_clean OK\n'
}

gate_oracle() {
    # independent host-side oracle: rotation-sort prediction, symbol counts,
    # backward counts, LF recovery, interleave verification
    python3 - "$WORK" "$BWT_ORACLE_TOOL" "$MILESTONE" "$FIXTURES" <<'PY'
import hashlib
import json
import os
import sys

work = sys.argv[1]
oracle_tool = sys.argv[2]
milestone = sys.argv[3]
fixtures = sys.argv[4]
sys.path.insert(0, os.path.dirname(oracle_tool))
import bwt_oracle  # noqa: E402

relationship = json.load(open(os.path.join(milestone, 'relationship-reader.json')))
expected_queries = dict((str(k), int(v))
                        for k, v in relationship['reader_smoke']['expected_queries'].items())

def payload_of(path):
    data = open(path, 'rb').read()
    header_len = data[8] | (data[9] << 8)
    return data[10 + header_len:]

primary = os.path.join(work, 'run-a', 'p1', 'msbwt.npy')
payload = payload_of(primary)
reads_a = bwt_oracle.read_fastq_sequences(os.path.join(fixtures, 'uniform-a.fastq'))
reads_b = bwt_oracle.read_fastq_sequences(os.path.join(fixtures, 'uniform-b.fastq'))
merged_reads = sorted(reads_a + reads_b)

report = {}
report['merged_reads'] = merged_reads
report['rotation_prediction_matches'] = (
    bwt_oracle.rotation_sort_bwt(merged_reads) == payload)
report['symbol_counts'] = bwt_oracle.symbol_counts(payload)
report['symbol_counts_match'] = report['symbol_counts'] == {
    '$': 8, 'A': 9, 'C': 9, 'G': 9, 'N': 4, 'T': 9}
mismatches = []
for kmer, expected in expected_queries.items():
    actual = bwt_oracle.backward_count(payload, kmer)
    if actual != expected:
        mismatches.append((kmer, actual, expected))
report['kmers_checked'] = len(expected_queries)
report['backward_mismatches'] = mismatches[:5]
report['backward_mismatch_count'] = len(mismatches)
report['lf_recovery'] = bwt_oracle.lf_recover_reads(payload)
report['lf_recovery_matches'] = report['lf_recovery'] == merged_reads

inter0_payload = payload_of(os.path.join(work, 'run-a', 'p1', 'inter0.npy'))
prediction = bwt_oracle.interleave_prediction(reads_a, reads_b)
interleave = bwt_oracle.verify_interleave(inter0_payload, 48, 24, 24, prediction)
report['interleave_verification'] = interleave

assert report['rotation_prediction_matches'], report
assert report['symbol_counts_match'], report
assert report['backward_mismatch_count'] == 0, report
assert report['lf_recovery_matches'], report
assert interleave['zero_count'] == 24 and interleave['one_count'] == 24, interleave
assert interleave['unambiguous_mismatches'] == 0, interleave
assert interleave['tied_positions_count'] == 18, interleave
assert interleave['unique_a_positions'] == 12, interleave
assert interleave['unique_b_positions'] == 18, interleave
json.dump(report, open(os.path.join(work, 'oracle.json'), 'w'),
          indent=2, sort_keys=True)
print('gate_oracle OK')
PY
}

gate_source_policy() {
    python3 - "$REPOSITORY" "$WORK" <<'PY'
import difflib
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

def unified_diff(frozen_path, modern_path):
    frozen_text = open(frozen_path, 'rb').read().replace(b'\r\n', b'\n').decode('utf-8')
    modern_text = open(modern_path, 'rb').read().replace(b'\r\n', b'\n').decode('utf-8')
    diff = list(difflib.unified_diff(
        frozen_text.splitlines(), modern_text.splitlines(), lineterm=''))
    added = [line[1:] for line in diff
             if line.startswith('+') and not line.startswith('+++')]
    removed = [line[1:] for line in diff
               if line.startswith('-') and not line.startswith('---')]
    return added, removed

report = {}
frozen_pyx = os.path.join(repo, 'MUSCython', 'GenericMerge.pyx')
modern_pyx = os.path.join(repo, 'packages', 'msbwt-modern2', 'MUSCython', 'GenericMerge.pyx')
frozen_cli = os.path.join(repo, 'MUS', 'CommandLineInterface.py')
modern_cli = os.path.join(repo, 'packages', 'msbwt-modern2', 'MUS', 'CommandLineInterface.py')
frozen_msw = os.path.join(repo, 'MUS', 'MultiStringBWT.py')
modern_msw = os.path.join(repo, 'packages', 'msbwt-modern2', 'MUS', 'MultiStringBWT.py')

report['frozen_GenericMerge_pyx_sha256'] = sha256_file(frozen_pyx)
assert report['frozen_GenericMerge_pyx_sha256'] == 'fe8b699c73a0e671b63cbbe7f2eeba941b91a321156a02df44bf0e010cedce87'
report['frozen_CommandLineInterface_py_sha256'] = sha256_file(frozen_cli)
assert report['frozen_CommandLineInterface_py_sha256'] == '5265558e9a04e41eab33493a4fed440e2c640c1198b99ae493810647d1b23189'
report['frozen_MultiStringBWT_py_sha256'] = sha256_file(frozen_msw)
assert report['frozen_MultiStringBWT_py_sha256'] == '95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0'

pyx_added, pyx_removed = unified_diff(frozen_pyx, modern_pyx)
report['pyx_diff_added'] = pyx_added
report['pyx_diff_removed'] = pyx_removed
assert pyx_added == ['#cython: language_level=2'], pyx_added
assert pyx_removed == [], pyx_removed

cli_added, cli_removed = unified_diff(frozen_cli, modern_cli)
report['cli_diff_added'] = cli_added
report['cli_diff_removed'] = cli_removed
assert cli_added == ['        numProcs = 1'], cli_added
assert cli_removed == [], cli_removed

msw_added, msw_removed = unified_diff(frozen_msw, modern_msw)
report['multistringbwt_added_count'] = len(msw_added)
report['multistringbwt_removed_count'] = len(msw_removed)
assert len(msw_added) == 7 and len(msw_removed) == 6, (msw_added, msw_removed)

json.dump(report, open(os.path.join(work, 'source.json'), 'w'),
          indent=2, sort_keys=True)
print('gate_source_policy OK')
PY
}

gate_env
record environment "$("$PREFIX/bin/python" -c 'import json, sys; sys.stdout.write(json.dumps({"python": sys.version.split()[0], "cython": __import__("Cython").__version__, "numpy": __import__("numpy").__version__, "pysam": __import__("pysam").__version__, "cc": __import__("os").environ.get("CC", "")}))')"
if [ "$DO_BUILD" -eq 1 ]; then gate_build; fi
if [ "$DO_BUILD" -eq 1 ]; then record build '{"status": "ok", "modules": 10, "cython": "3.0.12", "language_level": 2}'; else record build '{"status": "skipped"}'; fi
gate_py2_tests > "$WORK/py2-tests.log" 2>&1
record py2_tests '{"status": "ok"}'
gate_fixtures
record fixtures "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/fixtures.json")"

for run in run-a run-b; do
    build_inputs "$run"
    gate_inputs "$run"
    run_merge "$run" 1 p1
    run_merge "$run" 2 p2
done
gate_determinism
gate_merged_vs_clean
gate_output_files
gate_input_side_effects
gate_primary_bytes
gate_interleave_bytes
run_reader_probe "$WORK/run-a/p1"
run_cli_query_probe "$WORK/run-a/p1"
gate_oracle
gate_source_policy

record inputs '{"run-a": {"in_a_msbwt": "e277c7e5...", "in_b_msbwt": "15f40b98...", "clean_msbwt": "dd91d69e..."}, "run-b": "same"}'
record merged "$(python3 -c 'import json, sys; print(json.dumps({"p1_run_a_tree": open(sys.argv[1]).read().splitlines(), "p1_run_b_tree": open(sys.argv[2]).read().splitlines(), "p2_run_a_tree": open(sys.argv[3]).read().splitlines(), "p2_run_b_tree": open(sys.argv[4]).read().splitlines()}))' "$WORK/run-a-p1-tree.txt" "$WORK/run-b-p1-tree.txt" "$WORK/run-a-p2-tree.txt" "$WORK/run-b-p2-tree.txt")"
record determinism '{"p1_run_a_equals_run_b": true, "p2_run_a_equals_run_b": true, "p1_equals_p2": true, "note": "whole output trees byte-identical"}'
record merged_vs_clean '{"whole_file_equal": true, "msbwt_sha256": "dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f"}'
record output_files "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/output-files.json")"
record input_side_effects '{"in_a": ["fmIndex.npy", "totalCounts.npy"], "in_b": ["fmIndex.npy", "totalCounts.npy"], "classification": "lazy reader-derived indexes created by loadBWT(useMemmap=True); inputs otherwise unchanged"}'
record primary "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/primary.json")"
record interleave "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/interleave.json")"
record reader "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/reader.json")"
record cli_query "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/cli-query.json")"
record oracle "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/oracle.json")"
record source "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/source.json")"
record final '{"branch": "codex/modern2", "milestone": "modern2-milestone9-generic-merge", "oracle_class": "secondary-regenerated-source", "status": "passed"}'
if [ -n "$EVIDENCE" ]; then cp "$RESULT_FILE" "$EVIDENCE"; printf 'Evidence written to %s\n' "$EVIDENCE"; fi
printf 'generic-merge-milestone9 OK\n'
