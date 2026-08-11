#!/usr/bin/env bash
# Provision disposable WSL execution trees for the modern2 quality audit Q1.
#
# Creates two hash-verified execution trees on Linux-native storage:
#
#   1. FROZEN  -- a fresh disposable copy of the frozen 40-file projection
#      (repo root MUS/ MUSCython/ bin/ setup.py ...), hash-verified against
#      reference/original-0.3.0/environment/frozen-source.sha256, then built
#      through the committed pyx-historical-cython route: every frozen .pyx is
#      force-cythonized with the ORACLE profile's pinned Cython 0.29.36 and
#      `setup.py build_ext --inplace` is run with the oracle CPython 2.7.18.
#
#   2. MODERN2 -- a byte-identical copy of packages/msbwt-modern2 including
#      its previously built in-tree .so extensions (Cython 3.0.12,
#      language_level=2); every copied .so is hash-verified against the
#      source tree.  If any .so is missing or mismatched, the extensions are
#      rebuilt with the modern2 environment.
#
# Nothing is copied into the repository; the repository tree is only read.
# The frozen source projection is never modified.
#
# Usage:
#   provision.sh --repo /mnt/.../msbwt --work /home/.../msbwt-audit-q1 \
#       --oracle-python /abs/python2.7-oracle \
#       --modern2-python /abs/python2.7-modern2
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: provision.sh --repo /mnt/.../msbwt --work /home/.../msbwt-audit-q1 --oracle-python /abs --modern2-python /abs'
}

REPO=''
WORK=''
ORACLE_PYTHON=''
MODERN2_PYTHON=''
while [ "$#" -gt 0 ]; do
    case "$1" in
        --repo) REPO=${2:?--repo requires a value}; shift 2 ;;
        --work) WORK=${2:?--work requires a value}; shift 2 ;;
        --oracle-python) ORACLE_PYTHON=${2:?--oracle-python requires a value}; shift 2 ;;
        --modern2-python) MODERN2_PYTHON=${2:?--modern2-python requires a value}; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 64 ;;
    esac
done
for required in REPO WORK ORACLE_PYTHON MODERN2_PYTHON; do
    [ -n "${!required}" ] || { printf 'Missing --%s\n' "$(printf '%s' "$required" | tr '[:upper:]' '[:lower:]')" >&2; usage >&2; exit 64; }
