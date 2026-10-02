# Next feature: Feature 11B, LCP-preserving source removal

Status: implemented on `claude/zen-rubin-l4ferr` for `msbwt-modern3`
(`pymsbwt`) only. Date: 2026-10-02.

This document records why 11B was chosen over the other candidates
(including FMD bidirectional search), the exact contract, how it was built
and verified, and what should come after it.

## 1. Selection

### State at selection time

The August 2026 roadmap's step 1, Feature 11A.1 (exact post-merge LCP), had
already shipped in `pymsbwt` 0.4.0. Two shipped features did not work
together, though. `remove_sources`/`retain_sources` raised `LCPError` on any
index that carried an LCP layer. The only workaround, `drop_lcp=True`,
discarded the layer, and getting it back meant a full 11A reconstruction
that recovers every read.

### Candidates compared

| Candidate | Value now | Risk | Depends on | Verdict |
|---|---|---|---|---|
| **11B LCP-preserving removal** | Fixes a broken interaction between two shipped features | Low. The identity is textbook and the oracle already exists | 11A (done) | **Chosen** |
| 11C LCP applications (maximal repeats, interval traversal, source support) | New user-facing queries | Moderate | 11A, and 11B so results survive removal | Next |
| 8B.0 bidirectional (2BWT) feasibility | Proves correctness only. No user-facing speedup until MEM/SMEM | Low to moderate | Reverse index construction | After 11C, as a screen |
| FMD-index bidirectional | Strand-agnostic queries, O(1) right extension | High (see below) | New construction mode plus a strand model in every layer | Not now |
| 13A real-data campaign and research screens | Decides the compressed backend | Low code risk | Real public data, which this environment does not have | Runs in parallel, with data |

### Why not FMD yet

FMD is a sound idea for raw reads of unknown strand, but this codebase has
four structural reasons to defer it:

1. **It is a different index, not a query feature.** An FMD-index is the BWT
   of the reads *plus their reverse complements*. No existing `pymsbwt` index
   qualifies, so every user would need to rebuild. That conflicts with the
   project rule that persisted bytes are contracts.
2. **It changes the meaning of every enhanced layer.** Both strands of a
   read occupy rows. Source counts, `topSources`, read provenance (dollar
   IDs double), mate links, the Q1 quality sidecar (quality must be
   reversed for reverse-complement rows), tags, LCP, and Point-10 removal
   (both strands must go together) would all need a strand model. That is
   a format redesign, not a feature.
3. **The cheaper bidirectional route preserves semantics.** A forward plus
   reversed 2BWT (roadmap 8B.0) can be derived from an existing index by
   recovering reads, reversing them, and building a companion index. The
   forward index stays byte-identical, and the current single-strand
   semantics stay exact. Strand-agnostic counting is already available as
   `count(P) + count(revcomp(P))` (the legacy `-r` option does this).
4. **The payoff arrives later.** Bidirectional extension mostly pays off
   through MEM/SMEM (8B.3) and approximate search (R-BIDIR). Exact
   right-extension already works in 8A at a cost of |alphabet| full
   searches, which is fine for interactive use.

FMD becomes the right choice if 8B.0 succeeds **and** the project decides
that strand-agnostic semantics should be the default for raw-read cohorts.
That decision should come from users. It should not follow from what the
backend happens to support.

## 2. Contract

For a Point-10 reduction of an LCP-enabled package:

```text
lcps.npy(remove_sources(index, S))
  ==  lcps.npy(construct_lcp_from_bwt(remove_sources(index, S, drop_lcp=True)))
  ==  explicit suffix-sort LCP of the retained reads
```

element for element, with the same dtype.

**Identity used.** For survivor rows `s_k < s_{k+1}`,
`LCP(s_k, s_{k+1}) = min(lcps[s_k : s_{k+1}])`. This holds for any
lexicographically sorted list. Under the 11A terminator semantics, the
distinct virtual terminators add 0 to LCP and keep identical biological
suffixes contiguous, so the identity is exact for Holt collection order.

**Behavior change.** A removal on an LCP-enabled input used to raise. It now
carries the layer through by default. `drop_lcp=True` and `--drop-lcp`
keep their old meaning. Calls that succeeded before produce the same files
as before. See `COMPATIBILITY.md` entry `M3-F11B`.

