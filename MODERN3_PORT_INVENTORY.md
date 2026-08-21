# Modern3 Port Inventory

Repository-wide inventory of every surface requiring attention for the Python 2 → Python 3 port of msbwt-modern3. Generated from the `enhanced-modern3` branch at tag `msbwt-enhanced-modern2-0.3.0` (commit `746cf93`). Repaired M3-0R: now covers the complete enhanced-modern2 implementation (F1–F13A/Q1).

---

## 1. Distribution Structure

### 1.1 Two distributions in one monorepo

| Distribution | Path | Target |
|---|---|---|
| `msbwt` (root) | `MUS/`, `MUSCython/` | Original frozen core |
| `msbwt-modern2` | `packages/msbwt-modern2/` | Python 2.7 + Cython 3.0.12; includes frozen core + enhanced features |
| `msbwt-modern3` (planned) | `packages/msbwt-modern3/` | Python 3 target; does not yet exist |

### 1.2 packages/msbwt-modern2/ layout

```
packages/msbwt-modern2/
  MUS/               # 17 .py modules (frozen legacy + 11 enhanced)
  MUSCython/         # 11 .pyx + 1 .pxd + 11 .c + __init__.py
  tools/             # 6 console-script entry points
  tests/             # 24 test_*.py + _npy_compat.py helper
  validate/          # 43 shell/python evidence drivers
  evidence/          # 28 .json executed-evidence records
  environment/       # pinned build profile + locks
  setup.py           # distribution metadata (v0.3.0)
  bin/msbwt          # CLI launcher
```

---

## 2. Complete Module Inventory

### 2.1 Legacy/frozen MUS modules (in both root and modern2)

| Module | Purpose | Python 2 issues |
|---|---|---|
| `CommandLineInterface.py` | argparse CLI dispatch (9 subcommands + global) | `print` statements, `xrange`, implicit relative import |
| `MSBWTGen.py` | Pure-Python builders, merge, compress/decompress | `print`, `xrange`, `has_key`, integer division `/`, implicit imports |
| `MultiStringBWT.py` | Pure-Python readers, preprocessing, BAM, profiles | `print`, `xrange`, `has_key`, `.next()`, pickle text-mode I/O, `np.fromstring` with str, implicit imports |
| `TranscriptBuilder.py` | Graph/transcript assembly | `print`, `xrange`, `has_key` |
| `util.py` | CLI validators, FASTA/FASTQ iterators | gzip text-mode OK in Py3 |

### 2.2 Enhanced MUS modules (modern2 only)

| Module | Feature | Purpose | Python 2/3 issues |
|---|---|---|---|
| `SourceIndex.py` | F1 | Two-source rank-aware queries over `inter0.npy` | Pure Python; no Py2 syntax; `unicode` type check in `BWTTags.py` consumed |
| `MultiSourceProvenance.py` | F2 | N-source provenance tree + interleave persistence | Pure Python; atomic JSON writes; `os.replace` fallback needed |
| `MultiSourceQuery.py` | F3–F9, F11A, F12, Q1 | Constituent queries, extensions, read provenance, tags, quality, LCP | Pure Python; `unicode` type check for sequence normalization; `bytes([v])` pattern |
| `SourceMetadata.py` | F7 | Mutable source metadata + named groups | Pure Python; atomic JSON I/O |
| `ReadProvenance.py` | F9 | 20-byte/read lossless read identity | Pure Python; `np.save` with structured dtype |
| `SourceRemoval.py` | F10 | Remove/unmerge sources without FASTQ rebuild | Pure Python; reads all F1–F12 files |
| `BWTTags.py` | F12 | Generic row-aligned tag arrays | Pure Python; `unicode` type check; `np.save` with `allow_pickle=False` |
| `QualitySidecar.py` | Q1 | Exact lossless FASTQ quality sidecar | Pure Python; `unicode` type check; `np.memmap` for FASTQ archive |
| `LCP.py` | F11A | Exact post-construction LCP retrofit | Pure Python; `open_memmap` for temp arrays |
| `Benchmarking.py` | F13A | Whole-index structural + query benchmark | Pure Python; reads all files via `os.walk` |
| `BackendContract.py` | F13A | Semantic contract specification | Pure Python; no I/O |

### 2.3 Compiled MUSCython modules (in both root and modern2)

