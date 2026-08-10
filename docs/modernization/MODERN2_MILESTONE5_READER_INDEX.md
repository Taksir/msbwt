# MODERN2 — Milestone 5 (executed evidence): large reader/index boundary audit

Status date: 2026-08-10

This milestone determines whether the SAME Python-2 / NumPy promotion problem
already proven in decompression (uint64 scalar + Python int -> float64 under
CPython 2.7.18 / NumPy 1.16.6) affects real reader/query operations on large
BWTs, and repairs the affected reader sites with the same narrow,
value-preserving `int()` boundary-conversion policy.  Test-first: candidate
reader sites were located in the source, exercised through normal reader APIs
on the committed >1M-symbol evidence dataset, failures reproduced with exact
traceback/type evidence, and only then was source changed.  The frozen oracle
was not modified.

Evidence is from two consecutive full runs of the committed validation driver
`packages/msbwt-modern2/validate/reader-milestone5.sh` (both passed; the
second run's evidence JSON is committed under
`packages/msbwt-modern2/evidence/reader-milestone5.json`, with the committed
pre-fix failure probe under
`packages/msbwt-modern2/evidence/reader-milestone5-prefix-probe.json`).

## Evidence dataset (exactly the committed m3c2/milestone-4 evidence)

Reused without modification:

- Evidence primary: the committed uniform byte-BWT golden payload (48
  symbols) tiled 22000x: shape `(1056000,)`, whole-file SHA-256
  `24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35`.
- Compressed RLE: modern2 `compress -p 1` -> `comp_msbwt.npy`, shape
  `(484000,)`, SHA-256
  `681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99`.
- FM structure: 516 bins of 2048 symbols; bins 0..515, last bin covers
  `[1054720, 1056000)`.

No new large fixture was invented.

## Candidate reader/index sites inspected

Reader-side expressions conceptually of the form `refFM[binID+1] + 1` were
located in three places (plus the already-fixed decompression site):

1. Pure-Python `MUS/MultiStringBWT.py` `CompressedMSBWT.getCharAtIndex`
   (line 574): `endRange = self.refFM[binID+1]+1`.
2. Pure-Python `MUS/MultiStringBWT.py` `CompressedMSBWT.getFullFMAtIndex`
   (line 707): `endRange = self.refFM[binID+1]+1`.
3. Compiled `MUSCython/RLE_BWTCython.pyx` `RLE_BWT.decompressBlocks`
   (line 372): `endRange = self.refFM[endBlock+1]+1` (reached through the
   public `RLE_BWT.getBWTRange`).

All other reader sites were traced and exercised:

- Compiled `ByteBWT.getCharAtIndex` / `getOccurrenceOfCharAtIndex` /
  `getFullFMAtIndex` (and `BasicBWT.countOccurrencesOfSeq`) perform the
  arithmetic in C-typed Cython (`unsigned long`, typed memoryviews) — no
  NumPy promotion possible; exercised and correct on the >1M primary.
- Compiled `RLE_BWT.getCharAtIndex` / `getOccurrenceOfCharAtIndex` /
  `getFullFMAtIndex` (typed) — exercised and correct on the >1M RLE.
- Pure-Python `MultiStringBWT` (byte) reader — no `refFM` pattern; exercised
  on the 48-symbol collection.
- `CompressedMSBWT.getBWTRange`/`decompressBlocks` (line 628) — already
  repaired in milestone 4; re-exercised.

## Executed runtime type evidence (pinned environment, both probe runs)

| expression | runtime type before | after `+1` / arithmetic | value |
|---|---|---|---|
| `refFM[0+1]` (bin 0 boundary) | `numpy.uint64` | — | 938 |
| `refFM[0+1]+1` | `numpy.uint64` | **`numpy.float64`** | 939.0 |
| `refFM[488+1]` (work boundary) | `numpy.uint64` | — | 459008 |
| `refFM[488+1]+1` | `numpy.uint64` | **`numpy.float64`** | 459009.0 |
| `index - trueIndex` (dist) | Python int / uint64 | `numpy.float64` | 578.0 etc. |
| `int(np.uint64(x))` | — | Python int/long, exact | `int(big) == 9223372036854775813L` |

The float64 `dist` values are used only by `np.searchsorted` (comparison) and
exact scalar set-item casts — harmless (same classification as the
milestone-4 `dist`).  The float64 `endRange` values are used as array
indices/slice bounds — **invalid**: NumPy 1.16.6 rejects them with
`IndexError` (no `__index__`).

