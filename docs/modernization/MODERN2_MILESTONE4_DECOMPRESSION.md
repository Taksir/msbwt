# MODERN2 — Milestone 4 (executed evidence): multi-block decompression

Status date: 2026-08-10

This milestone validates and repairs the SECOND manifestation of the already-
understood Python-2 / NumPy integer-index bug: **multi-block decompression**
of an RLE MSBWT whose logical decoded size (1,056,000 symbols) exceeds the
decompression work size (1,000,000 symbols), splitting decompression into two
work regions.  The historical frozen implementation fails deterministically
with `IndexError` at `MUS/MultiStringBWT.py:630` in the first worker tuple
(the committed legacy m3c2 contract, exit 87).  Modern2 is NOT required to
reproduce that crash; multi-block decompression is explicitly permitted to be
FIXED as the second documented correctness deviation, reusing the same
representation-only `int()` boundary conversion policy established in
Milestone 3.  The frozen oracle was not modified, and the committed legacy
m3c2 failure evidence remains intact and is asserted read-only by the new
tests and the validation driver.

Evidence is from two consecutive full runs of the committed validation driver
`packages/msbwt-modern2/validate/decompression-milestone4.sh` (both passed;
the second run's evidence JSON is committed under
`packages/msbwt-modern2/evidence/decompression-milestone4.json`).  The frozen
oracle environment was not modified; the modern2 environment is the separate
prefix from Bootstrap Milestone 1 (CPython 2.7.18, Cython 3.0.12, NumPy
1.16.6, pysam 0.15.4).

## Evidence dataset (exactly the committed m3c2 evidence)

The compressed input is byte-identical to the committed legacy m3c2 evidence:

- Evidence primary: the committed uniform byte-BWT golden payload (48
  symbols) tiled 22000x (`np.tile`, exactly as the committed
  `compression_milestone3.py` probe generated it): shape `(1056000,)`,
  whole-file SHA-256
  `24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35`
  (byte-identical to the committed `relationship-m3c2.json`
  `evidence_primary`).
- Compressed RLE: modern2 `compress -p 1` produced `comp_msbwt.npy`, shape
  `(484000,)`, SHA-256
  `681caf56aa0630250234929f8bebee1f0b973b372c2786e48b2d2ad59940eb99`
  (byte-identical to the committed m3c2 clean-compression primary; modern2
  compression reproduces the frozen oracle bytes for this input).
- Decompression work size 1,000,000 → exactly two work regions:
  `[0, 1000000)` and `[1000000, 1056000)`.

No new large fixture was invented; the committed evidence dataset was
regenerated deterministically from the committed golden and hash-matched
before every run.

## Root cause (verified, matching the legacy evidence)

The failing expression is the region-end arithmetic of the pure-Python
`MUS.MultiStringBWT.CompressedMSBWT.decompressBlocks`:

```python
startRange = self.refFM[startBlock]
...
endRange = self.refFM[endBlock+1]+1
while endRange < self.bwt.shape[0] and (self.bwt[endRange] & self.mask) == (self.bwt[endRange-1] & self.mask):
    endRange += 1
```

- `refFM` is a `<u8` (uint64) array, so `self.refFM[endBlock+1]` is an
  `np.uint64` scalar.
- Under the pinned CPython 2.7.18 / NumPy 1.16.6 profile, NumPy's value-based
  type promotion computes `np.uint64 + 1` (Python int) as **`np.float64`**
  (int64 + uint64 -> float64), not as an integer.
- `np.float64` cannot index a NumPy array, so `self.bwt[endRange]` on the
  line-630 extension loop raises the committed legacy exception:
  `IndexError: only integers, slices (`:`), ellipsis (`...`),
  numpy.newaxis (`None`) and integer or boolean arrays are valid indices`
  — before any region completes (exit 87, mode
  `first-tuple-worker-failed-naturally`, tuple count 2, first tuple
  `[SOURCE, DESTINATION, 0, 1000000]`, zero completed regions).

Concrete runtime type evidence, recorded inside the pinned environment on the
regenerated evidence RLE (both worker regions):