| Module | Purpose | Key Python 2/3 issues |
|---|---|---|
| `BasicBWT.pyx` + `.pxd` | Base query API (installed ABI surface) | `xrange`, `unsigned long`, `nogil` blocks, `char *` views |
| `ByteBWTCython.pyx` | Uncompressed byte BWT reader | `shape` accessor, `np.load` modes |
| `RLE_BWTCython.pyx` | RLE BWT reader/query/deletion | `xrange`, `fopen` text modes, integer division |
| `LZW_BWTCython.pyx` | LZW BWT reader | `shape` accessor, `np.memmap`, `np.fromfile` |
| `MultimergeCython.pyx` | Multi-way merge BWT construction | `xrange`, integer division, `char *` paths, `pool.terminate()`, `tostring()` |
| `MultiStringBWTCython.pyx` | Top-level Cython API (loadBWT, create, preprocess) | `np.fromstring` with str, implicit imports, `.next()` |
| `MSBWTGenCython.pyx` | Uniform column-wise builder | `xrange`, `has_key`, `print`, integer division, `np.load` modes |
| `MSBWTCompGenCython.pyx` | Compressed uniform builder | `xrange`, `fopen` text modes |
| `GenericMerge.pyx` | Two-BWT merge via bit interleave | `xrange`, integer division, `char *` paths |
| `CompressToRLE.pyx` | Text-to-RLE streaming converter | `fopen` text modes, `xrange` |
| `AlignmentUtil.pyx` | Edit-distance alignment | `char *` views, `unsigned long` |
| `LCPGen.pyx` | LCP generation (DEAD/PRIVATE stub in modern2) | `fopen` text modes, not reachable from public API |

---

## 3. Enhanced Feature Surface (F1–F13A/Q1)

### 3.1 Feature summary

| Feature | Module(s) | CLI tool | New persisted files |
|---|---|---|---|
| F1 Two-Source Rank | `SourceIndex.py` | — | `inter0_rank.npz` (derived) |
| F2 Multi-Source Provenance | `MultiSourceProvenance.py` | — | `provenance.json`, `provenance/interleaves/*.npy` |
| F3 Query One Constituent | `MultiSourceQuery.py` | — | `provenance/ranks/*.npz` (derived) |
| F4 Sparse Source Listing | `MultiSourceQuery.py` | — | (extends F3) |
| F5 Source Frequency | `MultiSourceQuery.py` | — | (extends F3) |
| F6 Top-K Sources | `MultiSourceQuery.py` | — | (extends F3) |
| F7 Subsets/Groups/Predicates | `SourceMetadata.py`, `MultiSourceQuery.py` | — | `source_metadata.json` (mutable) |
| F8A Sequence Extensions | `MultiSourceQuery.py` | — | (no new files) |
| F9 Read Provenance | `ReadProvenance.py` | `retrofit_read_provenance.py` | `read_provenance.npy`, `read_provenance.json` |
| F10 Source Removal | `SourceRemoval.py` | `remove_sources.py` | (filtered copies of all layers) |
| F11A LCP | `LCP.py` | `lcp.py` | `lcps.npy`, `lcp.json` |
| F12 BWT Tags | `BWTTags.py` | `bwt_tags.py` | `bwt_tags.json`, `bwt_tags/tag_*.npy` |
| F13A Benchmark/Contract | `Benchmarking.py`, `BackendContract.py` | `benchmark_index.py` | (benchmark report JSON only) |
| Q1 Quality Sidecar | `QualitySidecar.py` | `quality_sidecar.py` | `quality_sidecar.json`, (tag array via F12) |

### 3.2 All persisted file formats

