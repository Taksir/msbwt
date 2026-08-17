# MSBWT compatibility deviationsIntentional, documented correctness deviations from the frozen originalimplementation (`reference/original-0.3.0/`, commit`7503346ec072ddb89520db86fef85569a9ba093a`).  Each entry records the affectedcommands/APIs/files, the old and new behavior, the rationale, and thereader/writer interoperability consequences.  The frozen oracle is nevermodified; these deviations exist only in the modern distributions(`packages/msbwt-modern2/`, and later `packages/msbwt-modern3/`).## 1. Decompression numeric/index fix (modern2)- Status: executed and validated GÇö Modern2 Milestone 3 (see  `docs/modernization/MODERN2_MILESTONE3_DECOMPRESSION.md`).- Affected commands/APIs: `msbwt decompress -p N SRC DST`;  `MUS.MSBWTGen.decompressBWT` / `decompressBWTPoolProcess`;  `MUS.MultiStringBWT.CompressedMSBWT.getBWTRange` / `decompressBlocks`.- Affected file: `packages/msbwt-modern2/MUS/MultiStringBWT.py`  (the only source line change of the fix: the `decompressBlocks` fill loop  converts the `<u8` run-count scalar with `int(...)` before slice  arithmetic; the modern2 file differs from the frozen original by exactly  those three lines).- Old (frozen) behavior: deterministic failure for every RLE input GÇö  `TypeError: slice indices must be integers or None or have an __index__  method` at `MUS/MultiStringBWT.py:662` (line 630 for multi-block inputs),  because `s + counts[lInd]` promotes `np.uint64 + Python int` to NumPy  `float64` under CPython 2.7 / NumPy 1.16.6, and `float64` has no  `__index__`.  The committed expected-failure evidence under  `compat/goldens/original-0.3.0/compression-milestone1/decompression-failure/`  is preserved unchanged.- New (modern2) behavior: decompression succeeds.  The decompressed  `msbwt.npy` (`|u1`, shape `(48,)`, header byte-identical to the legacy  decompression preallocation header) carries a payload byte-for-byte equal  to the authoritative uniform byte-BWT golden payload (SHA-256  `75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e`; whole  file SHA-256 `f536d60f356ed4a34e8253eecdd91e90db8c2ba3430c2e3d3e1855bb49007ef4`).  The whole-file bytes differ from the compiled-builder golden  (`dd91d69ee2785c88...`) only in the NumPy v1 shape literal `(48,)` vs  `(48L,)` GÇö the same documented pure-Python vs compiled-path serialization  distinction already accepted for the compressed routes.- Rationale: genuine correctness defect (AGENTS.md: "Correct genuine  correctness or security defects; do not preserve them merely for byte  equality").  The fix is the narrowest value-preserving conversion at the  slice boundary: `int(np.uint64(x))` is exact for every value; no  arithmetic meaning, run boundary, symbol count, output length, or payload  byte changes.- Interoperability: the decompressed primary is a valid `msbwt.npy` loadable  by the legacy byte reader semantics; the compressed input `comp_msbwt.npy`  is untouched.  Reader-derived indexes (`totalCounts.npy`, `fmIndex.npy`  for byte; `totalCounts.p`, `comp_fmIndex.npy`, `comp_refIndex.npy` for  compressed sources) are byte-identical to the legacy reader outputs for  the same payloads.## 2. `merge -p 1` CLI numProcs fix (modern2)- Status: executed and validated GÇö Modern2 Milestone 9 (see  `docs/modernization/MODERN2_MILESTONE9_GENERIC_MERGE.md`).- Affected command: `msbwt merge -p 1 OUT IN_A IN_B` (and the default  `merge` invocation, which defaults `-p` to 1).- Affected file: `packages/msbwt-modern2/MUS/CommandLineInterface.py` (the  modern2 file differs from the frozen original by exactly one added line:  `numProcs = 1` immediately before the `if args.numProcesses > 1:` branch  of the `merge` subcommand).- Old (frozen) behavior: `merge -p 1` raises  `UnboundLocalError: local variable 'numProcs' referenced before  assignment` because `numProcs` is bound only inside the  `args.numProcesses > 1` branch.  The output directory is created but  empty and the inputs are unchanged.  The committed failure evidence  (`compat/goldens/original-0.3.0/merge-milestone1/relationship-merge-p1-unboundlocalerror.json`,  stderr SHA-256  `186d471d861c4eaf8ef200076742e259182b6e3c050ebe26540fbdf1e7eb3a4c`) is  preserved; the frozen source is not repaired, and the modern2 Python-2  suite reproduces the historical failure by executing the frozen CLI  source.- New (modern2) behavior: `merge -p 1` performs the intended merge exactly  like the working multi-process route (`-p 2` also clamps to one process  with the same warning).  Both routes call  `MUSCython.GenericMerge.mergeTwoMSBWTs(..., 1, logger)`, whose algorithm  itself clamps `numProcs > 1` to 1.  `-p 1` and `-p 2` produce  byte-identical outputs (merged `msbwt.npy`  `dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f`,  `|u1`, shape `(48L,)`, payload  `75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e`;  retained `inter0.npy`  `4a6d97a36e9ef4e3c19fb873b7713a9357d207d29433a3eca67a41cc4221afd6`),  byte-identical to the committed secondary regenerated-source oracle and  to a clean-from-scratch combined construction.- Rationale: genuine CLI correctness defect, explicitly pre-authorized as a  LEGACY SOURCE BUG fix by the resolved merge compatibility policy  (`docs/modernization/MERGE_INDEXING_PLAN.md`).  The fix is the narrowest  possible: binding the same single-process value the working `-p 2` route  already binds.  No merge mathematics, persistent format, or output file  set changes.- Interoperability: the merged output is byte-identical to the committed  secondary regenerated-source oracle and loadable by the legacy reader;  the frozen `-p 1` failure evidence remains authoritative for the frozen  CLI only.  The historical committed `GenericMerge.c` SIGSEGV  (LEGACY GENERATED-CODE DEFECT) is a separate preserved defect that  modern2 never reproduces.

