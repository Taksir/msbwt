# MODERN2 — Milestone 6 (executed evidence): pure-Python FM reader defect fix

Status date: 2026-08-10

This milestone fixes the frozen pure-Python
`CompressedMSBWT.getFullFMAtIndex` fill-line defect discovered in
Milestone 5: `ret += np.bincount(letters[0:x-1], counts[0:x-1],
minlength=self.vcLen)` (frozen line 725 == modern2 line 726 pre-fix)
deterministically raised `TypeError: Cannot cast ufunc add output from
dtype('float64') to dtype('uint64') with casting rule 'same_kind'` under
CPython 2.7.18 / NumPy 1.16.6 whenever more than one run precedes the target
position.  The modern2 fill line is now the exact-integer accumulation
`np.add.at(ret, letters[0:x-1], counts[0:x-1])`, which matches the typed
Cython `RLE_BWT` reader arithmetic (`ret_view[prevChar] += prevCount`).

Test-first: the pre-fix failure was reproduced on the committed >1M-symbol
evidence and the 48-symbol valid collection with exact runtime dtype
evidence, the intended integer FM-count update was derived and compared with
the compiled implementation, and only then was source changed.  The frozen
oracle was not modified.

Evidence is from a full run of the committed validation driver
`packages/msbwt-modern2/validate/reader-milestone6.sh` (passed; the run's
evidence JSON is committed under
`packages/msbwt-modern2/evidence/reader-milestone6.json`, with the committed
modern2 pre-fix failure probe under
`packages/msbwt-modern2/evidence/reader-milestone6-prefix-probe.json`).
The milestone-5 driver `reader-milestone5.sh` was also re-run on the fixed
checkout and passes (its TypeError assertion now routes through the frozen
original source; see below).

## Evidence dataset (exactly the committed m3c2/milestone-5 evidence)

Reused without modification:

- Evidence primary: the committed uniform byte-BWT golden payload (48
  symbols) tiled 22000x: shape `(1056000,)`, whole-file SHA-256
  `24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35`.
- Compressed RLE: modern2 `compress -p 1` -> `comp_msbwt.npy`, shape
  `(484000,)`, SHA-256
  `681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99`.
- FM structure: 516 bins of 2048 symbols; bins 0..515, last bin covers
  `[1054720, 1056000)`.
- 48-symbol valid uniform collection (byte + RLE), single FM bin.

No new large fixture was invented.

## Executed runtime type evidence (pinned environment)

At `index = 1055998` (last bin, preceded by 584 runs), the frozen fill-site
inputs and outputs measured in the pinned environment:

| expression | runtime dtype/type | value |
|---|---|---|
| `ret` (`np.copy(partialFM[binID])`) | `uint64` | `[175785 373762 571758 769758 857896 1055759]` |
| `counts` (`right_shift(..., '<u8')`) | `uint64` | run lengths (after power scaling) |
| `letters` (`bitwise_and(..., mask)`) | `uint8` | run symbols 0..5 |
| `cs` (`cumsum(counts)-counts`) | `uint64` | run start positions |
| `np.bincount(letters[0:x-1], counts[0:x-1], minlength=6)` | **`float64`** | `[214 238 242 242 104 238]`, sum 1278 |
| weights slice `counts[0:x-1]` | `uint64` | run lengths |
| `ret.__iadd__(bincount(...))` | — | **`TypeError`**: `Cannot cast ufunc add output from dtype('float64') to dtype('uint64') with casting rule 'same_kind'` |
| `ret + bincount(...)` (out-of-place) | `float64` | `[175999 374000 572000 770000 858000 1055997]` |
| `np.add.at(ret, letters[0:x-1], counts[0:x-1])` | **`uint64`** | `[175999 374000 572000 770000 858000 1055997]` |

