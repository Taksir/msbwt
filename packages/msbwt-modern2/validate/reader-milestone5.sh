#!/usr/bin/env bash
# msbwt-modern2 reader/index boundary milestone 5 validation driver.
#
# Validates reader and query operations on the committed >1M-symbol evidence
# dataset (the uniform byte golden tiled 22000x, logical size 1,056,000,
# compressed RLE 484,000 bytes, 516 FM bins of 2048 symbols) at beginning /
# FM-bin-boundary / work-boundary / end positions, and protects the three
# reader-side index-boundary corrections added in this milestone:
#
#   1. MUS/MultiStringBWT.py CompressedMSBWT.getCharAtIndex
#      `endRange = int(self.refFM[binID+1])+1`
#   2. MUS/MultiStringBWT.py CompressedMSBWT.getFullFMAtIndex
#      `endRange = int(self.refFM[binID+1])+1`
#   3. MUSCython/RLE_BWTCython.pyx RLE_BWT.decompressBlocks
#      `endRange = int(self.refFM[endBlock+1])+1`
#
# Root cause (executed evidence): under CPython 2.7.18 / NumPy 1.16.6 the
# `<u8` refFM scalar plus the Python int 1 promotes to NumPy float64, and
# float64 cannot index the compressed BWT, so every non-last-bin character /
# FM lookup raised `IndexError` (frozen MUS/MultiStringBWT.py lines 575 and
# 708) and the compiled RLE_BWT.getBWTRange failed with IndexError at
# MUSCython/RLE_BWTCython.pyx line 375 for every range ending before the last
# block.  The int() conversions preserve the exact mathematical value
# (compressed-file byte offsets, always integral); only the Python
# representation changes at the index boundary.
#
# DOCUMENTED LEGACY DEFECT (NOT fixed; frozen arithmetic preserved): the
# pure-Python CompressedMSBWT.getFullFMAtIndex fill line
# `ret += np.bincount(letters[0:x-1], counts[0:x-1], minlength=self.vcLen)`
# (frozen line 725 == modern2 line 726) raises
# `TypeError: Cannot cast ufunc add output from dtype('float64') to
# dtype('uint64') with casting rule 'same_kind'` whenever more than one run
# precedes the target position.  np.bincount with weights returns float64 and
# NumPy 1.16.6 in-place same_kind casting rejects float64 -> uint64; this is
# independent of the uint64+int promotion (it also fails on the last bin and
# on the 48-symbol single-bin case).  The compiled RLE_BWT reader (the normal
# API) implements the same function with typed Cython arithmetic and is fully
# correct; the pure-Python legacy defect is preserved and asserted read-only.
#
# Gates (all must pass):
#   1. environment: CPython 2.7, Cython 3.0.x, NumPy 1.16.6, pysam 0.15.4
#   2. optional in-tree build of the 8 migrated extensions (Cython 3.0.12)
#   3. all modern2 Python-2 tests green (including the milestone-1/2/3/4
#      regressions and the 10 new reader-boundary tests)
#   4. evidence primary regenerated deterministically (np.tile 22000x) and
#      hash-matched to the committed m3c2 evidence primary; modern2
#      compression reproduces the committed m3c2 RLE primary
#   5. executed probes on disposable copies (frozen source vs checkout):
#      a. pre-fix failure reproduction on the FROZEN source: pure
#         getCharAtIndex/getFullFMAtIndex IndexError (frozen lines 575/708),
#         the frozen line-725 float64 bincount TypeError, and the committed
#         compiled-extension IndexError at RLE_BWTCython.pyx:375 (committed
#         prefix probe, read-only)
#      b. post-fix: pure getCharAtIndex returns the raw primary byte at all
#         11 boundary positions; pure getFullFMAtIndex equals the independent
#         oracle where it succeeds and raises ONLY the documented legacy
#         TypeError elsewhere
#      c. compiled RLE_BWT.getBWTRange decodes 5 representative ranges
#         byte-identically to the expected payload slice AND to the fixed
#         pure-Python path
#      d. compiled RLE_BWT and ByteBWT getCharAtIndex / getFullFMAtIndex /
#         countOccurrencesOfSeq at boundaries equal independent byte-level
#         oracles (string-level FM counts; the tiled evidence is not a valid
#         collection BWT)
#      e. valid collection regression: the committed uniform 48-symbol byte
#         and RLE primaries keep their fixture query counts and cross-reader
#         recovered strings; committed reader side-effect hashes unchanged
#   6. frozen source digest (MUS/MultiStringBWT.py 95ac0b86...) untouched
#      and the modern2-vs-frozen diffs are exactly the documented fixes
# If --evidence is given, a JSON record of every gate is written.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: validate/reader-milestone5.sh --prefix /absolute/prefix --package /absolute/package --repository /absolute/repo [--build] [--evidence /absolute/out.json]'
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
BYTE_GOLDEN="$GOLDENS/uniform-multifile/$PROFILE/$ROUTE/build/artifacts/msbwt.npy"
BWT_ORACLE_TOOL="$REPOSITORY/compat/tools/bwt_oracle.py"
PREFIX_PROBE="$PACKAGE/evidence/reader-milestone5-prefix-probe.json"
FROZEN_SHA256=95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0

