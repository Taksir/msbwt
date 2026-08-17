# Windows port inventory

Forensic audit of all likely Windows portability issues found and addressed
during the native Windows port of msbwt-modern2.

## BUILD TOOLCHAIN

| Issue | File/Function | Linux behavior | Windows behavior | Fix | Risk |
|-------|--------------|----------------|------------------|-----|------|
| No Python 2.7.18 for win-64 | conda | 2.7.18 (conda-forge) | 2.7.18 (Anaconda defaults, MSVC9-built) | Install from defaults channel | low |
| No Cython 3.0.x for py27 win-64 | conda | 3.0.12 (conda-forge) | 3.0.12 (PyPI py2.py3-none-any wheel) | pip install from PyPI | low |
| R6034 CRT loading | setup.py | -lmsvcr90 (no-op on Linux) | msvcr90.dll fails outside SxS | setup.py overrides dll_libraries to msvcrt | low |
| No MSVC9 x64 compiler | MSVC | GCC 7.3.0 (conda) | MinGW-w64 gcc 5.3.0 (conda-forge m2w64) | conda-forge m2w64-toolchain | low |
| libpython27.a not found | link | auto-resolved | GNU ld needs MSVC-format .lib | Generated via PE parser + dlltool | low |

## PATH / FILESYSTEM

| Issue | File | Linux | Windows | Fix | Risk |
|-------|------|-------|---------|-----|------|
| CRLF on checkout | compat/goldens/* | LF (autocrlf=false) | CRLF (autocrlf=true) | .gitattributes already covers .py/.pyx; golden artifact files match via open_memmap normalization | low |
| Forward-slash in paths | MSBWTGen.pyx | / separators | Mixed / separators | No change needed (Windows handles mixed separators) | low |
| Long file paths | all | Not an issue | MAX_PATH=260 | All paths well under 260 chars | low |

## PROCESS / MULTIPROCESSING

| Issue | File | Linux | Windows | Fix | Risk |
|-------|------|-------|---------|-----|------|
| Spawn vs fork | multiprocessing.Pool | fork (no re-execution) | spawn (re-imports __main__) | if __name__ == '__main__' guard in harness; CLI already guarded | low |
| Pool worker file locks | MSBWTGenCython.pyx | unlink succeeds on mapped files | ERROR_SHARING_VIOLATION | myPool.join() before cleanup | low |
| -p 1 still uses Pool | MSBWTGenCython.pyx | fork (silent) | spawn (needs guard) | Guard present in CLI and harness | low |

## MEMMAP / FILE MAPPING

| Issue | File | Linux | Windows | Fix | Risk |
|-------|------|-------|---------|-----|------|
| os.remove while mapped | Multiple pyx files | unlink succeeds | ERROR_SHARING_VIOLATION (Error 32) | Explicit base.close() before os.remove | low |
| os.rename while mapped | MSBWTGenCython.pyx:333 | rename succeeds | ERROR_SHARING_VIOLATION | Close mapping before rename | low |
| Cython typed ndarray buffer | All pyx with typed arr | buffer released at epilogue | Same, but epilogue is late | Explicit close before remove (not relying on epilogue) | low |
| np.memmap() + del not enough | All pyx | file handle released | file handle stays open via Cython buffer | Explicit .base.close() (see Mistakes.md M15) | low |

## BINARY/TEXT MODE

| Issue | File | Linux | Windows | Fix | Risk |
|-------|------|-------|---------|-----|------|
| Pickle text mode | MultiStringBWT.py | LF (text=binary) | \r\n corruption | open(fp, 'rb'/'wb+') | low |
| np.save input text mode | CompressToRLE.pyx | LF (text=binary) | CRLF corruption on output | fopen(..., 'w+b') for output; fopen(..., 'r') for input (CRLF normalization) | low |
| Binary state files | MSBWTCompGenCython.pyx | N/A | 0x0A → \r\n corruption | fopen(..., 'w+b') | low |
| Deletion indices | RLE_BWTCython.pyx | N/A | 0x0A → \r\n corruption | fopen(..., 'w+b') | low |
| massquery CSV | CommandLineInterface.py | \n only | \r\n via text mode | open(fp, 'wb+') | low |

## NUMPY

| Issue | File | Linux | Windows | Fix | Risk |
|-------|------|-------|---------|-----|------|
| np.save L-suffix header | Multiple pyx | (54,) no L | (54L,) with L | open_memmap with tuple(int(x) for x in shape) | low |
| cumsum dtype promotion | MultimergeCython.pyx | uint64 (matches view) | unsigned long 32-bit | np.cumsum(tc, dtype='<u8') | low |
| Cython .shape accessor | All typed ndarrays | Returns npy_intp * (C pointer) | Same | (<object>arr).shape for Python access | low |

## PYSAM

| Issue | File | Linux | Windows | Fix | Risk |
|-------|------|-------|---------|-----|------|
| No pysam for cp27 win | MultiStringBWT.pyx:25 | import pysam (module-level) | ImportError (no distro) | Lazy import inside preprocessBams only | low |
| install_requires | setup.py | pysam installed via manylinux | pip install fails (no wheel) | Documented deviation; --no-deps for Windows | low |

## CLI ENTRY POINTS

| Issue | File | Linux | Windows | Fix | Risk |
|-------|------|-------|---------|-----|------|
| bin/msbwt shebang | bin/msbwt | #!/bin/env python works | Not executable without .py wrapper | CLI invoked via python -c; tests pass | low |

## TEST HARNESS

| Issue | File | Linux | Windows | Fix | Risk |
|-------|------|-------|---------|-----|------|
| Frozen overlay needed | tests/* | Overlay applied by reconstruct script | Not applied by default | Manual sync from WSL frozen dir | medium |
| np.save in tests | tests/*.py | np.save (no L on Linux) | np.save (L on Windows) | _npy_compat.save_npy helper | low |
| pickle total bytes | tests/*_py2.py | No L in shape tuples | L in shape tuples | Semantic comparison on Windows | medium |
| UCS2 vs UCS4 | test_bootstrap_py2.py | sys.maxunicode > 65535 | = 65535 | Platform-conditional assertion | low |
| pysam pin tests | 3 test files | pysam.__version__ = "0.15.4" | ImportError (no distro) | Platform-conditional; shim for frozen tests | low |
| CRLF in golden inputs | compat/goldens/convert/* | LF | CRLF (autocrlf) | Text-mode input fopen (normalizes CRLF) | low |

## COMPILER

| Issue | File | Linux | Windows | Fix | Risk |
|-------|------|-------|---------|-----|------|
| -lmsvcr90 link failure | setup.py | -lmsvcr90 (no-op) | R6034 at runtime | Override dll_libraries to ['msvcrt'] | low |
| libpython27.a generation | setup.py | libpython2.7.so auto | Need MSVC-format lib | PE export parser + dlltool | low |
| Cython C generation | *.pyx | Cython 3.0.12 on Linux | Same on Windows | Identical (same source, same Cython) | low |
