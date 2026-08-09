# MODERN2 — Milestone 3 (executed evidence): decompression fix

Status date: 2026-08-09

This milestone implements the first intentional correctness fix in modern2:
**successful post-hoc decompression** of the uniform RLE MSBWT back to the
authoritative byte-BWT payload.  The historical frozen implementation has a
committed deterministic decompression failure caused by Python-2 / NumPy
integer-index arithmetic (`TypeError: slice indices must be integers or None
or have an __index__ method` at `MUS/MultiStringBWT.py:662`).  Modern2 is NOT
required to reproduce that crash; decompression is explicitly permitted to be
FIXED as a documented correctness deviation.  The frozen oracle was not
modified, and the committed legacy expected-failure evidence remains intact
and is asserted read-only by the new tests and the validation driver.

Evidence is from two consecutive full runs of the committed validation driver
`packages/msbwt-modern2/validate/decompression-milestone3.sh` (both passed;
the second run's evidence JSON is committed under
`packages/msbwt-modern2/evidence/decompression-milestone3.json`).  The frozen
oracle environment was not modified; the modern2 environment is the separate
prefix from Bootstrap Milestone 1.

## Root cause (verified, matching the legacy evidence)

The failing expression is the fill loop of the pure-Python
`MUS.MultiStringBWT.CompressedMSBWT.decompressBlocks`:

```python
ret[s:s+counts[lInd]] = letters[lInd]
s += counts[lInd]
```

- `counts` is a `<u8` (uint64) NumPy array, so `counts[lInd]` is a
  `np.uint64` scalar.
- Under the pinned CPython 2.7.18 / NumPy 1.16.6 profile, NumPy's value-based
  type promotion computes `s + counts[lInd]` (Python `int` + `np.uint64`) as
  **`np.float64`** (int64 + uint64 -> float64), not as an integer.
- `np.float64` has no `__index__`, so the slice `ret[s:s+counts[lInd]]`
  raises the committed legacy exception.  `s += counts[lInd]` would taint
  `s` the same way on any later iteration.
- The same mechanism (uint64 scalar + Python int -> float64) is the
  committed m3c2 line-630 failure for multi-block inputs; the canonical
  48-symbol uniform case fails first at line 662.
- Empirically confirmed inside the pinned environment:
  `type(0 + np.uint64(5))` is `float64`; `int(np.uint64(x))` is exact for
  every value (Python `int`, or `long` above 2^63-1).

The legacy expected-failure contract (committed under
`compat/goldens/original-0.3.0/compression-milestone1/decompression-failure/`)
is preserved byte-for-byte: exit 1, the exact TypeError, traceback locations
including `MUS/MultiStringBWT.py`, line 662, source-side effects
`totalCounts.p` + `comp_fmIndex.npy` + `comp_refIndex.npy`, and the all-zero
preallocated destination `msbwt.npy` (shape `(48,)`, header
`{'descr': '|u1', 'fortran_order': False, 'shape': (48,), }`).

## The fix (narrowest possible)

One site, `MUS/MultiStringBWT.py` `decompressBlocks` fill loop
(`packages/msbwt-modern2/` only):

```python
runLength = int(counts[lInd])
ret[s:s+runLength] = letters[lInd]
s += runLength
```

- `int(counts[lInd])` converts the `np.uint64` run-length scalar to a true
  Python integer.  The conversion preserves the **exact mathematical value**
  (verified for both the `int` and `long` cases in the pinned environment);
  only the Python representation changes so the slice bound is a valid index.
- `s += runLength` keeps `s` a Python `int` (previously the first iteration
  tainted it to `float64`).
- No arithmetic meaning, run boundary, symbol count, output length, or
  persisted byte changes: `[s, s+runLength)` is the identical mathematical
  slice to `[s, s+counts[lInd])`.
- The host-side test `test_modern2_diff_vs_frozen_is_exactly_the_index_fix`
  proves the modern2 `MultiStringBWT.py` differs from the LF-normalized
  frozen original by exactly these three lines and nothing else.

