# Feature 11C: LCP-interval applications with source support

Status: implemented for `msbwt-modern3` (`pymsbwt`). Date: 2026-10-02.
Roadmap step 3. Prerequisites 11A (shipped) and 11B (this branch).

Nothing here is new technique. These are the enhanced-suffix-array
primitives of Abouelhoda, Kurtz and Ohlebusch, applied to the Feature-11A
LCP layer. What 11C adds is the integration: an LCP interval is an
ordinary merged-BWT interval `[start, end)`, so the existing Feature 3–7
source and group queries and the Feature-9 read queries apply to it
unchanged. Repeats therefore come with per-sample evidence without
enumerating occurrences.

## Definitions

All definitions use the 11A terminator semantics: each read has its own
virtual terminator, and terminators contribute 0 to LCP.

| Term | Definition | Test |
|---|---|---|
| lcp-interval | rows `[s, e)`, `e - s >= 2`, inner LCPs `>= l` with one `== l`, boundary LCPs `< l` | generalized suffix-tree internal node |
| maximal repeat | occurs ≥ 2 times, cannot be extended on the right or the left | lcp-interval whose BWT symbols are not all equal (any `$` counts as distinct) |
| supermaximal repeat | maximal and not a substring of another maximal repeat | no nested lcp-interval, and the BWT symbols are pairwise distinct |

## API (`MUS.MultiSourceQuery.MultiSourceBWT`)

| Method | Returns |
|---|---|
| `lcpIntervals(min_lcp, max_lcp, min_occurrences)` | generator of `LCPInterval(lcp, start, end)`, bottom-up |
| `lcpChildren(interval)` | `(start, end, lcp)` children; `lcp=None` for a single suffix |
| `lcpIntervalSequence(interval)` | the shared prefix (bytes) |
| `maximalRepeats(...)` | generator of records (below) |

`maximalRepeats` filters by `min_length`/`max_length`,
`min_occurrences`, `min_sources`/`max_sources`, and `supermaximal`. It
also accepts one selection (`sources`, `group` or `where`) with
`min_selected`. Each record has `start`, `end`, `length`, `occurrences`,
`source_frequency`, and optionally:

- `sequence` (on by default)
- `sources` (Feature-4 sparse counts)
- `selected_count` (Feature 7)
- `read_count` (distinct reads, Feature 9)

The low-level functions live in `MUS/LCPIntervals.py` and work on any
`lcps.npy` and `msbwt.npy` arrays.

CLI: `msbwt-lcp repeats --input DIR --min-length 25 --min-sources 3
--include-sources` prints one JSON record per line.

## Cost

- One sequential pass over `lcps.npy`. NumPy skips boundaries below
  `min_lcp`, and the bottom-up stack runs in Python over the rest, at
  about 1 µs per visited boundary. On a synthetic 10M-row array:
  `min_lcp=1` took 7.9 s, `12` took 1.3 s, and `25` took 0.1 s.
- Per record: one provenance traversal for `source_frequency`. Spelling
  the sequence costs one LF walk over one read. `read_count` enumerates
  the interval's rows (output-sensitive).

## Verification

`compat/tests/test_lcp_intervals.py` has 15 tests. Every expectation comes
from the read strings alone:

- Interval enumeration matches the definition-level brute force on 150
  random arrays × 4 parameter sets × 4 chunk sizes.
- Maximal and supermaximal repeats match an oracle that enumerates every
  substring of every read, giving each read start and end its own distinct
  terminator. This covers the fixed fixture and 9 randomized collections
  with planted motifs, duplicates and `N`.
- Source support, `min_sources`/`max_sources`, subset and group counts,
  and read counts match direct substring counts.
- Children tile their parent and appear before it (bottom-up order).
- Repeats on an 11B-reduced package match the oracle on the retained
  reads.
- The compiled Holt BWT spelling path and the CLI are exercised end to
  end.

Mutation check: dropping the `$` left-maximality rule makes 3 tests fail,
dropping the supermaximal distinctness check makes 2 fail, and dropping
the run-closing visit makes 11 fail.

## Not done

- Suffix–prefix overlap queries (optional in the roadmap).
- A compiled stack loop. The Python baseline is the oracle for any
  later Cython version.
- Differential repeats across metadata groups. The building block
  (`selected_count` per group) exists. Defining a precise biological
  query and auditing its novelty is a separate step, as the roadmap
  requires.
