# MODERN2 — Milestone 2 (executed evidence): first RLE/compression slice

Status date: 2026-08-09

This milestone validates the first RLE/compression slice of msbwt-modern2 under
the pinned Cython 3.0.12 toolchain, specifically the integer/division/type
semantics deferred during Bootstrap Milestone 1.  All three uniform compressed
routes reproduce their committed legacy route-specific goldens byte-for-byte
with **zero source changes**: the migrated `.pyx` files were already
byte-identical to the frozen sources (plus the explicit `language_level=2`
header), and the executed evidence below proves the Cython-3 migration does
not alter any persisted byte.

Evidence is from the committed validation driver
`packages/msbwt-modern2/validate/compression-milestone2.sh` (two consecutive
full runs; the second run's evidence JSON is committed under
`packages/msbwt-modern2/evidence/compression-milestone2.json`).  The frozen
oracle environment was not modified; the modern2 environment is the separate
prefix from Bootstrap Milestone 1.

## Scope of this milestone

- Direct compressed construction (primary target):
  `pp -u OUT uniform-a.fastq uniform-b.fastq` then
  `cfpp -p 1 -u -c OUT` — exercises
  `MUSCython.MSBWTCompGenCython.createMsbwtFromSeqs` (compiled under Cython
  3.0.12) plus the compiled `MSBWTGenCython.clearAuxiliaryData`.
- Post-hoc compression (secondary target):
  `compress -p 1 SRC DST` over the committed uniform byte BWT — exercises the
  pure-Python `MUS.MSBWTGen.compressBWT`/`compressBWTPoolProcess` (no compiled
  code beyond module imports).
- Direct wrapper (optional, trivial after the above):
  `cffq -p 1 -u -c OUT` — exercises compiled
  `MUSCython.MultiStringBWTCython.createMSBWTCompFromFastq` (in-memory
  preprocess + the same compressed builder + cleanup).
- Reader/query validation of every produced RLE primary on disposable copies
  (compiled `MUSCython.RLE_BWTCython.RLE_BWT`).
- Decompression, recovery, interruption, merge, non-uniform, LZW, and convert
  remain OUT OF SCOPE for this milestone.

## Route contracts (committed legacy goldens)

| Route | Command | Golden case | `comp_msbwt.npy` whole SHA-256 | Shape literal |
|---|---|---|---|---|
| direct-split | `pp -u` + `cfpp -p 1 -u -c` | `uniform-direct-split` | `0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372` | `(22L,)` |
| direct-wrapper | `cffq -p 1 -u -c` | `uniform-direct-wrapper` | `0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372` | `(22L,)` |
| posthoc | `compress -p 1` | `uniform-compress-posthoc` | `53d82b388a9d565afa96ead611d5db964bee199869fd07f96b8c84258ba099a3` | `(22,)` |

Shared uniform RLE payload SHA-256 `6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb`;
decoded BWT `ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$` (SHA-256
`75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e`, equal to
the committed uniform byte primary).  Direct split and direct wrapper remain
whole-file byte-identical; post-hoc differs from direct only by the NumPy
shape literal `(22,)` vs `(22L,)` (both headers are exactly 118 bytes; the
padding space count compensates the literal length).  The direct
`(22L,)` literal comes from the `cdef unsigned long totalLength` shape value
persisted by `np.lib.format.open_memmap` under CPython 2; the post-hoc
`(22,)` literal comes from the Python-int shape value in the pure-Python
path.  Each route matches its OWN committed golden; the routes are NOT made
equal to each other.

## Executed validation (both driver runs identical)

### Determinism and process count

- Every route ran in fresh work directories: run-a (`-p 1`), run-b (`-p 1`),
  and run-p2 (`-p 2`).
- Same-route retained file sets and whole-file bytes are identical across
  run-a, run-b, and run-p2 (whole-directory tree hash comparison), i.e.
  `-p 1 == -p 2` byte-for-byte as required by the legacy evidence.
- direct-split retained set: `about.npy`, `comp_msbwt.npy`, `offsets.npy`,
  `seqs.npy.{0..5}.npy` (9 files); direct-wrapper: `about.npy`,
  `comp_msbwt.npy` (2 files); posthoc: `comp_msbwt.npy` (1 file).

### Golden comparison

For each route, verified with `compat/tools/artifact_manifest.py`:

1. retained file set vs the committed route manifest (no added/removed/changed
   files);
2. whole-file SHA-256 (see table above);
3. raw NPY header text (including the `(22L,)` vs `(22,)` distinction);
4. dtype `|u1`, logical shape `[22]`;
5. encoded payload SHA-256 `6aadcd547a78...`;
6. safe host-side RLE decoding (`decode_npy_rle_primary`, no NumPy/pickle)
   matches the committed `decoded-rle.json` field-for-field for each route:
   22 runs, decoded length 48, decoded BWT and SHA-256;
7. cross-route payload equality and run-signature equality;
8. decoded BWT equals the committed uniform byte primary payload.

### Reader/query validation (disposable copies only)

For each route's run-a output, on a disposable copy:

