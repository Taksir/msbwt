# Architecture checkpoint: FMD index vs 2BWT companion

Status: screen complete on **synthetic** data; the decision is
**provisional** until the real-data steps (roadmap 4–8) run. Date:
2026-10-02.

## Question

Bidirectional search can be built two ways:

| | 2BWT companion | FMD index |
|---|---|---|
| Indexes | forward (existing) + reversed reads | one index of reads + reverse complements |
| Partner of `P` | `reverse(P)` in the companion | `revcomp(P)` in the same index |
| Counts | single-strand (today's semantics) | both strands, always |

Both are prior art. This screen measured them on this codebase.

## Correctness: both are exact

The same extension code (`MUS.Bidirectional.BidirectionalIndex`) runs
with `T` = reverse or `T` = reverse complement. Both pass the full gate:

- all 4,320 extension orders of every pattern of length ≤ 3
- every read substring
- palindromes, `N`, duplicates, read ends and empty intervals

See `test_bidirectional.py` and `test_fmd_screen.py`. Holt's `$ACGNT`
order needs no special handling for FMD: the complement does not reverse
the order (`N` sits between `G` and `T`), but the offset rule only needs
counts per symbol, not order reversal.

## Measurements (synthetic cohort, `compat/screens/fmd_vs_2bwt.py`)

The cohort is a random 20 kb reference with 5 planted repeat families,
per-sample SNPs (0.2%), 100 bp reads from **both strands**, and 0.5%
substitution errors. Raw JSON is in `compat/screens/results/`.

| Run | Reads | Forward r/N | FMD r/N | FMD runs ÷ 2BWT runs | (FMD + forward) runs ÷ 2BWT runs |
|---|---:|---:|---:|---:|---:|
| 10 samples, 5× | 10,000 | 0.131 | 0.112 | **0.855** | 1.354 |
| 20 samples, 20× | 80,000 | 0.079 | 0.063 | **0.794** | 1.294 |

| Cost | 2BWT | FMD |
|---|---|---|
| Rows (uncompressed bytes) | 2N | 2N |
| Extension | ~12.5 µs/call | ~12.5 µs/call (same code, same step count) |
| Extra construction (20×20 run) | 70 s companion | 156 s (one 2N index) |

**Reading.** At equal size, FMD has 15–21% fewer BWT runs, and the
advantage grows with coverage. Reads already come from both strands, so
each reverse complement lands next to similar reads from the other strand
and extends their runs. A plain reversal creates a mirror index with no
such sharing. This is the strongest argument for FMD, and it only pays off
once a run-length backend exists (13B). If the forward index must also be
kept for single-strand semantics, FMD costs 29–35% *more* runs than 2BWT.

## Semantic cost: the deciding factor

FMD changes what every existing layer means. The 2BWT companion changes
nothing.

| Layer | 2BWT companion | FMD as primary index |
|---|---|---|
| `count(P)` | unchanged | counts `P` on both strands |
| Stranded data (e.g. stranded RNA-seq) | supported | strand lost unless a strand bit is added |
| Source provenance (F2–F7) | forward side unchanged | must be rebuilt over 2× reads |
| Read provenance and mates (F9) | unchanged | every read has two dollar IDs; needs a strand model |
| Q1 quality, tags (F12) | unchanged | reverse-strand rows need reversed quality and tags |
| LCP, 11B removal, 11C repeats | unchanged | must be re-derived; removal must drop both strands |
| Existing `pymsbwt` indexes | gain bidirectionality additively | must be rebuilt |

## Decision (provisional)

1. **For existing indexes and the current product, use the 2BWT
   companion.** It is additive, keeps the forward index authoritative,
   satisfies the persisted-contract rules, and costs fewer runs than
   keeping forward plus FMD.
2. **Do not discard FMD. Reclassify it** as a candidate *new primary
   index mode* ("both-strands cohort index"), not a query feature. Its
   15–21% run advantage is real on this synthetic data and should be
   re-measured on real reads in the 13A campaign. Promote it only if:
   - the run advantage holds on real data **and** materially shrinks the
     whole index once a run-length backend exists, **and**
   - a strand model for provenance, quality, tags and removal is designed
     first.
3. **Next bidirectional work** (8B.1 onward) should build on
   `BidirectionalIndex`, which already supports both partners, so the
   choice stays reversible.

## Caveats

- Synthetic data: uniform random reference, simple error model, no real
  coverage bias, no adapters and no low-complexity regions. Do not quote
  these numbers as biological results.
- Run counts are inputs to a future RLBWT. They are not measured
  compressed sizes.
- Timings come from one run in a shared cloud container, with
  single-process construction and the Python prototype loop.
- Public-data validation was blocked in this environment: outbound access
  to NCBI was denied by the network policy.