| expression (region 1, startBlock=0/endBlock=488) | runtime type | value |
|---|---|---|
| `self.refFM[endBlock+1]` | `numpy.uint64` | 459008 |
| `self.refFM[endBlock+1]+1` | `numpy.float64` | 459009.0 |
| `expectedIndex - trueIndex` (`dist`) | `numpy.float64` | 0.0 |
| `startRange` | `numpy.uint64` | 0 |

| expression (region 2, startBlock=488/endBlock=515) | runtime type | value |
|---|---|---|
| `endRange` (last-block branch) | `int` | 484000 |
| `expectedIndex - trueIndex` (`dist`) | `numpy.float64` | 2.0 |
| `startRange` | `numpy.uint64` | 458070 |

Additional verified behaviors: `counts[lInd] -= dist` with a float64
integral `dist` performs an exact set-item cast into the `<u8` array
(verified: `uint64[0] -= np.float64(2.0)` → 3, no exception), so the
float64 `dist` in the tail-region skip loop is harmless and requires NO
fix.  Every other index/slice in the exercised path already uses Python
integers or NumPy scalars implementing `__index__` (e.g. the `np.uint64`
`startRange` slice bound is legal; only `uint64 + int` promotions are not).

Classification: **representation/type problem only** — the arithmetic is
mathematically correct; only the promoted float64 representation breaks the
index/slice boundary.

## The fix (narrowest possible)

One additional site in `packages/msbwt-modern2/MUS/MultiStringBWT.py`
`decompressBlocks` (the region-end site):

```python
endRange = int(self.refFM[endBlock+1])+1
```

- `int(self.refFM[endBlock+1])` converts the `np.uint64` refFM scalar to a
  true Python integer before the `+1` arithmetic.  The conversion preserves
  the **exact mathematical value** (verified in the pinned environment for
  both the `int` and `long` cases; refFM values are compressed-file byte
  offsets, always integral); only the representation changes so the line-630
  loop index and the `self.bwt[startRange:endRange]` slice bound are legal.
- No arithmetic meaning, region size, run boundary, symbol count, output
  length, or persisted byte changes: the `+1` is still applied, and the
  extension loop still extends `endRange` across same-symbol bytes.
- The Milestone-3 fill-loop fix (`runLength = int(counts[lInd])`, line 662)
  is unchanged; the host-side diff test proves modern2 `MultiStringBWT.py`
  differs from the LF-normalized frozen original by exactly these two
  documented index-boundary corrections and nothing else.

## Executed validation (both driver runs identical)

### Environment and gates

- CPython 2.7.18, Cython 3.0.12, NumPy 1.16.6, pysam 0.15.4, GCC 7.3.0 conda
  toolchain, `PYTHONHASHSEED=0`, `LANG=C.UTF-8`, `TZ=UTC`, single BLAS/OMP
  threads.
- All 37 Python-2 tests pass (11 bootstrap + 6 compression + 10 milestone-3
  decompression + 10 new multi-block decompression tests), including the
  milestone-3 single-block decompression regression (no regression).
- The evidence primary regenerated deterministically and hash-matched the
  committed m3c2 `evidence_primary`; modern2 `compress -p 1` reproduced the
  committed m3c2 RLE primary byte-for-byte.

### Decompression runs

Four runs from fresh sources containing ONLY `comp_msbwt.npy`:
`-p 1` (run-a, run-b) and `-p 2` (run-a, run-b).

Result for every run:

- exit 0; destination contains exactly `msbwt.npy`.
- whole-file SHA-256 `24447374bcdfcfc11170cd76d46210dad8795c6eb667e2f4ba1eb8d437924e35`
  — **byte-identical to the committed m3c2 evidence primary** (header
  `(1056000,)`, dtype `|u1`, shape `[1056000]`; the same-file byte equality
  proves header and payload equality together).
- payload SHA-256 `7c27ccd61dec44ede4a02c883459eef78f5d909b8f30be327584c1a24391cc78`
  — byte-for-byte equal to the independent expectation: the committed
  uniform byte-golden payload repeated 22000x.
