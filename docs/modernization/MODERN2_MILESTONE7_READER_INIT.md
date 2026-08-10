# MODERN2 — Milestone 7 (executed evidence): pure reader initialization / index construction

Status date: 2026-08-10

This milestone characterizes the two pure-Python first-load paths

    CompressedMSBWT.constructTotalCounts
    CompressedMSBWT.constructFMIndex

on completely fresh inputs (all reader-derived caches removed) under CPython
2.7.18 / NumPy 1.16.6, and proves that the generated

    totalCounts.p, comp_fmIndex.npy, comp_refIndex.npy

are exact, deterministic, regenerable, and semantically correct.  Test-first:
fresh loads were executed on disposable copies of the committed RLE golden
inputs with all derived caches removed, runtime types/dtypes/intermediates
were recorded, the generated files were compared byte-for-byte against the
committed frozen-reader evidence and the compiled reader, and only then was
a fix policy decided.

**Verdict: neither path required a source change.**  The modern2-vs-frozen
diff remains exactly the documented five correction sites from milestones
3-6.  Both suspicious sites are proven safe by executed evidence; the one
interesting finding (a derived-file convention difference between the pure
and compiled readers at exact run-boundary bins) is proven semantically
irrelevant (both conventions are oracle-correct and fully interchangeable).

Evidence is from two consecutive full runs of the committed validation
driver `packages/msbwt-modern2/validate/reader-milestone7.sh` (both passed;
the run evidence JSON is committed under
`packages/msbwt-modern2/evidence/reader-milestone7.json`, byte-identical
across both runs).

## Evidence inputs (all committed, all fresh copies)

| case | primary | shape | source |
|---|---|---|---|
| `posthoc48` | `uniform-compress-posthoc` `comp_msbwt.npy` | `(22,)` | golden artifacts |
| `direct48` | `uniform-direct-split` `comp_msbwt.npy` | `(22L,)` | golden artifacts (full tree) |
| `nonuni30` | `nonuniform-compress-posthoc` `comp_msbwt.npy` | `(16,)` | golden artifacts |
| `big` | m3c2/milestone-5 evidence RLE, shape `(484000,)`, SHA-256 `681caf56...` | 1,056,000 symbols, 516 bins | regenerated + compressed, hash-checked |

For every case the driver copied the input into a disposable directory,
deleted every reader-derived cache (`totalCounts.p`, `comp_fmIndex.npy`,
`comp_refIndex.npy`), instantiated the pure `CompressedMSBWT` naturally
(`loadMsbwt`), and recorded the exact created file set, hashes, dtypes,
shapes, intermediate values, and reader semantics.

## constructTotalCounts analysis (frozen == modern2, one site)

Frozen line 457 (`self.totalCounts += np.bincount(letters,
np.multiply(counts, self.numPower**powers), minlength=self.vcLen)` with
`self.totalCounts = [0]*self.vcLen` initially):

- The accumulator starts as a Python list.
- **Executed runtime behavior under CPython 2.7.18 / NumPy 1.16.6:** `list
  += ndarray` performs ELEMENTWISE numpy addition and rebinds the name to a
  `float64` ndarray of length 6 (the list is converted by ndarray's
  reflected add).  It does NOT extend the list — list extension is the
  Python-3 behavior of the same expression.  This is why the suspicion that
  the accumulator grows by 6 elements per chunk is wrong for this
  environment.
- The weighted `np.bincount` returns `float64`; each chunk's per-symbol
  weighted run totals accumulate elementwise into the `float64` ndarray.
- Result: `ndarray float64`, length 6, values equal to the independent
  decoded-RLE symbol totals for every exercised input (48: `[8,9,9,9,4,9]`;
  30: `[7,5,4,3,2,9]`; >1M: `[176000, 198000, 198000, 198000, 88000,
  198000]`); `totalSize` (their sum) is exact.  All values are exact
  integers (float64 is exact up to 2^53, far beyond any exercised count).
- The pickled `totalCounts.p` (a float64 ndarray pickle, 346 bytes for the
  48-symbol collection) is byte-identical to the committed frozen-reader
  evidence from the compression-milestone1 decompression-failure manifests
  (SHA-256 `c038b778...`).

**Verdict: SAFE.**  The `+=` performs numeric addition in this environment
(executed), the math is correct, the persistence is deterministic, and the
bytes match the committed frozen evidence exactly.  The `float64` storage
is a legacy representation choice, not a correctness defect for any
characterized input.

## constructFMIndex analysis (frozen == modern2, one site)

- `countsSoFar = np.cumsum(self.totalCounts)-self.totalCounts` runs on the
  float64 totals -> `float64` (integral values, e.g. `[0,8,17,26,35,39]`).
- `np.bincount(letters, counts, vcLen)` -> `float64`; `np.add(...)` ->
  `float64`; `countsSoFar += ...` -> `float64`.
