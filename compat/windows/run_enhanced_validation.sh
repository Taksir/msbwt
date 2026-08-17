#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${MSBWT_MODERN2_REPO:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
BUILD_PREFIX="/home/mytho/.local/share/msbwt-modern2/python27-modern2"
MICROMAMBA="/home/mytho/.local/share/msbwt-oracle/bootstrap/micromamba"
WORK_BASE="/tmp/msbwt-enhanced-val-pass"

rm -rf "$WORK_BASE"

bash "$REPO/packages/msbwt-modern2/validate/enhanced-release-candidate.sh" \
  --repo "$REPO" \
  --build-prefix "$BUILD_PREFIX" \
  --micromamba "$MICROMAMBA" \
  --work-base "$WORK_BASE"
