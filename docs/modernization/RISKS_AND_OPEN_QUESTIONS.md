# Known risks and open questions

Status meanings: **confirmed** is directly established by source/repository inspection; **unverified** needs legacy execution, external specimens, or platform evidence.

## Critical compatibility and correctness risks

| Risk | Status and evidence | Required resolution before porting |
|---|---|---|
| One filename has multiple formats | Confirmed: uniform true `.npy`, variable true `.npy`, and multimerge raw files collide at `seqs.npy`/`offsets.npy` | Specify discriminators and fixture every producer/consumer pairing |
| Python 2 integer division | Confirmed: shapes, indexes, chunks, run digits, bit-array offsets, and progress use `/` throughout Python and Cython | Classify every division; lock results with tests before choosing C/Python `//` semantics |
| Python 3 bytes/text boundary | Confirmed: Cython APIs use `bytes`/`char *`; CLI/path/input parsers yield text in Python 3; gzip yields bytes by default | Define facade policy and test types, non-ASCII paths, gzip, recovered-string return values |
| Invalid alphabet can corrupt memory | Confirmed: sentinel 6 feeds six-element arrays with bounds checks disabled; compiled query unknown bytes map to `$` | Validate at boundaries, add corruption tests, document changed failures |
| Native integer width | Confirmed: pervasive `unsigned long`; 32-bit on Windows x64, 64-bit on LP64 | Replace indexes with explicit width after equivalence tests; test >32-bit boundaries without requiring huge allocations |
| Binary I/O in C text mode | Confirmed: `fopen(..., 'w+')`/`'r'` used for binary data | Use binary mode in ports and mark Windows difference as correctness fix |
| NumPy full-file drift | Unverified magnitude: `.npy` headers are library-generated and structured descriptors are implicit | Capture legacy header bytes and implement/pin exact emission where required |
| Old derived indexes accepted blindly | Confirmed: existence generally bypasses dtype/shape/content validation | Specify validation/rebuild behavior and avoid silent stale-index results |
| No dataset/version manifest | Confirmed | Add only after proving old-reader and cleanup compatibility; retain filename-based reading |

## Source-visible legacy defects to characterize

These are candidates for intentional fixes, not instructions to preserve them in modern code.

1. `msbwt merge` uses local `numProcs` only after `args.numProcesses > 1`; the default path raises `NameError`. One input also indexes a nonexistent second input, while more than two merely logs an error.
2. BAM mate handling tests `r[1-j]` instead of `reads[1-j]`. The Cython BAM path then hands five-field tuples to a merger that unpacks three fields and writes a two-field provenance dtype.
3. `MUS.util` uses `gzip` without importing it. `MultiStringBWTCython.preprocessFastas` can lose the last record of each FASTA except the final file because the per-file accumulator is reset before it is emitted.
4. `loadBWT(..., logger=None)` calls `logger.error` on invalid directories. LCP-dependent methods can operate without `lcps.npy`; base `findReadsMatchingSeq` silently returns an empty set.
5. `cffq` and `pp`+`cfpp` do not retain the same artifact set; direct wrappers clean preprocessing files while CLI `cfpp` does not. Unsupported non-uniform compressed builds log errors yet can exit successfully with an output directory.

Additional confirmed defects/ambiguities:

- `TranscriptBuilder` reads `abt.npy`, while preprocessors write `about.npy`; `origins.npy` is recognized only to raise.
- Generic merge retains bit-packed `inter0.npy`, while transcript source-count code indexes it as if one array element represented one read/source.
- Python pure and compiled readers use different count caches (`totalCounts.p` versus `.npy`) and different write modes.
- Pure variable preprocessing can produce `seqs.npy.npy`; the compiled version uses `seqs.npy`.
- No-subcommand behavior attempts string concatenation with `None`.
- Empty datasets/read lists reach indexing, logarithm, division, or uninitialized-buffer paths.
- `CompressToRLE.compressInput` does not check `fopen`, handwrites a header, closes stdin, and accesses the first buffer byte even for empty input.
- RLE `removeStrings` rewrites primary bytes in place, leaves the `.npy` allocation at its old compressed length padded with zero bytes, and mixes manual little-endian and native writes in its deletion work file.
- LCP generation returns arrays but does not persist `lcps.npy`; work-file cleanup may leave the next empty `lcpList.*.dat`.
- CLI logger initialization adds another handler on every in-process call.

## Python 2 to Python 3 semantic risks

- `print` statements, `xrange`, `dict.has_key`, `.next()`, and implicit-relative imports are widespread.
- Dict ordering differs. Many output-sensitive keys are sorted, but not every `dict.keys()` iteration is demonstrably irrelevant.
- `range` materialization, iterator/list behavior, and `heapq.merge` tuple comparisons must be tested with NumPy scalar/string fields.
- Python 2 `str` is the compiled `bytes` contract. Modern Python callers naturally pass Unicode; automatic encoding could change accepted data or exception types.
- gzip/text file iteration and binary temporary-file writes change types. Newline translation can change input symbols.
- Exception messages/types, argparse formatting, pickle protocol, integer representation, and sorting of mixed scalar types can drift.
- `time.clock()` is removed. Replacing timing must not change control flow or persisted state.

## Cython 3 and C/API risks

