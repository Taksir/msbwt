# Modern3 Port Inventory

Repository-wide inventory of every surface requiring attention for the Python 2 → Python 3 port of msbwt-modern3. Generated from the `enhanced-modern3` branch at tag `msbwt-enhanced-modern2-0.3.0` (commit `746cf93`).

---

## 1. Python 2-Only Syntax and Semantics

### 1.1 `print` statements (syntax error in Python 3)

| File | Approximate count | Notes |
|------|:-:|-------|
| `MUS/CommandLineInterface.py` | 3 | `print expr` form |
| `MUS/TranscriptBuilder.py` | 2 | `print 'ERROR...'` |
| `MUS/MSBWTGen.py` | 2 | progress/error prints |
| `MUS/MultiStringBWT.py` | 18 | debug/info prints |
| `MUSCython/MSBWTGenCython.pyx` | 4 | debug prints |
| `MUSCython/MultiStringBWTCython.pyx` | 1 | debug print |
| `MUSCython/RLE_BWTCython.pyx` | 1 | failure print |
| **Total (core MUS/ + MUSCython/)** | **31** | All must become `print()` |

### 1.2 `xrange` usage (NameError in Python 3)

| File | Approximate count |
|------|:-:|
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
| **Total** | **95+** | All must become `range()` |

### 1.3 `dict.has_key()` (removed in Python 3)

| File | Count |
|------|:-:|
| `MUS/TranscriptBuilder.py` | 6 |
| `MUS/MSBWTGen.py` | 5 |
| `MUS/MultiStringBWT.py` | 3 |
| `MUSCython/MSBWTGenCython.pyx` | 4 |
| **Total** | **18** | All must become `k in d` |

### 1.4 `.next()` method calls (use `next()` in Python 3)

| File | Count | Context |
|------|:-:|---------|
| `MUS/MultiStringBWT.py` | 2 | BAM iterator `bamFile.next()` |
| `MUSCython/MultiStringBWTCython.pyx` | 2 | Same BAM iterator |
| **Total** | **4** | Must become `next(iterator)` |

### 1.5 Python 2 implicit-relative imports (fail in Python 3)

| File | Import | Required change |
|------|--------|-----------------|
| `MUS/MSBWTGen.py` | `import MultiStringBWT` | `from . import MultiStringBWT` |
| `MUS/MultiStringBWT.py` | `import MSBWTGen` | `from . import MSBWTGen` |
| `MUS/CommandLineInterface.py` | `import MSBWTGen` | `from . import MSBWTGen` |
| `MUSCython/BasicBWT.pyx` | `import MultiStringBWTCython` | `from . import MultiStringBWTCython` |
| `MUSCython/GenericMerge.pyx` | `import MultiStringBWTCython` | `from . import MultiStringBWTCython` |
| `MUSCython/MultimergeCython.pyx` | `import MSBWTGenCython` | `from . import MSBWTGenCython` |
| `MUSCython/RLE_BWTCython.pyx` | `import MSBWTGenCython; import AlignmentUtil` | `from . import ...` |
| `MUSCython/MSBWTGenCython.pyx` | `import MultiStringBWTCython` | `from . import ...` |
| `MUSCython/MultiStringBWTCython.pyx` | `import MSBWTGenCython; import MSBWTCompGenCython` | `from . import ...` |
| `MUSCython/MultiStringBWTCython.pyx` | `from ByteBWTCython import ByteBWT` | `from .ByteBWTCython import ByteBWT` |
| `MUSCython/MultiStringBWTCython.pyx` | `from RLE_BWTCython import RLE_BWT` | `from .RLE_BWTCython import RLE_BWT` |
| `MUSCython/MultiStringBWTCython.pyx` | `from LZW_BWTCython import LZW_BWT` | `from .LZW_BWTCython import LZW_BWT` |
| `MUSCython/MSBWTCompGenCython.pyx` | `import MSBWTGenCython` | `from . import MSBWTGenCython` |
| **Total** | **~13 unique** | |

