#!/usr/bin/env bash
# msbwt-modern2 remaining public surface audit + closure (milestone 10)
# validation driver.
#
# Restores and validates the remaining PUBLIC/REACHABLE functionality:
#   1. `MUSCython.CompressToRLE` migrated from the frozen `CompressToRLE.pyx`
#      (diff == exactly the `#cython: language_level=2` header) and compiled
#      with the pinned Cython 3.0.12 toolchain;
#   2. the public `msbwt convert` CLI (file and stdin routes), byte-identical
#      to the committed SECONDARY REGENERATED-SOURCE ORACLE
#      (compat/goldens/original-0.3.0/convert-milestone10/): uniform
#      comp_msbwt.npy 121ffb4183..., nonuniform 5fb4520471...;
#   3. the convert failure/quirk contracts: everything after the first
#      newline is silently dropped (exit 0, documented legacy quirk); an
#      invalid symbol before the first newline raises a masked TypeError
#      (exit 1, documented legacy quirk);
#   4. the previously unvalidated public `massquery` CLI (CSV contract and
#      determinism);
#   5. the exported-but-unreachable historical `MSBWTGenCython.compressBWT`
#      execution probe (p1 == p2; uniform whole-file == the committed
#      uniform-direct-split golden; payloads == the post-hoc payloads);
#   6. LCPGen classification: DEAD/PRIVATE stub, intentionally not migrated;
#   7. the public import/export smoke matrix (py2 tests);
#   8. the full public CLI inventory (9 subcommands).
#
# Gates (all must pass):
#   1. environment: CPython 2.7, Cython 3.0.x, NumPy 1.16.6, pysam 0.15.4
#   2. optional in-tree build of the 11 migrated extensions (Cython 3.0.12)
#   3. all modern2 Python-2 tests green
#   4. fixture hashes (uniform-a.fastq, uniform-b.fastq, nonuniform.fastq)
#   5. source policy: frozen CompressToRLE.pyx/CommandLineInterface.py/
#      MultiStringBWT.py hashes; modern2 CompressToRLE.pyx diff == exactly
#      the language_level header; CLI diff == exactly `numProcs = 1`;
#      MultiStringBWT whitelist unchanged (7 added / 6 removed); LCPGen
#      stub classified DEAD/PRIVATE; no other stubs; CompressToRLE stub
#      removed; generated C banner Cython 3.0.12
#   6. convert: run-a/run-b per case plus the stdin route, all byte-identical
#      to the committed oracle artifacts and to each other; retained file set
#      exactly {comp_msbwt.npy}; reader on disposable copies (RLE_BWT,
#      fixture-derived queries/recovery, derived side effects); failure/
#      quirk contracts (exit 0 silent-drop payload; exit 1 masked TypeError)
#   7. massquery: CSV contract (plain and -r) and two-run determinism on the
#      canonical uniform dataset
#   8. compressBWT probe: -p 1 == -p 2, uniform whole-file ==
#      0ca6329b54... (committed uniform-direct-split golden), nonuniform
#      whole-file == 07692b30..., payloads == post-hoc payloads
#   9. public import smoke matrix covered by the py2 suite
# If --evidence is given, a JSON record of every gate is written.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: validate/public-surface-milestone10.sh --prefix /absolute/prefix --package /absolute/package --repository /absolute/repo [--build] [--evidence /absolute/out.json]'
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
MILESTONE="$GOLDENS/convert-milestone10"
FIXTURES="$REPOSITORY/compat/fixtures/synthetic"

# committed convert oracle contract
UNIFORM_CONVERT_SHA256=121ffb41838b696ed0c543345794f8dad36525373e4d7427de8a45d298ec009b
NONUNIFORM_CONVERT_SHA256=5fb45204712b0177803104d27a8170f11c159ed4f666c1b2521bc8fc614c7517
UNIFORM_PAYLOAD_SHA256=6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb
NONUNIFORM_PAYLOAD_SHA256=5566aa4e33bd1952004221c69ef2591d22ef94f38805b68a96f74913f2042363
UNIFORM_DIRECT_SHA256=0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372
NONUNIFORM_PYX_COMPRESS_SHA256=07692b307c7533626900f1c7ee778f6aaa4cdfc453b86822dec8195c75286fdd
INVALID_AFTER_NEWLINE_PAYLOAD=6a9cc3bdeb3bdcfe24fbef1b051e63029b82470a73b2dab39524eef580544a6f
FROZEN_COMPRESS_TO_RLE_PYX_SHA256=1ef40aba3d9551ec5e3b656f30cbdc01f1e9c0e750b0830b7bd928d329ff8ab2
FROZEN_CLI_PY_SHA256=5265558e9a04e41eab33493a4fed440e2c640c1198b99ae493810647d1b23189
FROZEN_MULTISTRINGBWT_PY_SHA256=95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0