| File/Pattern | Classification | Producer(s) | Consumer(s) |
|---|---|---|---|
| `msbwt.npy` | AUTHORITATIVE (baseline) | builders, merge, decompress | `ByteBWT`, `RLE_BWT`, all enhanced modules |
| `comp_msbwt.npy` | AUTHORITATIVE (baseline) | RLE builder, compress, convert | `RLE_BWT` |
| `comp_msbwt.dat` | AUTHORITATIVE (baseline, read-only) | none in tree | `LZW_BWT` |
| `comp_offsets.npy` | AUTHORITATIVE (baseline, read-only) | none in tree | `LZW_BWT` |
| `about.npy` | AUTHORITATIVE (baseline) | preprocessors | `ReadProvenance`, provenance consumers |
| `inter0.npy` | AUTHORITATIVE (baseline + F2 root) | `GenericMerge`, `MultiSourceProvenance` | `SourceIndex`, `MultiSourceQuery`, `BWTTags`, `QualitySidecar` |
| `totalCounts.npy` | DERIVED (compiled reader side-effect) | compiled readers | compiled readers |
| `totalCounts.p` | DERIVED (pure reader side-effect) | pure-Python reader | pure-Python reader |
| `fmIndex.npy` | DERIVED (compiled reader side-effect) | compiled readers | `ByteBWT` |
| `comp_fmIndex.npy` | DERIVED (compiled reader side-effect) | compiled readers | `RLE_BWT` |
| `comp_refIndex.npy` | DERIVED (compiled reader side-effect) | compiled readers | `RLE_BWT` |
| `lzw_fmIndex.npy` | DERIVED (compiled reader side-effect) | compiled readers | `LZW_BWT` |
| `provenance.json` | AUTHORITATIVE (F2) | `MultiSourceProvenance` | `MultiSourceQuery`, `SourceRemoval`, `BWTTags`, `QualitySidecar` |
| `provenance/interleaves/<uuid>.npy` | AUTHORITATIVE (F2) | `MultiSourceProvenance` | `MultiSourceQuery`, `SourceRemoval`, `BWTTags` |
| `inter0_rank.npz` | DERIVED/REBUILDABLE (F1) | `SourceIndex` | `SourceIndex` |
| `provenance/ranks/<node-id>.npz` | DERIVED/REBUILDABLE (F3) | `MultiSourceQuery` | `MultiSourceQuery` |
| `source_metadata.json` | MUTABLE/REBUILDABLE (F7) | `SourceMetadata` | `MultiSourceQuery`, `SourceRemoval` |
| `read_provenance.npy` | AUTHORITATIVE (F9) | `ReadProvenance` | `MultiSourceQuery`, `QualitySidecar`, `SourceRemoval` |
| `read_provenance.json` | AUTHORITATIVE (F9) | `ReadProvenance` | `MultiSourceQuery`, `QualitySidecar`, `SourceRemoval` |
| `bwt_tags.json` | AUTHORITATIVE (F12) | `BWTTags` | `BWTTags`, `MultiSourceQuery`, `QualitySidecar`, `SourceRemoval` |
| `bwt_tags/tag_<hash>.npy` | AUTHORITATIVE (F12) | `BWTTags` | `BWTTags`, `MultiSourceQuery`, `QualitySidecar`, `SourceRemoval` |
| `quality_sidecar.json` | AUTHORITATIVE (Q1) | `QualitySidecar` | `QualitySidecar`, `MultiSourceQuery`, `SourceRemoval` |
| `lcps.npy` | AUTHORITATIVE (F11A) | `LCP` | `LCP`, `MultiSourceQuery`, `SourceRemoval` |
| `lcp.json` | AUTHORITATIVE (F11A) | `LCP` | `LCP`, `MultiSourceQuery`, `SourceRemoval` |

### 3.3 Recovery/temporary artifacts

| Pattern | Producer | Consumer |
|---|---|---|
| `state.<symbol>.<column>.npy` / `.dat` | uniform builders | builder recovery |
| `fmStarts.<column>.npy` | builders | builder recovery |
| `fmDeltas.<column>.npy` | builders | builder recovery |
| `inserts.*.<column>.npy` | builders | builder recovery |
| `backup.<group_size>.npy` | multimerge | multimerge recovery |
| `msbwt.temp.<offset>.npy` | multimerge | multimerge |
| `comp_msbwt.npy.temp.<bin>.npy` | compression | compression recovery |
| `deletion_indices.dat` | RLE deletion | RLE deletion |

---

## 4. Public API Surface

### 4.1 MUS package (must remain importable)

**Frozen legacy:**
- `MUS.CommandLineInterface`, `MUS.MSBWTGen`, `MUS.MultiStringBWT`, `MUS.TranscriptBuilder`, `MUS.util`

**Enhanced (modern2 only):**
- `MUS.SourceIndex`, `MUS.MultiSourceProvenance`, `MUS.MultiSourceQuery`
- `MUS.SourceMetadata`, `MUS.ReadProvenance`, `MUS.SourceRemoval`
- `MUS.BWTTags`, `MUS.QualitySidecar`, `MUS.LCP`
- `MUS.Benchmarking`, `MUS.BackendContract`