### 1.6 Integer division `/` (returns float in Python 3)

Pervasive across the codebase. Critical locations:

| File | Lines (examples) | Impact |
|------|-----------------|--------|
| `MUS/MSBWTGen.py` | 376, 840-844, 875, 895, 966, 1006, 1010, 1187, 1191 | Array indexing, loop bounds, bin calculations |
| `MUS/MultiStringBWT.py` | 292, 1100 | FM-index bin sizing, seqArray length |
| `MUSCython/GenericMerge.pyx` | 59, 83, 92, 560, 564 | Byte-offset calculations for interleave arrays |
| `MUSCython/MultimergeCython.pyx` | 197, 228, 237, 627, 812, 910, 944, 949, 950, 953, 1641, 1645 | Same |
| `MUSCython/MSBWTGenCython.pyx` | 446, 450, 451, 643, 647, 741 | Same |
| `MUSCython/ByteBWTCython.pyx` | 116 | `float(...)` already wraps division |
| `MUSCython/RLE_BWTCython.pyx` | 177, 347 | `float(...)` already wraps division |
| **Total** | **~50+ locations** | All `/` on integers must become `//` |

---

## 2. Bytes/String Assumptions

### 2.1 `np.fromstring` with string input (TypeError in Python 3)

| File | Line | Issue |
|------|------|-------|
| `MUS/MultiStringBWT.py` | 773 | `np.fromstring(seqCopy, dtype='<u1')` where `seqCopy` is `str.join()` result |
| `MUSCython/MultiStringBWTCython.pyx` | 90 | Same pattern |
| `MUSCython/MultiStringBWTCython.pyx` | 122 | Same (compressed variant) |
| **Total** | **3** | Must use `np.frombuffer(seqCopy.encode('ascii'), ...)` or `np.array(list(seqCopy), dtype='<u1')` |

### 2.2 Cython `char *` function parameters receiving `str` in Python 3

All Cython functions accepting `char *` paths (MultimergeCython, GenericMerge, MSBWTGenCython, ByteBWTCython, RLE_BWTCython, LZW_BWTCython) auto-encode `str` → bytes in Cython 3 with `language_level=3`. This works for ASCII paths but should be explicitly typed as `str` or `bytes` for clarity.

Key affected signatures:
- `MultimergeCython.createMSBWTFromSeqs(list, char *, ...)`
- `MultimergeCython.mergeTwoMSBWTs(char *, char *, char *, ...)`
- `GenericMerge.mergeTwoMSBWTs(char *, char *, char *, ...)`
- `MSBWTGenCython.compressBWT(char *, char *, ...)`
- `ByteBWTCython.loadMsbwt(self, char *, ...)`
- `RLE_BWTCython.loadMsbwt(self, char *, ...)`
- `LZW_BWTCython.loadMsbwt(self, char *, ...)`

### 2.3 `.tostring()` → `.tobytes()` (deprecated in NumPy ≥1.19, removed ≥2.0)

| File | Count |
|------|:-:|
| `MUSCython/MultimergeCython.pyx` | 3 |
| Test files (modern2) | ~15 |
| **Total (core)** | **3** | Replace with `.tobytes()` |

### 2.4 Python 2 `unicode`/`basestring`/`long` type references

| File | Type | Count |
|------|------|:-:|
| `MUS/BWTTags.py` (modern2) | `unicode` | 2 |
| `MUS/QualitySidecar.py` (modern2) | `unicode` | 2 |
| Test files (modern2) | `unicode`, `basestring`, `long` | 5 |
| `compat/audit/` | `unicode` | 1 |
| `reference/` | `unicode`, `basestring` | 3 |
| **Total (core + modern2)** | | **~8** | Use `str` / `isinstance(x, str)` |

---

## 3. Binary/Text I/O

### 3.1 Pickle in text mode (will crash in Python 3)

