# pymsbwt 0.5.0 release notes

Built from `packages/msbwt-modern3`.  Supported runtime and platforms are
unchanged from 0.4.0: CPython 3.14, NumPy >=2.5,<3, wheels for Linux x86-64
and ARM64, Windows x86-64, and macOS ARM64.  No persisted format changes
existing files; the frozen Python 2.7 line (`msbwt-modern2`) is unchanged.

## Fixed

- **Construction no longer hangs or corrupts memory on invalid reads**
  (`M3-S2-INPUT`).  Reads containing anything other than uppercase
  `A C G N T` (lowercase soft-masking, IUPAC codes) previously caused heap
  corruption or a segfault inside a worker, and `msbwt cffq` hung forever in
  both `-u` and non-uniform modes.  An in-memory read without its terminal
  `$` could loop forever or silently produce a wrong BWT.  These now raise a
  `ValueError` naming the read, position and symbol.  Output for valid input
  is byte-identical to 0.4.0.

## New

- **Source removal keeps the LCP layer** (Feature 11B, `M3-F11B`).
  `msbwt-remove-sources` / `remove_sources` used to fail on an index with an
  LCP layer unless `--drop-lcp` was given.  The reduced index now gets an
  exact LCP layer computed in one sequential pass, equal to a fresh
  `msbwt-lcp construct`.  `--drop-lcp` still works.
- **Maximal repeats with per-sample support** (Feature 11C, `M3-F11C`).
  `MultiSourceBWT.maximalRepeats`, `lcpIntervals`, `lcpChildren`,
  `lcpIntervalSequence`, and `msbwt-lcp repeats`.  Each repeat reports how
  many samples contain it and, optionally, per-sample, group and read counts.
- **Experimental bidirectional search** (`MUS.Bidirectional`, `M3-8B0`,
  `M3-FMD-SCREEN`).  A reversed-read companion index (2BWT) and an FMD-index
  screen, both verified exact against direct search.  The API and the
  companion format may change.

## Behavior changes to check

- `remove_sources` on an LCP-enabled index now succeeds instead of raising
  `LCPError`, and its stats gain `lcp_preserved`.
- Construction input that was previously accepted silently (lowercase,
  IUPAC codes, unterminated in-memory reads, inner `$`) now raises
  `ValueError`.  Uppercase soft-masked input and map IUPAC codes to `N`.

All changes are recorded in `COMPATIBILITY.md` under the entry names above.