done
for path in "$REPO" "$WORK"; do case "$path" in /*) ;; *) printf 'Paths must be absolute Linux paths.\n' >&2; exit 64;; esac; done
[ -d "$REPO" ] || { printf 'Repository not found: %s\n' "$REPO" >&2; exit 66; }
[ -x "$ORACLE_PYTHON" ] || { printf 'Oracle python not executable: %s\n' "$ORACLE_PYTHON" >&2; exit 66; }
[ -x "$MODERN2_PYTHON" ] || { printf 'Modern2 python not executable: %s\n' "$MODERN2_PYTHON" >&2; exit 66; }
for tool in python3 sha256sum cp; do command -v "$tool" >/dev/null 2>&1 || { printf 'Missing tool: %s\n' "$tool" >&2; exit 69; }; done

export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export TZ=UTC
export PYTHONHASHSEED=0
export PYTHONNOUSERSITE=1

# Activate a prefix's conda compiler toolchain in a sanitized environment
# (mirrors the committed run-wsl-probe.sh activation block).
activate_toolchain() {
    local prefix=$1
    unset AR AS CC CXX CFLAGS CPPFLAGS CXXFLAGS LD LDFLAGS
    unset CONDA_BUILD_SYSROOT _CONDA_PYTHON_SYSCONFIGDATA_NAME
    export CONDA_PREFIX="$prefix"
    export PATH="$prefix/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    local activated=0
    set +u
    for activation_name in activate-binutils_linux-64.sh activate-gcc_linux-64.sh activate-gxx_linux-64.sh; do
        local activation_path="$prefix/etc/conda/activate.d/$activation_name"
        if [ -f "$activation_path" ]; then
            # shellcheck source=/dev/null
            . "$activation_path"
            activated=1
        fi
    done
    set -u
    if [ -z "${CC:-}" ]; then
        local wrapper
        for wrapper in "$prefix"/bin/*-gcc; do
            if [ -x "$wrapper" ]; then CC="$wrapper"; export CC; activated=1; break; fi
        done
    fi
    [ "$activated" -eq 1 ] || { printf 'No compiler toolchain in prefix: %s\n' "$prefix" >&2; exit 69; }
}

FROZEN_MANIFEST="$REPO/reference/original-0.3.0/environment/frozen-source.sha256"
[ -f "$FROZEN_MANIFEST" ] || { printf 'Frozen manifest missing: %s\n' "$FROZEN_MANIFEST" >&2; exit 66; }

mkdir -p "$WORK"
FROZEN="$WORK/frozen"
MODERN2="$WORK/modern2"
mkdir -p "$FROZEN" "$MODERN2"

sha256_file() { sha256sum "$1" | awk '{print $1}'; }

# ---------------------------------------------------------------------------
# 1. Frozen tree: copy the exact 40-file projection and verify every hash.
# ---------------------------------------------------------------------------
printf '== provisioning frozen tree ==\n'
for entry in AUTHORS LICENSE MANIFEST.in MUS MUSCython bin setup.cfg setup.py; do
    cp -r "$REPO/$entry" "$FROZEN/"
done
cp "$REPO/reference/original-0.3.0/frozen-source/README.md" "$FROZEN/README.md"
(cd "$FROZEN" && python3 - "$FROZEN_MANIFEST" <<'PY'
import hashlib
import os
import sys

manifest_path = sys.argv[1]
expected = {}
for line in open(manifest_path, 'rb').read().decode('ascii').splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    digest, _, declared = line.partition(' ')
    declared = declared.strip()
    if ' <- ' in declared:
        declared = declared.split(' <- ', 1)[0]
    expected[declared] = digest
mismatches = []
for relative, digest in sorted(expected.items()):
    path = os.path.join('.', relative)
    if not os.path.exists(path):
        mismatches.append((relative, 'MISSING', digest))
        continue
    hasher = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            hasher.update(block)
    if hasher.hexdigest() != digest:
        mismatches.append((relative, hasher.hexdigest(), digest))
if mismatches:
    for item in mismatches:
        print('MISMATCH', item, file=sys.stderr)
    sys.exit(1)
print('frozen projection verified: %d files' % len(expected))
PY
)
printf '== building frozen extensions (pyx-historical-cython, Cython 0.29.36) ==\n'
activate_toolchain "$(dirname "$(dirname "$ORACLE_PYTHON")")"
(cd "$FROZEN" && "$ORACLE_PYTHON" -B -c "from Cython.Build import cythonize; import numpy; cythonize('MUSCython/*.pyx', include_path=[numpy.get_include()], force=True)") > "$WORK/cythonize-frozen.log" 2>&1
(cd "$FROZEN" && "$ORACLE_PYTHON" -B setup.py build_ext --inplace) > "$WORK/build-frozen.log" 2>&1
for name in AlignmentUtil BasicBWT ByteBWTCython CompressToRLE GenericMerge LCPGen LZW_BWTCython \
            MSBWTCompGenCython MSBWTGenCython MultimergeCython MultiStringBWTCython RLE_BWTCython; do
    [ -f "$FROZEN/MUSCython/$name.so" ] || { printf 'frozen build missing %s.so\n' "$name" >&2; tail -30 "$WORK/build-frozen.log" >&2; exit 70; }
done
printf 'frozen extensions built: %s modules\n' "$(ls "$FROZEN"/MUSCython/*.so | wc -l)"

# ---------------------------------------------------------------------------
# 2. Modern2 tree: copy the package (with in-tree .so) and hash-verify .so.
# ---------------------------------------------------------------------------
printf '== provisioning modern2 tree ==\n'
cp -r "$REPO/packages/msbwt-modern2/MUS" "$MODERN2/"
cp -r "$REPO/packages/msbwt-modern2/MUSCython" "$MODERN2/"
cp -r "$REPO/packages/msbwt-modern2/bin" "$MODERN2/"
cp "$REPO/packages/msbwt-modern2/setup.py" "$MODERN2/"
cp "$REPO/packages/msbwt-modern2/README.md" "$MODERN2/"
cp "$REPO/packages/msbwt-modern2/MANIFEST.in" "$MODERN2/"
cp "$REPO/packages/msbwt-modern2/AUTHORS" "$MODERN2/" 2>/dev/null || true
cp "$REPO/packages/msbwt-modern2/LICENSE" "$MODERN2/" 2>/dev/null || true
NEED_REBUILD=0
for so in "$REPO"/packages/msbwt-modern2/MUSCython/*.so; do
    name=$(basename "$so")
    if [ -f "$MODERN2/MUSCython/$name" ] && \
       [ "$(sha256_file "$so")" = "$(sha256_file "$MODERN2/MUSCython/$name")" ]; then
        :
    else
        printf 'modern2 .so %s missing or mismatched; rebuild required\n' "$name" >&2
        NEED_REBUILD=1
    fi
done
if [ "$NEED_REBUILD" -eq 1 ]; then
    printf '== rebuilding modern2 extensions (Cython 3.0.12) ==\n'
    activate_toolchain "$(dirname "$(dirname "$MODERN2_PYTHON")")"
    (cd "$MODERN2" && "$MODERN2_PYTHON" -B setup.py build_ext --inplace) > "$WORK/build-modern2.log" 2>&1
    for name in AlignmentUtil BasicBWT ByteBWTCython CompressToRLE GenericMerge LZW_BWTCython \
                MSBWTCompGenCython MSBWTGenCython MultimergeCython MultiStringBWTCython RLE_BWTCython; do
        [ -f "$MODERN2/MUSCython/$name.so" ] || { printf 'modern2 build missing %s.so\n' "$name" >&2; tail -30 "$WORK/build-modern2.log" >&2; exit 70; }
    done
    printf 'modern2 extensions rebuilt: %s modules\n' "$(ls "$MODERN2"/MUSCython/*.so | wc -l)"
else
    printf 'modern2 .so files verified intact: %s modules\n' "$(ls "$MODERN2"/MUSCython/*.so | wc -l)"
fi

printf '== provisioning complete ==\n'
printf 'frozen:   %s\n' "$FROZEN"
printf 'modern2:  %s\n' "$MODERN2"
