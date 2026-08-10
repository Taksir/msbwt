# Modern2 legacy bug tracker

Proven legacy defects found while porting msbwt to `msbwt-modern2`, suitable
for later README use.  Every entry is EXECUTED / PROVEN; nothing here is
speculative.  Status values:

- `fixed` — modern2 repairs the defect as a documented deviation
  (COMPATIBILITY.md entry where applicable); frozen source is never modified;
- `generated-code defect` — the defect lives in the historical committed
  generated C; modern2 uses the migrated `.pyx` instead;
- `documented legacy quirk` — safe-but-surprising behavior preserved
  byte-for-byte by modern2;
- `intentionally preserved` — failure/defect evidence preserved for the
  frozen oracle and never re-run by modern2.

Milestone references: `docs/modernization/MODERN2_MILESTONE*_*.md`.

| # | Component | Legacy behavior | Root cause | Modern2 behavior | Status | Proof |
|---|---|---|---|---|---|---|
| 1 | decompression (`MUS/MultiStringBWT.py` `CompressedMSBWT.getBWTRange`/`decompressBlocks`) | Deterministic `TypeError: slice indices must be integers or None or have an __index__ method` at `MUS/MultiStringBWT.py:662` (line 630 for multi-block inputs) for every RLE input | `<u8` run-count scalar + Python `int` promotes to NumPy `float64` under CPython 2.7 / NumPy 1.16.6; `float64` has no `__index__`, so the slice bound is invalid | Decompression succeeds; output payload byte-equal to the authoritative byte-BWT golden; `int(...)` applied at the slice boundary only | fixed (COMPATIBILITY.md entry 1) | Milestone 3; committed expected-failure evidence `compression-milestone1/decompression-failure/` preserved; decompressed payload `75134b48...` |
| 2 | multi-block decompression (`MUS/MultiStringBWT.py` `decompressBlocks`) | Same uint64/int → float64 crash at line 630 for >1,000,000-symbol RLE inputs (milestone-3 m3c2: zero completed regions) | Same promotion mechanism as #1 at a different slice site | Multi-block decompression succeeds byte-identically across `-p 1`/`-p 2` | fixed (same COMPATIBILITY.md entry 1) | Milestone 4 |
| 3 | pure reader refFM construction (`MUS/MultiStringBWT.py`) | Pure-Python reader crashes/IndexError while constructing `refFM` indexes during `loadBWT`/`constructIndexing` | uint64/int index promotion into array positions (same NumPy promotion family as #1) | Pure reader builds `totalCounts.npy`/`fmIndex.npy`/`refFM`-equivalent byte-identically to the compiled reader | fixed | Milestones 5 (prefix probe), 7 |
| 4 | pure reader `getFullFMAtIndex` | Pure-Python `getFullFMAtIndex` produced wrong FM rows (weighted-bincount fill defect) | `np.bincount(...)` fill with float64 weights/positions mis-cast under NumPy 1.16.6 | Weighted-bincount fill corrected; FM rows byte-match the compiled reader | fixed | Milestone 6 |
| 5 | `merge -p 1` CLI (`MUS/CommandLineInterface.py` `merge` branch) | `UnboundLocalError: local variable 'numProcs' referenced before assignment`; output dir created empty; inputs unchanged | `numProcs` bound only inside the `args.numProcesses > 1` branch | `numProcs = 1` bound unconditionally; `merge -p 1` and `-p 2` produce byte-identical output equal to the committed secondary oracle | fixed (COMPATIBILITY.md entry 2, pre-authorized LEGACY SOURCE BUG) | Milestone 9; frozen failure evidence `relationship-merge-p1-unboundlocalerror.json` preserved and reproduced by the py2 suite |
| 6 | historical `MUSCython/GenericMerge.c` (Cython 0.23.4 generated C) | Deterministic SIGSEGV (exit -11) on the canonical two-input merge route; empty stderr | Generated-code defect in the historical committed C | Modern2 never runs the historical binary; `GenericMerge.pyx` migrated with `language_level=2` only and compiled under Cython 3.0.12; merge succeeds | generated-code defect / intentionally preserved | Milestone 9; `relationship-generic-merge-segfault.json` preserved |
| 7 | `convert` newline handling (`MUSCython/CompressToRLE.pyx`) | Everything after the FIRST newline is silently dropped, valid or invalid symbols alike; the conversion encodes only the prefix before the first newline (e.g. `A\\nC\\nG\\nT\\nN\\n` converts to a 1-byte RLE of `A` only). Exit 0. | In the `else` branch the `currSym == 10` case is `pass`, which never updates `currSym`; once `currSym` is `'\\n'` every later non-newline character hits the pass branch and is ignored | Identical behavior under Cython 3.0.12 + `language_level=2`; single-line inputs (the documented "BWT string" form) convert byte-identically to the frozen oracle | documented legacy quirk (preserved) | Milestone 10; `convert-milestone10/failure-contract-probes.json` (`invalid_after_newline`) |
| 8 | `convert` invalid-symbol error path (`MUSCython/CompressToRLE.pyx`) | An invalid symbol BEFORE the first newline reaches the raise site but the intended `Exception('UNEXPECTED SYMBOL DETECTED: '+currSym)` surfaces as `TypeError: cannot concatenate 'str' and 'int' objects` (exit 1, traceback at `MUSCython/CompressToRLE.pyx:77`) | Cython emits `PyNumber_Add(str, PyInt)` for the C `unsigned char` `currSym`; Python 2 `str + int` raises TypeError, masking the intended exception | Identical masked TypeError under Cython 3.0.12 + `language_level=2`; the raise site line number is preserved | documented legacy quirk (error path only, preserved) | Milestone 10; `convert-milestone10/failure-contract-probes.json` (`invalid_before_newline`) |

Not bugs (safe-but-suspicious behavior deliberately NOT recorded as defects):
`binSize` `2**20` vs `1000000` differences between the Cython and pure-Python
compressors, the handcrafted 96-byte NumPy header of `convert` output
(header_len 86, payload offset 96), and the RLE reader's `totalCounts.npy`
vs `totalCounts.p` naming — all match the frozen behavior byte-for-byte.
