# Forensic repository audit

Audit date: 2026-08-08
Audited commit: `7503346` (`pre-modernization`, upstream `master`)
Working branch: `codex/modernization`

## Audit boundary and evidence

The audit covered every tracked file in the repository: 6 Python files in `MUS` (including the empty package initializer), 12 `.pyx` extensions, `BasicBWT.pxd`, 12 generated C files, the launcher, build metadata, README, authorship, license, and Git history relevant to tests/build compatibility. The repository contains no test directory, CI configuration, dependency lock, benchmark, sample dataset, or format specification.

The host has CPython 3.14.6 and NumPy 2.5.1, but no Python 2, Cython, pysam, C compiler, Docker, or Podman. Four Python modules fail Python 3 syntax parsing. Therefore this document distinguishes source conclusions from behavior that still requires execution in a reconstructed Python 2 environment. No legacy build or biological operation was claimed to pass.

## Repository structure

| Area | Role | Audit result |
|---|---|---|
| `MUS/CommandLineInterface.py` | argparse CLI and dispatch | Nine subcommands; several source-visible failure paths |
| `MUS/MultiStringBWT.py` | older pure-Python readers, preprocessing, querying, BAM handling | Still packaged and importable on Python 2; behavior diverges from Cython path |
| `MUS/MSBWTGen.py` | older builders, merge, CLI compression/decompression | CLI still calls its compression/decompression, so it is not dead code |
| `MUS/TranscriptBuilder.py` | graph/transcript assembly | Imports `pyximport` at module import and references stale artifact names |
| `MUS/util.py` | CLI validators and FASTA/FASTQ iterators | Missing `gzip` import for its gzip iterators |
| `MUSCython/BasicBWT.pyx/.pxd` | compiled base query API | Largest public API; unchecked mapping and LCP preconditions |
| `ByteBWTCython.pyx` | byte-per-symbol reader/FM index | Preferred loader when `msbwt.npy` exists |
| `RLE_BWTCython.pyx` | base-32 RLE reader/query/deletion | Mutates datasets in place; derived-index formats |
| `LZW_BWTCython.pyx` | LZW reader | Reader exists; no writer exists in this repository |
| builder/merge extensions | uniform, compressed, variable-length, and two-BWT algorithms | Multiple overlapping algorithms and recovery schemes |
| `AlignmentUtil.pyx`, `LCPGen.pyx` | edit alignment and LCP generation | Public compiled functions not surfaced by the CLI |
| generated `.c` | legacy Cython output | Mixed Cython 0.18 and 0.23.4; obsolete CPython API access |

A tracked 156-byte `MUS/__init__.pyc` is a Python 2-era bytecode file containing the original developer path `/Users/Matt/Documents/workspace/MsbwtUtilitySuite/...`. It is historical/build debris, not a usable cross-version package asset. There is no `.gitignore`.

## Build and distribution system

`setup.py` defines distribution `msbwt` version `0.3.0`, packages `MUS` and `MUSCython`, 12 extensions, `numpy` in `setup_requires`, and `numpy`/`pysam` in `install_requires`. It installs `bin/msbwt` as a script. Both `__init__.py` files are empty; no explicit re-exports define a public API.

Key findings:

1. Imports throughout rely on Python 2 implicit-relative behavior (`import MSBWTGenCython`, `import MultiStringBWT`, `import util`). These resolve differently under Python 3.
2. If Cython is installed, all extensions build from `.pyx`; the language level is unspecified. The custom `sdist` cythonizes each file using whatever Cython happens to be installed.
3. Without Cython, 11 extensions use committed C but `CompressToRLE` mistakenly uses `CompressToRLE.pyx`, so the advertised generated-C fallback is broken.
4. Generated files identify six modules as Cython 0.18 output and six as Cython 0.23.4 output. They directly use removed/changed CPython internals such as old `PyCode_New`, `PyThreadState` exception fields, and `tp_print`; they are not a viable latest-CPython source.
5. NumPy headers are added late in a custom `build_ext`. No `NPY_NO_DEPRECATED_API` boundary is defined, and generated code embeds old NumPy buffer/API assumptions.
6. `setup.cfg` hardcodes `install_scripts=/usr/local/bin`, conflicting with virtual environments, Windows, and normal scheme selection. The launcher shebang is `#! /bin/env python`, not a portable `/usr/bin/env` shebang.
7. `MANIFEST.in` names `README` although only `README.md` exists. Modern setuptools may add README automatically, but the manifest claim itself is stale.
8. No Python version classifiers, wheel configuration, compiler flags, build isolation, exact dependency bounds, or platform configuration exist.

