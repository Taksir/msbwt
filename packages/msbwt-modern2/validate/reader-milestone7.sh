#!/usr/bin/env bash
# msbwt-modern2 pure reader initialization / index construction milestone 7
# validation driver.
#
# Characterizes the two pure-Python first-load paths
#   CompressedMSBWT.constructTotalCounts
#   CompressedMSBWT.constructFMIndex
# on completely fresh inputs (all reader-derived caches removed) under
# CPython 2.7.18 / NumPy 1.16.6, and proves that the generated
#   totalCounts.p, comp_fmIndex.npy, comp_refIndex.npy
# are exact, deterministic, regenerable, and semantically correct.
#
# Executed verdict (see docs/modernization/MODERN2_MILESTONE7_READER_INIT.md):
#   - constructTotalCounts: SAFE.  `self.totalCounts += np.bincount(...)` on a
#     Python-list accumulator performs ELEMENTWISE numpy addition under
#     CPython 2.7 (the list is converted by ndarray's reflected add and the
#     name is rebound to a float64 ndarray) -- NOT list extension (the
#     Python-3 behavior).  The float64 values are exact integers for all
#     exercised inputs; the pickled totalCounts.p bytes are identical to the
#     committed frozen-reader evidence (compression-milestone1
#     source-after-manifest).
#   - constructFMIndex: SAFE.  float64 intermediates (countsSoFar, np.add,
#     np.bincount) are integral and are cast to '<u8' only at memmap setitem;
#     all 516 bins of the >1M evidence validate against an independent
#     per-bin FM oracle; the generated files match the committed frozen-reader
#     bytes for the 48-symbol and 30-symbol collections.  At bins whose
#     2048-boundary coincides exactly with a run boundary (171 of 516 bins on
#     the tiled evidence) the pure sampling records the run CONTAINING the
#     boundary while the compiled RLE_BWT records the run ENDING at it; both
#     conventions are oracle-correct at every probed position and the two
#     derived-file sets are fully interchangeable between the readers
#     (executed).
#   - No source change was required; the modern2-vs-frozen diff remains
#     exactly the documented five correction sites from milestones 3-6.
#
# Gates (all must pass):
#   1. environment: CPython 2.7, Cython 3.0.x, NumPy 1.16.6, pysam 0.15.4
#   2. optional in-tree build of the 8 migrated extensions (Cython 3.0.12)
#   3. all modern2 Python-2 tests green
#   4. evidence regenerated deterministically (np.tile 22000x) and
#      hash-matched to the committed m3c2/milestone-5 evidence
#   5. executed fresh-load probes on disposable copies of the committed
#      uniform-compress-posthoc, uniform-direct-split, nonuniform-compress-
#      posthoc, and the >1M RLE evidence:
#      a. constructTotalCounts runtime type trace (list -> ndarray float64,
#         weighted bincount float64, elementwise accumulation)
#      b. constructFMIndex runtime type trace (offsets/countsSoFar float64,
#         bincount float64, uint64 memmap storage)
#      c. exact symbol totals == independent decoded-RLE counts
#      d. generated file set exactly {totalCounts.p, comp_fmIndex.npy,
#         comp_refIndex.npy} with recorded dtypes/shapes/hashes
#      e. deterministic regeneration (two fresh copies identical) and
#         cache-deletion reload equality
#      f. 48/30-symbol derived files byte-identical to the committed frozen
#         evidence and to the compiled-reader files; >1M files equal to the
#         compiled files at every bin except the documented exact-boundary
#         convention bins, with semantic equality at every probed position
#      g. pure-vs-compiled reader semantics (char/FM/occurrence/queries/
#         recovery) equal on every case; independent oracle agreement
#      h. interchangeability: pure reader on compiled-created files and
#         compiled reader on pure-created files remain oracle-correct
#   6. frozen source digest (MUS/MultiStringBWT.py 95ac0b86...) untouched;
#      constructTotalCounts/constructFMIndex text identical in frozen and
#      modern2 sources (the milestone made no change there)
# If --evidence is given, a JSON record of every gate is written.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: validate/reader-milestone7.sh --prefix /absolute/prefix --package /absolute/package --repository /absolute/repo [--build] [--evidence /absolute/out.json]'
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
FROZEN_SHA256=95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0

# committed evidence dataset constants (shared with milestones 5/6)
EVIDENCE_PRIMARY_SHA256=24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35
RLE_PRIMARY_SHA256=681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99
TOTAL_SIZE=1056000

# committed golden artifact roots for the three single-bin collections
POSTHOC_DIR="$GOLDENS/uniform-compress-posthoc/$PROFILE/$ROUTE/artifacts"
DIRECTSPLIT_DIR="$GOLDENS/uniform-direct-split/$PROFILE/$ROUTE/artifacts"
NONUNI_DIR="$GOLDENS/nonuniform-compress-posthoc/$PROFILE/$ROUTE/artifacts"