- exact logical length 1,056,000; symbol counts `$=176000, A=198000,
  C=198000, G=198000, N=88000, T=198000` (22000x the committed golden
  counts).
- source side effects: exactly `totalCounts.p`, `comp_fmIndex.npy`,
  `comp_refIndex.npy` added; `comp_msbwt.npy` unchanged (the same
  `loadMsbwt` support-file contract as the legacy failure source-after set).
- determinism: all four runs byte-identical (destinations and source
  side-effect trees); `-p 1` output == `-p 2` output.

### Independent RLE decode (host-side, no NumPy)

`compat/tools/artifact_manifest.decode_npy_rle_primary` on the modern2
`comp_msbwt.npy`: dtype `|u1`, 484,000 runs, decoded length 1,056,000,
decoded payload SHA-256 `7c27ccd6...` — exactly the decompressed payload.

### Block-boundary validation

Around the work-region boundary B=1,000,000 (and the edges), every position
matches the independent expectation:

| position | decoded | expected |
|---|---|---|
| 999998 | 0 ($) | 0 ($) |
| 999999 | 0 ($) | 0 ($) |
| 1000000 | 0 ($) | 0 ($) |
| 1000001 | 2 (C) | 2 (C) |
| 1000002 | 2 (C) | 2 (C) |
| 0 / 1 / 1055998 / 1055999 | 1,4 / 5,0 | 1,4 / 5,0 |

No off-by-one, duplicated run, missing symbol, overlapping write, or
unwritten region was observed anywhere in the decoded payload (the full
payload equals the expectation byte-for-byte).

### Reader/query validation (disposable copies only)

The compiled reader loads the >1M primary as `MUSCython.ByteBWTCython.ByteBWT`
on disposable copies: total size 1,056,000, dollar count 176,000, and
`countOccurrencesOfSeq` results for 13 representative k-mers match an
independent pure-Python FM backward search on the same payload (string-level
FM counts, e.g. `A=198000`, `AC=37125`, `ACGTN=111`, `AAAAAA=45`),
deterministic across two independent reader loads.  Reader-created side
effects are exactly `totalCounts.npy` and `fmIndex.npy` (SHA-256s
`e7fe29a99498d61a278845772782b10d22256a9556e865704d75a54e160fe348` and
`16e19742f54504b19ff72d278cea134b6063a0c51eac77f784699659013d8040`,
sizes 176 and 24896 bytes), identical across the two loads.

IMPORTANT SCOPE NOTE: the tiled evidence primary is a byte string, **not a
valid collection BWT**.  Tiling the BWT string interleaves equal rotations
instead of grouping them contiguously (the multiset BWT of
{read}x22000 would group them), so the reader's LF cycles do not decompose
into the 8 fixture reads (`recoverString` yields long pseudo-reads) and
collection-semantics query/recovery expectations are NOT applicable to this
input.  The decompression correctness contract is byte-level and is fully
validated independently (length, symbol counts, payload hash, boundary
neighborhoods, safe RLE decode, whole-file byte identity with the evidence
primary).  Reader validation therefore cross-checks the reader's query
arithmetic against the independent FM oracle on the same payload rather than
against a read multiset.

## Side-effect classification (modern2 successful multi-block decompression)

- Compressed primary input: `comp_msbwt.npy` (unmodified).
- Decompressed primary: destination `msbwt.npy` (the SUCCESS contract,
  byte-identical to the committed evidence primary).
- Required persistent support files (created in the source, same as the
  legacy `loadMsbwt` contract): `totalCounts.p`, `comp_fmIndex.npy`,
  `comp_refIndex.npy`.
- Lazy reader indexes (created only on disposable reader copies, never
  promoted): `totalCounts.npy`, `fmIndex.npy`.
- Temporary files: none inside the source/destination trees.
- The legacy m3c2 failure-only artifacts (all-zero preallocated `msbwt.npy`,
  partial writes) are NOT part of the modern2 successful format contract;
  the all-zero preallocated destination primary (SHA-256
  `d77f2be75db0b24fac38eb10296701625652fc7c98d77ebf9cf59b53fcd0a691`, payload
  all-zero `7585591907...`) remains failure evidence only.