The exact NumPy casting rule is NumPy 1.16.6 in-place ufunc casting
`'same_kind'`: `float64 -> uint64` is not same-kind, so `a += f64_array`
raises `TypeError` for a `uint64` target.  This is independent of the
milestone-5 uint64+int promotion (the same line fails on the last bin and on
the 48-symbol single-bin case) and would fail with perfectly integer
arithmetic; it is a frozen dtype-cast defect in the pure-Python RLE FM path.

## The fix (narrowest possible, one site)

`packages/msbwt-modern2/MUS/MultiStringBWT.py` line 726:

```python
# before (frozen line 725, modern2 line 726 pre-fix):
if x > 1:
    ret += np.bincount(letters[0:x-1], counts[0:x-1], minlength=self.vcLen)
# after (modern2):
if x > 1:
    np.add.at(ret, letters[0:x-1], counts[0:x-1])
```

- `np.bincount(letters[0:x-1], counts[0:x-1], minlength=vcLen)` computes the
  per-symbol sum of the run lengths of every run strictly before the target
  run, but returns `float64`.  `np.add.at(ret, letters[0:x-1], counts[0:x-1])`
  performs the identical per-symbol accumulation directly into the `uint64`
  `ret` in exact integer arithmetic (`ret[letters[j]] += counts[j]` per run,
  accumulating duplicate indices).
- The mathematical update is unchanged: full runs before the target are added
  per symbol, and the partial term `ret[letters[x-1]] += dist-cs[x-1]` is
  applied after, exactly as in the compiled `fillFmAtIndex`
  (`ret_view[prevChar] += prevCount` for fully consumed runs, then
  `ret_view[prevChar] += index-bwtIndex` for the current run).
- No cast is introduced.  The result is exact integer `uint64` for all
  magnitudes (no float64 precision bound), no count information is lost, and
  no persistent data representation changes.  `ret + bincount(...)` (float64)
  equals `np.add.at(ret, ...)` (uint64) exactly for the exercised inputs, so
  the mathematical counts do not depend on any cast choice.
- `MUS/MultiStringBWT.py` now differs from the LF-normalized frozen original
  by exactly the documented five correctness fixes (milestone-3 fill loop,
  milestone-4 `decompressBlocks`, milestone-5 `getCharAtIndex` +
  `getFullFMAtIndex` endRange sites, milestone-6 fill line).  No Cython
  change was required: the compiled `RLE_BWT` reader already implemented the
  exact integer arithmetic.

## Reproduced failures (pre-fix, executed)

- FROZEN original source (committed `MUS/MultiStringBWT.py`, SHA-256
  `95ac0b86...`): `getFullFMAtIndex(1055998)` / `(1055999)` raise
  `TypeError` at line 725 (last-bin positions reach the bincount fill);
  `getFullFMAtIndex(2048)` raises `IndexError` at line 708 (non-last-bin
  float64 `endRange` index); the 48-symbol single-bin collection raises the
  same line-725 `TypeError` for positions preceded by more than one run.
- MODERN2 pre-fix checkout (commit `eb45db9`, committed probe
  `reader-milestone6-prefix-probe.json`): pure `getFullFMAtIndex` raises the
  documented line-726 `TypeError` at positions `2047`, `999998`, `999999`,
  `1000000`, `1000001`, `1055998`, `1055999` on the >1M evidence and at
  positions `2`, `5`, `10`, `20`, `40`, `47` on the 48-symbol collection;
  positions with `x <= 1` (`0`, `1`, `2048`, `2049`) return oracle-exact
  arrays.

## Executed validation (driver run)

### Environment and gates

- CPython 2.7.18, Cython 3.0.12, NumPy 1.16.6, pysam 0.15.4, GCC 7.3.0 conda
  toolchain, `PYTHONHASHSEED=0`, `LANG=C.UTF-8`, `TZ=UTC`, single BLAS/OMP
  threads.
- All 55 Python-2 tests pass (11 bootstrap + 6 compression + 10 milestone-3
  + 10 milestone-4 + 10 milestone-5 reader-boundary + 8 new pure-FM), all
  200 host-side compat tests pass, and the milestone-5 driver passes on the
  fixed checkout.