# Windows port compatibility deviations

These entries document intentional, tested deviations made to support
native 64-bit Windows (CPython 2.7.18, MinGW-w64, numpy 1.16.6) in the
msbwt-modern2 distribution.  All entries preserve Linux parity: on Linux
the changes are no-ops or produce byte-identical results.

## W-PYSAM: Lazy pysam import

- Status: executed and validated â€” Windows port (133/133 tests pass).
- Affected commands/APIs: all CLI commands, `MUS.MultiStringBWT`,
  `MUSCython.MultiStringBWTCython`.
- Affected files: `packages/msbwt-modern2/MUS/MultiStringBWT.py`,
  `packages/msbwt-modern2/MUSCython/MultiStringBWTCython.pyx`.
- Old (frozen) behavior: `import pysam` at module scope in both
  `MUS/MultiStringBWT.py` and `MUSCython/MultiStringBWTCython.pyx`.
  Importing either module requires pysam to be installed.
- New behavior: `import pysam` is deferred to the `preprocessBams()` function
  body (the only consumer).  Module-level import of `MUS.MultiStringBWT`
  and `MUSCython.MultiStringBWTCython` no longer requires pysam.
- Rationale: pysam has no CPython 2.7 Windows distribution (no `cp27`
  `win_amd64` wheel exists on PyPI for any version; no `py27` `win-64`
  build exists in conda-forge).  All nine legacy CLI commands, all validated
  FASTQ construction/query/compression/decompression/merge operations, and
  the entire reader/FM surface work without pysam.  BAM input is the only
  consumer.
- Reader/writer interoperability: identical on Linux (pysam still required
  at import time for BAM; lazy import has no effect on FASTQ paths).
  On Windows: BAM input raises `NotImplementedError` at call time.
- Runtime requirement: pysam is NOT required for any Windows operation.
  `install_requires` retains `pysam` for Linux metadata; Windows users
  install with `pip install --no-deps`.

## W-BINARY-IO: Binary-mode file operations

- Status: executed and validated â€” Windows port (133/133 tests pass).
- Affected commands/APIs: `msbwt convert`, `msbwt massquery`, pickle I/O
  in `MUS.MultiStringBWT`, reader-side-effect pickle files.
- Affected files: `MUSCython/CompressToRLE.pyx`, `MUS/CommandLineInterface.py`,
  `MUS/MultiStringBWT.py`, `MUSCython/MSBWTCompGenCython.pyx`,
  `MUSCython/RLE_BWTCython.pyx`.