### 4.2 MUSCython package (must remain importable)

- `MUSCython.AlignmentUtil`, `MUSCython.BasicBWT`, `MUSCython.ByteBWTCython`
- `MUSCython.CompressToRLE`, `MUSCython.GenericMerge`, `MUSCython.LCPGen` (DEAD/PRIVATE stub)
- `MUSCython.LZW_BWTCython`, `MUSCython.MSBWTCompGenCython`, `MUSCython.MSBWTGenCython`
- `MUSCython.MultimergeCython`, `MUSCython.MultiStringBWTCython`, `MUSCython.RLE_BWTCython`

### 4.3 Enhanced console scripts (6 entry points)

| Script | Module | Subcommands |
|---|---|---|
| `msbwt-bwt-tags` | `tools/bwt_tags.py` | `list`, `validate`, `attach`, `retrofit`, `remove` |
| `msbwt-lcp` | `tools/lcp.py` | `construct`, `validate`, `inspect` |
| `msbwt-quality-sidecar` | `tools/quality_sidecar.py` | `init-leaf`, `retrofit-merged`, `validate`, `recover` |
| `msbwt-remove-sources` | `tools/remove_sources.py` | single command (`--remove`/`--keep`/`--group`/`--where`) |
| `msbwt-retrofit-read-provenance` | `tools/retrofit_read_provenance.py` | single command (`--merged`, `--source`) |
| `msbwt-benchmark-index` | `tools/benchmark_index.py` | `inspect`, `compare`, `query`, `contract` |

---

## 5. Python 2-Only Syntax and Semantics

### 5.1 `print` statements (syntax error in Python 3)

| File | Count | Notes |
|---|:-:|---|
| `MUS/CommandLineInterface.py` | 3 | `print expr` form |
| `MUS/TranscriptBuilder.py` | 2 | `print 'ERROR...'` |
| `MUS/MSBWTGen.py` | 2 | progress/error |
| `MUS/MultiStringBWT.py` | 18 | debug/info |
| `MUSCython/MSBWTGenCython.pyx` | 4 | debug |
| `MUSCython/MultiStringBWTCython.pyx` | 1 | debug |
| `MUSCython/RLE_BWTCython.pyx` | 1 | failure |
| **Total** | **31** | |

### 5.2 `xrange` usage (NameError in Python 3)

| File | Count |
|---|:-:|
| `MUS/MSBWTGen.py` | 28 |
| `MUS/MultiStringBWT.py` | 4 |
| `MUS/TranscriptBuilder.py` | 2 |
| `MUS/CommandLineInterface.py` | 1 |
| `MUSCython/BasicBWT.pyx` | 9 |
| `MUSCython/GenericMerge.pyx` | 5 |
| `MUSCython/MultimergeCython.pyx` | 30+ |
| `MUSCython/MSBWTGenCython.pyx` | 8 |
| `MUSCython/MSBWTCompGenCython.pyx` | 2 |
| `MUSCython/CompressToRLE.pyx` | 1 |
| `MUSCython/RLE_BWTCython.pyx` | 5 |
| **Total** | **95+** | |

### 5.3 `dict.has_key()` (removed in Python 3)

| File | Count |
|---|:-:|
| `MUS/TranscriptBuilder.py` | 6 |
| `MUS/MSBWTGen.py` | 5 |
| `MUS/MultiStringBWT.py` | 3 |
| `MUSCython/MSBWTGenCython.pyx` | 4 |
| **Total** | **18** | |

### 5.4 `.next()` method calls (use `next()` in Python 3)

| File | Count |
|---|:-:|
| `MUS/MultiStringBWT.py` | 2 |
| `MUSCython/MultiStringBWTCython.pyx` | 2 |
| **Total** | **4** | |

### 5.5 Python 2 implicit-relative imports (fail in Python 3)