## Dependencies and external behavior

Direct runtime imports are NumPy, pysam, and (only for `TranscriptBuilder`) Cython's `pyximport`. Standard-library dependencies include argparse, gzip, multiprocessing, threading, pickle, heapq, glob, shutil, and logging. README-reported tested versions are NumPy 1.10.1 and pysam 0.7.4; these are unverified historical claims, not current constraints.

No code reads environment variables, opens network connections, invokes a shell, or launches subprocess commands. Multiprocessing and thread pools are used heavily. Filesystem paths are assembled with `/` string concatenation and several C APIs accept `char *`, creating Python 3 Unicode/path-encoding and Windows risks.

## Algorithm families and dispatch

The code contains overlapping implementations rather than one pipeline:

- Uniform reads: column-oriented Bauer/Cox-style construction in `MSBWTGenCython` or direct RLE construction in `MSBWTCompGenCython`. Preprocessing lexicographically sorts sequences and writes one encoded column per file.
- Non-uniform reads: `MultimergeCython` first computes a cyclic BWT for each read, stores all of them in a raw byte file, and repeatedly solves bit-packed interleaves in groups (initially up to 256, later 2) until one MSBWT remains.
- Existing BWT merge: `GenericMerge` computes a bit interleave for two readers, then materializes `msbwt.npy`. It can read byte, RLE, or LZW input through the generic loader, despite older comments claiming byte-only input.
- Compression: CLI `compress` uses the pure-Python `MUS/MSBWTGen.py` implementation. A near-duplicate Cython implementation exists but is not the CLI dispatch target.
- Query: CLI imports the Cython generic loader. The loader prefers byte format, then RLE, then LZW if multiple primary files coexist.
- Decompression: CLI uses the pure-Python compressed reader and writes a byte BWT in fixed-size chunks.

Algorithms use the fixed symbol order `$`, `A`, `C`, `G`, `N`, `T`, encoded as 0 through 5. Other input bytes are not validated at core boundaries.

## Threading, process, recovery, and determinism

- Uniform build, compression, decompression, per-read preprocessing, and variable-length merge can create process pools. Generic two-BWT merge forcibly reduces its process count to one.
- `MultimergeCython` uses `imap_unordered` for disjoint sub-merges and contains a threaded range solver with shared bit arrays and boundary locking. Output determinism across process counts has not been demonstrated.
- Input filename order is preserved. Uniform preprocessing sorts tuples `(sequence, file_id, read_id)` and merges sorted runs with `heapq.merge`, giving an explicit tie-break. Most dictionary keys are sorted before output-sensitive construction, but some dictionary iteration remains.
- Recovery mechanisms are operation-specific: uniform compressed build scans `state.*`, `fmStarts.*`, and `fmDeltas.*`; variable merge scans `backup.*.npy`. Some older recovery code is commented/incomplete.
- Temporary file cleanup is not transactional. Interruption can leave files that a later run may treat as recovery state. There is no manifest, checksum, lock, atomic publish step, or format/version marker.
- CLI logs contain wall-clock timestamps, so byte-identical stdout is impossible without normalizing the timestamp field. Dataset bytes should still be deterministic; this requires proof across process counts and platforms.

## Platform and binary assumptions

Persistent numeric arrays normally request little-endian `<u8`, `<u4`, or byte types. Single-byte primary BWTs are endian-neutral. Raw offsets are emitted from a `<u8` array and therefore little-endian. However:

- Cython uses `unsigned long` for most sizes and indexes. It is 64-bit on LP64 Linux/macOS but 32-bit on 64-bit Windows (LLP64), limiting large datasets and creating ABI differences.
- Several C `fopen` calls use text modes (`r`, `w+`) for binary bytes. Windows newline translation can corrupt NumPy headers, raw compressed state, LCP work files, and deletion-index files.
- `removeStrings` manually writes most deletion indexes little-endian but writes each final read ID with native `unsigned long` byte order/width before reading the whole file as `<u8`.
- Bounds checking, wraparound checks, and often initialized checks are disabled. Corrupt arrays or invalid symbols can read/write outside allocated memory instead of raising Python errors.
- Hard-coded memory/file thresholds, path separators, and assumptions about writable input datasets are pervasive. Default Cython loaders open primary and auxiliary arrays in `r+`, so a query may require write access.