- Old behavior: `fopen(fn, 'r+')` / `fopen(fn, 'w+')` for binary data in
  CompressToRLE and MSBWTCompGenCython; `open(fp, 'w+')` for pickle dump;
  `open(args.outputFile, 'w+')` for massquery CSV output.
- New behavior: all binary data files use explicit binary mode (`'rb'`/`wb+'`
  / `w+b`); massquery CSV uses `'wb+'` for output; convert input stays in
  text mode for CRLF normalization; pickle I/O uses `'rb'`/`wb+'`.
- Rationale: Windows C runtime translates `\n` â†’ `\r\n` on text-mode write,
  corrupting pickle framing bytes, RLE byte streams, and BWT index data.
  Linux text mode is byte-transparent, so the change is invisible there.
- Reader/writer interoperability: identical on Linux. On Windows, converted
  BWT payloads now match the Linux byte contracts.

## W-MEMMAP-CLOSE: Explicit memmap close before file removal

- Status: executed and validated â€” Windows port (133/133 tests pass).
- Affected commands/APIs: all construction paths (`pp`, `cfpp`, `compress`),
  merge, decompression.
- Affected files: `MUSCython/MultiStringBWTCython.pyx`,
  `MUSCython/MSBWTGenCython.pyx`, `MUSCython/MSBWTCompGenCython.pyx`,
  `MUSCython/RLE_BWTCython.pyx`, `MUSCython/MultimergeCython.pyx`,
  `MUSCython/GenericMerge.pyx`.
- Old behavior: `os.remove()` on files that were still memory-mapped by
  Cython typed ndarray views (the mapping is held alive until the Cython
  function epilogue, not released by `del`).
- New behavior: explicit `(<object>arr).base.close()` on every memmap before
  `os.remove()` / `os.rename()` / `os.unlink()`.  Each site has a
  `(Windows portability)` comment.
- Rationale: on Windows, `os.remove()` fails with ERROR_SHARING_VIOLATION
  (Error 32) while a file has an open memory mapping.  On Linux,
  `unlink()` succeeds on mapped files, so this was never caught.
- Reader/writer interoperability: identical on Linux (close is a no-op
  for an already-closed mapping).

## W-POOL-JOIN: Pool join before file cleanup

- Status: executed and validated â€” Windows port (133/133 tests pass).
- Affected commands/APIs: `cfpp` (uniform and nonuniform builds).
- Affected files: `MUSCython/MSBWTGenCython.pyx`,
  `MUSCython/MSBWTCompGenCython.pyx`.
- Old behavior: `myPool.close()` without `myPool.join()`; pool workers
  hold `np.load(..., 'r+')` mappings open until process exit.
- New behavior: `myPool.join()` called immediately after `close()`,
  ensuring all workers have exited and released their file mappings
  before any subsequent `os.remove()` calls.
- Rationale: on Windows, `os.remove()` of a file still mapped by a
  lingering worker process fails with ERROR_SHARING_VIOLATION.  On Linux,
  `unlink()` succeeds silently.
- Reader/writer interoperability: identical on Linux (harmless join).

## W-CUMSUM-DTYPE: Forced uint64 cumsum in MultimergeCython

- Status: executed and validated â€” Windows port (133/133 tests pass).
- Affected commands/APIs: `cfpp -p N` for nonuniform inputs (Multimerge
  path).
- Affected file: `MUSCython/MultimergeCython.pyx`
  (the `memoryBWT` helper function).
- Old behavior: `fmOffsets = np.cumsum(totalCounts) - totalCounts`
  where `totalCounts` is `<u4` (uint32).
- New behavior: `fmOffsets = np.cumsum(totalCounts, dtype='<u8') - totalCounts`.
- Rationale: on Windows x64, `np.cumsum(uint32)` returns a value with
  C `unsigned long` dtype (32-bit on Windows), which cannot be assigned to
  a `cdef np.uint64_t` view.  On Linux x64, `unsigned long` is 64-bit so
  no mismatch occurs.  Forcing `<u8` is the explicit, cross-platform-safe
  form.  Values are identical.
- Reader/writer interoperability: identical on Linux (values unchanged).

## W-NPY-SHAPE: Normalized .npy header shapes

- Status: executed and validated â€” Windows port (133/133 tests pass).
- Affected commands/APIs: all construction/compression paths.
- Affected files: `MUSCython/ByteBWTCython.pyx`,
  `MUSCython/RLE_BWTCython.pyx`, `MUSCython/LZW_BWTCython.pyx`,
  `MUSCython/MultimergeCython.pyx`, `MUSCython/GenericMerge.pyx`,
  `MUS/MSBWTGen.pyx`.