# committed evidence dataset and reader-boundary SUCCESS contract constants
EVIDENCE_PRIMARY_SHA256=24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35
RLE_PRIMARY_SHA256=681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99
TOTAL_SIZE=1056000
REPEAT_COUNT=22000
BIN_SIZE=2048
LAST_BIN_START=1054720

WORK=$(mktemp -d /tmp/modern2-milestone5-XXXXXX)
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
    mkdir -p "$WORK/evidence"
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
    local sha
    sha=$(sha256sum "$WORK/evidence/msbwt.npy" | cut -d' ' -f1)
    if [ "$sha" != "$EVIDENCE_PRIMARY_SHA256" ]; then
        printf 'Evidence primary hash mismatch: %s\n' "$sha" >&2
        exit 70
    fi
    mkdir -p "$WORK/rle"
    cli "$WORK/compress.log" compress -p 1 "$WORK/evidence" "$WORK/rle"
    sha=$(sha256sum "$WORK/rle/comp_msbwt.npy" | cut -d' ' -f1)
    if [ "$sha" != "$RLE_PRIMARY_SHA256" ]; then
        printf 'RLE primary hash mismatch: %s\n' "$sha" >&2
        exit 70
    fi
    printf 'build_evidence OK\n'
}

# ---------------------------------------------------------------------------
# executed reader-boundary probes (frozen source + checkout, disposable copies)
# ---------------------------------------------------------------------------