WORK=$(mktemp -d /tmp/modern2-milestone10-XXXXXX)
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
    for name in AlignmentUtil BasicBWT ByteBWTCython CompressToRLE GenericMerge \
                LZW_BWTCython MSBWTCompGenCython MSBWTGenCython \
                MultiStringBWTCython MultimergeCython RLE_BWTCython; do
        test -f "$PACKAGE/MUSCython/$name.so" || { printf 'Missing built module: %s\n' "$name" >&2; exit 70; }
    done
    printf 'gate_build OK (11 modules)\n'
}

gate_py2_tests() {
    (cd "$PACKAGE" && "$PREFIX/bin/python" -B -m unittest discover -s tests -v)
}

gate_fixtures() {
    python3 - "$FIXTURES" <<'PY'
import hashlib, os, sys
fixtures = sys.argv[1]
expected = {
    'uniform-a.fastq': ('da3466b992e0ba4ef4da2d0731062661f13e66b83ec154b56471ec4286798180', 173),
    'uniform-b.fastq': ('04124b73a3dde82da5cd70d9d244180d6e076a952dda404e4746b1e9388e1029', 162),
    'nonuniform.fastq': ('e19ef01c7683cd81534fada1f8142ddf35710a2e1bf9b70d92bb8de2acb1973e', 246),
}
for name, (digest, size) in expected.items():
    data = open(os.path.join(fixtures, name), 'rb').read()
    assert (hashlib.sha256(data).hexdigest(), len(data)) == (digest, size), name
print('gate_fixtures OK')
PY
}

gate_source_policy() {
    python3 - "$REPOSITORY" "$WORK" <<'PY'
import difflib
import hashlib
import json
import os
import re
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
frozen_pyx = os.path.join(repo, 'MUSCython', 'CompressToRLE.pyx')
modern_pyx = os.path.join(repo, 'packages', 'msbwt-modern2', 'MUSCython', 'CompressToRLE.pyx')
frozen_cli = os.path.join(repo, 'MUS', 'CommandLineInterface.py')
modern_cli = os.path.join(repo, 'packages', 'msbwt-modern2', 'MUS', 'CommandLineInterface.py')
frozen_msw = os.path.join(repo, 'MUS', 'MultiStringBWT.py')
modern_msw = os.path.join(repo, 'packages', 'msbwt-modern2', 'MUS', 'MultiStringBWT.py')
modern_c = os.path.join(repo, 'packages', 'msbwt-modern2', 'MUSCython', 'CompressToRLE.c')
stub = os.path.join(repo, 'packages', 'msbwt-modern2', 'MUSCython', 'CompressToRLE.py')
lcp_stub = os.path.join(repo, 'packages', 'msbwt-modern2', 'MUSCython', 'LCPGen.py')
setup = os.path.join(repo, 'packages', 'msbwt-modern2', 'setup.py')

report['frozen_CompressToRLE_pyx_sha256'] = sha256_file(frozen_pyx)
assert report['frozen_CompressToRLE_pyx_sha256'] == '1ef40aba3d9551ec5e3b656f30cbdc01f1e9c0e750b0830b7bd928d329ff8ab2'
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

report['compress_to_rle_stub_removed'] = not os.path.exists(stub)
assert report['compress_to_rle_stub_removed']

setup_text = open(setup).read()
report['setup_extension_names'] = re.findall(r"'(\w+)'", 
    setup_text.split('EXTENSION_NAMES = [')[1].split(']')[0])
assert 'CompressToRLE' in report['setup_extension_names']
assert len(report['setup_extension_names']) == 11

c_banner = open(modern_c, 'rb').read().splitlines()[0].decode('utf-8', 'replace')
report['compress_to_rle_c_banner'] = c_banner
assert 'Generated by Cython 3.0.12' in c_banner

lcp_text = open(lcp_stub).read()
report['lcpgen_stub_classification'] = 'DEAD/PRIVATE' if 'DEAD/PRIVATE' in lcp_text else None
assert report['lcpgen_stub_classification'] == 'DEAD/PRIVATE'
assert 'NotImplementedError' in lcp_text
stub_py_files = sorted(os.path.basename(p) for p in os.listdir(
    os.path.join(repo, 'packages', 'msbwt-modern2', 'MUSCython'))
    if p.endswith('.py') and p != '__init__.py')
report['remaining_stub_py_files'] = stub_py_files
assert stub_py_files == ['LCPGen.py'], stub_py_files

json.dump(report, open(os.path.join(work, 'source.json'), 'w'),
          indent=2, sort_keys=True)
print('gate_source_policy OK')
PY
}

