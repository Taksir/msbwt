#!/usr/bin/env bash
# Run one frozen-oracle candidate in an already-provisioned WSL Linux Python 2
# environment.  This script deliberately does not invoke sudo, a shell init
# file, or any Windows executable.
set -euo pipefail

usage() {
    cat <<'USAGE'
Usage:
  run-wsl-probe.sh \
    --python /absolute/path/to/python2.7 \
    --source /absolute/path/to/msbwt \
    --results /absolute/path/to/new-oracle-results-parent \
    --candidate candidate-key \
    --route generated-c-no-cython|pyx-historical-cython|all \
    --fixture-root /absolute/path/to/synthetic-fixtures \
    [--compression-milestone1 --golden-root /absolute/path/to/original-0.3.0-goldens] \
    [--golden-case uniform-multifile|nonuniform-prefix|gzip-input]...

The Python environment is expected to be isolated already.  The supplied
results directory should be Linux-native storage (for example /home/...);
source may be a read-only /mnt/<drive>/ checkout.  The underlying probe writes
a fresh timestamped directory below --results and exits nonzero on any failed
dependency, exact-version, build, import, CLI, or golden gate.
USAGE
}

PYTHON=""
SOURCE=""
RESULTS=""
CANDIDATE=""
ROUTE=""
FIXTURE_ROOT=""
GOLDEN_CASES=()
COMPRESSION_MILESTONE1=0
GOLDEN_ROOT=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --python)
            PYTHON=${2:?--python requires a value}
            shift 2
            ;;
        --source)
            SOURCE=${2:?--source requires a value}
            shift 2
            ;;
        --results)
            RESULTS=${2:?--results requires a value}
            shift 2
            ;;
        --candidate)
            CANDIDATE=${2:?--candidate requires a value}
            shift 2
            ;;
        --route)
            ROUTE=${2:?--route requires a value}
            shift 2
            ;;
        --fixture-root)
            FIXTURE_ROOT=${2:?--fixture-root requires a value}
            shift 2
            ;;
        --golden-case)
            GOLDEN_CASES+=("${2:?--golden-case requires a value}")
            shift 2
            ;;
        --compression-milestone1)
            COMPRESSION_MILESTONE1=1
            shift
            ;;
        --golden-root)
            GOLDEN_ROOT=${2:?--golden-root requires a value}
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 64
            ;;
    esac
done

for required_name in PYTHON SOURCE RESULTS CANDIDATE ROUTE FIXTURE_ROOT; do
    if [ -z "${!required_name}" ]; then
        printf 'Missing required --%s argument.\n' "$(printf '%s' "$required_name" | tr '[:upper:]_' '[:lower:]-')" >&2
        usage >&2
        exit 64
    fi
done

case "$ROUTE" in
    all|generated-c-no-cython|pyx-historical-cython)
        ;;
    *)
        printf 'Unsupported route: %s\n' "$ROUTE" >&2
        exit 64
        ;;
esac