- Evidence primary regenerated deterministically and hash-matched; modern2
  compression reproduced the committed m3c2/milestone-5 RLE primary.

### >1M evidence: pure FM == compiled FM == oracle

At every boundary position `{0, 1, 2047, 2048, 2049, 999998, 999999,
1000000, 1000001, 1055998, 1055999}`, `pure.getFullFMAtIndex` returns a
`uint64` FM vector equal to the compiled `RLE_BWT.getFullFMAtIndex` and to
the independent `startIndex + cumulative symbol counts` oracle
(`full_fm_at` in the evidence record; e.g. at 1055998:
`[175999, 374000, 572000, 770000, 858000, 1055999]`).  Pure
`getCharAtIndex` is unchanged at every boundary.

All six alphabet symbols are represented: the near-end FM vector
(`1055999` -> `[175999, 374000, 572000, 770000, 858000, 1056000]`) has a
positive occurrence count for every symbol.

### >1M evidence: pure backward-search queries

Pure `CompressedMSBWT.countOccurrencesOfSeq` routes through
`getOccurrenceOfCharAtIndex -> getFullFMAtIndex` and, for the 13
representative k-mers (`A=198000`, `AC=37125`, `ACGTN=111`, `AAAAAA=45`, ...),
equals the compiled RLE/byte readers and the independent string-level FM
oracle exactly.

### 48-symbol valid collection

Pure `getFullFMAtIndex` at `{0, 1, 2, 5, 10, 20, 40, 47}` equals the
compiled `RLE_BWT` reader and the oracle (dtype `uint64`).  Query counts
(`AAAAA=1`, `ACGTN=3`, `CCCCC=1`, `AGCTA=0`, `AAAAAA=0`, `GGGGG=1`,
`NACGT=1`, `TTTTT=1`, `$=8`) are unchanged across the pure reader and both
compiled readers.  Recovered strings over all 8 dollar positions: compiled
byte == compiled RLE, and pure-reader recovery == compiled byte (a new
capability of the fixed fill line).  Compiled byte-reader side effects
`totalCounts.npy` (`ea104b61...`) and `fmIndex.npy` (`a5b4bf06...`) are
byte-identical to the committed milestone-3 reader evidence; the >1M byte
reader side effects (`e7fe29a9...`, `16e19742...`) are unchanged.

### Independent host-side verification

The driver's `verify_probe` re-checks every equality on the host (no NumPy),
including the `bwt_oracle.backward_count` string-level FM counts on the raw
evidence payload and the frozen/modern2 failure contracts.

## Tests added

- `packages/msbwt-modern2/tests/test_reader_fm_py2.py` (Python-2 suite, 8
  tests): the float64-bincount in-place TypeError root cause with the exact
  dtype set (`ret` <u8, weights <u8, `np.bincount` float64, `np.add.at`
  uint64-exact), pure `getFullFMAtIndex` == compiled == oracle at all >1M
  boundaries, all-symbols-represented FM vectors, pure backward-search
  queries == compiled == oracle, 48-symbol pure FM == compiled == oracle,
  48-symbol query/recovery regression with pure-reader recovery equality and
  committed side-effect hashes, frozen-original TypeError preservation (both
  evidence sizes), and the modern2 fill-line source assertion.
- `compat/tests/test_modern2_reader_fm.py` (host suite, 15 tests): driver
  presence/independent tooling, evidence-record consistency, dataset hashes,
  dtype root cause from evidence, pure-FM == compiled == oracle equality,
  all-symbols-represented, pure backward-search equality, compiled byte
  side-effect hashes, 48-symbol FM/query/recovery evidence, frozen failure
  contract (lines 708/725 + TypeError), modern2 pre-fix probe preservation
  (positions + dtypes + line 726), committed prefix-probe content, frozen
  original untouched (SHA-256 + failing expression), modern2 fill line
  assertion, and the 7-added/6-removed diff whitelist with the exact fill
  lines.
