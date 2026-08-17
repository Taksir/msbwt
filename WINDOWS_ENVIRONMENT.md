# Windows environment

Exact native Windows environment used for the modern2 port validation.

## Platform

| Component | Value |
|-----------|-------|
| OS | Windows 10/11 x86-64 |
| Shell | PowerShell 5.1 |
| CPython | 2.7.18 (Anaconda, win-64, cp27m, UCS2, MSVC9-built) |
| NumPy | 1.16.6 (PyPI wheel, cp27m-win_amd64) |
| Cython | 3.0.12 (PyPI, py2.py3-none-any universal wheel) |
| pip | 20.3.4 |
| setuptools | 44.1.1 |
| wheel | 0.37.1 |
| Compiler | MinGW-w64 gcc 5.3.0 (conda-forge m2w64-toolchain, MSYS2 origin) |
| pysam | None (no CPython 2.7 Windows distribution exists for any version) |

## Python environment

- Distribution: Anaconda defaults (CPython 2.7.18, `hfb89ab9_0` for win-64)
- ABI tag: `cp27m` (narrow/UCS2 build)
- `sys.maxunicode`: 65535 (UCS2)
- `sys.version`: `2.7.18 |Anaconda, Inc.| ...` (MSC v.1500 64 bit)

## NumPy

- Installed from PyPI: `numpy-1.16.6-cp27-cp27m-win_amd64.whl`
- NOT from conda-forge (max version on conda-forge for py27 win-64 is 1.16.5)
- Confirmed `numpy.core.multiarray` loads correctly
- Confirmed `_multiarray_umath` DLL dependencies resolve (libcblas via numpy package)

## Compiler

- `gcc.exe` (Rev5, Built by MSYS2 project) 5.3.0
- Located at: `Library/mingw-w64/bin/gcc.exe`
- Used via distutils `--compiler=mingw32`
- No R6034 issues after the `setup.py` dll_libraries override to msvcrt

## Extension build

```bash
# From packages/msbwt-modern2/
python setup.py build_ext --compiler=mingw32 --inplace
```

Generated C files (*.c) are re-derived from .pyx by Cython 3.0.12 during
the build.  The repo tracks the generated C files (repo policy: .pyx
authoritative, .c derived).

## pysam handling

No fake pysam.py or pysam.pyc is used in the current validation.
The two tests that require pysam are skipped on Windows (frozen-reader
regression tests).  All 464 tests pass; 2 are skipped.

## Validation copy

The test suite runs from a disposable validation copy of the repository
where the frozen original files (commit 7503346) are overlaid at the root
`MUS/` and `MUSCython/` directories.  The frozen overlay source is in
WSL at `/home/mytho/.local/share/msbwt-audit-q1/frozen/` and is synced
via `robocopy` + WSL cp for the Windows validation.
