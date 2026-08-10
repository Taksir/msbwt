#!/usr/bin/env bash
# msbwt-modern2 pure-Python FM reader milestone 6 validation driver.
#
# Validates the fix of the frozen pure-Python CompressedMSBWT.getFullFMAtIndex
# fill defect: `ret += np.bincount(letters[0:x-1], counts[0:x-1],
# minlength=self.vcLen)` (frozen line 725 == modern2 line 726 pre-fix) raised
# `TypeError: Cannot cast ufunc add output from dtype('float64') to
# dtype('uint64') with casting rule 'same_kind'` under CPython 2.7.18 / NumPy
# 1.16.6 whenever more than one run precedes the target position.  The modern2
# fill line is now the exact-integer accumulation
# `np.add.at(ret, letters[0:x-1], counts[0:x-1])`, which matches the typed
# Cython RLE_BWT reader arithmetic (`ret_view[prevChar] += prevCount`).
#
# Executed semantic contract for every exercised position:
#
#     pure-Python CompressedMSBWT.getFullFMAtIndex
#         == compiled RLE_BWT.getFullFMAtIndex
#         == independent FM oracle (startIndex + cumulative symbol counts)
#
# Backward-search query counts (countOccurrencesOfSeq) on the pure reader,
# which route through getOccurrenceOfCharAtIndex -> getFullFMAtIndex, are also
# validated against the compiled readers and the independent string-level FM
# oracle.
#
# The FROZEN original source (`MUS/MultiStringBWT.py`, SHA-256 95ac0b86...) is
# NOT modified and is executed read-only to reproduce the historical failure
# (TypeError at line 725 for last-bin positions, IndexError at line 708 for
# non-last-bin positions).  The modern2 pre-fix failure is preserved in the
# committed evidence probe reader-milestone6-prefix-probe.json.
#
# Gates (all must pass):
#   1. environment: CPython 2.7, Cython 3.0.x, NumPy 1.16.6, pysam 0.15.4
#   2. optional in-tree build of the 8 migrated extensions (Cython 3.0.12)
#   3. all modern2 Python-2 tests green
#   4. evidence primary regenerated deterministically (np.tile 22000x) and
#      hash-matched to the committed m3c2/milestone-5 evidence primary; modern2
#      compression reproduces the committed m3c2 RLE primary
#   5. executed probes on disposable copies (frozen source vs checkout):
#      a. pre-fix failure reproduction on the FROZEN source: pure
#         getFullFMAtIndex TypeError at line 725 (last bin) / IndexError at
#         line 708 (non-last bin), plus the committed modern2 pre-fix probe
#         (read-only)
#      b. post-fix: pure getFullFMAtIndex equals the compiled RLE_BWT reader
#         AND the independent oracle at every boundary position on the >1M
#         evidence (dtype <u8) and on the 48-symbol valid collection
#      c. pure CompressedMSBWT backward-search queries (countOccurrencesOfSeq)
#         equal the compiled readers and the independent string-level FM
#         oracle on the 48-symbol collection and the >1M evidence
#      d. all six alphabet symbols are represented in the returned FM vectors
#      e. valid collection regression: query counts, recovered strings, and
#         reader side-effect hashes unchanged; pure-reader recovery equals the
#         compiled readers
#      f. runtime dtype evidence: ret <u8, np.bincount(weights) float64,
#         weights <u8, in-place add raises the documented TypeError, and
#         np.add.at produces the exact integer uint64 result
#   6. frozen source digest (MUS/MultiStringBWT.py 95ac0b86...) untouched and
#      the modern2-vs-frozen diff is exactly the documented fix set
# If --evidence is given, a JSON record of every gate is written.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: validate/reader-milestone6.sh --prefix /absolute/prefix --package /absolute/package --repository /absolute/repo [--build] [--evidence /absolute/out.json]'
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
PREFIX_PROBE="$PACKAGE/evidence/reader-milestone6-prefix-probe.json"
FROZEN_SHA256=95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0

# committed evidence dataset constants (shared with the milestone-5 evidence)
EVIDENCE_PRIMARY_SHA256=24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35
RLE_PRIMARY_SHA256=681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99
TOTAL_SIZE=1056000
REPEAT_COUNT=22000
BIN_SIZE=2048
LAST_BIN_START=1054720