## Reproduced failures (pre-fix, executed)

Frozen source (the committed `MUS/MultiStringBWT.py`, hash
`95ac0b86...`) loaded and exercised directly inside the pinned environment on
the >1M RLE:

- `CompressedMSBWT.getCharAtIndex(2048)` — `IndexError` at line 575
  (`self.bwt[endRange]` with `np.float64`), message "only integers, slices
  (`:`), ... are valid indices".  Every non-last-bin position failed; only
  the last bin worked.
- `CompressedMSBWT.getFullFMAtIndex(2048)` — same `IndexError` at line 708.
- `CompressedMSBWT.getFullFMAtIndex(1055998)` (last bin) — reaches the fill
  line 725 `ret += np.bincount(...)` and raises
  `TypeError: Cannot cast ufunc add output from dtype('float64') to
  dtype('uint64') with casting rule 'same_kind'` (see the documented legacy
  defect below).
- Compiled `RLE_BWT.getBWTRange` / `decompressBlocks` on the bootstrap-built
  extension — `IndexError` at `MUSCython/RLE_BWTCython.pyx:375` for every
  range ending before the last block (committed prefix probe
  `reader-milestone5-prefix-probe.json`).  The extension loop at line 375
  indexes `self.bwt[endRange]` with the promoted float64 whenever the run at
  the block boundary spans two or more compressed bytes; the `int()`
  conversions at lines 379-380 occur only AFTER that loop.

## The fixes (narrowest possible, three sites)

`packages/msbwt-modern2/` only:

```python
# CompressedMSBWT.getCharAtIndex (line 574) and
# CompressedMSBWT.getFullFMAtIndex (line 707)
endRange = int(self.refFM[binID+1])+1

# MUSCython/RLE_BWTCython.pyx RLE_BWT.decompressBlocks (line 372)
endRange = int(self.refFM[endBlock+1])+1
```

- `int(np.uint64(x))` converts the refFM scalar to a true Python integer
  before the `+1` arithmetic.  The conversion preserves the **exact
  mathematical value** (proven in the pinned environment for both the `int`
  and `long` cases; refFM values are compressed-file byte offsets, always
  integral); only the representation changes so the extension-loop index and
  the `self.bwt[bwtIndex:endRange]` slice bounds are legal.
- No arithmetic meaning, region size, run boundary, symbol count, FM value,
  or persisted byte changes: the `+1` is still applied, the extension loops
  still extend `endRange` across same-symbol bytes, and the returned
  character/FM values are byte-identical to the independent oracles.
- `MUS/MultiStringBWT.py` now differs from the LF-normalized frozen original
  by exactly the documented four index-boundary corrections (milestone-3
  fill loop, milestone-4 `decompressBlocks`, milestone-5
  `getCharAtIndex`+`getFullFMAtIndex`); `RLE_BWTCython.pyx` differs by
  exactly the `language_level=2` directive plus the `decompressBlocks`
  endRange correction.  The generated `RLE_BWTCython.c` was regenerated with
  the pinned Cython 3.0.12 in the pinned environment (the committed .c
  regenerates cleanly); the .c diff is confined to the `decompressBlocks`
  function (register renumbering plus the `__Pyx_PyNumber_Int` call).

## DOCUMENTED LEGACY DEFECT (discovered, NOT fixed — frozen arithmetic preserved)

`CompressedMSBWT.getFullFMAtIndex` line 725 (`ret +=
np.bincount(letters[0:x-1], counts[0:x-1], minlength=self.vcLen)`):
`np.bincount` with weights returns float64, and NumPy 1.16.6 in-place
`same_kind` casting rejects float64 -> uint64, so the line raises the
TypeError above whenever more than one run precedes the target position.
This is **independent** of the uint64+int promotion (it also fails on the
last bin and on the 48-symbol single-bin case) and would fail with perfectly
integer arithmetic; it is a frozen dtype-cast defect in the pure-Python RLE
FM path, out of the milestone's index-boundary policy ("Do not add arbitrary
casts merely to silence errors"; stop condition 2).  It is preserved as
legacy evidence and asserted read-only by the tests and the driver.  The
compiled `RLE_BWT` reader (the normal API, returned by
`MultiStringBWTCython.loadBWT`) implements the same function with typed
Cython arithmetic and is fully correct.  A future slice may fix the pure
path under an approved compatibility decision.