| File | Import |
|---|---|
| `MUS/MSBWTGen.py` | `import MultiStringBWT` |
| `MUS/MultiStringBWT.py` | `import MSBWTGen` |
| `MUS/CommandLineInterface.py` | `import MSBWTGen` |
| `MUSCython/BasicBWT.pyx` | `import MultiStringBWTCython` |
| `MUSCython/GenericMerge.pyx` | `import MultiStringBWTCython` |
| `MUSCython/MultimergeCython.pyx` | `import MSBWTGenCython` |
| `MUSCython/RLE_BWTCython.pyx` | `import MSBWTGenCython; import AlignmentUtil` |
| `MUSCython/MSBWTGenCython.pyx` | `import MultiStringBWTCython` |
| `MUSCython/MultiStringBWTCython.pyx` | `import MSBWTGenCython; import MSBWTCompGenCython` |
| `MUSCython/MultiStringBWTCython.pyx` | `from ByteBWTCython import ByteBWT` |
| `MUSCython/MultiStringBWTCython.pyx` | `from RLE_BWTCython import RLE_BWT` |
| `MUSCython/MultiStringBWTCython.pyx` | `from LZW_BWTCython import LZW_BWT` |
| `MUSCython/MSBWTCompGenCython.pyx` | `import MSBWTGenCython` |

### 5.6 Integer division `/` (returns float in Python 3)

**WARNING:** Not every `/` on integers is a semantic floor division. Each expression must be individually audited for preserved semantics. Some `/` expressions in the codebase are intentionally floating-point (e.g., `float(self.totalSize+1)/self.binSize` in `ByteBWTCython.pyx:116`). The following are the locations requiring audit:

| File | Lines (examples) | Typical pattern |
|---|---|---|
| `MUS/MSBWTGen.py` | 376, 840–844, 875, 895, 966, 1006, 1010, 1187, 1191 | `shape[0]/binSize`, `numSeqs/numProcs` |
| `MUS/MultiStringBWT.py` | 292, 1100 | `shape[0]/binSize`, `len(seqArray)/3` |
| `MUSCython/GenericMerge.pyx` | 59, 83, 92, 560, 564 | `bwtLen/8` (byte-offset) |
| `MUSCython/MultimergeCython.pyx` | 197, 228, 237, 627, 812, 910, 944, 949, 950, 953, 1641, 1645 | `bwtLen/8`, `seqs.shape[0]/seqLen` |
| `MUSCython/MSBWTGenCython.pyx` | 446, 450, 451, 643, 647, 741 | `shape[0]/binSize` |
| `MUSCython/ByteBWTCython.pyx` | 116 | `float(...)/self.binSize` — already float; **leave as-is** |
| `MUSCython/RLE_BWTCython.pyx` | 177, 347 | `float(...)/binSize` — already float; **leave as-is** |

---

## 6. Bytes/String Assumptions

### 6.1 `np.fromstring` with string input (TypeError in Python 3)

| File | Line | Issue |
|---|---|---|
| `MUS/MultiStringBWT.py` | 773 | `np.fromstring(seqCopy, dtype='<u1')` where `seqCopy` is `str.join()` result |
| `MUSCython/MultiStringBWTCython.pyx` | 90, 122 | Same pattern |

### 6.2 Cython `char *` function parameters

In Cython 3 with `language_level=3`, implicit `str`→`char*` auto-encoding is NOT safe for non-ASCII Unicode filesystem paths. Each signature must be explicitly typed as `str` or `bytes`, or validated to reject non-ASCII input.

Key affected signatures:
- `MultimergeCython.createMSBWTFromSeqs(list, char *, ...)`
- `MultimergeCython.mergeTwoMSBWTs(char *, char *, char *, ...)`
- `GenericMerge.mergeTwoMSBWTs(char *, char *, char *, ...)`
- `ByteBWTCython.loadMsbwt(self, char *, ...)`
- `RLE_BWTCython.loadMsbwt(self, char *, ...)`
- `LZW_BWTCython.loadMsbwt(self, char *, ...)`

### 6.3 `.tostring()` → `.tobytes()` (removed in NumPy 2.0)

| File | Lines |
|---|---|
| `MUSCython/MultimergeCython.pyx` | 482, 495, 597 |

### 6.4 Python 2 `unicode`/`basestring` type references

| File | Type | Count |
|---|---|:-:|
| `MUS/BWTTags.py` (modern2) | `unicode` | 2 |
| `MUS/QualitySidecar.py` (modern2) | `unicode` | 2 |
| `MUS/MultiSourceQuery.py` (modern2) | `unicode` | 1 |
| Test files (modern2) | `unicode`, `basestring`, `long` | 5 |

---

## 7. Binary/Text I/O