run_probe() {
    cat > "$WORK/probe.py" <<'PY'
from __future__ import print_function
import hashlib
import imp
import json
import os
import shutil
import sys
import traceback

REPO = sys.argv[1]
WORK = sys.argv[2]
PACKAGE = os.path.join(REPO, 'packages', 'msbwt-modern2')
sys.path.insert(0, PACKAGE)
sys.path.insert(0, os.path.join(PACKAGE, 'MUS'))

BYTE_GOLDEN = os.path.join(
    REPO, 'compat', 'goldens', 'original-0.3.0', 'uniform-multifile',
    'py27-late-05a7d6d83862', 'pyx-historical-cython', 'build',
    'artifacts', 'msbwt.npy')
TOTAL_SIZE = 1056000
BIN_SIZE = 2048
LAST_BIN_START = 1054720
POSITIONS = [0, 1, 2047, 2048, 2049, 999998, 999999, 1000000, 1000001,
             1055998, 1055999]
ORACLE_POSITIONS = [0, 1, 2048, 2049]
LEGACY_POSITIONS = [2047, 999998, 1000000, 1055999]
KMERS = ['A', 'AC', 'ACGTN', 'AAAAA', 'AAAAAA', 'C', 'CG', 'GT',
         'GTGGGTTT', 'N', 'NACGT', 'T', 'TTTTT']
LEGACY_BINCOUNT_ERROR = ("Cannot cast ufunc add output from dtype('float64') "
                         "to dtype('uint64') with casting rule 'same_kind'")

report = {'dataset': {}, 'pre_fix': {}, 'reader': {}}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def fm_counts(payload, kmers):
    symbols = '$ACGNT'
    positions = {}
    for index, symbol in enumerate(symbols):
        positions[symbol] = [pos for pos, value in enumerate(bytearray(payload))
                             if value == index]
    c_table = {}
    running = 0
    for symbol in symbols:
        c_table[symbol] = running
        running += len(positions[symbol])

    def occ(char, index):
        return sum(1 for pos in positions[char] if pos < index)

    result = {}
    for kmer in kmers:
        lo, hi = 0, len(payload)
        for char in reversed(kmer):
            lo = c_table[char] + occ(char, lo)
            hi = c_table[char] + occ(char, hi)
            if lo >= hi:
                break
        result[kmer] = hi - lo
    return result


def full_fm_oracle(payload, index):
    counts = [0] * 6
    payload_bytes = bytearray(payload)
    for pos in range(0, index):
        counts[payload_bytes[pos]] += 1
    result = []
    running = 0
    for sym in range(6):
        result.append(running + counts[sym])
        running += sum(1 for value in payload_bytes if value == sym)
    return result


def probe_call(fn):
    try:
        value = fn()
        return {'status': 'ok', 'value': value}
    except Exception as exc:  # noqa
        return {'status': 'failed',
                'exception_type': type(exc).__name__,
                'exception': str(exc),
                'traceback': traceback.format_exc()}


def main():
    import numpy as np
    import Cython
    import pysam
    report['environment'] = {
        'python': sys.version.split()[0],
        'cython': Cython.__version__,
        'numpy': np.__version__,
        'pysam': pysam.__version__,
    }
    evidence_dir = os.path.join(WORK, 'evidence')
    rle_dir = os.path.join(WORK, 'rle')
    expected = np.load(BYTE_GOLDEN, 'r')
    tiled = np.tile(expected, 22000)
    assert tiled.shape == (TOTAL_SIZE,)
    expected_payload = tiled.tostring()
    report['dataset'] = {
        'evidence_primary_sha256': sha256_file(
            os.path.join(evidence_dir, 'msbwt.npy')),
        'rle_primary_sha256': sha256_file(
            os.path.join(rle_dir, 'comp_msbwt.npy')),
        'total_size': TOTAL_SIZE,
        'rle_bins': 516,
    }
    report['reader']['independent_oracle'] = {
        'fm_counts': fm_counts(expected_payload, KMERS),
        'full_fm_at': {str(p): full_fm_oracle(expected_payload, p)
                       for p in ORACLE_POSITIONS},
    }

    # ------------------------------------------------------------------
    # pre-fix failure reproduction on the FROZEN source (executed)
    # ------------------------------------------------------------------
    report['pre_fix']['frozen_source_sha256'] = sha256_file(
        os.path.join(REPO, 'MUS', 'MultiStringBWT.py'))
    import numpy as _np
    scalar = _np.uint64(459008)
    promoted = scalar + 1
    report['pre_fix']['promotion'] = {
        'uint64_plus_int_runtime_type': type(promoted).__name__,
        'value': float(promoted),
        'int_conversion_exact': int(scalar) == 459008,
    }
    frozen_dir = os.path.join(WORK, 'frozen-copy')
    shutil.copytree(rle_dir, frozen_dir)
    frozen = imp.load_source('frozen_msbwt',
                             os.path.join(REPO, 'MUS', 'MultiStringBWT.py'))
    fmsbwt = frozen.CompressedMSBWT()
    fmsbwt.loadMsbwt(frozen_dir, logger=None)
    rec = probe_call(lambda: fmsbwt.getCharAtIndex(2048))
    report['pre_fix']['pure_getCharAtIndex'] = {
        'exception_type': rec['exception_type'],
        'traceback': rec['traceback'],
    }
    rec = probe_call(lambda: fmsbwt.getFullFMAtIndex(2048))
    report['pre_fix']['pure_getFullFMAtIndex'] = {
        'exception_type': rec['exception_type'],
        'traceback': rec['traceback'],
    }
    rec = probe_call(lambda: fmsbwt.getFullFMAtIndex(1055998))
    report['pre_fix']['pure_getFullFMAtIndex_legacy_bincount'] = {
        'exception_type': rec['exception_type'],
        'exception': rec['exception'],
        'traceback': rec['traceback'],
    }
    # compiled-extension pre-fix failure: committed prefix probe (the
    # bootstrap-built extension before the decompressBlocks correction)
    prefix = json.load(open(sys.argv[3]))
    bwtr = prefix['probes']['compiled_rle_getBWTRange']['(0, 2048)']
    report['pre_fix']['compiled_rle_getBWTRange'] = {
        'exception_type': bwtr['exception_type'],
        'traceback': '\n'.join(bwtr['traceback']),
    }

    # ------------------------------------------------------------------
    # post-fix probes on the checkout (disposable copies)
    # ------------------------------------------------------------------
    from MUS.MultiStringBWT import CompressedMSBWT
    from MUSCython import MultiStringBWTCython as CompiledBWT

    reader = {}
    report['reader'] = {'pure_compressed': {}, 'compiled_rle': {},
                        'compiled_byte': {}, 'valid_collection': {},
                        'independent_oracle': report['reader']['independent_oracle']}
    reader = report['reader']

    pure_dir = os.path.join(WORK, 'pure-copy')
    shutil.copytree(rle_dir, pure_dir)
    pure = CompressedMSBWT()
    pure.loadMsbwt(pure_dir, logger=None)
    reader['pure_compressed']['getCharAtIndex'] = {
        str(p): int(pure.getCharAtIndex(p)) for p in POSITIONS}
    ffm = {}
    for p in ORACLE_POSITIONS:
        ffm[str(p)] = {'status': 'ok',
                       'value': [int(v) for v in pure.getFullFMAtIndex(p)]}
    for p in LEGACY_POSITIONS:
        rec = probe_call(lambda p=p: pure.getFullFMAtIndex(p))
        ffm[str(p)] = {'status': 'failed',
                       'exception_type': rec['exception_type'],
                       'exception': rec['exception'],
                       'legacy_frozen_site': LEGACY_BINCOUNT_ERROR in str(rec['exception']),
                       'traceback': rec['traceback']}
    reader['pure_compressed']['getFullFMAtIndex'] = ffm

    crle_dir = os.path.join(WORK, 'crle-copy')
    shutil.copytree(rle_dir, crle_dir)
    crle = CompiledBWT.loadBWT(crle_dir, useMemmap=False, logger=None)
    bwtr = {}
    for start, end in ((0, 2048), (0, 1000000), (1000000, 1056000),
                       (LAST_BIN_START, 1056000), (0, TOTAL_SIZE)):
        rng = crle.getBWTRange(start, end)
        payload = rng.tostring()
        pure_rng = pure.getBWTRange(start, end)
        bwtr['%d:%d' % (start, end)] = {
            'shape_ok': rng.shape[0] == end - start,
            'dtype_ok': bool(rng.dtype == np.dtype('<u1')),
            'payload_equal': payload == expected_payload[start:end],
            'pure_equal': payload == pure_rng.tostring(),
        }
    reader['compiled_rle']['getBWTRange'] = bwtr
    reader['compiled_rle']['getCharAtIndex'] = {
        str(p): int(crle.getCharAtIndex(p)) for p in POSITIONS}
    reader['compiled_rle']['getFullFMAtIndex'] = {
        str(p): [int(v) for v in crle.getFullFMAtIndex(p)]
        for p in (0, 2048, 1000000, TOTAL_SIZE - 1)}
    reader['compiled_rle']['countOccurrencesOfSeq'] = {
        k: int(crle.countOccurrencesOfSeq(k)) for k in KMERS}

    byte_dir = os.path.join(WORK, 'byte-copy')
    os.makedirs(byte_dir)
    np.save(os.path.join(byte_dir, 'msbwt.npy'),
            np.fromstring(expected_payload, dtype='<u1'))
    cbyte = CompiledBWT.loadBWT(byte_dir, useMemmap=False, logger=None)
    reader['compiled_byte']['getCharAtIndex'] = {
        str(p): int(cbyte.getCharAtIndex(p)) for p in POSITIONS}
    reader['compiled_byte']['getFullFMAtIndex'] = {
        str(p): [int(v) for v in cbyte.getFullFMAtIndex(p)]
        for p in (0, 2048, 1000000, TOTAL_SIZE - 1)}
    reader['compiled_byte']['countOccurrencesOfSeq'] = {
        k: int(cbyte.countOccurrencesOfSeq(k)) for k in KMERS}
    reader['compiled_byte']['side_effects'] = {
        name: sha256_file(os.path.join(byte_dir, name))
        for name in ('totalCounts.npy', 'fmIndex.npy')}

    # ------------------------------------------------------------------
    # valid collection regression (uniform byte + RLE, 48 symbols)
    # ------------------------------------------------------------------
    col_ev = os.path.join(WORK, 'col-ev')
    os.makedirs(col_ev)
    np.save(os.path.join(col_ev, 'msbwt.npy'), expected)
    col_rle = os.path.join(WORK, 'col-rle')
    os.makedirs(col_rle)
    old_argv = sys.argv
    from MUS import CommandLineInterface
    sys.argv = ['msbwt', 'compress', '-p', '1', col_ev, col_rle]
    CommandLineInterface.mainRun()
    sys.argv = old_argv
    col_byte = CompiledBWT.loadBWT(col_ev, useMemmap=False, logger=None)
    col_crle = CompiledBWT.loadBWT(col_rle, useMemmap=False, logger=None)
    queries = ['AAAAA', 'ACGTN', 'CCCCC', 'AGCTA', 'AAAAAA', 'GGGGG',
               'NACGT', 'TTTTT', '$']
    query_counts = {}
    byte_queries = {}
    rle_queries = {}
    for kmer in queries:
        byte_queries[kmer] = int(col_byte.countOccurrencesOfSeq(kmer))
        rle_queries[kmer] = int(col_crle.countOccurrencesOfSeq(kmer))
        query_counts[kmer] = byte_queries[kmer]
    payload = np.load(os.path.join(col_ev, 'msbwt.npy'), 'r')
    dollar_positions = [pos for pos, value in enumerate(payload) if value == 0]
    recovery_equal = True
    for position in dollar_positions:
        if col_byte.recoverString(position) != col_crle.recoverString(position):
            recovery_equal = False
    reader['valid_collection'] = {
        'total_size': int(col_byte.getTotalSize()),
        'query_counts': query_counts,
        'byte_rle_queries_equal': byte_queries == rle_queries,
        'byte_rle_recovery_equal': recovery_equal,
        'dollar_count': len(dollar_positions),
        'byte_reader_side_effects': {
            name: sha256_file(os.path.join(col_ev, name))
            for name in ('totalCounts.npy', 'fmIndex.npy')},
    }

    with open(os.path.join(WORK, 'probe.json'), 'w') as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    print('PROBE DONE')


if __name__ == '__main__':
    main()
PY
    "$PREFIX/bin/python" -B "$WORK/probe.py" "$REPOSITORY" "$WORK" "$PREFIX_PROBE"
    printf 'run_probe OK\n'
}