| File | Line | Issue |
|------|------|-------|
| `MUS/MultiStringBWT.py` | 245 | `open(abtFN, 'r')` for pickle load |
| `MUS/MultiStringBWT.py` | 261 | `open(abtFN, 'w+')` for pickle dump |
| `MUS/MultiStringBWT.py` | 422 | Same (CompressedMSBWT load) |
| `MUS/MultiStringBWT.py` | 459 | Same (CompressedMSBWT dump) |
| **Total** | **4** | Must use `'rb'`/`'wb'` |

### 3.2 C `fopen` with text modes (CRLF corruption on Windows)

| File | Line | Mode | Issue |
|------|------|------|-------|
| `MUSCython/CompressToRLE.pyx` | 26 | `'r'` | Input: text mode; should be `'rb'` |
| `MUSCython/CompressToRLE.pyx` | 32 | `'w+'` | Output: text mode; should be `'w+b'` |
| `MUSCython/LCPGen.pyx` | 50 | `'w+'` | Binary data; should be `'w+b'` |
| `MUSCython/LCPGen.pyx` | 85 | `'w+'` | Same |
| `MUSCython/MSBWTCompGenCython.pyx` | 138 | `'w+'` | Same |
| `MUSCython/MSBWTCompGenCython.pyx` | 539 | `'w+'` | Same |
| `MUSCython/RLE_BWTCython.pyx` | 707 | `'w+'` | Same |
| **Total** | **7** | Must use binary modes |

### 3.3 gzip.open text mode (changes semantics in Python 3)

| File | Line | Mode | Notes |
|------|------|------|-------|
| `MUS/util.py` | 117, 141 | `'r'` | FASTA/FASTQ text reading: OK in Py3 |
| `MUS/MultiStringBWT.py` | 848 | `'r'` | FASTQ text reading: OK in Py3 |
| `MUSCython/MultiStringBWTCython.pyx` | 240 | `'r'` | FASTA reading: OK in Py3 |
| `MUSCython/MultimergeCython.pyx` | 369, 404 | `'r'` | FASTA reading: OK in Py3 |
| **Total** | **6** | Low risk (text FASTA/FASTQ); verify line iteration works with `str` |

### 3.4 `np.memmap` without explicit dtype

| File | Line | Issue |
|------|------|-------|
| `MUS/MultiStringBWT.py` | 920 | `np.memmap(tempFN)` — no dtype |
| `MUS/MultiStringBWT.py` | 1074 | Same |
| `MUSCython/MultiStringBWTCython.pyx` | 554 | Same |
| **Total** | **3** | Specify `dtype='<u1'` explicitly |

---

## 4. NumPy Legacy/Deprecated APIs

### 4.1 `np.fromstring` (deprecated for non-string buffers, removed in NumPy 2.0)

| File | Line | Replacement |
|------|------|-------------|
| `MUS/MultiStringBWT.py` | 773 | `np.frombuffer(...)` |
| `MUSCython/MultiStringBWTCython.pyx` | 90, 122 | `np.frombuffer(...)` |

### 4.2 `.tostring()` (deprecated, removed in NumPy 2.0)

| File | Lines | Replacement |
|------|-------|-------------|
| `MUSCython/MultimergeCython.pyx` | 482, 495, 597 | `.tobytes()` |

### 4.3 `allow_pickle` parameter (default changed in NumPy 1.16+)

All `np.load()` calls should specify `allow_pickle=True` when loading pickle files (e.g., `totalCounts.p`). Current code does not specify this parameter.

### 4.4 `.npy` header format

NumPy 2.x may produce different `.npy` header formatting than NumPy 1.x. The codebase uses `np.save` and `open_memmap` with normalized shapes (via `_int_shape()` helper in modern2). This pattern is correct but must be validated against NumPy 2.5.

---

## 5. Cython Language Level and Directives

### 5.1 No `language_level` declared in any .pyx file

