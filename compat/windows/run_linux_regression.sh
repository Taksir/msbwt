#!/usr/bin/env bash
# Run enhanced-modern2 test suite on Linux/WSL at the currently checked-out commit.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${MSBWT_MODERN2_REPO:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
PY27="${PY27:-/home/mytho/.local/share/msbwt-modern2/python27-modern2/bin/python}"

if [ ! -d "$REPO/packages/msbwt-modern2" ]; then
    echo "ERROR: Repository packages directory not found at: $REPO/packages/msbwt-modern2" >&2
    exit 1
fi

if [ ! -x "$PY27" ]; then
    echo "ERROR: Python 2.7 interpreter not found or not executable at: $PY27" >&2
    echo "Set PY27 environment variable to a valid Python 2.7 interpreter." >&2
    exit 1
fi

cd "$REPO/packages/msbwt-modern2"
export MSBWT_MODERN2_REPO="$REPO"

echo "=== HEAD ==="
git -C "$REPO" log -1 --oneline
echo "=== branch ==="
git -C "$REPO" branch --show-current
echo "=== running tests ==="
"$PY27" -m unittest discover -s tests -p '*_py2.py' -v
echo "=== pysam check ==="
"$PY27" -c "import pysam; print('pysam', pysam.__version__)"
