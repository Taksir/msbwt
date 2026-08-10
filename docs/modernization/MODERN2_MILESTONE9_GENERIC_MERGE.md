# MODERN2 — Milestone 9 (executed evidence): GenericMerge + public merge CLI

Status date: 2026-08-10

This milestone restores and validates the actual public MSBWT merge
functionality in modern2:

1. `MUSCython.GenericMerge` is migrated from the frozen `GenericMerge.pyx`
   and compiled with the pinned Cython 3.0.12 toolchain, and
2. the public `msbwt merge` CLI works for both `merge -p 1` and
   `merge -p 2` (the frozen `-p 1` UnboundLocalError is fixed as the
   documented LEGACY SOURCE BUG deviation).

**Verdict: PASS.**  The unchanged frozen `GenericMerge.pyx` (semantic source
authority) compiled under Cython 3.0.12 on the first attempt with only the
`#cython: language_level=2` migration, and the canonical merge reproduced the
committed SECONDARY REGENERATED-SOURCE ORACLE byte-for-byte on the first
execution.  The modern2 merged `msbwt.npy` whole-file SHA-256 is
`dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f`
(`|u1`, shape `(48L,)`, payload
`75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e`) and the
retained merge-provenance `inter0.npy` is
`4a6d97a36e9ef4e3c19fb873b7713a9357d207d29433a3eca67a41cc4221afd6`
(`|u1`, shape `(7,)`).  `merge -p 1` and `merge -p 2` are byte-identical
(primary, interleave, and whole output trees), deterministic across two
independent fresh runs each, and equal to a clean-from-scratch combined
construction of the same read multiset.

Evidence is from two consecutive full runs of the committed validation driver
`packages/msbwt-modern2/validate/generic-merge-milestone9.sh` (both passed;
the run evidence JSON is committed under
`packages/msbwt-modern2/evidence/generic-merge-milestone9.json`, SHA-256
`8a981f17f867cdbd0a01a8421bd1076f582dba949d0f291ff5ff6886d525301e`,
byte-identical across both runs).

## The two historical merge findings stay separate

- **A. Historical generated-C defect**: the committed
  `MUSCython/GenericMerge.c` (Cython 0.23.4 provenance, frozen projection)
  deterministically segfaults on the characterized merge route (exit -11 /
  SIGSEGV).  Modern2 does NOT reproduce it and does NOT use the historical
  generated C as implementation authority.  The evidence
  (`relationship-generic-merge-segfault.json`, `oracle_class:
  historical-generated-c`) remains committed and untouched under
  `compat/goldens/original-0.3.0/merge-milestone1/`.
- **B. `merge -p 1` CLI source bug**: the frozen
  `MUS/CommandLineInterface.py` binds `numProcs` only inside the
  `args.numProcesses > 1` branch, so `merge -p 1` raised
  `UnboundLocalError: local variable 'numProcs' referenced before assignment`
  (LEGACY SOURCE BUG, evidence `relationship-merge-p1-unboundlocalerror.json`
  preserved).  Modern2 is explicitly permitted to fix it; the frozen source is
  not repaired.  A functional regression in the modern2 Python-2 suite loads
  the *frozen* CLI source and proves the historical failure still exists,
  while the modern2 CLI succeeds.

The successful merge semantics come from the unchanged frozen
`GenericMerge.pyx`, whose execution contract is the committed secondary
regenerated-source oracle.  The three categories remain clearly distinct:

| category | source | result |
|---|---|---|
| historical committed `GenericMerge.c` | Cython 0.23.4 generated C (frozen) | deterministic crash evidence (preserved, never re-run) |
| unchanged `GenericMerge.pyx` regenerated under pinned Cython 0.29.36 | legacy oracle profile | successful secondary oracle (committed) |
| modern2 `GenericMerge.pyx` built by Cython 3.0.12 | language-level migration only | successful production implementation (this milestone) |

## The one source change: GenericMerge migration

- `MUSCython/GenericMerge.pyx` (frozen, hash-pinned
  `fe8b699c73a0e671b63cbbe7f2eeba941b91a321156a02df44bf0e010cedce87`) was
  copied to `packages/msbwt-modern2/MUSCython/GenericMerge.pyx` with the
  `#cython: language_level=2` header inserted after the `#!python` shebang;
  the LF-normalized text is otherwise byte-identical to the frozen file
  (verified by the driver's source-policy gate and the host + Python-2
  regression tests).
- The bootstrap-milestone-1 stub (`GenericMerge.py`, `GenericMerge.pyc`) was
  deleted; `setup.py` now builds `MUSCython.GenericMerge` (10 extensions
  total).