All 12 `.pyx` files in `MUSCython/` lack a `language_level` directive. For Python 3 port:
- Add `#cython: language_level=3str` (or `language_level=3`) to every `.pyx` file
- This changes: `print` statement → function, `xrange` → `range`, string literals are `str` by default

### 5.2 `cdivision=True` never set

All integer divisions in Cython go through Python division semantics (safe but slow). Since we're changing `/` → `//` everywhere anyway, consider adding `cdivision=True` after verifying correctness, but not during initial port.

### 5.3 `initializedcheck=False` missing

Missing from `ByteBWTCython.pyx` and `LZW_BWTCython.pyx`. Should be added for consistency with other .pyx files.

### 5.4 `unsigned long` width (32-bit on Windows, 64-bit on Linux)

Pervasive `cdef unsigned long` declarations across all .pyx files. On Windows x64, `unsigned long` is 32-bit (LLP64), limiting large datasets. For cross-platform correctness, consider `cdef uint64_t` or `Py_ssize_t` for sizes/indexes. **This is a known risk per the handoff — do not change during initial port, but document.**

### 5.5 `BasicBWT.pxd` ABI surface

`BasicBWT.pxd` is installed as part of the package. Any changes to `cdef` layout break downstream compiled modules. Must remain source-compatible or version the ABI.

---

## 6. Generated C Files

### 6.1 23 committed .c files (12 in MUSCython/, 11 in packages/msbwt-modern2/)

| Location | Count | Status |
|----------|:-:|--------|
| `MUSCython/*.c` | 12 | Committed, mixed Cython 0.18/0.23.4 provenance |
| `packages/msbwt-modern2/MUSCython/*.c` | 11 | Committed, Cython 3.0.12 provenance |
| **Total** | **23** | |

**Generated-C policy for modern3:** Do NOT commit generated C. Build from `.pyx` in pinned CI. Release sdists include generated C from the release job. The frozen reference area retains the original generated C unchanged.

---

## 7. pysam Usage

### 7.1 Import locations

| File | Line | Import style |
|------|------|-------------|
| `MUS/MultiStringBWT.py` | ~21 | Module-level `import pysam` |
| `MUSCython/MultiStringBWTCython.pyx` | ~25 | Module-level `import pysam` |

Modern2 already changed these to lazy imports inside `preprocessBams()`.

### 7.2 Deprecated pysam APIs

| API | File | Replacement |
|-----|------|-------------|
| `pysam.Samfile` | `MUS/MultiStringBWT.py:950` | `pysam.AlignmentFile` |
| `.next()` on BAM iterator | `MUS/MultiStringBWT.py:963,974` | `next(iterator)` |
| `.qname` | `MUS/MultiStringBWT.py` | `.query_name` |
| `.seq` | `MUS/MultiStringBWT.py` | `.query_sequence` |
| `.rstart` | `MUS/MultiStringBWT.py` | `.reference_start` |

These are all Python 2 pysam APIs removed in pysam 0.21+.

### 7.3 Native Windows support

**pysam does NOT support native Windows.** Confirmed by GitHub issue #1320 (open, marked duplicate of #1375/PR #1274). Wheels are only built for macOS and Linux (manylinux_2_28, musllinux_1_2). Building from source on Windows fails due to htslib configure script issues.

**Conclusion:** BAM functionality will be unavailable on native Windows. This matches the modern2 approach (lazy import, `NotImplementedError` on Windows).

---

## 8. Multiprocessing

### 8.1 Pool creation without proper shutdown

| File | Line | Issue |
|------|------|-------|
| `MUS/MSBWTGen.py` | 386, 532, 928, 1018, 1198 | `Pool(numProcs)` without `close()`/`join()` before file ops |

### 8.2 Windows spawn guard

All scripts using `multiprocessing` must have `if __name__ == '__main__':` guard. The CLI entry points are guarded. Library modules (`MSBWTGen.py`, Cython modules) use pool workers at function level, which is OK because they're called from guarded contexts.