case "$PYTHON" in
    /*)
        ;;
    *)
        printf '--python must be an absolute Linux path: %s\n' "$PYTHON" >&2
        exit 64
        ;;
esac

if [ ! -x "$PYTHON" ]; then
    printf 'Python executable is not executable: %s\n' "$PYTHON" >&2
    exit 66
fi
if [ ! -d "$SOURCE" ] || [ ! -d "$FIXTURE_ROOT" ]; then
    printf '--source and --fixture-root must be existing directories.\n' >&2
    exit 66
fi

ENV_PREFIX=$("$PYTHON" -c 'import sys; print(sys.prefix)')
ENV_BIN="$ENV_PREFIX/bin"
if [ ! -d "$ENV_BIN" ]; then
    printf 'Python sys.prefix has no bin directory: %s\n' "$ENV_PREFIX" >&2
    exit 66
fi

# Do not inherit Windows interop paths or user shell initialization.  Keep the
# isolated environment first, followed only by standard Linux system paths.
export PATH="$ENV_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
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

# Compiler packages need their own sysroot and linker variables.  Start from a
# known build environment, then use only activation scripts shipped inside the
# selected isolated prefix (never user or system shell initialization).
unset AR AS CC CXX CFLAGS CPPFLAGS CXXFLAGS LD LDFLAGS
unset CONDA_BUILD_SYSROOT _CONDA_PYTHON_SYSCONFIGDATA_NAME
export CONDA_PREFIX="$ENV_PREFIX"

TOOLCHAIN_ACTIVATED=0
set +u
for activation_name in activate-binutils_linux-64.sh activate-gcc_linux-64.sh activate-gxx_linux-64.sh; do
    activation_path="$ENV_PREFIX/etc/conda/activate.d/$activation_name"
    if [ -f "$activation_path" ]; then
        # shellcheck source=/dev/null
        . "$activation_path"
        TOOLCHAIN_ACTIVATED=1
    fi
done
set -u

pick_wrapper() {
    local suffix=$1
    local candidate_path
    for candidate_path in "$ENV_BIN"/*-"$suffix"; do
        if [ -x "$candidate_path" ]; then
            printf '%s\n' "$candidate_path"
            return 0
        fi
    done
    return 1
}

if [ "$TOOLCHAIN_ACTIVATED" -eq 0 ]; then
    if CC_WRAPPER=$(pick_wrapper gcc); then
        export CC="$CC_WRAPPER"
    elif command -v gcc >/dev/null 2>&1; then
        export CC=$(command -v gcc)
    else
        printf 'No conda gcc wrapper or Linux gcc found in sanitized PATH.\n' >&2
        exit 69
    fi

    if CXX_WRAPPER=$(pick_wrapper g++); then
        export CXX="$CXX_WRAPPER"
    elif command -v g++ >/dev/null 2>&1; then
        export CXX=$(command -v g++)
    else
        printf 'No conda g++ wrapper or Linux g++ found in sanitized PATH.\n' >&2
        exit 69
    fi
fi

if [ -z "${CC:-}" ] || [ -z "${CXX:-}" ]; then
    printf 'Compiler activation did not provide both CC and CXX.\n' >&2
    exit 69
fi

if [[ "$RESULTS" == /mnt/* ]]; then
    printf 'Warning: --results is on a Windows mount; Linux-native storage is preferred for reproducible extension builds.\n' >&2
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROBE="$SCRIPT_DIR/../probe_legacy.py"
if [ ! -f "$PROBE" ]; then
    printf 'Frozen oracle probe is missing: %s\n' "$PROBE" >&2
    exit 66
fi

GOLDEN_ARGS=()
if [ "${#GOLDEN_CASES[@]}" -eq 0 ] && [ "$COMPRESSION_MILESTONE1" -eq 0 ]; then
    GOLDEN_ARGS+=(--run-first-goldens)
else
    for golden_case in "${GOLDEN_CASES[@]}"; do
        GOLDEN_ARGS+=(--golden-case "$golden_case")
    done
fi

COMPRESSION_ARGS=()
if [ "$COMPRESSION_MILESTONE1" -eq 1 ]; then
    if [ -z "$GOLDEN_ROOT" ] || [ ! -d "$GOLDEN_ROOT" ]; then
        printf '%s\n' '--compression-milestone1 requires an existing --golden-root.' >&2
        exit 66
    fi
    COMPRESSION_ARGS+=(--compression-milestone1 --golden-root "$GOLDEN_ROOT")
fi

exec "$PYTHON" "$PROBE" \
    --source "$SOURCE" \
    --results "$RESULTS" \
    --candidate "$CANDIDATE" \
    --route "$ROUTE" \
    --install-dependencies \
    "${GOLDEN_ARGS[@]}" \
    "${COMPRESSION_ARGS[@]}" \
    --fixture-root "$FIXTURE_ROOT"
