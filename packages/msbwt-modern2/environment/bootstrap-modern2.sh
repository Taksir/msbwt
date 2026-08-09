#!/usr/bin/env bash
# Bootstrap the isolated msbwt-modern2 Python-2.7 environment without sudo.
#
# Creates a brand-new conda prefix with CPython 2.7.18 and the verified GCC
# 7.3.0 x86_64-conda_cos6-linux-gnu toolchain (the same conda artifact set as
# the verified oracle profile py27-late-05a7d6d83862), then installs the
# pinned modern2 wheel set, including Cython 3.0.12 (the last Cython 3.0.x;
# Cython 3.1+ is prohibited for modern2).
#
# This script NEVER touches the legacy oracle environment.  It requires its
# own dedicated prefix.
set -euo pipefail

usage() {
    printf '%s\n' 'Usage: bootstrap-modern2.sh --micromamba /absolute/path --prefix /new/absolute/prefix'
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

unset PYTHONHOME PYTHONPATH PYTHONUSERBASE
export PYTHONNOUSERSITE=1
export PIP_CONFIG_FILE=/dev/null

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
CONDA_SHA_LOCK="$LOCK_DIR/modern2-conda-sha256.json"
WHEEL_LOCK="$LOCK_DIR/modern2-wheels.txt"
test -f "$CONDA_SHA_LOCK" && test -f "$WHEEL_LOCK" || { printf 'Required lock file is missing.\n' >&2; exit 66; }

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT
export MAMBA_ROOT_PREFIX="$WORK_DIR/mamba-root"
export HOME="$WORK_DIR/home"
export XDG_CACHE_HOME="$WORK_DIR/xdg-cache"
ARCHIVE_DIR="$WORK_DIR/artifacts"
LOCAL_EXPLICIT="$WORK_DIR/explicit.txt"
mkdir -p "$HOME" "$XDG_CACHE_HOME" "$ARCHIVE_DIR"
cd "$WORK_DIR"
printf '@EXPLICIT\n' > "$LOCAL_EXPLICIT"

# The JSON lock carries SHA-256 because conda explicit syntax carries only MD5.
while IFS=$'\t' read -r url md5 sha256; do
    filename=${url##*/}
    archive="$ARCHIVE_DIR/$filename"
    curl --disable --fail --location --proto '=https' --tlsv1.2 --retry 3 --output "$archive" "$url"
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

# ensurepip supplies pip 19.2.3, which cannot parse the PEP 508 direct
# references in WHEEL_LOCK.  Bootstrap the already-locked pip 20.3.4 wheel
# locally, verify it first, and only then ask it to process the full lock.
IFS=$'\t' read -r PIP_BOOTSTRAP_URL PIP_BOOTSTRAP_SHA256 < <(python3 - "$WHEEL_LOCK" <<'PY'
import os
import re
import sys

expected_filename = 'pip-20.3.4-py2.py3-none-any.whl'
matches = []
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    for line in handle:
        match = re.match(r'^pip @ (https://\S+) --hash=sha256:([0-9a-f]{64})$', line.rstrip('\n'))
        if match:
            matches.append(match.groups())
if len(matches) != 1 or os.path.basename(matches[0][0]) != expected_filename:
    raise SystemExit('wheel lock must contain exactly one pinned pip 20.3.4 wheel')
print('\t'.join(matches[0]))
PY
)
PIP_BOOTSTRAP="$ARCHIVE_DIR/${PIP_BOOTSTRAP_URL##*/}"
curl --disable --fail --location --proto '=https' --tlsv1.2 --retry 3 --output "$PIP_BOOTSTRAP" "$PIP_BOOTSTRAP_URL"
printf '%s  %s\n' "$PIP_BOOTSTRAP_SHA256" "$PIP_BOOTSTRAP" | sha256sum --check --status || {
    printf 'pip 20.3.4 bootstrap artifact SHA-256 does not match the wheel lock.\n' >&2
    exit 65
}
"$PREFIX/bin/python" -m pip install --isolated --disable-pip-version-check --no-cache-dir --no-deps --only-binary=:all: --no-index --upgrade "$PIP_BOOTSTRAP"
PIP_VERSION_OUTPUT=$("$PREFIX/bin/python" -m pip --version)
case "$PIP_VERSION_OUTPUT" in
    "pip 20.3.4 from $PREFIX/"*) ;;
    *) printf 'Expected prefix-local pip 20.3.4, got: %s\n' "$PIP_VERSION_OUTPUT" >&2; exit 65 ;;
esac

"$PREFIX/bin/python" -m pip install --isolated --disable-pip-version-check --no-cache-dir --no-deps --only-binary=:all: --require-hashes --upgrade -r "$WHEEL_LOCK"
"$PREFIX/bin/python" -c "import Cython,numpy,pysam,pip,setuptools,wheel; assert (Cython.__version__,numpy.__version__,pysam.__version__,pip.__version__,setuptools.__version__,wheel.__version__)==('3.0.12','1.16.6','0.15.4','20.3.4','44.1.1','0.37.1'), 'modern2 wheel version mismatch'"
"$PREFIX/bin/python" -c "import sys; assert sys.version_info[:2] == (2, 7) and sys.maxunicode > 65535, 'expected CPython 2.7 UCS4'"
printf 'OK modern2 environment: %s\n' "$PREFIX"