- Old behavior: `np.save(fn, arr)` which uses `repr(arr.shape)` for the
  `.npy` header; on CPython 2.7 Windows, `arr.shape` returns a tuple of
  py2 `long` objects, producing `L`-suffixed literals (e.g., `(54L,)`).
- New behavior: `np.save` calls replaced with `open_memmap` + copy using
  `tuple(int(x) for x in arr.shape)`, producing `(54,)` on both platforms.
  A `_int_shape()` helper function normalizes shapes in the Cython modules.
- Rationale: on Windows CPython 2.7, `numpy.ndarray.shape` returns py2
  `long` objects (because numpy's C converter uses `PyLong_FromSsize_t`
  when `npy_intp` is 64-bit), producing `L`-suffixed header literals
  that differ from the Linux byte contracts.  The frozen goldens and the
  modern2 test constants assume the no-`L` form.  `open_memmap` with
  normalized shapes produces byte-identical headers on both platforms.
- Reader/writer interoperability: identical on Linux (int and long
  produce the same value; the header bytes match).

## W-MATCHUP-SHAPE: Cython shape accessor workaround

- Status: executed and validated â€” Windows port (133/133 tests pass).
- Affected files: `MUSCython/ByteBWTCython.pyx`,
  `MUSCython/RLE_BWTCython.pyx`, `MUSCython/LZW_BWTCython.pyx`,
  `MUSCython/MultimergeCython.pyx`, `MUSCython/GenericMerge.pyx`.
- Old behavior: Cython code using `arr.shape` directly (where `arr` is a
  `cdef np.ndarray`) â€” on all platforms, the shape accessor returns a C
  `npy_intp *` pointer, not a Python tuple.
- New behavior: `(<object>arr).shape` casts to Python before passing to
  `_int_shape()`.  This is a Cython-specific pattern, not a platform
  difference.
- Rationale: Cython's typed ndarray `.shape` returns a raw C pointer that
  cannot be passed to Python functions expecting a tuple.  The cast is
  required in Cython 3.0.x on all platforms.

## W-R6034: MinGW CRT linkage

- Status: executed and validated â€” Windows port (133/133 tests pass).
- Affected commands/APIs: all extension module builds.
- Affected file: `packages/msbwt-modern2/setup.py`.
- Old behavior: distutils on CPython 2.7 passes `-lmsvcr90` to the
  MinGW linker (derived from `sys.version` containing `MSC v.1500`).
- New behavior: `build_ext.build_extensions()` overrides
  `compiler.dll_libraries = ['msvcrt']` when the compiler is `mingw32`.
- Rationale: `msvcr90.dll` cannot be loaded outside an SxS activation
  context on Windows 10/11, causing R6034 runtime errors.  MinGW-w64
  extensions link against `msvcrt.dll` (always available; no manifest
  required).  Cross-CRT risk is minimal: msbwt modules perform no
  cross-CRT resource passing (no FILE* handles, no shared malloc/free
  across module boundaries).
- Reader/writer interoperability: no effect (this is a build-time change
  only; the runtime behavior is unchanged).

## W-COMPLETION: Windows port overall status

- Status: verified â€” 133/133 tests pass on native Windows.
- Environment: Python 2.7.18 (Anaconda defaults, win-64, MSVC9-built),
  NumPy 1.16.6 (PyPI wheel, cp27m-win_amd64), Cython 3.0.12, MinGW-w64
  gcc 5.3.0 (conda-forge m2w64-toolchain).
- Golden byte parity: uniform `msbwt.npy` SHA-256
  `dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f`
  (identical to Linux), payload `75134b48...`, nonuniform payload
  `7a97b19a...`, decompression contract `f536d60f...`.
- Process-count invariance: `-p 1`/`-p 2`/`-p 4` produce byte-identical
  artifacts on Windows (8/8 stages pass).
- Known platform differences (documented):
  - UCS2 vs UCS4 (narrow vs wide Python 2.7 build).
  - `totalCounts.p` pickle framing differs (numpy py2 shape elements
    are longs on Windows, ints on Linux; logical content identical).
  - pysam absent on Windows (BAM input unsupported).