## Tests added

- `packages/msbwt-modern2/tests/test_multiblock_decompression_py2.py`
  (Python-2 suite, 10 tests): >1M decompression success contract, `-p 1`
  determinism, `-p 1`/`-p 2` byte equality, logical length, symbol counts,
  payload equality with the tiled-golden expectation, block-boundary
  neighborhoods, source side effects, the concrete uint64+int→float64
  promotion type evidence, the focused line-630 regression through the real
  `getBWTRange`/`decompressBlocks` on both regions, reader FM-count
  cross-check on a disposable copy, and the committed legacy m3c2 failure
  evidence preservation.
- `compat/tests/test_modern2_multiblock_decompression.py` (host suite, 10
  tests): driver presence/independent-tooling, evidence-record consistency,
  success-contract hashes (whole `24447374...`, payload `7c27ccd6...`,
  shape, counts), block-boundary evidence, reader gate vs the committed
  string-level FM counts, legacy m3c2 contract assertions, and the frozen
  digest + two-site whitelist source checks.
- `compat/tests/test_modern2_decompression.py` (host suite, milestone-3 file
  updated): the diff whitelist and conversion-site assertions were extended
  from the single milestone-3 fix to the documented TWO-site index-boundary
  correction set.  No assertion was weakened.

## Files changed

- `packages/msbwt-modern2/MUS/MultiStringBWT.py` — the ONLY source change:
  the `decompressBlocks` region-end site (1 line, exact-diff proven along
  with the milestone-3 fill-loop fix).
- `packages/msbwt-modern2/validate/decompression-milestone4.sh` — validation
  driver (evidence regeneration, compress reproduction, `-p 1` x2 + `-p 2`
  x2 from fresh sources, header/payload/boundary/independent-RLE-decode
  verification, `-p 1`/`-p 2` and determinism checks, reader FM cross-check,
  legacy-evidence read-only assertions, evidence JSON).
- `packages/msbwt-modern2/evidence/decompression-milestone4.json` — executed
  evidence record (second driver run).
- `packages/msbwt-modern2/tests/test_multiblock_decompression_py2.py` —
  Python-2 regression tests.
- `compat/tests/test_modern2_multiblock_decompression.py` — host-side
  regression tests.
- `compat/tests/test_modern2_decompression.py` — milestone-3 host tests
  updated to the documented two-site diff whitelist.
- `docs/modernization/MODERN2_MILESTONE4_DECOMPRESSION.md` — this document.

No frozen file, `.pyx`, generated `.c`, setup.py, environment, or golden
file was modified.

## Test counts

- Legacy compatibility suite: 125 tests (unchanged, green).
- Modern2-specific suite (host-side): 45 + 10 = 55.
- Modern2 Python-2 suite: 27 + 10 = 37 tests, green.

## Stop conditions

None triggered: the root cause is exactly the characterized numeric/index
type problem at a second site; the fix preserves mathematical arithmetic;
decompressed bytes equal the independent expectation for BOTH work regions
(and the whole file is byte-identical to the committed evidence primary);
block boundaries are exact; `-p 1` is deterministic and equals `-p 2`; no
destination region was left unwritten or overlapped; reader/query arithmetic
is consistent with the independent FM oracle; no persistent format change;
frozen source untouched; the milestone-3 single-block decompression contract
regresses nowhere; no new compatibility-policy decision was required.

## Out of scope / next slice

Recovery/resume, interruption, merge, nonuniform decompression, LZW,
convert, and broader CLI bugs were NOT touched.  With the line-662 and
line-630 sites both repaired under the same documented policy, byte/RLE
decompression is broadly repaired for the characterized uniform paths
(single-block and multi-block).  Natural next modern2 slices: the compiled
`MSBWTGenCython.compressBWT` typed-division site, nonuniform
construction/decompression characterization, or the reader-side
`getCharAtIndex`/`getFullFMAtIndex` query paths that share the
`refFM[binID+1]+1` promotion pattern (outside decompression).