### 8.3 `pool.terminate()` vs `pool.close()`+`pool.join()`

| File | Line | Pattern |
|------|------|---------|
| `MUSCython/MultimergeCython.pyx` | 498-499 | `pool.terminate(); pool.join()` — abrupt termination |
| `MUSCython/MultimergeCython.pyx` | 734+ | Same pattern |

Should use `pool.close(); pool.join()` for graceful shutdown.

---

## 9. Windows/POSIX Filesystem

### 9.1 `os.rename()` where destination exists

Multiple locations use `os.rename(old, new)` which fails on Windows if `new` exists. Should use `os.replace()`.

### 9.2 Forward-slash path concatenation

Pervasive `dirName + '/file.npy'` pattern. Works on Windows (Python normalizes `/`), but consider `os.path.join()` for consistency.

### 9.3 memmap close before `os.remove`

The modern2 port (W-MEMMAP-CLOSE deviation) added explicit `(<object>arr).base.close()` before every `os.remove()` on memmap files. The core `MUSCython/` code still has the original pattern and must receive the same fix.

---

## 10. Public Python API

### 10.1 Import paths

All these must remain importable:

**MUS package:**
- `MUS.CommandLineInterface`
- `MUS.MSBWTGen`
- `MUS.MultiStringBWT`
- `MUS.TranscriptBuilder`
- `MUS.util`

**MUSCython package:**
- `MUSCython.AlignmentUtil`
- `MUSCython.BasicBWT`
- `MUSCython.ByteBWTCython`
- `MUSCython.CompressToRLE`
- `MUSCython.GenericMerge`
- `MUSCython.LCPGen`
- `MUSCython.LZW_BWTCython`
- `MUSCython.MSBWTCompGenCython`
- `MUSCython.MSBWTGenCython`
- `MUSCython.MultimergeCython`
- `MUSCython.MultiStringBWTCython`
- `MUSCython.RLE_BWTCython`

### 10.2 Return-type contracts

- `recoverString()` returns Python 2 `str` (bytes). In Python 3, must return `bytes` or `str` (decision required).
- `countOccurrencesOfSeq()` accepts `str`/`bytes` — must accept both in Python 3.
- `loadBWT()` returns a compiled object with methods accepting `bytes` sequences.

---

## 11. Legacy CLI Commands

All 9 CLI commands must remain functional:

| Command | Key porting concerns |
|---------|---------------------|
| `cffq` | `xrange`, `print`, integer division, implicit imports |
| `pp` | Same |
| `cfpp` | Same |
| `merge` | Same + `numProcs` bug (legacy defect) |
| `query` | `xrange`, implicit imports |
| `massquery` | Binary CSV output mode, `xrange` |
| `compress` | Pickle I/O mode, integer division |
| `decompress` | Same |
| `convert` | Cython `CompressToRLE`, `fopen` modes |

---

## 12. Persisted Formats

### 12.1 Primary files

| File | Format | Porting concern |
|------|--------|-----------------|
| `msbwt.npy` | `.npy` v1, `|u1` | NumPy 2.x header may differ; must validate byte compatibility |
| `comp_msbwt.npy` | `.npy` v1, `|u1` | Same |
| `comp_msbwt.dat` | Raw LZW bytes | No Python version dependency |
| `about.npy` | `.npy` structured array | Descriptor spelling must match |
| `inter0.npy` | `.npy` `|u1` bit-packed | No Python version dependency |
| `totalCounts.npy` | `.npy` `<u8`, shape `(6,)` | NumPy header format |
| `totalCounts.p` | Pickle protocol 0 | **Python-2-pickled file; Python 3 cannot load protocol-0 pickles of numpy arrays containing long shape elements** |
| `fmIndex.npy` | `.npy` `<u8` | NumPy header format |
| `comp_fmIndex.npy` | `.npy` `<u8` | Same |
| `comp_refIndex.npy` | `.npy` `<u8` | Same |
| `lcps.npy` | `.npy` `<u1` | Same |