- `compat/tests/test_modern2_reader_boundaries.py` — the diff-whitelist test
  extended from 6/5 to the documented FIVE-site correction set (7 added / 6
  removed, including the `np.add.at` line).
- `compat/tests/test_modern2_decompression.py` — `FIX_ADDED_LINES` /
  `FIX_REMOVED_LINES` extended with the milestone-6 fill line; docstrings
  updated from four to five corrections.
- `packages/msbwt-modern2/tests/test_reader_boundaries_py2.py` — the
  milestone-5 legacy-defect test now asserts the FROZEN original still
  raises the TypeError while the checkout returns correct integer FM vectors
  equal to the oracle.
- `packages/msbwt-modern2/validate/reader-milestone5.sh` — kept re-runnable
  on the fixed checkout: the checkout pure `getFullFMAtIndex` now records
  correct `uint64` values at all positions (equal to the oracle), and the
  TypeError assertion routes through the frozen original source (which still
  fails at line 725).

Tests fail if the float64 in-place cast is reintroduced (behavioral positions
+ source whitelist).

## Files changed

- `packages/msbwt-modern2/MUS/MultiStringBWT.py` — the pure-FM fill-line
  correction (line 726, `np.add.at`).
- `packages/msbwt-modern2/validate/reader-milestone6.sh` — validation driver
  (gates, evidence regen, frozen-source pre-fix reproduction, dtype evidence,
  checkout post-fix probes, independent verification, evidence JSON).
- `packages/msbwt-modern2/evidence/reader-milestone6.json` — executed
  evidence record.
- `packages/msbwt-modern2/evidence/reader-milestone6-prefix-probe.json` —
  committed modern2 pre-fix failure probe (executed at commit `eb45db9`).
- `packages/msbwt-modern2/tests/test_reader_fm_py2.py` — Python-2 regression
  tests.
- `packages/msbwt-modern2/tests/test_reader_boundaries_py2.py` — milestone-5
  legacy-defect test updated for the fixed checkout + frozen preservation.
- `packages/msbwt-modern2/validate/reader-milestone5.sh` — re-runnability
  update (see above).
- `compat/tests/test_modern2_reader_fm.py` — host-side regression tests.
- `compat/tests/test_modern2_reader_boundaries.py` / `test_modern2_decompression.py`
  — whitelist updates.
- `docs/modernization/MODERN2_MILESTONE6_READER_FM.md` — this document.

No frozen file, golden file, environment, persisted format, or Cython source
was modified.

## Test counts

- Legacy compatibility suite: 125 tests (unchanged, green).
- Modern2-specific host suite: 60 + 15 = 75 (200 total compat tests, green).
- Modern2 Python-2 suite: 47 + 8 = 55 tests, green.

## Stop conditions

None triggered: the defect was exactly a dtype/casting representation
problem; the correction does not change FM arithmetic (integer semantics
unchanged, verified equal to the float64 intermediate and to the compiled
reader); different valid integer casts produce the same mathematical counts
(the exact `np.add.at` result equals the float64 `ret + bincount` result);
pure and compiled readers imply identical semantics on every exercised input;
the independent FM oracle agrees on every exercised position; valid-collection
query/recovery behavior is unchanged; no persistent format change; the frozen
source was not modified; no dtype redesign was required; no new
compatibility-policy decision was required (this is the approved fix of the
Milestone-5 documented legacy defect).

## Out of scope / next slice

`MSBWTGenCython.compressBWT`, nonuniform construction, gzip, recovery,
merge, LZW, convert, and performance were NOT touched.  With the pure-Python
`CompressedMSBWT.getFullFMAtIndex` now returning correct FM vectors, the
pure and compiled readers agree with the independent oracle for
character/FM/query/recovery operations on the characterized uniform paths at
large boundaries.  Natural next modern2 slices: the compiled
`MSBWTGenCython.compressBWT` typed-division site, nonuniform
construction/decompression characterization, or the other pure-Python
bincount-with-weights sites (e.g. the `constructTotalCounts` list `+=`
float64 accumulation) under a documented compatibility decision.
