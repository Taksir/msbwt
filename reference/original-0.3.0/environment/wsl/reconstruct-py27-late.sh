#!/usr/bin/env bash
# Reconstruct the verified late-Python-2 oracle environment without sudo.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: reconstruct-py27-late.sh --micromamba /absolute/path --prefix /new/absolute/prefix'
}

MICROMAMBA=''
PREFIX=''
while [ "$#" -gt 0 ]; do
    case "$1" in
        --micromamba) MICROMAMBA=${2:?--micromamba requires a value}; shift 2 ;;
        --prefix) PREFIX=${2:?--prefix requires a value}; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 64 ;;
    esac
done
if [ -z "$MICROMAMBA" ] || [ -z "$PREFIX" ]; then usage >&2; exit 64; fi
case "$MICROMAMBA:$PREFIX" in /*:/*) ;; *) printf 'Paths must be absolute Linux paths.\n' >&2; exit 64;; esac
if [ ! -x "$MICROMAMBA" ]; then printf 'micromamba is not executable: %s\n' "$MICROMAMBA" >&2; exit 66; fi
if [ -e "$PREFIX" ]; then printf 'Refusing existing target prefix: %s\n' "$PREFIX" >&2; exit 73; fi
for tool in curl sha256sum python3; do command -v "$tool" >/dev/null 2>&1 || { printf 'Missing required tool: %s\n' "$tool" >&2; exit 69; }; done

MICROMAMBA_VERSION='2.8.1'
MICROMAMBA_SHA256='9689782d863c05a1bf5d2d371ba527104e7a4eb4310c1637d8653b751aed9c82'
printf '%s  %s\n' "$MICROMAMBA_SHA256" "$MICROMAMBA" | sha256sum --check --status || {
    printf 'micromamba artifact SHA-256 does not match the verified bootstrap.\n' >&2
    exit 65
}
if [ "$("$MICROMAMBA" --version)" != "$MICROMAMBA_VERSION" ]; then
    printf 'micromamba version must be exactly %s.\n' "$MICROMAMBA_VERSION" >&2
    exit 65
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LOCK_DIR="$SCRIPT_DIR/locks"
CONDA_SHA_LOCK="$LOCK_DIR/py27-late-05a7d6d83862-conda-sha256.json"
WHEEL_LOCK="$LOCK_DIR/py27-late-05a7d6d83862-wheels.txt"
test -f "$CONDA_SHA_LOCK" && test -f "$WHEEL_LOCK" || { printf 'Required lock file is missing.\n' >&2; exit 66; }

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT
export MAMBA_ROOT_PREFIX="$WORK_DIR/mamba-root"
ARCHIVE_DIR="$WORK_DIR/artifacts"
LOCAL_EXPLICIT="$WORK_DIR/explicit.txt"
mkdir "$ARCHIVE_DIR"
printf '@EXPLICIT\n' > "$LOCAL_EXPLICIT"

# The JSON lock carries SHA-256 because conda explicit syntax carries only MD5.
while IFS=$'\t' read -r url md5 sha256; do
    filename=${url##*/}
    archive="$ARCHIVE_DIR/$filename"
    curl --fail --location --proto '=https' --tlsv1.2 --retry 3 --output "$archive" "$url"
    printf '%s  %s\n' "$sha256" "$archive" | sha256sum --check --status
    printf 'file://%s#%s\n' "$archive" "$md5" >> "$LOCAL_EXPLICIT"
done < <(python3 - "$CONDA_SHA_LOCK" <<'PY'
import json
import re
import sys
lock = json.load(open(sys.argv[1], 'rb'))
for package in lock['packages']:
    url, md5, sha256 = package['url'], package['md5'], package['sha256']
    if not (url.startswith('https://') and re.match(r'^[0-9a-f]{32}$', md5) and re.match(r'^[0-9a-f]{64}$', sha256)):
        raise SystemExit('invalid artifact lock entry: ' + package.get('name', '<unknown>'))
    print('\t'.join((url, md5, sha256)))
PY
)

"$MICROMAMBA" create --yes --offline --no-rc --prefix "$PREFIX" --file "$LOCAL_EXPLICIT"
"$PREFIX/bin/python" -m ensurepip --upgrade
"$PREFIX/bin/python" -m pip install --disable-pip-version-check --no-cache-dir --no-deps --only-binary=:all: --require-hashes --upgrade -r "$WHEEL_LOCK"
"$PREFIX/bin/python" -c "import Cython,numpy,pysam,pip,setuptools,wheel; assert (Cython.__version__,numpy.__version__,pysam.__version__,pip.__version__,setuptools.__version__,wheel.__version__)==('0.29.36','1.16.6','0.15.4','20.3.4','44.1.1','0.37.1')"