No present evidence supports Windows, macOS, ARM64, big-endian, WSL, Conda, or current HPC toolchains. Historical use appears Unix/Python 2 oriented.

## NumPy and serialization findings

- Primary arrays are NumPy `.npy` v1-style products in most paths, but NumPy decides header padding/version. A dependency change can alter full-file bytes even when payloads match.
- Several structured dtypes are specified as comma strings without field names; NumPy assigns `f0`, `f1`, etc. Their descriptor spelling and header representation are part of the byte contract.
- Pure-Python readers use `totalCounts.p`, a pickle opened in text mode. Cython readers use numeric `totalCounts.npy`. Both are recognized/removed as historical auxiliary forms.
- `np.load` calls do not specify `allow_pickle`. With historical NumPy defaults, loading a malicious object array can execute pickle payloads.
- The code uses deprecated/changed APIs including `np.fromstring` for binary strings, `.tostring()`, old memmap calling conventions, and shape expressions dependent on Python 2 integer division.
- Some files named `.npy` are intentionally headerless raw binary. Consumers must choose `np.load` versus `np.memmap` based on the construction path, not the suffix.

## pysam and biological input

The BAM path uses obsolete `pysam.Samfile`, iterator `.next()`, `.qname`, and `.seq`. It assumes name-sorted BAM and reconstructs original orientation for reverse-complemented alignments. Source-visible defects make the current BAM surface unreliable:

- Mate detection checks `r[1-j]` where `r` is the read string, not `reads[1-j]`; mate provenance is therefore wrong and can raise on very short reads.
- The Cython BAM preprocessor emits five-field sort records but calls `mergeSubSorts`, which unpacks three fields and creates a two-field `about.npy`.
- Empty BAM input calls `.next()` without handling `StopIteration`; files are not explicitly closed.

FASTQ parsers take every second line of each four-line group, ignore names/qualities, and do not validate record structure, alphabet, uniformity unless a uniform Cython path is selected, or final partial records. They strip `\n` but not explicitly `\r`. Gzip is opened in binary-default mode, which is a Python 3 bytes/str fault. FASTA support exists only in APIs, not the CLI.

## Security-sensitive findings

1. Loading `totalCounts.p` from an untrusted dataset invokes pickle; historical `np.load` defaults can also unpickle object arrays.
2. Invalid symbols map to sentinel value 6 and are then used against six-element arrays while bounds checks are disabled. Query maps unknown bytes to 0 (`$`). These can yield silent wrong results, crashes, or memory corruption.
3. LCP-dependent calls do not consistently reject datasets without `lcps.npy`; they may access an uninitialized memoryview.
4. C `fopen` results are not checked before `fread`/`fwrite`. Invalid paths or permissions can reach null FILE pointers.
5. Process counts are unrestricted; zero, negative, or huge values cause exceptions or resource exhaustion. Regex `*` search can expand recursively without a work limit.
6. Cleanup can delete every `seqs.npy*` file in an API-provided directory, and RLE deletion mutates primary data in place without rollback. Output directory validation is not a security boundary.

These issues warrant fixes, but fixes must receive explicit compatibility entries and legacy-oracle tests rather than being silently folded into the port.

## Documentation and provenance

The MIT license, original author James Holt, UNC-CH attribution, and the Holt/McMillan publications are present. README covers the nine CLI commands and common files but omits most compiled APIs, LCP/LZW/deletion/transcript features, recovery files, raw-vs-NumPy format differences, and known limitations. URLs and installation instructions are historical.

## Existing verification coverage

There are zero automated tests in the current tree and none were found as deleted source tests in Git history. Commit `102fe83` saying “removing test” removed only a 13-line wiki page. There are no CI checks, fixtures, goldens, coverage configuration, benchmarks, wheels, or release workflows. All claimed historical behavior must be reconstructed and captured before modernization.
