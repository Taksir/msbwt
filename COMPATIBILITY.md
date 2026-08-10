# MSBWT compatibility deviations

Intentional, documented correctness deviations from the frozen original
implementation (`reference/original-0.3.0/`, commit
`7503346ec072ddb89520db86fef85569a9ba093a`).  Each entry records the affected
commands/APIs/files, the old and new behavior, the rationale, and the
reader/writer interoperability consequences.  The frozen oracle is never
modified; these deviations exist only in the modern distributions
(`packages/msbwt-modern2/`, and later `packages/msbwt-modern3/`).

## 1. Decompression numeric/index fix (modern2)

- Status: executed and validated — Modern2 Milestone 3 (see
  `docs/modernization/MODERN2_MILESTONE3_DECOMPRESSION.md`).
- Affected commands/APIs: `msbwt decompress -p N SRC DST`;
  `MUS.MSBWTGen.decompressBWT` / `decompressBWTPoolProcess`;
  `MUS.MultiStringBWT.CompressedMSBWT.getBWTRange` / `decompressBlocks`.
- Affected file: `packages/msbwt-modern2/MUS/MultiStringBWT.py`
  (the only source line change of the fix: the `decompressBlocks` fill loop
  converts the `<u8` run-count scalar with `int(...)` before slice
  arithmetic; the modern2 file differs from the frozen original by exactly
  those three lines).
- Old (frozen) behavior: deterministic failure for every RLE input —
  `TypeError: slice indices must be integers or None or have an __index__
  method` at `MUS/MultiStringBWT.py:662` (line 630 for multi-block inputs),
  because `s + counts[lInd]` promotes `np.uint64 + Python int` to NumPy
  `float64` under CPython 2.7 / NumPy 1.16.6, and `float64` has no
  `__index__`.  The committed expected-failure evidence under
  `compat/goldens/original-0.3.0/compression-milestone1/decompression-failure/`
  is preserved unchanged.
- New (modern2) behavior: decompression succeeds.  The decompressed
  `msbwt.npy` (`|u1`, shape `(48,)`, header byte-identical to the legacy
  decompression preallocation header) carries a payload byte-for-byte equal
  to the authoritative uniform byte-BWT golden payload (SHA-256
  `75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e`; whole
  file SHA-256 `f536d60f356ed4a34e8253eecdd91e90db8c2ba3430c2e3d3e1855bb49007ef4`).
  The whole-file bytes differ from the compiled-builder golden
  (`dd91d69ee2785c88...`) only in the NumPy v1 shape literal `(48,)` vs
  `(48L,)` — the same documented pure-Python vs compiled-path serialization
  distinction already accepted for the compressed routes.
- Rationale: genuine correctness defect (AGENTS.md: "Correct genuine
  correctness or security defects; do not preserve them merely for byte
  equality").  The fix is the narrowest value-preserving conversion at the
  slice boundary: `int(np.uint64(x))` is exact for every value; no
  arithmetic meaning, run boundary, symbol count, output length, or payload
  byte changes.
- Interoperability: the decompressed primary is a valid `msbwt.npy` loadable
  by the legacy byte reader semantics; the compressed input `comp_msbwt.npy`
  is untouched.  Reader-derived indexes (`totalCounts.npy`, `fmIndex.npy`
  for byte; `totalCounts.p`, `comp_fmIndex.npy`, `comp_refIndex.npy` for
  compressed sources) are byte-identical to the legacy reader outputs for
  the same payloads.

## 2. `merge -p 1` CLI numProcs fix (modern2)

- Status: executed and validated — Modern2 Milestone 9 (see
  `docs/modernization/MODERN2_MILESTONE9_GENERIC_MERGE.md`).
- Affected command: `msbwt merge -p 1 OUT IN_A IN_B` (and the default
  `merge` invocation, which defaults `-p` to 1).
- Affected file: `packages/msbwt-modern2/MUS/CommandLineInterface.py` (the
  modern2 file differs from the frozen original by exactly one added line:
  `numProcs = 1` immediately before the `if args.numProcesses > 1:` branch
  of the `merge` subcommand).
- Old (frozen) behavior: `merge -p 1` raises
  `UnboundLocalError: local variable 'numProcs' referenced before
  assignment` because `numProcs` is bound only inside the
  `args.numProcesses > 1` branch.  The output directory is created but
  empty and the inputs are unchanged.  The committed failure evidence
  (`compat/goldens/original-0.3.0/merge-milestone1/relationship-merge-p1-unboundlocalerror.json`,
  stderr SHA-256
  `186d471d861c4eaf8ef200076742e259182b6e3c050ebe26540fbdf1e7eb3a4c`) is
  preserved; the frozen source is not repaired, and the modern2 Python-2
  suite reproduces the historical failure by executing the frozen CLI
  source.
- New (modern2) behavior: `merge -p 1` performs the intended merge exactly
  like the working multi-process route (`-p 2` also clamps to one process
  with the same warning).  Both routes call
  `MUSCython.GenericMerge.mergeTwoMSBWTs(..., 1, logger)`, whose algorithm
  itself clamps `numProcs > 1` to 1.  `-p 1` and `-p 2` produce
  byte-identical outputs (merged `msbwt.npy`
  `dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f`,
  `|u1`, shape `(48L,)`, payload
  `75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e`;
  retained `inter0.npy`
  `4a6d97a36e9ef4e3c19fb873b7713a9357d207d29433a3eca67a41cc4221afd6`),
  byte-identical to the committed secondary regenerated-source oracle and
  to a clean-from-scratch combined construction.
- Rationale: genuine CLI correctness defect, explicitly pre-authorized as a
  LEGACY SOURCE BUG fix by the resolved merge compatibility policy
  (`docs/modernization/MERGE_INDEXING_PLAN.md`).  The fix is the narrowest
  possible: binding the same single-process value the working `-p 2` route
  already binds.  No merge mathematics, persistent format, or output file
  set changes.
- Interoperability: the merged output is byte-identical to the committed
  secondary regenerated-source oracle and loadable by the legacy reader;
  the frozen `-p 1` failure evidence remains authoritative for the frozen
  CLI only.  The historical committed `GenericMerge.c` SIGSEGV
  (LEGACY GENERATED-CODE DEFECT) is a separate preserved defect that
  modern2 never reproduces.