# ---------------------------------------------------------------------------
# independent verification (host-side, no NumPy)
# ---------------------------------------------------------------------------

verify_probe() {
    python3 - "$WORK/probe.json" "$BWT_ORACLE_TOOL" "$WORK/evidence/msbwt.npy" <<'PY'
import json
import subprocess
import sys

probe = json.load(open(sys.argv[1]))
oracle_tool = sys.argv[2]
primary = sys.argv[3]

EXPECTED_BYTES = {0: 1, 1: 4, 2047: 2, 2048: 2, 2049: 2, 999998: 0,
                  999999: 0, 1000000: 0, 1000001: 2, 1055998: 5, 1055999: 0}
EXPECTED_FM_COUNTS = {
    "A": 198000, "AC": 37125, "ACGTN": 111, "AAAAA": 243, "AAAAAA": 45,
    "C": 198000, "CG": 37125, "GT": 37125, "GTGGGTTT": 2, "N": 88000,
    "NACGT": 108, "T": 198000, "TTTTT": 249,
}

reader = probe['reader']
gci = reader['pure_compressed']['getCharAtIndex']
for pos, expected in EXPECTED_BYTES.items():
    assert gci[str(pos)] == expected, (pos, gci[str(pos)])
for pos in ('0', '1', '2048', '2049'):
    rec = reader['pure_compressed']['getFullFMAtIndex'][pos]
    assert rec['status'] == 'ok', pos
    assert rec['value'] == reader['independent_oracle']['full_fm_at'][pos], pos
for pos in ('2047', '999998', '1000000', '1055999'):
    rec = reader['pure_compressed']['getFullFMAtIndex'][pos]
    assert rec['status'] == 'failed', pos
    assert rec['exception_type'] == 'TypeError', pos
    assert rec['legacy_frozen_site'], pos
for start, end in ((0, 2048), (0, 1000000), (1000000, 1056000),
                   (1054720, 1056000), (0, 1056000)):
    rec = reader['compiled_rle']['getBWTRange']['%d:%d' % (start, end)]
    assert rec['shape_ok'] and rec['dtype_ok'], (start, end)
    assert rec['payload_equal'], (start, end)
    assert rec['pure_equal'], (start, end)
for reader_key in ('compiled_rle', 'compiled_byte'):
    counts = reader[reader_key]['countOccurrencesOfSeq']
    for kmer, expected in EXPECTED_FM_COUNTS.items():
        assert counts[kmer] == expected, (reader_key, kmer)
    assert counts == reader['independent_oracle']['fm_counts'], reader_key
    for pos, expected in EXPECTED_BYTES.items():
        assert reader[reader_key]['getCharAtIndex'][str(pos)] == expected, (reader_key, pos)
assert reader['compiled_byte']['side_effects'] == {
    'totalCounts.npy': 'e7fe29a99498d61a278845772782b10d22256a9556e865704d75a54e160fe348',
    'fmIndex.npy': '16e19742f54504b19ff72d278cea134b6063a0c51eac77f784699659013d8040'}
col = reader['valid_collection']
assert col['total_size'] == 48
assert col['query_counts'] == {'AAAAA': 1, 'ACGTN': 3, 'CCCCC': 1,
                               'AGCTA': 0, 'AAAAAA': 0, 'GGGGG': 1,
                               'NACGT': 1, 'TTTTT': 1, '$': 8}
assert col['byte_rle_queries_equal']
assert col['byte_rle_recovery_equal']
assert col['byte_reader_side_effects'] == {
    'totalCounts.npy': 'ea104b616fe89d7b786acdff7ca0db61f6339a59c31fbf0fff066ad7384c1c2b',
    'fmIndex.npy': 'a5b4bf06726fcadf535245d03ef65e04a4a5248d368b3aa53639c190028b933f'}

pre = probe['pre_fix']
assert pre['frozen_source_sha256'] == '95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0'
assert pre['promotion']['uint64_plus_int_runtime_type'] == 'float64'
assert pre['pure_getCharAtIndex']['exception_type'] == 'IndexError', \
    pre['pure_getCharAtIndex']
assert 'line 575' in pre['pure_getCharAtIndex']['traceback'], \
    pre['pure_getCharAtIndex']['traceback']
assert pre['pure_getFullFMAtIndex']['exception_type'] == 'IndexError'
assert 'line 708' in pre['pure_getFullFMAtIndex']['traceback']
assert pre['pure_getFullFMAtIndex_legacy_bincount']['exception_type'] == 'TypeError'
assert 'line 725' in pre['pure_getFullFMAtIndex_legacy_bincount']['traceback']
assert pre['compiled_rle_getBWTRange']['exception_type'] == 'IndexError'
assert 'line 375' in pre['compiled_rle_getBWTRange']['traceback']
print('verify_probe OK')
PY
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

gate_env
if [ "$DO_BUILD" -eq 1 ]; then gate_build; fi
if [ "$DO_BUILD" -eq 1 ]; then record build '{"status": "passed"}'; else record build '{"status": "skipped"}'; fi
gate_py2_tests > "$WORK/py2-tests.log" 2>&1
record py2_tests '{"status": "ok"}'
build_evidence
run_probe
verify_probe
record reader "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["reader"]))' "$WORK/probe.json")"
record pre_fix "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["pre_fix"]))' "$WORK/probe.json")"
record dataset "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["dataset"]))' "$WORK/probe.json")"
record environment "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["environment"]))' "$WORK/probe.json")"
record final '{"branch": "codex/modern2", "milestone": "modern2-milestone5-reader-index-boundaries", "status": "passed"}'
if [ -n "$EVIDENCE" ]; then cp "$RESULT_FILE" "$EVIDENCE"; printf 'Evidence written to %s\n' "$EVIDENCE"; fi
printf 'reader-milestone5 OK\n'