- Every assignment into the preallocated `'<u8'` memmaps
  (`comp_fmIndex.npy`, `comp_refIndex.npy`) is a float64 -> uint64 setitem.
  All exercised values are exact integers within uint64 range, so the
  conversion is exact (verified against an independent per-bin oracle, see
  below); NumPy 1.16.6 setitem performs the cast without loss for these
  values.
- `self.partialFM[0][:] = countsSoFar` and the row updates are exact; the
  final files are `uint64` with shapes `(samplingSize, 6)` and
  `(samplingSize,)`.

**Verdict: SAFE.**  The float64 intermediates are exact-integer-valued for
all exercised inputs, the stored uint64 rows are exact, the files are
deterministic, and the semantics are oracle-verified at every bin (below).

## Byte-equality vs committed evidence and the compiled reader

- 48-symbol collection (both `posthoc48` and `direct48`): all three
  derived files are byte-identical to the committed frozen pure-reader
  side-effect hashes (`totalCounts.p` `c038b778...`, `comp_fmIndex.npy`
  `f6565545...`, `comp_refIndex.npy` `30c0c0f3...`), and the two npy files
  are byte-identical to the compiled `RLE_BWT` reader's files for the same
  input.
- 30-symbol collection: `comp_fmIndex.npy` `d3e57fa2...` and
  `comp_refIndex.npy` `30c0c0f3...` byte-identical to the committed frozen
  evidence and to the compiled reader.
- >1M evidence: `totalCounts.p` values correct; `comp_fmIndex.npy` /
  `comp_refIndex.npy` differ from the compiled reader's files at exactly
  171 of 516 bins — see the documented convention difference below.

## Documented pure-vs-compiled sampling convention difference (not a defect)

At bins whose 2048-boundary coincides EXACTLY with a run boundary (171 bins
on the tiled evidence: every third bin, because 2048*3 = 6144 is a multiple
of the 48-symbol tile length and each tile ends in a run boundary):

- Pure sampling records the run CONTAINING the boundary (for an exact
  boundary this is the next run) and the counts before it — its stored row
  IS the FM value at the boundary position.
- Compiled `RLE_BWT` sampling records the run ENDING at the boundary and
  the counts before it — one run earlier.