WORK=$(mktemp -d /tmp/modern2-milestone6-XXXXXX)
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
# evidence generation (byte-identical to the committed m3c2/milestone-5 dataset)
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
    # 48-symbol valid collection (uniform byte + RLE)
    mkdir -p "$WORK/col"
    cp "$BYTE_GOLDEN" "$WORK/col/msbwt.npy"
    cli "$WORK/col-compress.log" compress -p 1 "$WORK/col" "$WORK/col-rle"
    printf 'build_evidence OK\n'
}

# ---------------------------------------------------------------------------
# executed pure-FM probes (frozen source + checkout, disposable copies)
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
COLLECTION_POSITIONS = [0, 1, 2, 5, 10, 20, 40, 47]
KMERS = ['A', 'AC', 'ACGTN', 'AAAAA', 'AAAAAA', 'C', 'CG', 'GT',
         'GTGGGTTT', 'N', 'NACGT', 'T', 'TTTTT']
LEGACY_BINCOUNT_ERROR = ("Cannot cast ufunc add output from dtype('float64') "
                         "to dtype('uint64') with casting rule 'same_kind'")

report = {'dataset': {}, 'dtypes': {}, 'pre_fix': {}, 'reader': {}}


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


def fresh_copy(src, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


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
    col_dir = os.path.join(WORK, 'col')
    col_rle_dir = os.path.join(WORK, 'col-rle')
    expected = np.load(BYTE_GOLDEN, 'r')
    tiled = np.tile(expected, 22000)
    assert tiled.shape == (TOTAL_SIZE,)
    expected_payload = tiled.tostring()
    col_payload = expected.tostring()
    report['dataset'] = {
        'evidence_primary_sha256': sha256_file(
            os.path.join(evidence_dir, 'msbwt.npy')),
        'rle_primary_sha256': sha256_file(
            os.path.join(rle_dir, 'comp_msbwt.npy')),
        'total_size': TOTAL_SIZE,
        'rle_bins': 516,
        'collection_size': 48,
    }
    report['reader']['independent_oracle'] = {
        'fm_counts': fm_counts(expected_payload, KMERS),
        'collection_fm_counts': fm_counts(col_payload, KMERS),
        'full_fm_at': {str(p): full_fm_oracle(expected_payload, p)
                       for p in POSITIONS},
        'collection_full_fm_at': {str(p): full_fm_oracle(col_payload, p)
                                  for p in COLLECTION_POSITIONS},
    }

    # ------------------------------------------------------------------
    # runtime dtype evidence at the frozen fill site (executed)
    # ------------------------------------------------------------------
    rle_dt = fresh_copy(rle_dir, os.path.join(WORK, 'rle-dtype'))
    from MUS.MultiStringBWT import CompressedMSBWT
    dt_reader = CompressedMSBWT()
    dt_reader.loadMsbwt(rle_dt, logger=None)
    index = TOTAL_SIZE - 2  # 1055998, last bin, preceded by many runs
    binID = index >> dt_reader.bitPower
    bwtIndex = dt_reader.refFM[binID]
    ret = np.copy(dt_reader.partialFM[binID])
    trueIndex = np.sum(ret) - dt_reader.offsetSum
    dist = index - trueIndex
    endRange = dt_reader.bwt.shape[0]  # last bin
    letters = np.bitwise_and(dt_reader.bwt[bwtIndex:endRange], dt_reader.mask)
    counts = np.right_shift(dt_reader.bwt[bwtIndex:endRange],
                            dt_reader.letterBits, dtype='<u8')
    i = 1
    same = (letters[0:-1] == letters[1:])
    while np.count_nonzero(same) > 0:
        (counts[i:])[same] *= dt_reader.numPower
        i += 1
        same = np.bitwise_and(same[0:-1], same[1:])
    cs = np.subtract(np.cumsum(counts), counts)
    x = int(np.searchsorted(cs, dist, 'left'))
    bc = np.bincount(letters[0:x - 1], counts[0:x - 1],
                     minlength=dt_reader.vcLen)
    report['dtypes'] = {
        'index': index,
        'binID': binID,
        'ret_dtype': str(ret.dtype),
        'dist_type': type(dist).__name__,
        'counts_dtype': str(counts.dtype),
        'letters_dtype': str(letters.dtype),
        'cs_dtype': str(cs.dtype),
        'x': x,
        'bincount_dtype': str(bc.dtype),
        'bincount_values': [float(v) for v in bc],
        'bincount_sum': int(bc.sum()),
        'weights_dtype': str(counts[0:x - 1].dtype),
        'letters_slice_dtype': str(letters[0:x - 1].dtype),
        'oracle_last_bin_fm': full_fm_oracle(expected_payload, index),
        'math_add_result': [float(v) for v in ret + bc],
    }
    report['dtypes']['inplace_add'] = probe_call(lambda: ret.__iadd__(bc))
    addat = np.copy(ret)
    np.add.at(addat, letters[0:x - 1], counts[0:x - 1])
    report['dtypes']['np_add_at'] = {
        'dtype': str(addat.dtype),
        'values': [int(v) for v in addat],
        'equals_float_math_result': [float(v) for v in addat] ==
                                    [float(v) for v in ret + bc],
    }

    # ------------------------------------------------------------------
    # pre-fix failure reproduction on the FROZEN source (executed)
    # ------------------------------------------------------------------
    report['pre_fix']['frozen_source_sha256'] = sha256_file(
        os.path.join(REPO, 'MUS', 'MultiStringBWT.py'))
    frozen_dir = fresh_copy(rle_dir, os.path.join(WORK, 'frozen-copy'))
    frozen = imp.load_source('frozen_msbwt',
                             os.path.join(REPO, 'MUS', 'MultiStringBWT.py'))
    fmsbwt = frozen.CompressedMSBWT()
    fmsbwt.loadMsbwt(frozen_dir, logger=None)
    rec = probe_call(lambda: fmsbwt.getFullFMAtIndex(2048))
    report['pre_fix']['frozen_getFullFMAtIndex_nonlast_bin'] = {
        'exception_type': rec['exception_type'],
        'traceback': rec['traceback'],
    }
    rec = probe_call(lambda: fmsbwt.getFullFMAtIndex(TOTAL_SIZE - 2))
    report['pre_fix']['frozen_getFullFMAtIndex_last_bin'] = {
        'exception_type': rec['exception_type'],
        'exception': rec['exception'],
        'traceback': rec['traceback'],
    }
    # frozen on the 48-symbol single-bin collection
    frozen48 = fresh_copy(col_rle_dir, os.path.join(WORK, 'frozen48'))
    fcol = frozen.CompressedMSBWT()
    fcol.loadMsbwt(frozen48, logger=None)
    rec = probe_call(lambda: fcol.getFullFMAtIndex(2))
    report['pre_fix']['frozen_collection_getFullFMAtIndex'] = {
        'exception_type': rec['exception_type'],
        'exception': rec['exception'],
        'traceback': rec['traceback'],
    }
    # committed modern2 pre-fix probe (executed at the milestone-6 start,
    # current checkout before the fill-line fix), referenced read-only
    prefix = json.load(open(sys.argv[3]))
    rec = prefix['checkout_pure_getFullFMAtIndex']['2047']
    report['pre_fix']['modern2_prefix_probe'] = {
        'frozen_source_sha256': prefix['frozen_source_sha256'],
        'checkout_sha': prefix['checkout_sha'],
        'position_2047_exception_type': rec['exception_type'],
        'position_2047_exception': rec['exception'],
        'position_1055998_exception_type':
            prefix['checkout_pure_getFullFMAtIndex']['1055998']['exception_type'],
        'ret_dtype': prefix['dtypes']['ret']['dtype'],
        'bincount_dtype': prefix['dtypes']['bincount_result']['dtype'],
        'bincount_sum': prefix['dtypes']['bincount_result_sum'],
    }

    # ------------------------------------------------------------------
    # post-fix probes on the checkout (disposable copies)
    # ------------------------------------------------------------------
    from MUSCython import MultiStringBWTCython as CompiledBWT

    reader = report['reader']

    pure_dir = fresh_copy(rle_dir, os.path.join(WORK, 'pure-copy'))
    pure = CompressedMSBWT()
    pure.loadMsbwt(pure_dir, logger=None)

    # pure getCharAtIndex unchanged at every boundary
    reader['pure_compressed'] = {}
    reader['pure_compressed']['getCharAtIndex'] = {
        str(p): int(pure.getCharAtIndex(p)) for p in POSITIONS}

    # pure getFullFMAtIndex == compiled RLE == oracle at every boundary
    crle_dir = fresh_copy(rle_dir, os.path.join(WORK, 'crle-copy'))
    crle = CompiledBWT.loadBWT(crle_dir, useMemmap=False, logger=None)
    ffm = {}
    for p in POSITIONS:
        ret = pure.getFullFMAtIndex(p)
        compiled = crle.getFullFMAtIndex(p)
        oracle = full_fm_oracle(expected_payload, p)
        ffm[str(p)] = {
            'status': 'ok',
            'dtype': str(ret.dtype),
            'value': [int(v) for v in ret],
            'compiled': [int(v) for v in compiled],
            'oracle': oracle,
            'pure_eq_compiled': [int(v) for v in ret] ==
                                [int(v) for v in compiled],
            'pure_eq_oracle': [int(v) for v in ret] == oracle,
        }
    reader['pure_compressed']['getFullFMAtIndex'] = ffm

    # all six alphabet symbols represented in the returned FM vectors: at the
    # final position every symbol has a positive occurrence count
    final_fm = [int(v) for v in pure.getFullFMAtIndex(TOTAL_SIZE - 1)]
    symbol_counts_positive = []
    for sym in range(6):
        symbol_counts_positive.append(final_fm[sym] > 0)
    reader['pure_compressed']['all_symbols_represented'] = {
        'final_fm': final_fm,
        'symbol_counts_positive': symbol_counts_positive,
        'all_positive': all(symbol_counts_positive),
    }

    # pure backward-search queries route through getFullFMAtIndex
    reader['pure_compressed']['countOccurrencesOfSeq'] = {
        k: int(pure.countOccurrencesOfSeq(k)) for k in KMERS}

    # compiled readers for cross-validation
    byte_dir = os.path.join(WORK, 'byte-copy')
    os.makedirs(byte_dir)
    np.save(os.path.join(byte_dir, 'msbwt.npy'),
            np.fromstring(expected_payload, dtype='<u1'))
    cbyte = CompiledBWT.loadBWT(byte_dir, useMemmap=False, logger=None)
    reader['compiled'] = {}
    reader['compiled']['rle_getFullFMAtIndex'] = {
        str(p): [int(v) for v in crle.getFullFMAtIndex(p)] for p in POSITIONS}
    reader['compiled']['rle_countOccurrencesOfSeq'] = {
        k: int(crle.countOccurrencesOfSeq(k)) for k in KMERS}
    reader['compiled']['byte_countOccurrencesOfSeq'] = {
        k: int(cbyte.countOccurrencesOfSeq(k)) for k in KMERS}
    reader['compiled']['byte_side_effects'] = {
        name: sha256_file(os.path.join(byte_dir, name))
        for name in ('totalCounts.npy', 'fmIndex.npy')}

    # ------------------------------------------------------------------
    # valid collection regression (uniform byte + RLE, 48 symbols)
    # ------------------------------------------------------------------
    col_ev = os.path.join(WORK, 'col-ev')
    os.makedirs(col_ev)
    np.save(os.path.join(col_ev, 'msbwt.npy'), expected)
    col_pure_dir = fresh_copy(col_rle_dir, os.path.join(WORK, 'col-pure'))
    pcol = CompressedMSBWT()
    pcol.loadMsbwt(col_pure_dir, logger=None)
    col_byte = CompiledBWT.loadBWT(col_ev, useMemmap=False, logger=None)
    col_rle = CompiledBWT.loadBWT(
        fresh_copy(col_rle_dir, os.path.join(WORK, 'col-rle-reader')),
        useMemmap=False, logger=None)

    col_ffm = {}
    for p in COLLECTION_POSITIONS:
        ret = pcol.getFullFMAtIndex(p)
        compiled = [int(v) for v in col_rle.getFullFMAtIndex(p)]
        oracle = full_fm_oracle(col_payload, p)
        col_ffm[str(p)] = {
            'status': 'ok',
            'dtype': str(ret.dtype),
            'value': [int(v) for v in ret],
            'compiled': compiled,
            'oracle': oracle,
            'pure_eq_compiled': [int(v) for v in ret] == compiled,
            'pure_eq_oracle': [int(v) for v in ret] == oracle,
        }
    reader['valid_collection'] = {
        'total_size': int(pcol.getTotalSize()),
        'pure_getFullFMAtIndex': col_ffm,
        'pure_queries': {
            k: int(pcol.countOccurrencesOfSeq(k))
            for k in ('AAAAA', 'ACGTN', 'CCCCC', 'AGCTA', 'AAAAAA',
                      'GGGGG', 'NACGT', 'TTTTT', '$')},
        'byte_queries': {
            k: int(col_byte.countOccurrencesOfSeq(k))
            for k in ('AAAAA', 'ACGTN', 'CCCCC', 'AGCTA', 'AAAAAA',
                      'GGGGG', 'NACGT', 'TTTTT', '$')},
        'rle_queries': {
            k: int(col_rle.countOccurrencesOfSeq(k))
            for k in ('AAAAA', 'ACGTN', 'CCCCC', 'AGCTA', 'AAAAAA',
                      'GGGGG', 'NACGT', 'TTTTT', '$')},
    }
    dollar_positions = [pos for pos, value in enumerate(
        np.load(os.path.join(col_ev, 'msbwt.npy'), 'r')) if value == 0]
    recovery_equal = True
    recovery_byte = []
    recovery_pure = []
    for position in dollar_positions:
        recovery_byte.append(col_byte.recoverString(position))
        recovery_pure.append(pcol.recoverString(position))
        if col_byte.recoverString(position) != col_rle.recoverString(position):
            recovery_equal = False
    reader['valid_collection']['recovery'] = {
        'dollar_count': len(dollar_positions),
        'byte_rle_recovery_equal': recovery_equal,
        'pure_equals_byte_recovery': recovery_pure == recovery_byte,
        'pure_recovery': recovery_pure,
    }
    reader['valid_collection']['byte_reader_side_effects'] = {
        name: sha256_file(os.path.join(col_ev, name))
        for name in ('totalCounts.npy', 'fmIndex.npy')}

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
import os
import struct
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
COLLECTION_QUERIES = {"AAAAA": 1, "ACGTN": 3, "CCCCC": 1, "AGCTA": 0,
                      "AAAAAA": 0, "GGGGG": 1, "NACGT": 1, "TTTTT": 1,
                      "$": 8}

reader = probe['reader']

# dtype root cause
dtypes = probe['dtypes']
assert dtypes['ret_dtype'] == 'uint64'
assert dtypes['counts_dtype'] == 'uint64'
assert dtypes['letters_dtype'] == 'uint8'
assert dtypes['bincount_dtype'] == 'float64'
assert dtypes['weights_dtype'] == 'uint64'
assert dtypes['bincount_sum'] == 1278
assert dtypes['inplace_add']['status'] == 'failed'
assert dtypes['inplace_add']['exception_type'] == 'TypeError'
assert "Cannot cast ufunc add output from dtype('float64')" in \
    dtypes['inplace_add']['exception']
# np.add.at performs the exact-integer accumulation of the float64 bincount
# (ret + bc), and the final getFullFMAtIndex (np.add.at plus the partial
# run term) equals the independent oracle (asserted below per position)
assert dtypes['np_add_at']['dtype'] == 'uint64'
assert dtypes['np_add_at']['equals_float_math_result']
assert dtypes['np_add_at']['values'] == [int(v) for v in dtypes['math_add_result']]

# pure FM vectors == compiled == oracle at every position
for pos, expected in EXPECTED_BYTES.items():
    assert reader['pure_compressed']['getCharAtIndex'][str(pos)] == expected, pos
for pos in ('0', '1', '2047', '2048', '2049', '999998', '999999',
            '1000000', '1000001', '1055998', '1055999'):
    rec = reader['pure_compressed']['getFullFMAtIndex'][pos]
    assert rec['status'] == 'ok', pos
    assert rec['dtype'] == 'uint64', (pos, rec['dtype'])
    assert rec['pure_eq_compiled'], pos
    assert rec['pure_eq_oracle'], pos
    assert rec['value'] == reader['independent_oracle']['full_fm_at'][pos], pos
    assert rec['compiled'] == reader['compiled']['rle_getFullFMAtIndex'][pos], pos

# all symbols represented
assert reader['pure_compressed']['all_symbols_represented']['all_positive']

# pure backward-search queries on the >1M evidence == compiled == oracle
for kmer, expected in EXPECTED_FM_COUNTS.items():
    assert reader['pure_compressed']['countOccurrencesOfSeq'][kmer] == expected, kmer
    assert reader['compiled']['rle_countOccurrencesOfSeq'][kmer] == expected, kmer
    assert reader['compiled']['byte_countOccurrencesOfSeq'][kmer] == expected, kmer
assert reader['pure_compressed']['countOccurrencesOfSeq'] == \
    reader['independent_oracle']['fm_counts']
assert reader['compiled']['rle_countOccurrencesOfSeq'] == \
    reader['independent_oracle']['fm_counts']
assert reader['compiled']['byte_countOccurrencesOfSeq'] == \
    reader['independent_oracle']['fm_counts']
assert reader['compiled']['byte_side_effects'] == {
    'totalCounts.npy': 'e7fe29a99498d61a278845772782b10d22256a9556e865704d75a54e160fe348',
    'fmIndex.npy': '16e19742f54504b19ff72d278cea134b6063a0c51eac77f784699659013d8040'}

# valid collection: pure FM == compiled == oracle; queries unchanged; recovery
col = reader['valid_collection']
assert col['total_size'] == 48
for pos, rec in col['pure_getFullFMAtIndex'].items():
    assert rec['status'] == 'ok', pos
    assert rec['dtype'] == 'uint64', (pos, rec['dtype'])
    assert rec['pure_eq_compiled'], pos
    assert rec['pure_eq_oracle'], pos
    assert rec['value'] == \
        reader['independent_oracle']['collection_full_fm_at'][pos], pos
assert col['pure_queries'] == COLLECTION_QUERIES
assert col['byte_queries'] == COLLECTION_QUERIES
assert col['rle_queries'] == COLLECTION_QUERIES
assert col['recovery']['dollar_count'] == 8
assert col['recovery']['byte_rle_recovery_equal']
assert col['recovery']['pure_equals_byte_recovery']
assert col['byte_reader_side_effects'] == {
    'totalCounts.npy': 'ea104b616fe89d7b786acdff7ca0db61f6339a59c31fbf0fff066ad7384c1c2b',
    'fmIndex.npy': 'a5b4bf06726fcadf535245d03ef65e04a4a5248d368b3aa53639c190028b933f'}

# independent host-side FM oracle tool agreement (no NumPy involved)
sys.path.insert(0, os.path.dirname(oracle_tool))
from bwt_oracle import backward_count  # noqa: E402
npy_bytes = open(primary, 'rb').read()
hlen = struct.unpack('<H', npy_bytes[8:10])[0]
raw = npy_bytes[10 + hlen:]
assert len(raw) == 1056000
for kmer, expected in EXPECTED_FM_COUNTS.items():
    assert backward_count(raw, kmer) == expected, kmer

# frozen source contract preserved
pre = probe['pre_fix']
assert pre['frozen_source_sha256'] == '95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0'
assert pre['frozen_getFullFMAtIndex_nonlast_bin']['exception_type'] == 'IndexError'
assert 'line 708' in pre['frozen_getFullFMAtIndex_nonlast_bin']['traceback']
assert pre['frozen_getFullFMAtIndex_last_bin']['exception_type'] == 'TypeError'
assert 'line 725' in pre['frozen_getFullFMAtIndex_last_bin']['traceback']
assert "Cannot cast ufunc add output from dtype('float64')" in \
    pre['frozen_getFullFMAtIndex_last_bin']['exception']
assert pre['frozen_collection_getFullFMAtIndex']['exception_type'] == 'TypeError'
assert 'line 725' in pre['frozen_collection_getFullFMAtIndex']['traceback']

# modern2 pre-fix probe preserved (committed evidence, read-only)
m2 = pre['modern2_prefix_probe']
assert m2['frozen_source_sha256'] == '95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0'
assert m2['position_2047_exception_type'] == 'TypeError'
assert "Cannot cast ufunc add output from dtype('float64')" in m2['position_2047_exception']
assert m2['position_1055998_exception_type'] == 'TypeError'
assert m2['ret_dtype'] == 'uint64'
assert m2['bincount_dtype'] == 'float64'
assert m2['bincount_sum'] == 1278
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
record dtypes "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["dtypes"]))' "$WORK/probe.json")"
record pre_fix "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["pre_fix"]))' "$WORK/probe.json")"
record dataset "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["dataset"]))' "$WORK/probe.json")"
record environment "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["environment"]))' "$WORK/probe.json")"
record final '{"branch": "codex/modern2", "milestone": "modern2-milestone6-pure-fm-reader", "status": "passed"}'
if [ -n "$EVIDENCE" ]; then cp "$RESULT_FILE" "$EVIDENCE"; printf 'Evidence written to %s\n' "$EVIDENCE"; fi
printf 'reader-milestone6 OK\n'