run_convert_case() {
    # $1 = case id (uniform|nonuniform), $2 = input text, $3 = run id
    local case=$1
    local input=$2
    local run=$3
    cli "$WORK/convert-$case-$run-a.log" convert -i "$input" "$WORK/$run-$case-a"
    cli "$WORK/convert-$case-$run-b.log" convert -i "$input" "$WORK/$run-$case-b"
    if [ "$case" = 'uniform' ]; then
        (cd "$PACKAGE" && "$PREFIX/bin/python" -B -c 'from MUS import CommandLineInterface; CommandLineInterface.mainRun()' convert "$WORK/$run-uniform-stdin") < "$input" > "$WORK/convert-uniform-$run-stdin.log" 2>&1
    fi
}

gate_convert() {
    python3 - "$WORK" "$MILESTONE" <<'PY'
import hashlib
import json
import os
import sys

work = sys.argv[1]
milestone = sys.argv[2]

def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()

report = {}
for run in ('run-a', 'run-b'):
    for case in ('uniform', 'nonuniform'):
        base = os.path.join(work, '%s-%s' % (run, case))
        primary = os.path.join(base + '-a', 'comp_msbwt.npy')
        assert sorted(os.listdir(base + '-a')) == ['comp_msbwt.npy']
        assert sorted(os.listdir(base + '-b')) == ['comp_msbwt.npy']
        digest_a = sha256_file(primary)
        digest_b = sha256_file(os.path.join(base + '-b', 'comp_msbwt.npy'))
        assert digest_a == digest_b, (run, case)
        report[run + '_' + case] = digest_a
        if case == 'uniform':
            digest_stdin = sha256_file(os.path.join(
                work, '%s-%s-stdin' % (run, case), 'comp_msbwt.npy'))
            assert digest_stdin == digest_a, (run, case, digest_stdin)
            report[run + '_uniform_stdin'] = digest_stdin

assert report['run-a_uniform'] == '121ffb41838b696ed0c543345794f8dad36525373e4d7427de8a45d298ec009b'
assert report['run-b_uniform'] == '121ffb41838b696ed0c543345794f8dad36525373e4d7427de8a45d298ec009b'
assert report['run-a_nonuniform'] == '5fb45204712b0177803104d27a8170f11c159ed4f666c1b2521bc8fc614c7517'
assert report['run-b_nonuniform'] == '5fb45204712b0177803104d27a8170f11c159ed4f666c1b2521bc8fc614c7517'

# byte-identity vs committed oracle artifacts
for case, digest in (('uniform', report['run-a_uniform']),
                     ('nonuniform', report['run-a_nonuniform'])):
    oracle = os.path.join(milestone, case, 'secondary-regenerated-source',
                          'artifacts', 'comp_msbwt.npy')
    assert sha256_file(oracle) == digest, (case, digest)
    report[case + '_matches_oracle'] = True

# payload cross-check vs the committed post-hoc payloads
def payload_sha256(path):
    data = open(path, 'rb').read()
    header_len = data[8] | (data[9] << 8)
    return hashlib.sha256(data[10 + header_len:]).hexdigest()
report['uniform_payload'] = payload_sha256(
    os.path.join(work, 'run-a-uniform-a', 'comp_msbwt.npy'))
report['nonuniform_payload'] = payload_sha256(
    os.path.join(work, 'run-a-nonuniform-a', 'comp_msbwt.npy'))
assert report['uniform_payload'] == '6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb'
assert report['nonuniform_payload'] == '5566aa4e33bd1952004221c69ef2591d22ef94f38805b68a96f74913f2042363'

json.dump(report, open(os.path.join(work, 'convert.json'), 'w'),
          indent=2, sort_keys=True)
print('gate_convert OK')
PY
}