# committed frozen pure-reader side-effect hashes (compression-milestone1
# decompression-failure source-after-manifest)
FROZEN_48_TOTALCOUNTS_P=c038b778aa21d53a42ba552e59cfe48d036ed7b8f4d6ce77d0ab55ede2638916
FROZEN_48_FM=f6565545114d769fbe6ba6010ce125c8690256f2d97562ceb65064b38d48c881
FROZEN_48_REF=30c0c0f336e69b86ee3da30f0f4ce1d9a138d503845c586e993ff31e8003fee1
FROZEN_30_FM=d3e57fa28f3b49910012d4fb2a51f48a22f62b112bc773d8fe825a5905c7be55

WORK=$(mktemp -d /tmp/modern2-milestone7-XXXXXX)
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
    printf 'build_evidence OK\n'
}

# ---------------------------------------------------------------------------
# executed fresh-load probes (disposable copies)
# ---------------------------------------------------------------------------

run_probe() {
    cat > "$WORK/probe.py" <<'PY'
from __future__ import print_function
import hashlib
import json
import os
import pickle
import shutil
import sys

REPO = sys.argv[1]
WORK = sys.argv[2]
PACKAGE = os.path.join(REPO, 'packages', 'msbwt-modern2')
sys.path.insert(0, PACKAGE)
sys.path.insert(0, os.path.join(PACKAGE, 'MUS'))

GOLDENS = os.path.join(REPO, 'compat', 'goldens', 'original-0.3.0')
PROFILE = 'py27-late-05a7d6d83862'
ROUTE = 'pyx-historical-cython'
BYTE_GOLDEN = os.path.join(GOLDENS, 'uniform-multifile', PROFILE, ROUTE,
                           'build', 'artifacts', 'msbwt.npy')
POSTHOC_DIR = os.path.join(GOLDENS, 'uniform-compress-posthoc', PROFILE,
                           ROUTE, 'artifacts')
DIRECTSPLIT_DIR = os.path.join(GOLDENS, 'uniform-direct-split', PROFILE,
                               ROUTE, 'artifacts')
NONUNI_DIR = os.path.join(GOLDENS, 'nonuniform-compress-posthoc', PROFILE,
                          ROUTE, 'artifacts')

TOTAL_SIZE = 1056000
POSITIONS = [0, 1, 2047, 2048, 2049, 999998, 999999, 1000000, 1000001,
             1055998, 1055999]
COLLECTION_POSITIONS = [0, 1, 2, 5, 10, 20, 40, 47]
BIG_KMERS = ['A', 'AC', 'ACGTN', 'AAAAA', 'AAAAAA', 'C', 'CG', 'GT',
             'GTGGGTTT', 'N', 'NACGT', 'T', 'TTTTT']
COLLECTION_KMERS = ['AAAAA', 'ACGTN', 'CCCCC', 'AGCTA', 'AAAAAA', 'GGGGG',
                    'NACGT', 'TTTTT', '$']
NONUNI_KMERS = ['A', 'AAAAAAAA', 'AC', 'ACG', 'ACGT', 'ACGTN', 'C', 'CG',
                'CGT', 'CGTN', 'G', 'GT', 'GTN', 'N', 'T', 'TN', 'TT',
                'TTT', 'TTTT', 'TTTTT', 'TTTTTT', 'TTTTTTT']

report = {'dataset': {}, 'constructTotalCounts': {}, 'constructFMIndex': {},
          'derived': {}, 'independent': {}, 'reader': {},
          'interchangeability': {}, 'historical': {}}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def fresh_copy(src, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


def derive_names():
    return ('totalCounts.p', 'comp_fmIndex.npy', 'comp_refIndex.npy')


def remove_derived(directory):
    for name in derive_names():
        path = os.path.join(directory, name)
        if os.path.exists(path):
            os.remove(path)


def after_load_file_set(directory, baseline):
    return sorted(name for name in os.listdir(directory)
                  if os.path.isfile(os.path.join(directory, name))
                  and name not in baseline)


def derived_hashes(directory):
    return {name: sha256_file(os.path.join(directory, name))
            for name in derive_names()}


def decode_rle_counts(path):
    """Independent base-32 RLE decoder (no reader code)."""
    with open(path, 'rb') as handle:
        raw = handle.read()
    assert raw[0:6] == b'\x93NUMPY'
    header_len = ord(raw[8]) | (ord(raw[9]) << 8)
    payload = raw[10 + header_len:]

    def run_length(digits):
        total = 0
        for digit in digits:
            total = total * 32 + digit
        return total

    counts = [0] * 6
    symbols = []
    prev_sym = -1
    digits = []
    for byte in payload:
        sym = ord(byte) & 7
        digit = ord(byte) >> 3
        if sym != prev_sym:
            if digits:
                counts[prev_sym] += run_length(digits)
                symbols.extend([prev_sym] * run_length(digits))
            digits = []
            prev_sym = sym
        digits.append(digit)
    if digits:
        counts[prev_sym] += run_length(digits)
        symbols.extend([prev_sym] * run_length(digits))
    return counts, symbols


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

    from MUS.MultiStringBWT import CompressedMSBWT
    from MUSCython import MultiStringBWTCython as CompiledBWT

    expected = np.load(BYTE_GOLDEN, 'r')
    tiled = np.tile(expected, 22000)
    assert tiled.shape == (TOTAL_SIZE,)
    expected_payload = tiled.tostring()
    col_payload = expected.tostring()
    rle_dir = os.path.join(WORK, 'rle')

    report['dataset'] = {
        'evidence_primary_sha256': sha256_file(
            os.path.join(WORK, 'evidence', 'msbwt.npy')),
        'rle_primary_sha256': sha256_file(
            os.path.join(rle_dir, 'comp_msbwt.npy')),
        'total_size': TOTAL_SIZE,
    }

    # independent decoded-RLE symbol totals for every case
    dec = {}
    decoded_symbols = {}
    for case, directory in (('posthoc48', POSTHOC_DIR),
                            ('direct48', DIRECTSPLIT_DIR),
                            ('nonuni30', NONUNI_DIR)):
        dec[case], decoded_symbols[case] = decode_rle_counts(
            os.path.join(directory, 'comp_msbwt.npy'))
    dec['big'], decoded_symbols['big'] = decode_rle_counts(
        os.path.join(rle_dir, 'comp_msbwt.npy'))
    report['independent']['decoded_counts'] = dec
    report['independent']['decoded_counts_total'] = {
        case: sum(values) for case, values in dec.items()}
    report['independent']['decoded_symbol_counts'] = {
        case: len(symbols) for case, symbols in decoded_symbols.items()}

    # per-case fresh-load probes
    cases = (('posthoc48', POSTHOC_DIR, 48, COLLECTION_KMERS,
              COLLECTION_POSITIONS, True, True),
             ('direct48', DIRECTSPLIT_DIR, 48, COLLECTION_KMERS,
              COLLECTION_POSITIONS, True, True),
             ('nonuni30', NONUNI_DIR, 30, NONUNI_KMERS,
              [0, 1, 2, 5, 10, 20, 29], True, True),
             ('big', rle_dir, TOTAL_SIZE, BIG_KMERS, POSITIONS,
              False, False))
    for case, src, total_size, kmers, positions, is_collection, \
            do_committed in cases:
        case_dir = os.path.join(WORK, 'case-' + case)
        fresh_copy(src, case_dir)
        remove_derived(case_dir)
        baseline = set(os.listdir(case_dir))

        reader = CompressedMSBWT()
        reader.loadMsbwt(case_dir, logger=None)

        created = after_load_file_set(case_dir, baseline)
        hashes = derived_hashes(case_dir)
        tc = pickle.load(open(os.path.join(case_dir, 'totalCounts.p'), 'rb'))
        entry = {
            'created_files': created,
            'hashes': hashes,
            'totalCounts_p': {
                'type': type(tc).__name__,
                'dtype': str(tc.dtype),
                'len': int(len(tc)),
                'values': [float(v) for v in tc],
                'sum': float(np.sum(tc)),
            },
            'fm': {
                'dtype': str(reader.partialFM.dtype),
                'shape': [int(s) for s in reader.partialFM.shape],
                'row0': [int(v) for v in reader.partialFM[0]],
            },
            'ref': {
                'dtype': str(reader.refFM.dtype),
                'shape': [int(s) for s in reader.refFM.shape],
                'row0': int(reader.refFM[0]),
            },
            'totalSize': int(reader.getTotalSize()),
            'exact_integer_counts': all(float(v).is_integer() for v in tc),
        }

        # determinism: second fresh copy
        case_dir2 = os.path.join(WORK, 'case-' + case + '-b')
        fresh_copy(src, case_dir2)
        remove_derived(case_dir2)
        reader2 = CompressedMSBWT()
        reader2.loadMsbwt(case_dir2, logger=None)
        entry['determinism'] = {
            'hashes_equal': derived_hashes(case_dir2) == hashes}

        # regeneration: delete caches on case_dir and reload
        remove_derived(case_dir)
        reader3 = CompressedMSBWT()
        reader3.loadMsbwt(case_dir, logger=None)
        entry['regeneration'] = {
            'hashes_equal': derived_hashes(case_dir) == hashes}

        # compiled reader on a fresh copy: compare derived files and semantics
        cdir = os.path.join(WORK, 'case-' + case + '-compiled')
        fresh_copy(src, cdir)
        creader = CompiledBWT.loadBWT(cdir, useMemmap=False, logger=None)
        entry['compiled'] = {
            'derived_hashes': {name: sha256_file(os.path.join(cdir, name))
                               for name in
                               ('comp_fmIndex.npy', 'comp_refIndex.npy')},
            'fm_bytes_equal': sha256_file(
                os.path.join(cdir, 'comp_fmIndex.npy')) ==
                hashes['comp_fmIndex.npy'],
            'ref_bytes_equal': sha256_file(
                os.path.join(cdir, 'comp_refIndex.npy')) ==
                hashes['comp_refIndex.npy'],
        }

        # reader semantics: char / FM / occurrence / queries / recovery
        sem = {'getCharAtIndex': {}, 'getFullFMAtIndex': {},
               'getOccurrenceOfCharAtIndex': {}, 'queries': {}}
        for p in positions:
            sem['getCharAtIndex'][str(p)] = int(reader.getCharAtIndex(p))
            sem['getFullFMAtIndex'][str(p)] = [int(v) for v in
                                               reader.getFullFMAtIndex(p)]
            sem['getOccurrenceOfCharAtIndex'][str(p)] = int(
                reader.getOccurrenceOfCharAtIndex(0, p))
            sem['getCharAtIndex']['compiled_' + str(p)] = int(
                creader.getCharAtIndex(p))
            sem['getFullFMAtIndex']['compiled_' + str(p)] = [int(v) for v in
                creader.getFullFMAtIndex(p)]
        for k in kmers:
            sem['queries'][k] = int(reader.countOccurrencesOfSeq(k))
            sem['queries']['compiled_' + k] = int(
                creader.countOccurrencesOfSeq(k))
        if is_collection:
            dollar_positions = [pos for pos, value in
                                enumerate(decoded_symbols[case])
                                if value == 0]
            sem['recovery'] = [reader.recoverString(pos)
                               for pos in dollar_positions]
            sem['recovery_compiled'] = [creader.recoverString(pos)
                                        for pos in dollar_positions]
            sem['dollar_count'] = len(dollar_positions)
        report['reader'][case] = sem
        report['derived'][case] = entry

        if do_committed:
            expected = {
                'posthoc48': {
                    'totalCounts.p': 'c038b778aa21d53a42ba552e59cfe48d036ed7b8f4d6ce77d0ab55ede2638916',
                    'comp_fmIndex.npy': 'f6565545114d769fbe6ba6010ce125c8690256f2d97562ceb65064b38d48c881',
                    'comp_refIndex.npy': '30c0c0f336e69b86ee3da30f0f4ce1d9a138d503845c586e993ff31e8003fee1',
                },
                'direct48': {
                    'totalCounts.p': 'c038b778aa21d53a42ba552e59cfe48d036ed7b8f4d6ce77d0ab55ede2638916',
                    'comp_fmIndex.npy': 'f6565545114d769fbe6ba6010ce125c8690256f2d97562ceb65064b38d48c881',
                    'comp_refIndex.npy': '30c0c0f336e69b86ee3da30f0f4ce1d9a138d503845c586e993ff31e8003fee1',
                },
                'nonuni30': {
                    'comp_fmIndex.npy': 'd3e57fa28f3b49910012d4fb2a51f48a22f62b112bc773d8fe825a5905c7be55',
                    'comp_refIndex.npy': '30c0c0f336e69b86ee3da30f0f4ce1d9a138d503845c586e993ff31e8003fee1',
                },
            }[case]
            entry['matches_committed_frozen'] = all(
                hashes[name] == digest for name, digest in expected.items())
            entry['committed_expected'] = expected

    # ------------------------------------------------------------------
    # constructTotalCounts runtime type trace (48-symbol collection)
    # ------------------------------------------------------------------
    trace_dir = os.path.join(WORK, 'trace')
    fresh_copy(POSTHOC_DIR, trace_dir)
    remove_derived(trace_dir)
    tr = CompressedMSBWT()
    tr.bwt = np.load(os.path.join(trace_dir, 'comp_msbwt.npy'), 'r')
    tr.dirName = trace_dir
    tr.vcLen = 6
    tr.letterBits = 3
    tr.numberBits = 8 - tr.letterBits
    tr.numPower = 2 ** tr.numberBits
    tr.mask = 255 >> tr.numberBits
    tr.totalCounts = [0] * tr.vcLen
    trace = {'initial_type': type(tr.totalCounts).__name__,
             'initial_len': len(tr.totalCounts)}
    binSize = 2 ** 15
    end = 0
    chunk_index = 0
    while end < tr.bwt.shape[0]:
        start = end
        end = end + binSize
        if end > tr.bwt.shape[0]:
            end = tr.bwt.shape[0]
        while end < tr.bwt.shape[0] and (
                (tr.bwt[end] & tr.mask) == (tr.bwt[end - 1] & tr.mask)):
            end += 1
        letters = np.bitwise_and(tr.bwt[start:end], tr.mask)
        counts = np.right_shift(tr.bwt[start:end], tr.letterBits, dtype='<u8')
        powers = np.zeros(dtype='<u8', shape=(end - start,))
        i = 1
        same = (letters[0:-1] == letters[1:])
        while np.sum(same) > 0:
            (powers[i:])[same] += 1
            i += 1
            same = np.bitwise_and(same[0:-1], same[1:])
        before_type = type(tr.totalCounts).__name__
        bc = np.bincount(letters, np.multiply(counts, tr.numPower ** powers),
                         minlength=tr.vcLen)
        tr.totalCounts += bc
        trace['chunk_%d' % chunk_index] = {
            'before_type': before_type,
            'bincount_dtype': str(bc.dtype),
            'after_type': type(tr.totalCounts).__name__,
            'after_len': int(len(tr.totalCounts)),
            'after_dtype': str(tr.totalCounts.dtype)}
        chunk_index += 1
    trace['final_type'] = type(tr.totalCounts).__name__
    trace['final_dtype'] = str(tr.totalCounts.dtype)
    trace['final_values'] = [float(v) for v in tr.totalCounts]
    report['constructTotalCounts'] = trace

    # ------------------------------------------------------------------
    # constructFMIndex runtime type trace (48-symbol collection)
    # ------------------------------------------------------------------
    fm_dir = os.path.join(WORK, 'fmtrace')
    fresh_copy(POSTHOC_DIR, fm_dir)
    remove_derived(fm_dir)
    fr = CompressedMSBWT()
    fr.loadMsbwt(fm_dir, logger=None)
    counts_so_far = np.cumsum(fr.totalCounts) - fr.totalCounts
    report['constructFMIndex'] = {
        'totalCounts_type': type(fr.totalCounts).__name__,
        'countsSoFar_dtype': str(counts_so_far.dtype),
        'countsSoFar_values': [float(v) for v in counts_so_far],
        'partialFM_dtype': str(fr.partialFM.dtype),
        'refFM_dtype': str(fr.refFM.dtype),
        'offsetSum': int(fr.offsetSum),
    }

    # ------------------------------------------------------------------
    # interchangeability on the >1M evidence
    # ------------------------------------------------------------------
    big_dir = os.path.join(WORK, 'case-big')
    cbig_dir = os.path.join(WORK, 'case-big-compiled')
    pure_on_compiled = CompressedMSBWT()
    pure_on_compiled.loadMsbwt(cbig_dir, logger=None)
    comp_on_pure = CompiledBWT.loadBWT(big_dir, useMemmap=False,
                                       logger=None)
    inter = {'pure_on_compiled': {}, 'compiled_on_pure': {}}
    for p in (0, 2048, 6144, 1000000, 1055998):
        a = [int(v) for v in pure_on_compiled.getFullFMAtIndex(p)]
        b = [int(v) for v in comp_on_pure.getFullFMAtIndex(p)]
        inter['pure_on_compiled'][str(p)] = a
        inter['compiled_on_pure'][str(p)] = b
    for k in ('A', 'AC', 'ACGTN', 'AAAAAA'):
        inter['pure_on_compiled'][k] = int(
            pure_on_compiled.countOccurrencesOfSeq(k))
        inter['compiled_on_pure'][k] = int(
            comp_on_pure.countOccurrencesOfSeq(k))
    inter['pure_on_compiled']['getCharAtIndex_6144'] = int(
        pure_on_compiled.getCharAtIndex(6144))
    inter['compiled_on_pure']['getCharAtIndex_6144'] = int(
        comp_on_pure.getCharAtIndex(6144))
    report['interchangeability'] = inter

    # full per-bin validation of the pure >1M FM files (all 516 bins)
    start_index = [0, 176000, 374000, 572000, 770000, 858000]
    payload_arr = np.frombuffer(expected_payload, dtype=np.uint8)
    pure_big = CompressedMSBWT()
    pure_big.loadMsbwt(big_dir, logger=None)
    bins_ok = 0
    bad_bins = []
    for b in range(pure_big.partialFM.shape[0]):
        pos = b * 2048
        counts = np.bincount(payload_arr[0:pos].astype(np.int64),
                             minlength=6)
        oracle = [start_index[s] + int(counts[s]) for s in range(6)]
        got = [int(v) for v in pure_big.getFullFMAtIndex(pos)]
        if got == oracle:
            bins_ok += 1
        else:
            bad_bins.append((b, got, oracle))
    report['independent']['all_bins'] = {
        'bins_total': int(pure_big.partialFM.shape[0]),
        'bins_ok': bins_ok,
        'bad_bins': bad_bins[:3],
        'bad_count': len(bad_bins),
    }
    # pure-vs-compiled file difference classification (documented convention)
    cpm = np.load(os.path.join(cbig_dir, 'comp_fmIndex.npy'), 'r')
    crf = np.load(os.path.join(cbig_dir, 'comp_refIndex.npy'), 'r')
    pfm = np.load(os.path.join(big_dir, 'comp_fmIndex.npy'), 'r')
    prf = np.load(os.path.join(big_dir, 'comp_refIndex.npy'), 'r')
    diff_bins = [int(b) for b in range(prf.shape[0])
                 if int(prf[b]) != int(crf[b])]
    report['independent']['pure_vs_compiled_bins'] = {
        'differing_bin_count': len(diff_bins),
        'first_differing_bins': diff_bins[:10],
        'all_differing_bins_are_tile_boundaries': all(
            b % 3 == 0 for b in diff_bins),
        'pure_ref_eq_compiled_ref_minus_1': all(
            int(prf[b]) == int(crf[b]) + 1 for b in diff_bins),
        'pure_fm_row0_equal': bool(np.array_equal(pfm[0], cpm[0])),
        'pure_fm_lastrow_equal': bool(np.array_equal(pfm[-1], cpm[-1])),
    }

    # ------------------------------------------------------------------
    # historical classification
    # ------------------------------------------------------------------
    frozen_path = os.path.join(REPO, 'MUS', 'MultiStringBWT.py')
    modern2_path = os.path.join(PACKAGE, 'MUS', 'MultiStringBWT.py')
    frozen_src = open(frozen_path, 'rb').read()
    modern2_src = open(modern2_path, 'rb').read()
    report['historical'] = {
        'frozen_sha256': sha256_file(frozen_path),
        'modern2_sha256': sha256_file(modern2_path),
    }
    import re
    frozen_text = frozen_src.decode().replace('\r\n', '\n')
    modern2_text = modern2_src.decode().replace('\r\n', '\n')
    for name in ('constructTotalCounts', 'constructFMIndex'):
        f = re.search(r'(    def %s\(self, logger\):.*?\n        ' % name +
                      r'.*?)(?=\n    def |\nclass |\ndef )', frozen_text, re.S)
        m = re.search(r'(    def %s\(self, logger\):.*?\n        ' % name +
                      r'.*?)(?=\n    def |\nclass |\ndef )', modern2_text, re.S)
        report['historical']['init_%s_identical' % name] = bool(
            f and m and f.group(1) == m.group(1))

    with open(os.path.join(WORK, 'probe.json'), 'w') as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    print('PROBE DONE')


if __name__ == '__main__':
    main()
PY
    "$PREFIX/bin/python" -B "$WORK/probe.py" "$REPOSITORY" "$WORK"
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

# committed constants
FROZEN_48 = {
    'totalCounts.p': 'c038b778aa21d53a42ba552e59cfe48d036ed7b8f4d6ce77d0ab55ede2638916',
    'comp_fmIndex.npy': 'f6565545114d769fbe6ba6010ce125c8690256f2d97562ceb65064b38d48c881',
    'comp_refIndex.npy': '30c0c0f336e69b86ee3da30f0f4ce1d9a138d503845c586e993ff31e8003fee1',
}
FROZEN_30_FM = 'd3e57fa28f3b49910012d4fb2a51f48a22f62b112bc773d8fe825a5905c7be55'
FROZEN_30_REF = '30c0c0f336e69b86ee3da30f0f4ce1d9a138d503845c586e993ff31e8003fee1'
DECODED = {
    'posthoc48': [8, 9, 9, 9, 4, 9],
    'direct48': [8, 9, 9, 9, 4, 9],
    'nonuni30': [7, 5, 4, 3, 2, 9],
    'big': [176000, 198000, 198000, 198000, 88000, 198000],
}
COLLECTION_QUERIES = {'AAAAA': 1, 'ACGTN': 3, 'CCCCC': 1, 'AGCTA': 0,
                      'AAAAAA': 0, 'GGGGG': 1, 'NACGT': 1, 'TTTTT': 1,
                      '$': 8}
BIG_QUERIES = {"A": 198000, "AC": 37125, "ACGTN": 111, "AAAAA": 243,
               "AAAAAA": 45, "C": 198000, "CG": 37125, "GT": 37125,
               "GTGGGTTT": 2, "N": 88000, "NACGT": 108, "T": 198000,
               "TTTTT": 249}
BIG_BYTES = {0: 1, 1: 4, 2047: 2, 2048: 2, 2049: 2, 999998: 0, 999999: 0,
             1000000: 0, 1000001: 2, 1055998: 5, 1055999: 0}

# independent decoded-RLE counts
for case, expected in DECODED.items():
    assert probe['independent']['decoded_counts'][case] == expected, case
    assert probe['independent']['decoded_counts_total'][case] == \
        sum(expected), case

# constructTotalCounts runtime semantics
tc = probe['constructTotalCounts']
assert tc['initial_type'] == 'list' and tc['initial_len'] == 6
assert tc['chunk_0']['before_type'] == 'list'
assert tc['chunk_0']['bincount_dtype'] == 'float64'
assert tc['chunk_0']['after_type'] == 'ndarray'
assert tc['chunk_0']['after_len'] == 6
assert tc['final_type'] == 'ndarray'
assert tc['final_dtype'] == 'float64'
assert tc['final_values'] == [8.0, 9.0, 9.0, 9.0, 4.0, 9.0]

# constructFMIndex runtime semantics
fm = probe['constructFMIndex']
assert fm['totalCounts_type'] == 'ndarray'
assert fm['countsSoFar_dtype'] == 'float64'
assert fm['countsSoFar_values'] == [0.0, 8.0, 17.0, 26.0, 35.0, 39.0]
assert fm['partialFM_dtype'] == 'uint64'
assert fm['refFM_dtype'] == 'uint64'

# per-case derived files: set, dtypes, hashes, determinism, regeneration
for case in ('posthoc48', 'direct48', 'nonuni30', 'big'):
    entry = probe['derived'][case]
    assert entry['created_files'] == ['comp_fmIndex.npy',
                                      'comp_refIndex.npy',
                                      'totalCounts.p'], case
    assert entry['fm']['dtype'] == 'uint64', case
    assert entry['ref']['dtype'] == 'uint64', case
    assert entry['totalCounts_p']['type'] == 'ndarray', case
    assert entry['totalCounts_p']['dtype'] == 'float64', case
    assert entry['totalCounts_p']['len'] == 6, case
    assert entry['exact_integer_counts'], case
    assert entry['determinism']['hashes_equal'], case
    assert entry['regeneration']['hashes_equal'], case
    if case == 'big':
        assert entry['totalSize'] == 1056000
    else:
        assert entry['totalSize'] in (48, 30), case

# committed frozen evidence byte equality (single-bin collections)
for case, expected in (('posthoc48', FROZEN_48), ('direct48', FROZEN_48)):
    entry = probe['derived'][case]
    assert entry['matches_committed_frozen'], case
    for name, digest in expected.items():
        assert entry['hashes'][name] == digest, (case, name)
entry = probe['derived']['nonuni30']
assert entry['hashes']['comp_fmIndex.npy'] == FROZEN_30_FM
assert entry['hashes']['comp_refIndex.npy'] == FROZEN_30_REF

# pure == compiled derived files on the single-bin collections
for case in ('posthoc48', 'direct48', 'nonuni30'):
    entry = probe['derived'][case]
    assert entry['compiled']['fm_bytes_equal'], case
    assert entry['compiled']['ref_bytes_equal'], case

# exact symbol totals
for case in ('posthoc48', 'direct48', 'nonuni30', 'big'):
    entry = probe['derived'][case]
    assert [float(v) for v in entry['totalCounts_p']['values']] == \
        [float(v) for v in DECODED[case]], case

# reader semantics: pure == compiled == committed constants
sem = probe['reader']
# recovery orientation matches the executed milestone-6 evidence
# (recoverString returns the read with the trailing '$')
COLLECTION_RECOVERY = {
    'posthoc48': ['AAAAA$', 'ACGTN$', 'ACGTN$', 'ACGTN$', 'CCCCC$',
                  'GGGGG$', 'NACGT$', 'TTTTT$'],
    'direct48': ['AAAAA$', 'ACGTN$', 'ACGTN$', 'ACGTN$', 'CCCCC$',
                 'GGGGG$', 'NACGT$', 'TTTTT$'],
    'nonuni30': ['A$', 'AC$', 'ACG$', 'ACGT$', 'ACGTN$', 'N$', 'TTTTTTT$'],
}
for case in ('posthoc48', 'direct48'):
    s = sem[case]
    for k, v in COLLECTION_QUERIES.items():
        assert s['queries'][k] == v, (case, k)
        assert s['queries']['compiled_' + k] == v, (case, k)
    assert s['dollar_count'] == 8, case
    assert s['recovery'] == s['recovery_compiled'], case
    assert s['recovery'] == COLLECTION_RECOVERY[case], case
    for p in ('0', '1', '2', '5', '10', '20', '40', '47'):
        assert s['getFullFMAtIndex'][p] == \
            s['getFullFMAtIndex']['compiled_' + p], (case, p)
        assert s['getCharAtIndex'][p] == \
            s['getCharAtIndex']['compiled_' + p], (case, p)
s = sem['nonuni30']
NONUNI_QUERIES = {"A": 5, "AAAAAAAA": 0, "AC": 4, "ACG": 3, "ACGT": 2,
                  "ACGTN": 1, "C": 4, "CG": 3, "CGT": 2, "CGTN": 1,
                  "G": 3, "GT": 2, "GTN": 1, "N": 2, "T": 9, "TN": 1,
                  "TT": 6, "TTT": 5, "TTTT": 4, "TTTTT": 3, "TTTTTT": 2,
                  "TTTTTTT": 1}
for k, v in NONUNI_QUERIES.items():
    assert s['queries'][k] == v, k
    assert s['queries']['compiled_' + k] == v, k
assert s['dollar_count'] == 7
assert s['recovery'] == s['recovery_compiled']
assert s['recovery'] == COLLECTION_RECOVERY['nonuni30']
s = sem['big']
for p, b in BIG_BYTES.items():
    assert s['getCharAtIndex'][str(p)] == b, p
    assert s['getCharAtIndex']['compiled_' + str(p)] == b, p
    assert s['getCharAtIndex'][str(p)] == \
        s['getCharAtIndex']['compiled_' + str(p)], p
    assert s['getFullFMAtIndex'][str(p)] == \
        s['getFullFMAtIndex']['compiled_' + str(p)], p
for k, v in BIG_QUERIES.items():
    assert s['queries'][k] == v, k
    assert s['queries']['compiled_' + k] == v, k

# all 516 bins of the pure >1M FM files == independent per-bin oracle
bins = probe['independent']['all_bins']
assert bins['bins_total'] == 516
assert bins['bins_ok'] == 516
assert bins['bad_count'] == 0

# pure-vs-compiled >1M file difference classification (documented convention)
d = probe['independent']['pure_vs_compiled_bins']
assert d['differing_bin_count'] == 171
assert d['all_differing_bins_are_tile_boundaries']
assert d['pure_ref_eq_compiled_ref_minus_1']
assert d['pure_fm_row0_equal'] and d['pure_fm_lastrow_equal']

# interchangeability: pure reader on compiled files, compiled on pure files
inter = probe['interchangeability']
for p in ('0', '2048', '6144', '1000000', '1055998'):
    assert inter['pure_on_compiled'][p] == \
        inter['compiled_on_pure'][p], p
# exact oracle FM vectors at the documented convention-difference bins
# (1055998 value matches the committed milestone-6 evidence)
assert inter['pure_on_compiled']['6144'] == \
    [1024, 177152, 375152, 573152, 770512, 859152]
assert inter['pure_on_compiled']['1055998'] == \
    [175999, 374000, 572000, 770000, 858000, 1055999]
for k, v in (('A', 198000), ('AC', 37125), ('ACGTN', 111), ('AAAAAA', 45)):
    assert inter['pure_on_compiled'][k] == v, k
    assert inter['compiled_on_pure'][k] == v, k
assert inter['pure_on_compiled']['getCharAtIndex_6144'] == 1
assert inter['compiled_on_pure']['getCharAtIndex_6144'] == 1

# independent host-side FM oracle tool agreement (no NumPy involved)
sys.path.insert(0, os.path.dirname(oracle_tool))
from bwt_oracle import backward_count  # noqa: E402
npy_bytes = open(primary, 'rb').read()
hlen = struct.unpack('<H', npy_bytes[8:10])[0]
raw = npy_bytes[10 + hlen:]
assert len(raw) == 1056000
for kmer, expected in BIG_QUERIES.items():
    assert backward_count(raw, kmer) == expected, kmer

# historical classification: frozen source untouched; init paths identical
hist = probe['historical']
assert hist['frozen_sha256'] == '95ac0b8659aa9148ef82a844bb750f1b2f07e82e4a647f5e3c3244050de7b1b0'
assert hist['modern2_sha256'] != hist['frozen_sha256']
assert hist['init_constructTotalCounts_identical']
assert hist['init_constructFMIndex_identical']
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
record constructTotalCounts "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["constructTotalCounts"]))' "$WORK/probe.json")"
record constructFMIndex "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["constructFMIndex"]))' "$WORK/probe.json")"
record derived "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["derived"]))' "$WORK/probe.json")"
record independent "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["independent"]))' "$WORK/probe.json")"
record reader "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["reader"]))' "$WORK/probe.json")"
record interchangeability "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["interchangeability"]))' "$WORK/probe.json")"
record historical "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["historical"]))' "$WORK/probe.json")"
record dataset "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["dataset"]))' "$WORK/probe.json")"
record environment "$(python3 -c 'import json, sys; print(json.dumps(json.load(open(sys.argv[1]))["environment"]))' "$WORK/probe.json")"
record final '{"branch": "codex/modern2", "milestone": "modern2-milestone7-reader-init", "status": "passed"}'
if [ -n "$EVIDENCE" ]; then cp "$RESULT_FILE" "$EVIDENCE"; printf 'Evidence written to %s\n' "$EVIDENCE"; fi
printf 'reader-milestone7 OK\n'