### 7.1 Pickle in text mode (will crash in Python 3)

| File | Line | Issue |
|---|---|---|
| `MUS/MultiStringBWT.py` | 245 | `open(abtFN, 'r')` for pickle load |
| `MUS/MultiStringBWT.py` | 261 | `open(abtFN, 'w+')` for pickle dump |
| `MUS/MultiStringBWT.py` | 422 | Same (CompressedMSBWT load) |
| `MUS/MultiStringBWT.py` | 459 | Same (CompressedMSBWT dump) |

Note: modern2 already fixed these to `'rb'`/`'wb+'`.

### 7.2 C `fopen` with text modes (CRLF corruption on Windows)

| File | Line | Mode | Fix |
|---|---|---|---|
| `MUSCython/CompressToRLE.pyx` | 26 | `'r'` | → `'rb'` |
| `MUSCython/CompressToRLE.pyx` | 32 | `'w+'` | → `'w+b'` |
| `MUSCython/LCPGen.pyx` | 50, 85 | `'w+'` | → `'w+b'` |
| `MUSCython/MSBWTCompGenCython.pyx` | 138, 539 | `'w+'` | → `'w+b'` |
| `MUSCython/RLE_BWTCython.pyx` | 707 | `'w+'` | → `'w+b'` |

### 7.3 `np.memmap` without explicit dtype

| File | Line | Issue |
|---|---|---|
| `MUS/MultiStringBWT.py` | 920, 1074 | `np.memmap(tempFN)` — no dtype |
| `MUSCython/MultiStringBWTCython.pyx` | 554 | Same |

---

## 8. NumPy Legacy/Deprecated APIs

### 8.1 `np.fromstring` (removed in NumPy 2.0)

| File | Line | Replacement |
|---|---|---|
| `MUS/MultiStringBWT.py` | 773 | `np.frombuffer(...)` |
| `MUSCython/MultiStringBWTCython.pyx` | 90, 122 | `np.frombuffer(...)` |

### 8.2 `.tostring()` (removed in NumPy 2.0)

| File | Lines | Replacement |
|---|---|---|
| `MUSCython/MultimergeCython.pyx` | 482, 495, 597 | `.tobytes()` |

### 8.3 `allow_pickle` parameter

Modern2 already uses `allow_pickle=False` on all enhanced-module `np.load` calls. Legacy `MultiStringBWT.py` loads `totalCounts.p` via `pickle.load` directly (not `np.load`), so `allow_pickle` does not apply there. **Do NOT blanket-recommend `allow_pickle=True`** — each `np.load` site must be audited individually.

### 8.4 `.npy` header format

NumPy 2.x may produce different `.npy` header padding/formatting than NumPy 1.x. The modern2 code uses `open_memmap` with normalized shapes via `_int_shape()` helper. This pattern must be validated against NumPy 2.5 but the approach is correct.

---

## 9. Cython Language Level and Source/API Contracts

### 9.1 No `language_level` declared in any .pyx file

All 12 `.pyx` files in `MUSCython/` lack a `language_level` directive. For Python 3 port, add `#cython: language_level=3str` to every file.

### 9.2 `BasicBWT.pxd` source/API contract

`BasicBWT.pxd` is installed as package data and defines the `cdef` layout and method signatures. The Python 2→3 port does NOT guarantee binary ABI compatibility — only source-level compatibility. The `.pxd` must compile against the new Cython + Python 3 but the cdef layout may need adjustment. Do NOT claim Python-2→Python-3 binary ABI compatibility.

### 9.3 `cdivision`/`initializedcheck` directives — DO NOT ADD during parity port

The M3-0R inventory must NOT recommend adding `cdivision=True` or `initializedcheck=False` as part of the initial parity port. These are performance optimizations that change arithmetic semantics (e.g., division-by-zero behavior) and should only be considered after the parity port passes its test suite.

### 9.4 `unsigned long` width (32-bit on Windows, 64-bit on Linux)

Pervasive `cdef unsigned long` across all .pyx files. On Windows x64, `unsigned long` is 32-bit (LLP64), limiting large datasets. This is a known risk — document but do not fix during initial port.

---

## 10. Generated C Files

23 committed `.c` files (12 in `MUSCython/`, 11 in `packages/msbwt-modern2/MUSCython/`). The root files have mixed Cython 0.18/0.23.4 provenance; modern2 files have Cython 3.0.12 provenance.

