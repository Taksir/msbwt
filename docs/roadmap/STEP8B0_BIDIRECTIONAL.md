# 8B.0: bidirectional (2BWT) correctness prototype

Status: **gate passed** on fixtures for `msbwt-modern3`. Experimental
module `MUS/Bidirectional.py`. Date: 2026-10-02. Roadmap step 10.

This is a feasibility gate. It does not add a production feature and makes
no performance claim. It answers one question: are synchronized
forward/reverse intervals exact under Holt multi-string semantics? On the
fixtures here, they are.

## What was built

- `build_reverse_companion(forward_dir, reverse_dir)`: recovers every read
  from the existing forward MSBWT, reverses it, and builds a Holt MSBWT of
  the reversed reads with `MultimergeCython.createMSBWTFromSeqs`.
  - The forward package is untouched.
  - `reverse_companion.json` binds the companion to the forward and
    companion `msbwt.npy` digests.
  - The companion is published atomically, and only after its symbol
    counts equal the forward ones.
- `BidirectionalIndex`: the state is `BiInterval(forward, reverse,
  size)`, with `extend_left/right` and `extend_left_all/right_all`.
  - Each extension costs one backward step per symbol on one index, which
    is the standard 2BWT cost.
  - The class is written for a general partner transform `T`, so the FMD
    screen reuses the same verified code with `T` = reverse complement.

**Offset rule.** Inside the partner interval of `T(P)`, rows are ordered
by the symbol that follows `T(P)`. That symbol is `tau(the symbol
preceding P in the forward index)`, so a child's offset is the number of
forward-interval rows whose preceding symbol maps before `tau(c)`. Rows
preceded by `$` are occurrences at a read start, and they sort first.

## Gate results

`compat/tests/test_bidirectional.py`, 9 tests on real Multimerge-built and
merged indexes:

| Check | Result |
|---|---|
| Every pattern over `ACGNT` of length ≤ 3, every seed position, every L/R order: every intermediate state equals two direct searches | 4,320 orderings, all exact |
| Every substring of every read (random orders), size equal to an independent string count | exact |
| Duplicate reads, N-containing reads, full-read matches | exact |
| Read-end boundaries: children sum to parent minus read-end occurrences | exact |
| Empty intervals stay empty; invalid symbols and `$` rejected | yes |
| Source-specific intervals: per-source counts from the bidirectional forward interval equal per-source string counts (10-source merged fixture) | exact |
| Right extension equals 8A `extendRight` counts | exact |
| Stale or reused companion rejected | yes |

Mutation check: ignoring `$`-preceded rows makes 3 tests fail, and an
off-by-one in the "sorts before" bound makes 3 fail.

## Findings worth keeping

1. **Holt merges are per-read cyclic, but the naive test fixtures are
   not.** LF cycles in the fixtures span several reads. The companion
   builder therefore splits each LF cycle on `$`, which is exact for any
   valid collection BWT.
2. **Legacy hazard (since fixed by `M3-S2-INPUT`).**
   `MultimergeCython.createMSBWTFromSeqs` requires `$`-terminated input.
   `memoryBWT` looped forever on an unterminated periodic read such as
   `TTTT`, and because it runs in a `multiprocessing` worker, the parent
   waited forever instead of failing. The same root cause also allowed
   out-of-bounds writes on lowercase or IUPAC input.
3. **Python 3.14 uses `forkserver` on Linux.** Construction must be called
   from an importable `__main__`. A script file or pytest works; `python -`
   from stdin hangs.

## Not done (deliberately)

- No source provenance on the companion. 8B.2 needs it only if
  source-aware state must live on the reverse side. The forward side
  already carries source semantics.
- No compressed or move-structure backend (roadmap 13B, 8B.4).
- No MEM/SMEM (8B.3). This gate only clears the way for them.
- Construction holds all recovered reads in memory.