- Cython 3.0.12 compiled it first try; the emitted messages are performance
  hints only (exception-check GIL notes on `setBit_p`/`clearBit_p`/`fillBin`
  inside `nogil` regions — the same class of hints as the migrated
  `MultimergeCython` in milestone 8) plus the standard NumPy deprecated-API
  warning.  No semantic rewrite was needed: division, buffer typing, bit
  packing, and the two-input interleave algorithm are unchanged under
  `language_level=2`.

## The one CLI change: `merge -p 1` fix (COMPATIBILITY.md entry 2)

- `packages/msbwt-modern2/MUS/CommandLineInterface.py` differs from the
  frozen original by exactly one added line in the `merge` branch:

      numProcs = 1

  placed immediately before `if args.numProcesses > 1:`.  Root cause of the
  historical bug: `numProcs` was assigned only inside that branch, so the
  default/`-p 1` path referenced an unbound local.  The intended algorithm
  always runs single-process (`GenericMerge.mergeTwoMSBWTs` clamps
  `numProcs > 1` to 1 itself and logs "Multi-processing not implemented");
  binding the same value unconditionally makes `-p 1` execute exactly the
  same intended algorithm as the working `-p 2` route, with no change to
  merge mathematics, no persistent-format change, and no invented default.
- The `-p 2` warning log ("Multi-processing is not supported at this
  time...") is unchanged.

## Exact canonical merge inputs and command

| logical input | fixture | reads | symbols | builder |
|---|---|---|---|---|
| `IN_A` | `uniform-a.fastq` | ACGTN, AAAAA, ACGTN, NACGT | 24 | `pp -u` + `cfpp -p 1 -u` |
| `IN_B` | `uniform-b.fastq` | ACGTN, CCCCC, GGGGG, TTTTT | 24 | `pp -u` + `cfpp -p 1 -u` |
| merged | union (8 reads) | 48 | `merge -p N MERGED IN_A IN_B` |
| clean control | both files | 8 reads | 48 | `pp -u` + `cfpp -p 1 -u` |

Source `msbwt.npy` hashes (identical across runs, matching the committed
relationship record): `IN_A` `e277c7e5c529808c230fb9dae61626a24eeddad54df2f38e22357a12520f69a1`
(payload `03ad79575d8bb793ff10796eb678101b67bd8bcae89cdd7aac8c1b1b724742ff`),
`IN_B` `15f40b98ce3310dfe71c15c34509075e68a271bcc93b125b7005cd2b8f82ff08`
(payload `0de0ad12b21ffa120a371c1f2d02e22b697396092c39eed12ce3178859ce4c13`),
clean control `dd91d69ee2785c88...` (byte-identical to the committed uniform
golden).  Input reader semantics (recorded, disposable copies): both inputs
load as `ByteBWT` with total size 24 and dollar count 4.

## First execution policy result

After the migration and before any algorithm change, the driver's exact
committed canonical case was executed through the public CLI:

1. inputs and clean control built and hash-verified;
2. `merge -p 2` executed through the CLI: **PASS**, merged primary
   byte-identical to the committed secondary oracle on the first run;
3. `merge -p 1` executed through the CLI with the one-line fix: **PASS**,
   byte-identical to `-p 2`.

Classification: **PASS** (narrow Python/Cython migration + the permitted CLI
bug fix; no semantic difference, no stop condition triggered).

## Byte contract (modern2 == committed secondary oracle, all four runs)

- Merged output directory contains exactly `["inter0.npy", "msbwt.npy"]`;
  no derived files are written into the output.
- `msbwt.npy`: whole-file SHA-256 `dd91d69e...`, 176 bytes, `|u1`, raw NPY
  header `{'descr': '|u1', 'fortran_order': False, 'shape': (48L,), }`
  (header length 118, NumPy v1), payload SHA-256 `75134b48...` (48 bytes).
- `inter0.npy`: whole-file SHA-256 `4a6d97a3...`, 135 bytes, `|u1`, shape
  `(7,)`, payload SHA-256 `688c323f...` (bit-packed interleave: 24 zero bits
  for `IN_A`, 24 one bits for `IN_B`).
- Input side effects: each input directory gains exactly
  `fmIndex.npy` + `totalCounts.npy` (lazy reader-derived indexes created by
  `loadBWT(useMemmap=True)` during the merge); every pre-existing input file
  (including `msbwt.npy`) is byte-unchanged.
- Merged primary == clean control == committed uniform golden byte-for-byte
  (whole file).

## Determinism and process count

- Two independent fresh executions per route: `p1-a == p1-b`,
  `p2-a == p2-b` byte-for-byte (whole output trees, primary, interleave).
- `p1 == p2` byte-for-byte (primary, payload, header, interleave, retained
  files, reader semantics).
- No auxiliary file differs between `-p 1` and `-p 2`; both routes run the
  same single-process algorithm (`numProcs = 1` in both cases).

## Reader validation (disposable copies, compiled reader)

On a disposable copy of the merged output, the compiled reader loads as
`MUSCython.ByteBWTCython.ByteBWT`, total size 48, dollar count 8, all 36
committed `expected_queries` match (e.g. `A=9, AA=4, ACGTN=3, AAAAA=1,
AAAAAA=0`), recovered strings match the committed table
(`$AAAAA, $ACGTN x3, $CCCCC, $GGGGG, $NACGT, $TTTTT`), and the created
derived indexes match the committed side-effect hashes exactly:
`fmIndex.npy` `a5b4bf06726fcadf535245d03ef65e04a4a5248d368b3aa53639c190028b933f`
(176 B) and `totalCounts.npy`
`ea104b616fe89d7b786acdff7ca0db61f6339a59c31fbf0fff066ad7384c1c2b` (176 B).
Deleting the derived indexes and reloading regenerates byte-identical files;
deleting `inter0.npy` and reloading still works (`required_by_reader =
false`).  Output file classification:

| file | classification |
|---|---|
| `msbwt.npy` | primary persistent output |
| `inter0.npy` | merge provenance/intermediate retained by the frozen merge; not reader-required |
| `totalCounts.npy`, `fmIndex.npy` | lazy reader-derived caches (in output only if a reader touched it; regenerable byte-identically) |
| `fmIndex.npy`, `totalCounts.npy` in input dirs after merge | same lazy reader caches; side effects of the merge's `loadBWT(useMemmap=True)`, not output artifacts |

## CLI query (disposable copy)

`query COPY ACGTN` prints `3`; `query -d COPY ACGTN` dumps exactly three
`ACGTN,<dollarID>` lines (string set equality per the committed plan; dollar
IDs are tie-order-dependent and recorded, not asserted across builds).

## Independent semantic validation (host-side, `compat/tools/bwt_oracle.py`)

- rotation-sort prediction of the 8-read union multiset == merged payload
  byte-for-byte;
- symbol multiset counts match: `A=9, C=9, G=9, N=4, T=9, $=8`;
- backward-search counts equal the committed query table for all 36 k-mers
  (0 mismatches);
- LF recovery reproduces exactly the 8-read multiset
  (`AAAAA, ACGTN x3, CCCCC, GGGGG, NACGT, TTTTT`);
- interleave verification: 24 zeros / 24 ones, 12 unique-to-A positions,
  18 unique-to-B positions, 18 tied positions, 0 unambiguous mismatches —
  matching the committed `relationship-independent-oracle.json` block table
  exactly (same per-block zero/one counts and expected bits for all 36
  rotation blocks).

## Source policy / diff whitelist status

- Frozen sources untouched: `MUSCython/GenericMerge.pyx`
  `fe8b699c...`, `MUS/CommandLineInterface.py` `5265558e...`,
  `MUS/MultiStringBWT.py` `95ac0b86...` (hash-verified by the driver gate
  and host tests).
- modern2 `GenericMerge.pyx` vs frozen: exactly
  `#cython: language_level=2` added, nothing removed.
- modern2 `MUS/CommandLineInterface.py` vs frozen: exactly
  `        numProcs = 1` added, nothing removed (documented deviation,
  COMPATIBILITY.md entry 2).
- Existing whitelists unchanged: `MUS/MultiStringBWT.py` remains the five
  documented correction sites (7 added / 6 removed); all previous pyx diffs
  unchanged.
- The modern2 `GenericMerge.c` is regenerated by Cython 3.0.12 and differs
  substantially from the historical Cython-0.23.4 generated C; generated-C
  byte equality is not a compatibility requirement (the `.pyx` semantic
  identity, Cython version pin, generated-C presence, and runtime behavior
  are the pins).

## Historical failure evidence preservation

- The committed historical `GenericMerge.c` segfault record
  (`relationship-generic-merge-segfault.json`, exit -11/SIGSEGV, empty
  stderr, `oracle_class: historical-generated-c`) is unchanged; unsafe
  historical binaries were not re-executed.
- The frozen `merge -p 1` UnboundLocalError record
  (`relationship-merge-p1-unboundlocalerror.json`, stderr SHA-256
  `186d471d861c4eaf8ef200076742e259182b6e3c050ebe26540fbdf1e7eb3a4c`) is
  unchanged.
- New regressions prove both remain historically reproducible: the Python-2
  suite executes the frozen CLI source and observes the UnboundLocalError
  (output dir created empty, inputs unchanged), and the host suite pins the
  frozen bug pattern in the frozen source.

## Tests added

- `packages/msbwt-modern2/tests/test_generic_merge_py2.py` (Python-2 suite,
  24 tests): migrated-module surface, one-line pyx diff whitelist, one-line
  CLI diff whitelist, frozen bug-pattern regression, functional frozen
  `-p 1` UnboundLocalError reproduction, fixture hashes, input/clean
  contract hashes, exact `-p 1`/`-p 2` merged contracts, p1==p2 byte
  equality, merged==clean, deterministic independent runs, input side-effect
  inventory, compiled reader vs the committed relationship-reader table,
  derived-index regeneration + interleave classification, CLI query
  count/dump, payload symbol counts, independent pure-Python-2 oracle
  (rotation sort, backward counts, LF recovery), and interleave bit
  invariants.
- `packages/msbwt-modern2/tests/test_bootstrap_py2.py` updated: the
  `GenericMerge` stub assertion is replaced by a migrated-module assertion
  (+1 test).
- `compat/tests/test_modern2_generic_merge.py` (host suite, 15 tests):
  driver presence, evidence-record consistency, evidence trees/primary/
  interleave/reader/oracle/CLI-query vs the committed merge-milestone1
  contracts, evidence source-policy whitelists, frozen-source hashes,
  pyx/CLI diff whitelists, frozen bug-pattern regression, stub removal,
  setup.py coverage, Cython 3.0.12 generated-C banner, generated-C
  difference from the historical C, unchanged 7/6 whitelist, and committed
  secondary-oracle artifact pins.
- `compat/tests/test_modern2_bootstrap.py` updated: `GenericMerge` moved
  from `STUB_MODULES` to `MIGRATED_MODULES`, `MUS/CommandLineInterface.py`
  added to `DOCUMENTED_DEVIATIONS` with coverage by the new exact-diff test.

## Test counts

- Legacy compatibility suite: 125 tests (unchanged, green).
- Modern2-specific host suite: 109 + 23 = 132 (total compat suite
  234 + 23 = 257, green).
- Modern2 Python-2 suite: 89 + 24 + 1 = 114 tests, green.

## Stop conditions

None triggered: the unchanged `GenericMerge.pyx` under Cython 3.0.12
preserved merge semantics (byte-identical primary); the modern2 merged
primary equals the committed secondary regenerated-source oracle; `-p 1` and
`-p 2` produce identical primary bytes; the recovered collection matches;
symbol/query semantics match; no persistent-format change was needed; the
merge algorithm required no redesign; historical crash evidence was not
rewritten; frozen source was not modified; no new compatibility-policy
decision was required (the `-p 1` fix was pre-authorized as LEGACY SOURCE
BUG).

## Files changed

- `packages/msbwt-modern2/MUSCython/GenericMerge.pyx` — migrated module
  (frozen pyx + `#cython: language_level=2`).
- `packages/msbwt-modern2/MUSCython/GenericMerge.c` — generated by Cython
  3.0.12 (committed per the modern2 generated-C policy).
- `packages/msbwt-modern2/MUSCython/GenericMerge.py` / `.pyc` — deleted
  (stub replaced by the real module).
- `packages/msbwt-modern2/setup.py` — `GenericMerge` added to
  `EXTENSION_NAMES`.
- `packages/msbwt-modern2/MUS/CommandLineInterface.py` — the documented
  one-line `merge -p 1` fix (COMPATIBILITY.md entry 2).
- `packages/msbwt-modern2/validate/generic-merge-milestone9.sh` —
  milestone-9 validation driver (gates, evidence regen).
- `packages/msbwt-modern2/evidence/generic-merge-milestone9.json` —
  executed evidence record (byte-identical across two consecutive full
  driver runs).
- `packages/msbwt-modern2/tests/test_generic_merge_py2.py` — Python-2
  regression tests.
- `packages/msbwt-modern2/tests/test_bootstrap_py2.py` — stub assertion
  replaced by migrated-module assertion.
- `compat/tests/test_modern2_generic_merge.py` — host-side regression
  tests.
- `compat/tests/test_modern2_bootstrap.py` — module lists and documented-
  deviation gate updated.
- `COMPATIBILITY.md` — deviation entry 2 (`merge -p 1` fix).
- `docs/modernization/MODERN2_MILESTONE9_GENERIC_MERGE.md` — this document.

## Next slice

Modern2 now covers both construction routes, plain and gzip input, the full
reader stack, compression, decompression, and the public merge CLI
(`-p 1`/`-p 2`).  Natural next slices: the remaining `MUSCython` stubs
(`CompressToRLE`, `LCPGen`), the compiled `MSBWTGenCython.compressBWT`
typed-division site, `convert`, or modern3.