## Executed validation (both driver runs identical)

### Environment and gates

- CPython 2.7.18, Cython 3.0.12, NumPy 1.16.6, pysam 0.15.4, GCC 7.3.0 conda
  toolchain, `PYTHONHASHSEED=0`, `LANG=C.UTF-8`, `TZ=UTC`, single BLAS/OMP
  threads.
- All 47 Python-2 tests pass (11 bootstrap + 6 compression + 10 milestone-3
  + 10 milestone-4 + 10 new reader-boundary), including all prior
  regressions.
- Evidence primary regenerated deterministically and hash-matched; modern2
  compression reproduced the committed m3c2 RLE primary.

### Large ByteBWT boundary results (compiled reader, >1M primary)

At positions 0, 1, 2047, 2048, 2049, 999998, 999999, 1000000, 1000001,
1055998, 1055999 (`getCharAtIndex`), every returned symbol equals the raw
primary byte (1,4,2,2,2,0,0,0,2,5,0).  `getFullFMAtIndex` at 0/2048/1000000/
1055999 equals the independent startIndex+cumulative-count oracle exactly.
`countOccurrencesOfSeq` for 13 representative k-mers equals the independent
string-level FM backward counts (`A=198000`, `AC=37125`, `ACGTN=111`,
`AAAAAA=45`, ...).  Reader-created side effects remain exactly
`totalCounts.npy` (`e7fe29a9...`) and `fmIndex.npy` (`16e19742...`),
byte-identical to the milestone-4 evidence.

### Large RLE_BWT boundary results (compiled reader, >1M RLE)

`getCharAtIndex`/`getFullFMAtIndex`/`countOccurrencesOfSeq` — identical
oracle-exact results to the byte reader (validated independently; the
compressed-reference-index FM arithmetic agrees with the byte-level oracles).

`getBWTRange` (the fixed `decompressBlocks`) for five representative ranges —
`(0,2048)`, `(0,1000000)`, `(1000000,1056000)`, `(1054720,1056000)`,
`(0,1056000)` — returns byte-identical slices of the expected payload AND is
byte-identical to the fixed pure-Python `getBWTRange` (cross-path equality;
the pure path was already validated byte-for-byte in milestone 4).

### Pure-Python CompressedMSBWT boundary results

- `getCharAtIndex`: all 11 boundary positions return the raw primary byte
  (pre-fix: IndexError at line 575 for every non-last-bin position).
- `getFullFMAtIndex`: positions with `x <= 1` (0, 1, 2048, 2049) return
  oracle-exact arrays (pre-fix: IndexError at line 708).  Positions preceded
  by more than one run (2047, 999998, 1000000, 1055999) raise ONLY the
  documented legacy line-726 TypeError — proving the fix removed exactly the
  promotion defect and changed no frozen arithmetic.
- 48-symbol single-bin case unchanged (works, refFM shape 1).

### Independent FM/backward-count comparison

All reader query/FM results are compared against independent pure-Python
oracles (startIndex + cumulative symbol counts for full-FM; C-table + rank
backward search for k-mer counts) on the raw payload — never only against
another reader path.  The driver also cross-checks ranges between the
compiled and pure readers.  (The tiled evidence is not a valid collection
BWT; collection-semantics query/recovery expectations apply only to the
committed 48-symbol fixtures, per the milestone-4 scope note.)

### Valid collection regression (uniform byte + RLE, 48 symbols)

- Compiled byte and RLE readers: total size 48, dollar count 8, query counts
  unchanged (`AAAAA=1`, `ACGTN=3`, `CCCCC=1`, `AGCTA=0`, `AAAAAA=0`,
  `GGGGG=1`, `NACGT=1`, `TTTTT=1`, `$=8`), byte-vs-RLE queries equal.
- Recovered strings over all 8 dollar positions: byte reader == RLE reader.
- Byte-reader side effects `totalCounts.npy` (`ea104b61...`) and
  `fmIndex.npy` (`a5b4bf06...`) byte-identical to the committed milestone-3
  reader evidence.

## Tests added

