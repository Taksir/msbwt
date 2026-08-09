#!/usr/bin/env bash
# Build msbwt-modern2 in its pinned Python-2.7 environment.
#
# Usage: build-modern2.sh --prefix /absolute/modern2/env/prefix --source /path/to/packages/msbwt-modern2
#
# Sources the conda toolchain activation scripts INSIDE the modern2 prefix and
# runs the deterministic environment used by the verified oracle harness.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: build-modern2.sh --prefix /absolute/prefix --source /absolute/package-dir'
}

PREFIX=''
SOURCE=''
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=${2:?--prefix requires a value}; shift 2 ;;
        --source) SOURCE=${2:?--source requires a value}; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 64 ;;
    esac
done
if [ -z "$PREFIX" ] || [ -z "$SOURCE" ]; then usage >&2; exit 64; fi
case "$PREFIX:$SOURCE" in /*:/*) ;; *) printf 'Paths must be absolute Linux paths.\n' >&2; exit 64;; esac
if [ ! -x "$PREFIX/bin/python" ]; then printf 'Python not found in prefix: %s\n' "$PREFIX" >&2; exit 66; fi
if [ ! -d "$SOURCE" ]; then printf 'Source directory not found: %s\n' "$SOURCE" >&2; exit 66; fi

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

unset AR AS CC CXX CFLAGS CPPFLAGS CXXFLAGS LD LDFLAGS
unset CONDA_BUILD_SYSROOT _CONDA_PYTHON_SYSCONFIGDATA_NAME
export CONDA_PREFIX="$PREFIX"

set +u
for activation_name in activate-binutils_linux-64.sh activate-gcc_linux-64.sh activate-gxx_linux-64.sh; do
    activation_path="$PREFIX/etc/conda/activate.d/$activation_name"
    if [ -f "$activation_path" ]; then
        . "$activation_path"
    fi
done
set -u

if [ -z "${CC:-}" ]; then
    printf 'Compiler activation failed: CC is empty.\n' >&2
    exit 69
fi

"$PREFIX/bin/python" -c 'import sys; assert sys.version_info[:2] == (2, 7), sys.version'
"$PREFIX/bin/python" -c 'import Cython; assert Cython.__version__.startswith("3.0."), Cython.__version__'

cd "$SOURCE"
"$PREFIX/bin/python" setup.py build_ext --inplace