The full decompression call chain was audited: `decompress` CLI ->
`MSBWTGen.decompressBWT` -> `decompressBWTPoolProcess` ->
`getBWTRange` -> `decompressBlocks`.  Every other index/slice in the
exercised path already uses Python integers or NumPy scalars that implement
`__index__` (e.g. `np.uint64` slice bounds are legal; only `uint64 + int`
promotions are not).  No other numeric code was touched.

## Executed validation (both driver runs identical)

### Environment and gates

- CPython 2.7.18, Cython 3.0.12, NumPy 1.16.6, pysam 0.15.4, GCC 7.3.0
  conda toolchain, `PYTHONHASHSEED=0`, `LANG=C.UTF-8`, `TZ=UTC`, single
  BLAS/OMP threads.
- All 27 Python-2 tests pass (11 bootstrap + 6 compression + 10 new
  decompression tests), including the compression-slice tests (no
  regression).

### Decompression runs

For each of the two modern2/legacy-compatible uniform RLE routes —
`uniform-direct-split` (`pp -u` + `cfpp -p 1 -u -c`, `comp_msbwt.npy`
SHA-256 `0ca6329b54f0...`) and `uniform-compress-posthoc` (`compress -p 1`
from the committed byte golden, `comp_msbwt.npy` SHA-256 `53d82b388a9d...`)
— decompression ran from three fresh sources containing ONLY the compressed
primary: run-a (`-p 1`), run-b (`-p 1`), run-p2 (`-p 2`).

Result for every run, both routes:

- exit 0; destination contains exactly `msbwt.npy` (176 bytes).
- whole-file SHA-256 `f536d60f356ed4a34e8253eecdd91e90db8c2ba3430c2e3d3e1855bb49007ef4`.
- raw NPY header byte-identical to the committed legacy decompression
  preallocation header:
  `{'descr': '|u1', 'fortran_order': False, 'shape': (48,), }` — the
  pure-Python `open_memmap` path serializes the Python-int shape literal as
  `(48,)`, exactly as the legacy failure evidence documented (NOT the
  `(48L,)` literal of the compiled byte builder).
- dtype `|u1`, logical shape `[48]`.
- payload SHA-256 `75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e`
  — byte-for-byte equal to the committed authoritative uniform byte-BWT
  golden payload (`dd91d69ee2785c88...` whole-file golden from
  `uniform-multifile`; the two files differ ONLY in the `(48,)` vs `(48L,)`
  header literal, the documented route serialization artifact).
- independent symbol counts (`compat/tools/bwt_oracle.py`) equal the
  fixture-derived expectations: `$=8, A=9, C=9, G=9, N=4, T=9` (48 total).
- source side effects: exactly `totalCounts.p`, `comp_fmIndex.npy`,
  `comp_refIndex.npy` added (the `loadMsbwt` support files, identical to the
  legacy failure source-after set); `comp_msbwt.npy` unchanged.
- same-route determinism: destination trees, whole-file hashes, headers,
  payloads, and source side-effect trees are identical across run-a, run-b,
  and run-p2; `-p 1` and `-p 2` produce byte-identical outputs (both routes
  use the same repaired semantic path: the canonical 48-symbol case is a
  single sub-region tuple).

### Cross-route and round trip

- Direct-RLE and post-hoc-RLE decompressed primaries are byte-identical
  (`f536d60f...`), despite the different NPY shape-header serialization of
  their compressed inputs — decompression accepts both valid inputs.
- Round trip `byte golden -> modern2 compress -> modern2 decompress`:
  the final decompressed primary's payload equals the byte golden payload
  byte-for-byte and the whole file matches the decompression SUCCESS
  contract (`f536d60f...`).

### Reader/query validation (disposable copies only)

For the run-a decompressed primary of each route, the compiled reader loads
it as `MUSCython.ByteBWTCython.ByteBWT`; total size 48, dollar count 8, all
35 fixture-derived query counts match (`ACGTN=3`, `AAAAA=1`, `AGCTA=0`,
`AAAAAA=0`, ...), and the recovered sequence multiset is exactly
`$AAAAA, $ACGTN x3, $CCCCC, $GGGGG, $NACGT, $TTTTT`.  Reader-created side
effects are exactly `totalCounts.npy` and `fmIndex.npy` with SHA-256s
`ea104b616fe8...` and `a5b4bf06726f...` — byte-identical to the committed
legacy byte-reader derived indexes for the same payload
(`compression-milestone1/coexistence-loader-preference.json`).  No primary
directory was mutated.