- `packages/msbwt-modern2/tests/test_reader_boundaries_py2.py` (Python-2
  suite, 10 tests): the uint64+int->float64 promotion root cause (int and
  long exactness), pure `getCharAtIndex` at all 11 boundaries vs raw bytes,
  pure single-bin small-RLE regression, pure `getFullFMAtIndex` oracle
  positions + preserved legacy line-726 TypeError, compiled
  `RLE_BWT.getBWTRange` five ranges vs payload and pure path, compiled
  RLE_BWT character/FM/query oracles, compiled ByteBWT boundaries/FM/queries
  + committed side-effect hashes, and valid-collection query/recovery
  regression on both compiled readers.
- `compat/tests/test_modern2_reader_boundaries.py` (host suite, 14 tests):
  driver presence/independent tooling, evidence-record consistency,
  dataset hashes, pure getCharAtIndex boundary values, pure getFullFMAtIndex
  fix + preserved legacy defect, compiled RLE ranges, compiled query-oracle
  equality for both readers, valid-collection regression, pre-fix frozen
  failure contract (lines 575/708/725/375 + float64 promotion), frozen
  reader-site arithmetic preservation, pyx diff whitelist
  (language_level + one fix line), regenerated-.c site check, and the
  MultiStringBWT.py diff whitelist.
- `compat/tests/test_modern2_decompression.py` — the diff-whitelist
  assertions extended from two to the documented FOUR-site correction set.
- `compat/tests/test_modern2_compression.py` — the pyx identity test now
  exempts `RLE_BWTCython.pyx` and a new test pins its exact two-line diff.

Tests fail if the invalid float64 index representation is reintroduced
(behavioral positions + source whitelists).

## Files changed

- `packages/msbwt-modern2/MUS/MultiStringBWT.py` — two reader-site
  corrections (getCharAtIndex line 574, getFullFMAtIndex line 707).
- `packages/msbwt-modern2/MUSCython/RLE_BWTCython.pyx` — decompressBlocks
  endRange correction (line 372).
- `packages/msbwt-modern2/MUSCython/RLE_BWTCython.c` — regenerated with the
  pinned Cython 3.0.12 (diff confined to decompressBlocks).
- `packages/msbwt-modern2/validate/reader-milestone5.sh` — validation driver
  (gates, evidence regen, frozen-source pre-fix reproduction, checkout
  post-fix probes, independent verification, evidence JSON).
- `packages/msbwt-modern2/evidence/reader-milestone5.json` — executed
  evidence record (second driver run).
- `packages/msbwt-modern2/evidence/reader-milestone5-prefix-probe.json` —
  committed pre-fix failure probe (unmodified frozen source and the
  bootstrap-built extension, executed in the pinned environment).
- `packages/msbwt-modern2/tests/test_reader_boundaries_py2.py` — Python-2
  regression tests.
- `compat/tests/test_modern2_reader_boundaries.py` — host-side regression
  tests.
- `compat/tests/test_modern2_decompression.py` / `test_modern2_compression.py`
  — whitelist updates.
- `docs/modernization/MODERN2_MILESTONE5_READER_INDEX.md` — this document.

No frozen file, golden file, environment, or persisted format was modified.

## Test counts

- Legacy compatibility suite: 125 tests (unchanged, green).
- Modern2-specific suite (host-side): 55 + 14 + 1 = 70 (185 total compat
  tests, green).
- Modern2 Python-2 suite: 37 + 10 = 47 tests, green.

## Stop conditions

None triggered: reader results agree with the independent byte-level
semantics on both large ByteBWT and large RLE_BWT paths; the issues were
exactly representation/index-boundary problems (the one non-boundary defect
discovered — the frozen line-725 bincount dtype cast — is preserved as
documented legacy evidence, not fixed); no FM arithmetic changed; ByteBWT
and RLE_BWT imply the same policy; valid-collection query/recovery behavior
is unchanged; no persistent format change; frozen source untouched; no
dtype redesign; no new compatibility-policy decision was required (the
line-725 fix is deferred to a future slice with an explicit decision).

## Out of scope / next slice

`MSBWTGenCython.compressBWT`, nonuniform construction, gzip, recovery,
merge, LZW, convert, and performance were NOT touched.  With the
decompression sites (lines 662/630) and the reader sites (574/707/372) all
repaired under the same documented policy, byte/RLE reader/query behavior is
broadly repaired for the characterized uniform paths at large boundaries.
Natural next modern2 slices: the pure-Python `getFullFMAtIndex` line-725
float64-bincount legacy defect (needs a documented compatibility decision),
the compiled `MSBWTGenCython.compressBWT` typed-division site, or nonuniform
construction/decompression characterization.