**Generated-C policy for modern3:** Do NOT commit generated C. Build from `.pyx` in pinned CI. Release sdists include generated C from the release job.

---

## 11. pysam

### 11.1 Import locations

| File | Import style |
|---|---|
| `MUS/MultiStringBWT.py` | Module-level (modern2 changed to lazy import inside `preprocessBams`) |
| `MUSCython/MultiStringBWTCython.pyx` | Module-level (modern2 changed to lazy import) |

### 11.2 Deprecated pysam APIs (removed in pysam 0.21+)

`pysam.Samfile` → `pysam.AlignmentFile`, `.next()` → `next()`, `.qname` → `.query_name`, `.seq` → `.query_sequence`, `.rstart` → `.reference_start`

### 11.3 Native Windows

**pysam does NOT support native Windows.** BAM functionality unavailable. Modern3 should use conditional dependency packaging (extras_require or optional feature), NOT `pip install --no-deps` as a package design. See MODERN3_REFERENCE_ENVIRONMENT.md for direction.

---

## 12. Multiprocessing

### 12.1 Pool creation without proper shutdown

| File | Lines |
|---|---|
| `MUS/MSBWTGen.py` | 386, 532, 928, 1018, 1198 |

### 12.2 `pool.terminate()` vs `pool.close()`+`pool.join()`

| File | Lines | Pattern |
|---|---|---|
| `MUSCython/MultimergeCython.pyx` | 498–499, 734+ | `pool.terminate(); pool.join()` |

---

## 13. Windows/POSIX Filesystem

### 13.1 `os.rename()` where destination exists

Multiple locations. Should use `os.replace()`. Modern2 enhanced modules already use atomic-write patterns with `os.replace` fallback.

### 13.2 memmap close before `os.remove`

Modern2 port (W-MEMMAP-CLOSE) added explicit `(<object>arr).base.close()` before `os.remove()` on memmap files. Core `MUSCython/` code must receive the same fix.

---

## 14. Tests, Fixtures, and Goldens

### 14.1 Test inventory

| Location | Count | Python version |
|---|:-:|---|
| `compat/tests/` | 39 | Python 3 compatible |
| `packages/msbwt-modern2/tests/` | 24 + 1 helper | Python 2 |
| **Total** | **64** | |

### 14.2 Enhanced feature tests (in modern2)

24 `test_*_py2.py` files covering all F1–F13A/Q1 features. These use Python 2 constructs (`StringIO`, `imp.load_source`, `unicode`, `long` literals, `from __future__`).

### 14.3 Goldens

All goldens under `compat/goldens/original-0.3.0/` are Python-2-generated. Must NOT be regenerated with Python 3. Modern3 needs its own golden outputs.

---

## 15. Packaging and Build

### 15.1 Current build system

- `setup.py` with setuptools + Cython (no `pyproject.toml`)
- Custom `build_ext` injects numpy include dirs
- Custom `sdist` cythonizes before packaging
- `setup.cfg` hardcodes `install_scripts=/usr/local/bin` (Windows-incompatible)
- `MANIFEST.in` references `README` (should be `README.md`)

### 15.2 Required changes for modern3

- Create `pyproject.toml` with `[build-system]`
- Remove hardcoded `install_scripts`
- Fix `MANIFEST.in`
- Remove committed `.c` files from VCS
- Define separate `packages/msbwt-modern3/` distribution metadata
- Port 6 enhanced console scripts

---

## 16. Platform-Specific Risks Summary

| Risk | Severity | Status |
|---|---|---|
| `unsigned long` 32-bit on Windows | HIGH | Known; do not fix in initial port |
| pysam unavailable on Windows | HIGH | Conditional dependency packaging needed |
| C `fopen` text modes on Windows | HIGH | Fix in initial port |
| memmap close before `os.remove` on Windows | MEDIUM | Port modern2 W-MEMMAP-CLOSE |
| `os.rename` where dest exists on Windows | MEDIUM | Use `os.replace()` |
| Pool join before file cleanup on Windows | MEDIUM | Port modern2 W-POOL-JOIN |
| `unsigned long` cumsum dtype on Windows | LOW | Port modern2 W-CUMSUM-DTYPE |
| `.npy` header L-suffix on Windows | LOW | Eliminated in Python 3; validate |