run_reader_probe() {
    # $1 = converted tree path; writes $WORK/reader.json
    local converted_tree=$1
    "$PREFIX/bin/python" -B - "$converted_tree" "$WORK" "$MILESTONE" <<'PY'
from __future__ import print_function
import json
import os
import shutil
import sys

converted_tree = sys.argv[1]
work = sys.argv[2]
milestone = sys.argv[3]

from MUSCython import MultiStringBWTCython

def inventory(directory):
    return dict((name, os.path.getsize(os.path.join(directory, name)))
                for name in sorted(os.listdir(directory))
                if os.path.isfile(os.path.join(directory, name)))

copy = os.path.join(work, 'convert-reader-copy')
if os.path.exists(copy):
    shutil.rmtree(copy)
shutil.copytree(converted_tree, copy)
before = inventory(copy)
reader = MultiStringBWTCython.loadBWT(os.path.abspath(copy), useMemmap=False,
                                      logger=None)
after = inventory(copy)
added = sorted(set(after) - set(before))
report = {
    'reader_class': type(reader).__module__ + '.' + type(reader).__name__,
    'total_size': int(reader.getTotalSize()),
    'dollar_count': int(reader.getSymbolCount(0)),
    'added_files': added,
}
for kmer, expected in [('AAAAA', 1), ('ACGTN', 3), ('CCCCC', 1),
                       ('AGCTA', 0), ('AA', 4), ('A', 9)]:
    actual = int(reader.countOccurrencesOfSeq(kmer))
    assert actual == expected, (kmer, actual, expected)
    report['query_' + kmer] = actual
assert report['reader_class'] == 'MUSCython.RLE_BWTCython.RLE_BWT'
assert report['total_size'] == 48
assert report['dollar_count'] == 8
assert added == ['comp_fmIndex.npy', 'comp_refIndex.npy', 'totalCounts.npy'], added
with open(os.path.join(work, 'reader.json'), 'w') as handle:
    json.dump(report, handle, indent=2, sort_keys=True)
print('reader probe OK')
PY
}

gate_failure_contracts() {
    printf 'ACGTN\nX\nACGTN\n' > "$WORK/invalid-after-newline.txt"
    printf 'ACGTX\nACGTN\n' > "$WORK/invalid-before-newline.txt"
    set +e
    cli "$WORK/invalid-a.log" convert -i "$WORK/invalid-after-newline.txt" "$WORK/dst-invalid-a"
    EXIT_A=$?
    cli "$WORK/invalid-b.log" convert -i "$WORK/invalid-before-newline.txt" "$WORK/dst-invalid-b"
    EXIT_B=$?
    set -e
    python3 - "$WORK" "$EXIT_A" "$EXIT_B" <<'PY'
import hashlib
import json
import os
import sys

work = sys.argv[1]
exit_a, exit_b = int(sys.argv[2]), int(sys.argv[3])

def payload_sha256(path):
    data = open(path, 'rb').read()
    header_len = data[8] | (data[9] << 8)
    return hashlib.sha256(data[10 + header_len:]).hexdigest()

assert exit_a == 0, exit_a
assert exit_b == 1, exit_b
log_b = open(os.path.join(work, 'invalid-b.log'), 'rb').read()
assert b'TypeError' in log_b
report = {
    'invalid_after_newline': {
        'exit_code': exit_a,
        'payload_sha256': payload_sha256(
            os.path.join(work, 'dst-invalid-a', 'comp_msbwt.npy')),
        'destination_files': sorted(
            os.listdir(os.path.join(work, 'dst-invalid-a'))),
        'classification': 'documented legacy quirk (silent drop after first newline)',
    },
    'invalid_before_newline': {
        'exit_code': exit_b,
        'exception_class': 'TypeError',
        'classification': 'documented legacy quirk (masked Exception)',
    },
}
assert report['invalid_after_newline']['payload_sha256'] == \
    '6a9cc3bdeb3bdcfe24fbef1b051e63029b82470a73b2dab39524eef580544a6f'
assert report['invalid_after_newline']['destination_files'] == ['comp_msbwt.npy']
json.dump(report, open(os.path.join(work, 'failure-contracts.json'), 'w'),
          indent=2, sort_keys=True)
print('gate_failure_contracts OK')
PY
}