## Side-effect classification (modern2 successful decompression)

- Compressed primary input: `comp_msbwt.npy` (unmodified).
- Decompressed primary: destination `msbwt.npy` (the SUCCESS contract).
- Required persistent support files (created in the source, same as the
  legacy `loadMsbwt` contract): `totalCounts.p`, `comp_fmIndex.npy`,
  `comp_refIndex.npy`.
- Lazy reader indexes (created only on disposable reader copies, never
  promoted): `totalCounts.npy`, `fmIndex.npy`.
- Temporary files: none inside the source/destination trees.
- The legacy failure-only artifacts (all-zero preallocated `msbwt.npy`,
  partial writes) are NOT part of the modern2 successful format contract.

## Tests added

- `packages/msbwt-modern2/tests/test_decompression_py2.py` (Python-2 suite,
  10 tests): direct-RLE -> byte golden, post-hoc-RLE -> byte golden,
  cross-route byte identity, `-p 1`/`-p 2` byte equality, repeated-run
  determinism (destination and source side effects), source/destination
  side-effect inventory, byte-golden compress/decompress round trip,
  ByteBWT reader/query/recovered-string behavior on disposable copies with
  the legacy byte-reader side-effect hashes, the focused
  `getBWTRange`/`decompressBlocks` uint64-index regression (fails if the
  `int()` conversion is removed), and the committed legacy expected-failure
  evidence contract preservation.
- `compat/tests/test_modern2_decompression.py` (host suite, 11 tests):
  driver presence, evidence-record consistency, evidence success-contract
  hashes (whole `f536d60f...`, payload `75134b48...`, `(48,)` header equal
  to the legacy preallocated header, symbol counts, determinism flags),
  evidence reader side effects vs the committed legacy byte-reader indexes,
  the frozen `MUS/MultiStringBWT.py` digest (untouched), and the
  exact-diff proof that modern2 differs from frozen only by the three
  index-fix lines.

## Files changed

- `packages/msbwt-modern2/MUS/MultiStringBWT.py` — the ONLY source change:
  the `decompressBlocks` fill loop (3 lines, exact-diff proven).
- `packages/msbwt-modern2/validate/decompression-milestone3.sh` — validation
  driver (routes x2 runs + `-p 2`, header/payload/golden comparison,
  independent symbol counts, round trip, reader smoke, legacy-evidence
  check, evidence JSON).
- `packages/msbwt-modern2/evidence/decompression-milestone3.json` — executed
  evidence record.
- `packages/msbwt-modern2/tests/test_decompression_py2.py` — Python-2
  regression tests.
- `compat/tests/test_modern2_decompression.py` — host-side regression tests.
- `docs/modernization/MODERN2_MILESTONE3_DECOMPRESSION.md` — this document.

No frozen file, `.pyx`, generated `.c`, setup.py, environment, or golden
file was modified.

## Test counts

- Legacy compatibility suite: 125 tests (unchanged, green).
- Modern2-specific suite (host-side): 34 + 11 = 45.
- Modern2 Python-2 suite: 17 + 10 = 27 tests, green.

## Stop conditions

None triggered: the root cause is exactly the characterized numeric/index
type problem; the fix preserves mathematical arithmetic; decompressed bytes
equal the byte-BWT golden payload (whole file differs only by the documented
`(48,)` vs `(48L,)` header literal, matching the legacy decompression
preallocation contract); both compressed inputs decompress identically;
`-p 1` is deterministic; reader/query semantics are unchanged; no persistent
format change; frozen source untouched; no recovery/merge redesign involved.

## Out of scope / next slice

Recovery/resume, interruption, merge, nonuniform decompression, LZW,
convert, and broader CLI bugs were NOT touched.  The compiled
`MSBWTGenCython.compressBWT` typed-division site and the multi-block
(>1,000,000-symbol) decompression path (the m3c2 line-630 manifestation of
the same promotion mechanism) remain the natural candidates for the next
decompression-adjacent slice; the canonical uniform decompression SUCCESS
contract is complete.  Safe to proceed to the next modern2 slice.