- No source declares `language_level`; modern2 requires explicit level 2, modern3 level 3.
- Cython 3 binding, arithmetic, exception, `nogil`, `char *` conversion, and NumPy memoryview rules differ from 0.18/0.23.4.
- Generated C directly touches obsolete CPython internals and must be regenerated; compiling it is not a meaningful current-Python strategy.
- Many `nogil` loops rely on disabled bounds/initialized checks and pointer casts stored in `uint64` arrays. Audit pointer lifetime, alignment, and Windows width.
- Base virtual methods are dummy zero/no-op implementations. Cython dispatch changes could silently call them instead of subclass methods.
- `BasicBWT.pxd` is part of the installed package and therefore a Cython consumer ABI surface. Changing cdef layout breaks downstream compiled modules even if Python tests pass.
- NumPy 2 C API and dtype/memoryview validation may reject assumptions accepted by NumPy 1.10.
- Regenerated C will not be byte-identical across Cython versions/paths; reproducibility applies to controlled regeneration and wheels, not matching 2016 C text.

## Persistence and mutual-readability risks

- `.npy` version/header formatting, structured unnamed fields, scalar shape spelling, and pickle cannot be treated as abstract NumPy values when bit equality is required.
- RLE has no format marker and permits zero base-32 digits within a run. Reader behavior on malformed same-symbol sequences is not validated.
- LZW primary format is reader-only in this tree; no specimen or writer is present. Its true compatibility importance is unknown.
- `about.npy` source IDs are `uint8`, limiting input files to 256 and using 255 as a BAM sentinel. Read IDs are `uint64`.
- Dollar IDs depend on stable suffix tie ordering. Duplicate reads and multiprocessing are therefore essential golden cases.
- Loading is mutating: missing count/FM files are created. Read-only legacy datasets can fail even for queries.
- An interrupted writer can leave a primary file and stale derived indexes; existence-based loading may accept the mixture.
- Compressed and byte primaries can coexist; old loader preference may hide one. Writer/read matrix must test coexistence.

## Security and operational risks

- Pickle and old NumPy object loading make untrusted dataset directories code-execution risks.
- Corrupt/unvalidated arrays plus unchecked Cython memory access can crash the interpreter or corrupt memory.
- Recursive regex and unconstrained process counts permit CPU/memory exhaustion; gzip and giant record lines permit decompression/memory denial of service.
- Output cleanup uses broad prefix globs and in-place deletes. APIs do not enforce an empty dedicated output directory.
- Recovery files lack locks/checksums. Two processes operating on one directory can corrupt it.
- Writable memmaps mean query processes can unexpectedly require and possess mutation rights.
- There is no security policy, supported-version statement, dependency scanning, or release provenance.

## Performance risks to measure, not guess

- Porting Python loops directly may expose large Python 3 overhead; conversely, Cython 3 can change generated code and release the GIL differently.
- Windows spawning serializes more state than Unix fork and may amplify current multiprocessing assumptions.
- Stable/validated I/O and atomic output can add costs that need operation-specific baselines.
- Fixed 2048 FM samples, chunk sizes, 1 GB thresholds, per-read BWT construction, and LCP search-space behavior may dominate differently on SSD/HPC storage.
- Memory mapping behavior and page cache make one-shot timing misleading. Output hashes must accompany benchmark results.

## Questions the repository cannot answer

1. Which CLI commands and imported functions do real users depend on, especially pure-Python modules, approximate/LCP APIs, transcript assembly, BAM/FASTA builders, and LZW?
2. Must `msbwt-modern2` and `msbwt-modern3` ever be installed simultaneously in one environment, despite identical legacy import packages and command name?
3. Do original production datasets exist for every primary/provenance form, particularly LZW (`comp_msbwt.dat`/`comp_offsets.npy`), `origins.npy`, `abt.npy`, `auxiliary.npy`, and `backrefs.npy`?
4. What exact historical Python/NumPy/pysam/Cython/compiler environment produced trusted datasets, and are any trusted raw hashes available?
5. Is `about.npy`/interleave provenance a required cross-merge contract, and what are the intended semantics for paired reads and dollar-ID tie ordering?
6. Which original bugs were relied on operationally, and what deprecation window is acceptable for corrected CLI exit codes/errors?
7. Which public bacterial and viral accessions and licenses should be canonical repository fixtures? This requires live archive selection and checksum verification.
8. What are acceptable package licenses/distribution channels and wheel baselines for the Python 2 release, especially bundled pysam/native dependencies?
9. Which HPC schedulers, compilers, filesystems, offline-build constraints, and CPU architectures represent required environments?
10. May modern writers add ignored metadata/checksum files to dataset directories, or must the exact directory file set remain unchanged?

## Decisions to make after evidence collection

After the legacy oracle produces goldens, decide and record:

- Python 3 sequence return/input types and path encoding;
- exact `.npy` writer/header strategy;
- whether LZW remains a supported read-only format;
- which auxiliary/recovery files are formal compatibility surfaces;
- safe default for read-only versus writable memmaps;
- coexistence policy for byte/RLE primaries and the two distributions;
- severity/compatibility entries for each confirmed legacy defect.

None of these decisions requires algorithm redesign during the initial compatibility port.
