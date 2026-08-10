# MODERN2 — Milestone 8 (executed evidence): nonuniform construction + gzip input

Status date: 2026-08-10

This milestone broadens modern2 from the characterized uniform byte/RLE path to
two already-established real legacy contracts:

1. nonuniform read-length construction (`pp` + `cfpp -p 1` without `-u`), and
2. gzip FASTQ input (`pp` of `.gz` fixtures + `cfpp -p 1` without `-u`).

Both routes go through `MUSCython.MultimergeCython`, which was still a
not-implemented stub (`NotImplementedError`) when the milestone started, so a
real source change was required: the frozen 2036-line `MultimergeCython.pyx`
was migrated to the pinned Cython 3.0.12 toolchain.  **The migration diff is
exactly one line** — `#cython: language_level=2` after the `#!python` shebang
— and the module compiled and reproduced the committed legacy bytes
byte-for-byte on the first execution.

**Verdict: both cases PASS byte-exact.**  The modern2-vs-frozen source diff is
now the documented five correction sites in `MUS/MultiStringBWT.py` (7 added /
6 removed, milestones 3-6) plus the one-line `MultimergeCython.pyx`
language-level header; nothing else changed.  No stop condition triggered.

Evidence is from two consecutive full runs of the committed validation driver
`packages/msbwt-modern2/validate/nonuniform-gzip-milestone8.sh` (both passed;
the run evidence JSON is committed under
`packages/msbwt-modern2/evidence/nonuniform-gzip-milestone8.json`,
SHA-256 `43eb6592ddd051c1db6777b5ec6b8aed7713c2da3abe7a6ba541953331e6e365`,
byte-identical across both runs).

## The one source change: MultimergeCython migration