**Persisted format.** Still `msbwt-lcp` version 1, with identical
`lcps.npy` layout and dtype rules. `lcp.json` gains these fields:

| Field | Meaning |
|---|---|
| `algorithm` | `point10-survivor-range-minimum` |
| `derived_from` | input `bwt_sha256`, `bwt_rows`, `max_lcp`, `algorithm` (provenance chain) |
| `max_read_length_exact` | `false`: value inherited from the input layer and still a valid upper bound |
| `source`, `working_storage` | descriptive |

Recomputing the exact maximum read length would mean recovering every
retained read, which defeats the purpose. Validation only uses the field as
an upper bound on LCP values, and an inherited value preserves that bound.

## 3. Implementation

- `MUS/LCP.py`: `filter_lcp_for_removal(input_dir, output_dir, keep_mask,
  chunk_rows)` validates the input layer first, so a stale or copied layer
  is never propagated. It then runs a chunked segmented minimum
  (`np.minimum.reduceat`) that carries the running minimum across chunk
  boundaries, writes to a temp `.npy`, binds the result to the reduced BWT
  digest, and validates.
- `MUS/SourceRemoval.py`: the fail-safe is replaced by a call to the filter
  inside the existing atomic temp-directory publish, after the manifest is
  written. `stats["lcp_preserved"]` reports what happened.
- `tools/remove_sources.py`: help text only.
- Cost: one sequential pass with no FASTQ, string recovery, or suffix
  comparison. Measured at about 52M rows/s on a 100M-row synthetic array,
  with peak RSS dominated by the boolean keep mask.

## 4. Verification

`compat/tests/test_lcp_source_removal.py`, 12 tests:

- Filter against its definition-level reference across 200 random arrays
  and every chunk size from 1 to beyond N, plus edge masks.
- Ten-source fixture, five selections (including keep-one): checked against
  both oracles, with byte-identical `msbwt.npy` against the `drop_lcp` path.
- Repetitive fixture with chunk sizes 1, 3, and 2^20, checked to produce
  non-trivial joins (max LCP ≥ 6).
- Chained removal (10→8→6) equals one-shot removal (10→6), and
  `derived_from` chains correctly.
- `retain_sources`, randomized collections (3 seeds, `N`, duplicates, mixed
  lengths), and tag plus quality coexistence.
- Stale input layer: `LCPError`, nothing published, no temp leftovers.
- **Old reader / new writer:** the modern2 `LCPIndex`/`validate_lcp`
  (subprocess) reads the 11B layer and returns identical values.
- **New reader / old writer:** a modern2-constructed 11A layer is carried
  by modern3 11B and matches the oracle.
- CLI: carries the layer by default and drops it with `--drop-lcp`.

Mutation check: ignoring the cross-chunk carry makes 4 tests fail, and
naive row-for-row filtering makes 9 tests fail.

`test_lcp.py::RemovalFailSafeHostTests` now branches on capability. Under
`--msbwt-package=msbwt-modern2` it still asserts the original rejection.

## 5. Not done, and what comes next

- **modern2 is unchanged.** It still rejects LCP removal. Porting needs the
  pinned Python 2.7 profile, which this environment does not have.
- **No version bump or release.** Publishing 0.4.1 or 0.5.0 is a
  maintainer decision.
- **Next: 11C.** Use LCP-interval enumeration and maximal repeats with
  per-source and per-group support. Feed them through the existing
  `nonzero_sources_interval`/`subset_counts_interval` paths, so a repeat
  reports the samples that contain it without enumerating occurrences.
- **Update (same day):** 11C, 8B.0 and the FMD screen are done; see
  `FEATURE11C.md`, `STEP8B0_BIDIRECTIONAL.md` and
  `CHECKPOINT_FMD_VS_2BWT.md`.
- **Then: 8B.0 as a 2BWT screen.** Build a reversed companion index from
  recovered reads, and check that `bidir_extend_left/right` equals ordinary
  search over the roadmap's edge cases. Revisit FMD at the architecture
  checkpoint.