Both conventions are valid FM samplings: each reader's fill logic
(`getFullFMAtIndex`'s walk-forward) compensates for its own convention, and

- `pure.getFullFMAtIndex(bin*2048)` == independent oracle at **all 516
  bins** (executed, 0 mismatches);
- the compiled reader equals the oracle at every probed position;
- **interchangeability (executed):** the pure reader loaded against
  compiled-created files and the compiled reader loaded against
  pure-created files both return oracle-correct FM vectors at the
  convention-difference bins (e.g. position 6144 -> `[1024, 177152,
  375152, 573152, 770512, 859152]`, position 1055998 -> `[175999, 374000,
  572000, 770000, 858000, 1055999]` matching the committed milestone-6
  evidence), correct characters, and correct backward-search queries.

The differing bins satisfy `pure_refFM == compiled_refFM + 1` and every
differing bin is a tile boundary (all `binID % 3 == 0`); first and last
rows are identical between the two files.

## Required fresh-load validation (all executed)

For every case, on disposable copies with caches deleted:

1. fresh load constructs all three files successfully (no exception);
2. created file set is exactly `{totalCounts.p, comp_fmIndex.npy,
   comp_refIndex.npy}` next to the untouched primary;
3. dtypes/shapes/hashes recorded (see evidence);
4. **determinism:** a second fresh copy regenerates byte-identical files;
5. **regeneration:** deleting the caches and reloading reproduces the same
   bytes;
6. totals equal the independent decoded-RLE counts;
7. all 516 >1M bins equal the independent per-bin FM oracle;
8. queries equal the independent string-level FM oracle and the compiled
   readers;
9. valid collection query/recovery equal the committed values and the
   compiled reader.

## Reader semantics after fresh index construction

- `getCharAtIndex` at every probed position equals the raw decoded byte
  (pure == compiled == raw payload).
- `getFullFMAtIndex` pure == compiled == independent oracle (all 516 bins
  on the >1M evidence; `{0,1,2,5,10,20,40,47}` on the collections).
- `getOccurrenceOfCharAtIndex` and `countOccurrencesOfSeq` route through
  `getFullFMAtIndex` and match the committed query counts
  (`AAAAA=1, ACGTN=3, CCCCC=1, AGCTA=0, AAAAAA=0, GGGGG=1, NACGT=1,
  TTTTT=1, $=8` for the uniform collection; the committed nonuniform
  query table for the 30-symbol collection; `A=198000, AC=37125,
  ACGTN=111, ...` on the >1M evidence).
- Recovery over all dollar positions (8 for the uniform collection, 7 for
  nonuniform) equals the compiled reader and the committed evidence
  (`AAAAA$, ACGTN$, ACGTN$, ACGTN$, CCCCC$, GGGGG$, NACGT$, TTTTT$`).

## Historical behavior preservation

The frozen source is untouched (SHA-256 `95ac0b86...`), and the frozen and
modern2 `constructTotalCounts` / `constructFMIndex` function texts are
identical (CRLF-normalized) — the milestone made no change to either path.
The modern2-vs-frozen diff remains exactly the documented five correction
sites (7 added / 6 removed lines).  No historical evidence was rewritten:
the committed frozen pure-reader side-effect hashes were reproduced
byte-for-byte by the modern2 reader, confirming the frozen implementation
produces correct derived indexes despite the float64 intermediates.

## Out-of-scope observations (not fixes)

- `constructTotalCounts` persists float64 counts; values remain exact
  integers up to 2^53.  A uint64 representation (as the compiled reader
  uses in `totalCounts.npy`) would change `totalCounts.p` bytes and is
  therefore a compatibility-policy decision, not a milestone-7 fix.
- The pure `constructFMIndex` chunk walk-back cannot cross chunk boundaries
  (chunkSize 10000 bytes) for runs longer than one chunk; no characterized
  input has such runs (all evidence runs are single-byte runs).  This is
  frozen behavior, out of scope.
- The pure `samplingSize` is `ceil(totalSize/binSize)` while the compiled
  reader uses `ceil((totalSize+1)/binSize)`; the two agree on every
  exercised input (differing only when `totalSize % 2048 == 0`, not
  exercised).
- `MSBWTGenCython.compressBWT`, nonuniform construction, gzip, recovery,
  merge, LZW, convert, and performance were NOT touched.

## Tests added

- `packages/msbwt-modern2/tests/test_reader_init_py2.py` (Python-2 suite,
  13 tests): the CPython-2 `list += ndarray` elementwise-addition root
  cause, fresh `constructTotalCounts` runtime semantics, fresh
  `constructFMIndex` runtime semantics, exact symbol totals on all four
  inputs, committed frozen-evidence byte equality, exact created file set,
  determinism + regeneration on the multi-bin >1M case, pure == compiled
  == oracle semantics, all-516-bins oracle validation, pure-vs-compiled
  derived-file convention classification, interchangeability, valid
  collection query/recovery, and frozen-init-path identity + frozen SHA.
- `compat/tests/test_modern2_reader_init.py` (host suite, 17 tests):
  driver presence, evidence-record consistency, dataset hashes,
  constructTotalCounts/constructFMIndex runtime semantics from evidence,
  exact symbol totals, derived-file set/dtypes/determinism/regeneration,
  committed frozen byte equality, single-bin pure == compiled bytes, >1M
  convention classification, all-516-bins validation, collection
  semantics, big reader semantics, interchangeability constants,
  historical classification, frozen source untouched (including the two
  suspicious init expressions), and the unchanged 7/6 diff whitelist.

## Files changed

- `packages/msbwt-modern2/validate/reader-milestone7.sh` — validation
  driver (gates, evidence regen, fresh-load probes, independent
  verification, evidence JSON).
- `packages/msbwt-modern2/evidence/reader-milestone7.json` — executed
  evidence record (byte-identical across two consecutive driver runs).
- `packages/msbwt-modern2/tests/test_reader_init_py2.py` — Python-2
  regression tests.
- `compat/tests/test_modern2_reader_init.py` — host-side regression tests.
- `docs/modernization/MODERN2_MILESTONE7_READER_INIT.md` — this document.

No frozen file, golden file, environment, persisted format, Cython source,
or modern2 source was modified.

## Test counts

- Legacy compatibility suite: 125 tests (unchanged, green).
- Modern2-specific host suite: 75 + 17 = 92 (217 total compat tests,
  green).
- Modern2 Python-2 suite: 55 + 13 = 68 tests, green.

## Stop conditions

None triggered: constructTotalCounts semantics are unambiguous (executed
elementwise addition, byte-identical to frozen evidence); no competing
fixes were needed since no fix was required; constructFMIndex mathematics
unchanged; derived bytes agree with all committed evidence (single-bin) and
the documented convention difference is proven semantically irrelevant on
the >1M evidence; pure and compiled readers imply identical semantics on
every exercised input; valid-collection semantics unchanged; no persistent
format change; no dtype redesign; frozen source untouched; no new
compatibility-policy decision required.

## Next slice

With the pure-Python first-load paths proven safe, the core modern2 reader
stack (load/init, char, FM, occurrence, backward search, queries, recovery,
decompression) is fully repaired and characterized for the uniform byte/RLE
paths.  Natural next modern2 slices: the compiled
`MSBWTGenCython.compressBWT` typed-division site, nonuniform
construction/decompression characterization, or a uint64 `totalCounts.p`
representation under an approved compatibility decision.