- `loadBWT` returns `MUSCython.RLE_BWTCython.RLE_BWT`;
- total size 48, dollar count 8 (`getSymbolCount(0)`);
- all 35 fixture-derived query counts match (the full k-mer matrix from the
  committed reader smoke, e.g. `ACGTN=3`, `AAAAA=1`, `AGCTA=0`,
  `AAAAAA=0`);
- `recoverString` over the 8 dollar IDs returns the committed recovered
  strings (`$AAAAA`, `$ACGTN` x3, `$CCCCC`, `$GGGGG`, `$NACGT`, `$TTTTT`);
- reader-created side effects are exactly `totalCounts.npy`,
  `comp_fmIndex.npy`, `comp_refIndex.npy` with SHA-256s
  `ea104b616fe8...`, `f6565545114d...`, `30c0c0f336e6...` — byte-identical to
  the committed legacy reader-smoke side-effect inventory.  No primary
  directory was mutated; reader caches were never promoted as persistent
  state.

## Cython-3 typed-semantics audit (compression slice)

The audit covered every division/modulo/power/type-sensitive expression on the
three exercised paths and on the reader slice (`.pyx` sources
`MSBWTCompGenCython`, `MSBWTGenCython`, `RLE_BWTCython`,
`MultiStringBWTCython`, `BasicBWT`; pure-Python `MUS/MSBWTGen.py`):

- The direct compressed builder (`MSBWTCompGenCython.pyx`) contains **no**
  typed `/` division at all.  Its only modulo site is
  `(columnID+2) % seqLen` (two positive `unsigned long` operands: Python and
  C modulo agree), and its only power sites are `32**finalSymbolPos` and
  `32**startPoint` (small positive operands; Cython-3 `**` on C integers uses
  C semantics but values are identical for this domain).  No cast or fix was
  needed; none was applied.
- The post-hoc path (`MUS/MSBWTGen.py`) is pure Python and NumPy 1.16.6;
  `delta /= numPower` operates on `np.uint32` scalars with positive values.
- The compiled `MSBWTGenCython.compressBWT` (not reachable from the CLI
  `compress` route) contains the typed division `prevTotal / (numPower**power)`
  (Cython-3 Python-semantics division on positive operands — identical
  results).  It is documented here and protected by the pyx-identity test;
  it will be exercised directly if a later slice routes through it.
- The RLE reader (`RLE_BWTCython`/`BasicBWT`) division sites are either
  float-based (`float(...)/binSize`) or positive-operand C divisions
  (`strLen/2`, `self.totalSize % binSize`, `numPower**self.iterPower`); all
  results are identical under Cython 2 and Cython 3.
- `unsigned long` shape values still serialize as Python-2 `long` literals in
  NumPy v1 headers under Cython 3.0.12 (`(22L,)`), preserving the historical
  header contract.

Every fix question answered "can this alter persisted bytes?" was verified
empirically: the whole-file, header, payload, and decoded comparisons above
are byte-exact against the committed goldens.  No arbitrary casts were made;
no source change of any kind was required for this milestone.

## Tests added

- `packages/msbwt-modern2/tests/test_compression_py2.py` (Python-2 suite, 6
  tests): direct-split golden identity, post-hoc golden identity,
  direct-wrapper golden identity, NPY header distinction, payload equality
  between routes, `-p 1`/`-p 2` byte equality, and RLE reader behavior on
  disposable copies — all with an independent in-test safe decoder (no
  NumPy/pickle).
- `compat/tests/test_modern2_compression.py` (host suite, 8 tests): driver
  presence, evidence-record consistency, evidence route hashes vs committed
  goldens, evidence reader side effects vs committed legacy reader smoke,
  compression-slice pyx byte-identity with the frozen originals (the
  strongest protection of the no-semantic-change audit), and the audited
  operator-site scan of the direct compressed builder.

## Files added/changed

- `packages/msbwt-modern2/validate/compression-milestone2.sh` — validation
  driver (routes x2 runs + `-p 2`, golden comparison, safe decode, reader
  smoke, evidence JSON).
- `packages/msbwt-modern2/evidence/compression-milestone2.json` — executed
  evidence record.
- `packages/msbwt-modern2/tests/test_compression_py2.py` — Python-2
  regression tests.
- `compat/tests/test_modern2_compression.py` — host-side regression tests.
- `docs/modernization/MODERN2_MILESTONE2_COMPRESSION.md` — this document.

No `.pyx`, `.pxd`, generated `.c`, setup.py, environment, or golden files
were modified.

## Test counts

- Legacy compatibility suite: 125 tests (unchanged, green).
- Modern2-specific suite (host-side): 26 bootstrap + 8 compression = 34.
- Modern2 Python-2 suite: 11 bootstrap + 6 compression = 17 tests, green.

## Out of scope / next slice

Decompression (including the documented Python-2/NumPy integer-index failure
contract), recovery, interruption, merge, non-uniform, LZW, and convert were
NOT touched.  The compiled `MSBWTGenCython.compressBWT` typed-division site
remains unexercised by any CLI route and is the natural first candidate for
the next compression-adjacent slice.  Safe to proceed to the next modern2
slice.