### 12.2 Recovery/temporary files

All recovery file patterns (state.*.npy, inserts.*.npy, backup.*.npy, etc.) use `.npy` format and are affected by NumPy header changes.

---

## 13. Tests, Fixtures, and Goldens

### 13.1 Test file inventory

| Location | Count | Python version |
|----------|:-:|----------------|
| `compat/tests/` | 39 | Python 3 compatible (run on 3.14 per `__pycache__`) |
| `packages/msbwt-modern2/tests/` | 24 + 1 helper | Python 2 (test_*_py2.py) |
| `compat/audit/modern2-q1/tests/` | 1 | Mixed |
| **Total** | **64** | |

### 13.2 Reusable for Python 3

The `compat/tests/` suite (39 files) appears to be written for Python 3 and has been run on CPython 3.14. These are the primary test suite for modern3 validation.

### 13.3 Requiring Python-3-specific updates

The `packages/msbwt-modern2/tests/test_*_py2.py` files use:
- `StringIO`/`cStringIO` imports
- `imp.load_source()`
- `unicode`/`basestring` type checks
- Python 2 `long` literals
- `from __future__ import print_function`

### 13.4 Goldens

All goldens under `compat/goldens/original-0.3.0/` are Python-2-generated and must NOT be regenerated with Python 3. They serve as the legacy oracle. Modern3 will need its own golden outputs for comparison.

### 13.5 Cross-version interoperability tests

Required: modern3 writer → modern2 reader, and modern2 writer → modern3 reader tests for every persisted format. These do not yet exist.

---

## 14. Packaging and Build

### 14.1 Current build system

- `setup.py` with setuptools + Cython (no `pyproject.toml`)
- Custom `build_ext` injects numpy include dirs
- Custom `sdist` cythonizes before packaging
- `setup.cfg` hardcodes `install_scripts=/usr/local/bin` (Windows-incompatible)
- `MANIFEST.in` references `README` (should be `README.md`)
- No `[build-system]` table, no PEP 517 configuration

### 14.2 Required changes for modern3

- Create `pyproject.toml` with `[build-system]` requiring setuptools, wheel, Cython, numpy
- Remove hardcoded `install_scripts` from `setup.cfg`
- Fix `MANIFEST.in` to reference `README.md`
- Remove committed `.c` files from VCS
- Add `.gitignore` entries for build artifacts
- Define separate `packages/msbwt-modern3/` distribution metadata

### 14.3 Enhanced console scripts (modern2)

6 scripts in `packages/msbwt-modern2/tools/`: `msbwt-bwt-tags`, `msbwt-lcp`, `msbwt-quality-sidecar`, `msbwt-remove-sources`, `msbwt-retrofit-read-provenance`, `msbwt-benchmark-index`. These must be ported to modern3 as well.

---

## 15. Platform-Specific Risks Summary

| Risk | Severity | Status |
|------|----------|--------|
| `unsigned long` 32-bit on Windows | HIGH | Known; do not fix in initial port |
| pysam unavailable on Windows | HIGH | Lazy import + `NotImplementedError` (matches modern2) |
| C `fopen` text modes on Windows | HIGH | Fix in initial port (binary modes) |
| memmap close before `os.remove` on Windows | MEDIUM | Fix in initial port (port modern2 W-MEMMAP-CLOSE) |
| `os.rename` where dest exists on Windows | MEDIUM | Fix with `os.replace()` |
| Pool join before file cleanup on Windows | MEDIUM | Fix in initial port (port modern2 W-POOL-JOIN) |
| `unsigned long` cumsum dtype on Windows | LOW | Fix with explicit `dtype='<u8'` (port modern2 W-CUMSUM-DTYPE) |
| `.npy` header L-suffix on Windows | LOW | Eliminated in Python 3 (no `long` type); validate |
| CRLF in golden input files | LOW | Ensure `.gitattributes` covers test inputs |
