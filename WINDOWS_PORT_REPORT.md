# Enhanced-modern2 Windows port report

## Executive Result
**ENHANCED-MODERN2 NATIVE-WINDOWS RELEASE VERIFIED**

## Evidence Summary

| Gate | Count | Result |
|------|-------|--------|
| Source-tree test suite | 464 tests | OK (2 skipped for frozen-reader pysam) |
| Smoke gate (modern2 core) | 12/12 | PASS |
| Process-count invariance | 8/8 | PASS |
| Installed sdist gate | 8/8 | PASS |
| Installed wheel gate | 8/8 | PASS |
| Enhanced randomized audit (seed 20260810) | 14 categories, 60 ops | 0 mismatches |
| Linux regression (WSL) | 464 tests | OK |

## Packaging

| Artifact | Size | SHA-256 |
|----------|------|---------|
| msbwt-modern2-0.3.0.tar.gz | 2,659,783 B | `9833ed9774e884a65f30e679b77998ab48e71104e9c591981da6374f89187d64` |
| msbwt_modern2-0.3.0-cp27-cp27m-win_amd64.whl | 1,473,705 B | `a2dc4b418875c769c6f5b90c105241bfcb723d9124216b9e51ce21de424b3227` |

Wheel contains 11 .pyd modules: AlignmentUtil, BasicBWT, ByteBWTCython, CompressToRLE, GenericMerge, LZW_BWTCython, MSBWTCompGenCython, MSBWTGenCython, MultimergeCython, MultiStringBWTCython, RLE_BWTCython.

## Packaging Dependency Resolution

**Windows**: `install_requires=['numpy', 'pysam; sys_platform != "win32"']` — PEP 508 marker excludes pysam. Normal `pip install` succeeds without `--no-deps`.

**Linux/WSL**: pysam required as before.

## Installed-Enhanced Gate (both sdist and wheel)

| Stage | Sdist | Wheel |
|-------|-------|-------|
| imports from site-packages | PASS | PASS |
| all 6 enhanced console scripts importable | PASS | PASS |
| uniform pp+cfpp | PASS | PASS |
| golden == dd91d69e | PASS | PASS |
| F12 BWTTags (attach/list/array/schema/release) | PASS | PASS |
| F2 MultiSourceProvenance (initialize/load/list) | PASS | PASS |
| nonuniform pp+cfpp | PASS | PASS |
| CLI -V command | PASS | PASS |

## Enhanced Console Scripts (all 6 verified)

1. `msbwt-bwt-tags` — tools.bwt_tags:main (F12: BWT tags)
2. `msbwt-lcp` — tools.lcp:main (F11A: LCP)
3. `msbwt-quality-sidecar` — tools.quality_sidecar:main (Q1: quality sidecar)
4. `msbwt-remove-sources` — tools.remove_sources:main (F10: source removal)
5. `msbwt-retrofit-read-provenance` — tools.retrofit_read_provenance:main (F9: read provenance)
6. `msbwt-benchmark-index` — tools.benchmark_index:main (F13A: benchmark)

## Git State

- **Branch**: `enhanced-modern2-windows`
- **HEAD**: `3474119` (12 commits from `08737ca`)
- **New commits this session**: `3474119` (atomic file operation fixes)
- **Status**: clean (pre-existing uncommitted enhanced-release work preserved)

## Remaining Limitations

1. pysam/BAM unavailable on Windows (no cp27 distribution exists)
2. UCS2 vs UCS4 (inherent CPython 2.7 platform difference)
3. totalCounts.p pickle framing differs (numpy py2 shape elements)
4. macOS untested