- `MUSCython/MultimergeCython.pyx` (frozen, hash-pinned `9c591c05...`) was
  copied to `packages/msbwt-modern2/MUSCython/MultimergeCython.pyx` with the
  `#cython: language_level=2` header inserted after the shebang; the LF
  normalized text is otherwise byte-identical to the frozen file (verified by
  the driver's source-policy gate and the host regression test).
- The bootstrap-milestone-1 stub (`MultimergeCython.py`, `MultimergeCython.pyc`)
  was deleted; `setup.py` now builds `MUSCython.MultimergeCython` (9
  extensions total).
- Cython 3.0.12 compiled it first try; the emitted messages are
  performance hints only (exception-check GIL notes inside `nogil` regions and
  an uninitialized-pointer warning on the `numInputs == 2` path that mirrors
  the frozen generated code's structure).  No semantic rewrite was needed: the
  module's C-level semantics (uint division, buffer typing, `nogil` loops)
  are unchanged under `language_level=2`.

## Exact operations executed (modern2, both cases, two independent fresh runs)

| case | commands |
|---|---|
| `nonuniform-prefix` | `pp OUT nonuniform.fastq`, then `cfpp -p 1 OUT` |
| `gzip-input` | `pp OUT uniform-a.fastq.gz nonuniform.fastq.gz`, then `cfpp -p 1 OUT` |

This matches the committed provenance for both legacy goldens exactly.

## Byte contract (modern2 == committed legacy, run-a == run-b)

### nonuniform-prefix

- pre stage retained set (exactly 2 files): `offsets.npy`
  `da7fcb73c1fa0bdc0c84ee2f137e566ce2ba506a15aad58c2358d8c446e6d08e` (64 B,
  raw `<u8` cumulative offsets `[0,2,5,9,14,20,28,30]`), `seqs.npy`
  `f4239e43bfeffcfa48e4439b27faafa670dc6f16b117e8a92b3d3f7a4bbff303` (30 B,
  raw per-read BWT bytes) — byte-identical to the committed pre manifest.
- build stage retained set (exactly 3 files): `msbwt.npy` (whole-file
  `da28963ca3726568dd7a26eccea35f107bd4cb8b295c909de628374db38dd4b2`, 158 B,
  `|u1`, shape `(30,)`, header length 118, payload
  `7a97b19addd3c41a79dbd6ce5e43609766eca78a971576e1ab2b32e3df80ca03`) plus the
  unchanged pre files — byte-identical to the committed build manifest.

### gzip-input

- pre stage (exactly 2 files): `offsets.npy`
  `9f96565f1486a66ea7726b0f8cb68da50871469c1e16f99b2a800573cc1f6194` (96 B,
  12 u8 offsets for the 11 reads), `seqs.npy`
  `605c199e1023112d5e113dc1a4f9761b66d52937d2d56eeeaad4d51521ecf8c9` (54 B).
- build stage (exactly 3 files): `msbwt.npy` (whole-file
  `da40d02ef42d4cf61d7b4814a2bc2c44c48f3516a53d6111a19bf2fdba8ff33b`, 182 B,
  `|u1`, shape `(54,)`, payload
  `13c687364c3ca7ebae5379d4f8d9814d880616dd23968fdfa2c2697ced9f24ee`).

## Nonuniform-specific audit (paths actually reached)

The preprocess route (`MultimergeCython.preprocessFastqs` ->
`fastqIterator` -> `formatSeqsForMerge` -> `memoryBWT`) was traced and
validated: each read's own rotation-sorted BWT (numeric encoding `$=0, A=1,
C=2, G=3, N=4, T=5`) is written raw to `seqs.npy` in input order with raw
little-endian `<u8` cumulative offsets in `offsets.npy` (leading zero offset
for the nonuniform case), which explains the committed raw (headerless) pre
artifacts exactly.  The build route (`interleaveLevelMerge` ->
`levelIterator` -> `buildViaMerge256` -> `targetedIterationMerge2` single
thread, `initializeFMIndex`, `getFmAtIndex`, `singleIterationMerge2`,
`getBit_p`/`setBit_p`/`clearBit_p`) writes the merged BWT in place into
`msbwt.npy` (`np.save` of the initial copy, `np.load 'r+'` updates) and
retains `seqs.npy`/`offsets.npy`.  The committed nonuniform ordering (the
multimerge interleave, not rotation-sort) is reproduced exactly; no
integer/division behavior was changed under Cython 3, and the result is the
committed byte contract.

## Gzip-specific audit

`fastqIterator` opens `.gz` inputs with `gzip.open(fn, 'r')` (Python-2 binary
stream) and captures the sequence line of every 4-line record (`i % 4 == 1`
with `i` starting at 0 on the `@` header line).  Executed checks: all 11
records of `uniform-a.fastq.gz` + `nonuniform.fastq.gz` were read (no final
record lost — `seqs.npy` is exactly the concatenation of the 4 + 7 per-read
BWTs, 54 bytes), no CR/LF mutation occurred (fixtures are LF; `strip('\n')`
leaves `\r` alone as in the frozen code), and a `pp` run over the plain
fixtures produced byte-identical preprocess artifacts (the `.gz` fixtures
decompress byte-identically to the plain fixtures, hash-verified).

## Determinism and process count

- Two fresh independent executions per case: identical retained file sets,
  whole-file SHA-256, headers, payloads, reader results, and recovered
  strings (driver `determinism` gate, byte-identical trees).
- `-p 2` was exercised for both cases (fresh preprocess dirs): the build
  files are byte-identical to the `-p 1` builds (the multimerge writes to
  disjoint offset-defined regions, so `imap_unordered` ordering does not
  affect output bytes).  There is no committed legacy `-p 2` contract for
  these cases; the `-p 1` byte contract is the compatibility target.

## Reader validation (disposable copies, compiled reader)

For both final builds the compiled `ByteBWT` reader matches the committed
`reader-smoke.json` exactly:

| case | class | total size | dollars | queries | recovery | side effects |
|---|---|---|---|---|---|---|
| nonuniform | `MUSCython.ByteBWTCython.ByteBWT` | 30 | 7 | 22/22 | 7/7 | `fmIndex.npy` `fc626114...` (176), `totalCounts.npy` `2959abbf...` (176) |
| gzip | same | 54 | 11 | 30/30 | 11/11 | `fmIndex.npy` `9207663e...` (176), `totalCounts.npy` `d5a953fe...` (176) |

Queries and recovered strings were asserted against the committed
`expected_queries`/`expected_recovered_strings` tables (e.g. nonuniform
`A=5, AC=4, ACGTN=1, TTTTTTT=1`; recovery `$A, $AC, $ACG, $ACGT, $ACGTN, $N,
$TTTTTTT`).  Deleting the derived indexes and reloading regenerates
byte-identical files (`regeneration_bytes_identical`).

## Independent semantic validation

- `compat/tools/bwt_oracle.py` `backward_count` on the raw build payloads
  equals the committed query tables for every k-mer (22 for nonuniform, 30
  for gzip; 0 mismatches).  Backward-search counts are ordering-independent,
  so this validates the multimerge output semantically without assuming
  rotation-sort ordering.
- The pre artifacts were decoded independently: `seqs.npy` is the per-read
  rotation-sort BWT concatenation in input order and `offsets.npy` the
  cumulative lengths — both consistent with the committed bytes.

## Compression / decompression extension

After both primary contracts were green, the small low-risk extension was
characterized: nonuniform byte primary -> `compress -p 1` -> `decompress -p 1`
-> byte primary.  The compressed `comp_msbwt.npy` is byte-identical to the
committed `nonuniform-compress-posthoc` golden (`9d19222e...`, `|u1` `(16,)`)
and the decompressed `msbwt.npy` is byte-identical to the committed nonuniform
byte primary (`da28963c...`).  No new semantic issue appeared; the extension
is a driver gate and regression test, not a scope expansion.

## Source policy / diff whitelist status

- Frozen sources untouched: `MUSCython/MultimergeCython.pyx`
  `9c591c05...`, `MUS/MultiStringBWT.py` `95ac0b86...` (hash-verified by the
  driver gate and host tests).
- modern2 `MultimergeCython.pyx` vs frozen: exactly `#cython:
  language_level=2` added, nothing removed.
- Existing whitelists unchanged: `MUS/MultiStringBWT.py` remains the five
  documented correction sites (7 added / 6 removed); all previous pyx diffs
  unchanged.
- No frozen source, golden file, environment, or persistent format was
  modified; no new compatibility-policy decision was required.

## Tests added

- `packages/msbwt-modern2/tests/test_nonuniform_gzip_py2.py` (Python-2 suite,
  20 tests): migrated-module surface, one-line pyx diff whitelist, exact
  nonuniform pre/build contracts, primary header/payload, deterministic
  independent runs, `-p 2` byte equality, committed reader query/recovery/
  side-effect tables, gzip fixture hashes, gzip plain-vs-compressed input
  equivalence, and the compress/decompress roundtrip.
- `packages/msbwt-modern2/tests/test_bootstrap_py2.py` updated: the
  `MultimergeCython` stub assertion is replaced by a migrated-module
  assertion (+1 test).
- `compat/tests/test_modern2_nonuniform_gzip.py` (host suite, 17 tests):
  driver presence, evidence-record consistency, evidence trees/primaries/
  readers/oracle vs the committed goldens, frozen-source hashes, the
  one-line pyx diff whitelist, stub removal, setup.py coverage, and the
  unchanged 7/6 whitelist.

## Test counts

- Legacy compatibility suite: 125 tests (unchanged, green).
- Modern2-specific host suite: 92 + 17 = 109 (total compat suite 217 + 17 =
  234, green).
- Modern2 Python-2 suite: 68 + 1 (bootstrap update) + 20 = 89 tests, green.

## Stop conditions

None triggered: both primaries are byte-identical to the committed legacy
bytes; preprocess artifacts match; recovered read multisets match; reader/
query semantics match; Cython 3 did not alter the nonuniform ordering (the
committed multimerge ordering is reproduced byte-for-byte); gzip behavior
needed no compatibility-policy decision; no persistent format changed; no
frozen source modification was required; no broad architectural change was
needed.

## Files changed

- `packages/msbwt-modern2/MUSCython/MultimergeCython.pyx` — migrated module
  (frozen pyx + `#cython: language_level=2`).
- `packages/msbwt-modern2/MUSCython/MultimergeCython.py` / `.pyc` — deleted
  (stub replaced by the real module).
- `packages/msbwt-modern2/setup.py` — `MultimergeCython` added to
  `EXTENSION_NAMES`.
- `packages/msbwt-modern2/validate/nonuniform-gzip-milestone8.sh` —
  milestone-8 validation driver (gates, evidence regen).
- `packages/msbwt-modern2/evidence/nonuniform-gzip-milestone8.json` —
  executed evidence record (byte-identical across two consecutive full
  driver runs).
- `packages/msbwt-modern2/tests/test_nonuniform_gzip_py2.py` — Python-2
  regression tests.
- `packages/msbwt-modern2/tests/test_bootstrap_py2.py` — stub assertion
  replaced by migrated-module assertion.
- `compat/tests/test_modern2_nonuniform_gzip.py` — host-side regression
  tests.
- `docs/modernization/MODERN2_MILESTONE8_NONUNIFORM_GZIP.md` — this document.

## Next slice

Modern2 now covers both construction routes (uniform byte via
`MSBWTGenCython`, nonuniform via `MultimergeCython`), plain and gzip input,
the full reader stack, compression, and decompression.  Natural next slices:
the compiled `MSBWTGenCython.compressBWT` typed-division site, the remaining
`MUSCython` stubs (`GenericMerge`, `CompressToRLE`, `LCPGen`), or modern3.