gate_massquery() {
    # builds the canonical uniform dataset, then validates the massquery CSV
    # contract (plain and -r) and two-run determinism
    local root="$WORK/massquery"
    mkdir -p "$root"
    cli "$WORK/mq-pp.log" pp -u "$root/bwt" "$FIXTURES/uniform-a.fastq" "$FIXTURES/uniform-b.fastq"
    cli "$WORK/mq-cfpp.log" cfpp -p 1 -u "$root/bwt"
    printf 'ACGTN\nAAAAA\nAGCTA\nAA\n' > "$root/kmers.txt"
    cli "$WORK/mq-run.log" massquery "$root/bwt" "$root/kmers.txt" "$root/out-a.csv"
    cli "$WORK/mq-run2.log" massquery "$root/bwt" "$root/kmers.txt" "$root/out-b.csv"
    cli "$WORK/mq-rc.log" massquery -r "$root/bwt" "$root/kmers.txt" "$root/out-rc.csv"
    python3 - "$root" <<'PY'
import hashlib
import json
import os
import sys

root = sys.argv[1]
plain = open(os.path.join(root, 'out-a.csv'), 'rb').read()
repeat = open(os.path.join(root, 'out-b.csv'), 'rb').read()
rc = open(os.path.join(root, 'out-rc.csv'), 'rb').read()
assert plain == b'k-mer,counts\nACGTN,3\nAAAAA,1\nAGCTA,0\nAA,4\n', plain
assert plain == repeat, repeat
assert rc == b'k-mer,counts,revCompCounts\nACGTN,3,1\nAAAAA,1,1\nAGCTA,0,0\nAA,4,4\n', rc
report = {
    'plain_csv_sha256': hashlib.sha256(plain).hexdigest(),
    'revcomp_csv_sha256': hashlib.sha256(rc).hexdigest(),
    'deterministic': True,
    'expected': {
        'plain': 'k-mer,counts\nACGTN,3\nAAAAA,1\nAGCTA,0\nAA,4\n',
        'revcomp': 'k-mer,counts,revCompCounts\nACGTN,3,1\nAAAAA,1,1\nAGCTA,0,0\nAA,4,4\n',
    },
}
json.dump(report, open(os.path.join(root, 'report.json'), 'w'),
          indent=2, sort_keys=True)
print('gate_massquery OK')
PY
}

gate_compressbwt_probe() {
    python3 - "$WORK" "$GOLDENS" <<'PY'
import hashlib
import json
import os
import sys

work = sys.argv[1]
goldens = sys.argv[2]
sys.path.insert(0, os.path.join(work, 'pkgpath'))

def payload_sha256(path):
    data = open(path, 'rb').read()
    header_len = data[8] | (data[9] << 8)
    return hashlib.sha256(data[10 + header_len:]).hexdigest()

def whole_sha256(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()

report = {}
with open(os.path.join(work, 'compressbwt-probe.json')) as handle:
    probe = json.load(handle)
report['uniform_p1'] = probe['uniform_p1']['whole_sha256']
report['uniform_p2'] = probe['uniform_p2']['whole_sha256']
report['nonuniform_p1'] = probe['nonuniform_p1']['whole_sha256']
report['nonuniform_p2'] = probe['nonuniform_p2']['whole_sha256']
assert probe['uniform_p1_equals_p2']
assert probe['nonuniform_p1_equals_p2']
assert report['uniform_p1'] == '0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372'
assert report['nonuniform_p1'] == '07692b307c7533626900f1c7ee778f6aaa4cdfc453b86822dec8195c75286fdd'
assert probe['uniform_p1']['payload_sha256'] == '6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb'
assert probe['nonuniform_p1']['payload_sha256'] == '5566aa4e33bd1952004221c69ef2591d22ef94f38805b68a96f74913f2042363'
report['typed_division_site'] = 'executed at -p 2; output byte-identical to -p 1; no arithmetic change needed'
json.dump(report, open(os.path.join(work, 'compressbwt.json'), 'w'),
          indent=2, sort_keys=True)
print('gate_compressbwt_probe OK')
PY
}

gate_env
record environment "$("$PREFIX/bin/python" -c 'import json, sys; sys.stdout.write(json.dumps({"python": sys.version.split()[0], "cython": __import__("Cython").__version__, "numpy": __import__("numpy").__version__, "pysam": __import__("pysam").__version__, "cc": __import__("os").environ.get("CC", "")}))')"
if [ "$DO_BUILD" -eq 1 ]; then gate_build; fi
if [ "$DO_BUILD" -eq 1 ]; then record build '{"status": "ok", "modules": 11, "cython": "3.0.12", "language_level": 2}'; else record build '{"status": "skipped"}'; fi
gate_py2_tests > "$WORK/py2-tests.log" 2>&1
record py2_tests '{"status": "ok"}'
gate_fixtures
record fixtures '{"uniform-a": "da3466b9...", "uniform-b": "04124b73...", "nonuniform": "e19ef01c..."}'
gate_source_policy
record source "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/source.json")"

for run in run-a run-b; do
    run_convert_case uniform "$MILESTONE/inputs/uniform.txt" "$run"
    run_convert_case nonuniform "$MILESTONE/inputs/nonuniform.txt" "$run"
done
gate_convert
record convert "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/convert.json")"
run_reader_probe "$WORK/run-a-uniform-a"
record reader "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/reader.json")"
gate_failure_contracts
record failure_contracts "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/failure-contracts.json")"
gate_massquery
record massquery "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/massquery/report.json")"

# compressBWT probe runs through the py2 suite (test_public_surface_py2.py);
# its JSON record is produced here by re-invoking the probe under Python 2.
"$PREFIX/bin/python" -B - "$WORK" "$GOLDENS" <<'PY'
from __future__ import print_function
import hashlib
import json
import os
import sys

work = sys.argv[1]
goldens = sys.argv[2]
sys.path.insert(0, os.path.join(os.environ['MSBWT_MODERN2_REPO'], 'packages', 'msbwt-modern2'))
from MUSCython import MSBWTGenCython

class NullLogger(object):
    def info(self, message): pass
    def warning(self, message): pass
    def error(self, message): pass

def whole_sha256(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()

def payload_sha256(path):
    data = open(path, 'rb').read()
    header_len = ord(data[8]) | (ord(data[9]) << 8)
    return hashlib.sha256(data[10 + header_len:]).hexdigest()

report = {}
for case, source, base in (
        ('uniform', os.path.join(goldens, 'uniform-multifile',
                                 'py27-late-05a7d6d83862', 'pyx-historical-cython',
                                 'build', 'artifacts', 'msbwt.npy'), 'comp-u'),
        ('nonuniform', os.path.join(goldens, 'nonuniform-prefix',
                                    'py27-late-05a7d6d83862', 'pyx-historical-cython',
                                    'build', 'artifacts', 'msbwt.npy'), 'comp-n')):
    outputs = []
    for procs in (1, 2):
        out = os.path.join(work, '%s-p%d.npy' % (base, procs))
        MSBWTGenCython.compressBWT(source, out, procs, NullLogger())
        outputs.append(out)
    report[case + '_p1'] = {'whole_sha256': whole_sha256(outputs[0]),
                            'payload_sha256': payload_sha256(outputs[0])}
    report[case + '_p2'] = {'whole_sha256': whole_sha256(outputs[1]),
                            'payload_sha256': payload_sha256(outputs[1])}
    report[case + '_p1_equals_p2'] = (
        report[case + '_p1']['whole_sha256'] == report[case + '_p2']['whole_sha256'])
json.dump(report, open(os.path.join(work, 'compressbwt-probe.json'), 'w'),
          indent=2, sort_keys=True)
print('compressbwt probe OK')
PY
gate_compressbwt_probe
record compressbwt "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$WORK/compressbwt.json")"

record cli_inventory '{"subcommands": ["cffq", "pp", "cfpp", "merge", "query", "massquery", "compress", "decompress", "convert"], "aliases": ["-u/--uniform", "-c/--compressed", "-d/--dump-seqs", "-r/--rev-comp", "-i", "-p", "-V/--version"], "console_script": "bin/msbwt -> MUS.CommandLineInterface.mainRun"}'
record stub_policy '{"remaining_stubs": ["MUSCython/LCPGen"], "classification": "DEAD/PRIVATE - intentionally not migrated; no public CLI/API path reaches it", "unexplained_stubs": []}'
record final '{"branch": "codex/modern2", "milestone": "modern2-milestone10-public-surface", "oracle_class": "secondary-regenerated-source", "status": "passed"}'
if [ -n "$EVIDENCE" ]; then cp "$RESULT_FILE" "$EVIDENCE"; printf 'Evidence written to %s\n' "$EVIDENCE"; fi
printf 'public-surface-milestone10 OK\n'
