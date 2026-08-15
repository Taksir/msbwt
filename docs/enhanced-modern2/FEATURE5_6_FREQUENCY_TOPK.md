# ENHANCED-MODERN2 — Features 5 & 6 (executed evidence): Sample frequency and top-k exact sources

Status date: 2026-08-15

Branch: `enhanced-modern2` (Feature-4 commits `25f27c2`, `085cf4c`,
`51770e6`)

This milestone integrates research Features 5 and 6 (candidate authority:
`research/feature-candidates/5 and 6/`) as one additive milestone, per the
candidate.  No core baseline algorithm, persistent format, or CLI command
was modified, and no Feature-1/2/3/4 code was changed.

**Verdict: PASS.**  Both claims are VERIFIED-CORRECT:

- Feature 5: `sourceFrequency(P)` == the number of constituents with
  exact count > 0, computed by a dedicated count-only provenance
  traversal that never materializes source dictionaries (instrumented:
  the Feature-4 listing is not called), one merged FM search per query.
- Feature 6: `topSources(P, k)` == the exact sparse listing sorted by
  (-count, provenance/input order) and truncated to k, via Feature-4
  candidates + `heapq.nlargest` when k < support size (never an
  F-length zero-filled vector), with deterministic tie-breaking.

Verified over >=350 patterns x k in {0,1,2,3,5,10,20} (2,814 top-k
comparisons), a real canonical two-source merge, a real 5-source balanced
merge, and a randomized Level-3 differential — 0 mismatches.

## 1. Public API (additions to `MUS/MultiSourceQuery.py`)

- `MultiSourceBWT.sourceFrequency(seq, givenRange=None,
  include_stats=False)` -> int (or a rich dict with `sequence`,
  `merged_interval`, `merged_count`, `source_frequency`, `source_count`,
  `stats` when `include_stats=True`).
- `countSourcesWithOccurrences` — alias for `sourceFrequency`.
- `MultiSourceBWT.topSources(seq, k=10, givenRange=None,
  include_intervals=False, include_stats=False)` -> list of
  `{"source_id", "source_name", "count"}` records (plus
  `"source_interval"` when requested) ordered by (-count, provenance
  order); rich dict form with `include_stats=True`.
- `topSourcesByAbundance` — alias for `topSources`.
- Interval-level primitives: `MultiSourceQueryIndex.source_frequency_interval(start, end, include_stats=False)` and `top_sources_interval(start, end, k, include_intervals=False, include_stats=False)`.

Error contract: negative k raises `ValueError`; k = 0 returns []; absent
patterns return 0 / [].

## 2. Efficiency invariants

- ONE merged FM search per frequency/top-k operation (instrumented: 8
  operations on a counter-wrapped oracle make exactly 8 searches).
- Feature 5's count-only traversal does not build or resolve source
  records (instrumented by replacing `nonzero_sources_interval` with a
  spy: zero listing calls).
- Feature 6 selects from Feature-4 sparse candidates only; no F-length
  vector is built; `heapq.nlargest` bounds selection when k < support
  size, and the full sort path is used when k >= support (both paths
  produce identical output, verified).

## 3. Candidate audit and defects

Candidate files audited: `POINTS5_6_README.md`, `MultiSourceQuery.py`,
`test_points5_6_ten_sources.py`, `test_points5_6_integration.py`,
`POINTS5_6_BENCHMARK.json`.  The count-only traversal, heap-based top-k
selection, tie rule, stats contracts, aliases, and error behavior were
preserved verbatim in semantics.

No CANDIDATE DEFECTS found in the incremental Feature-5/6 behavior.  (The
candidate's Feature-3 module copy still carries the Feature-3 rank-cache
staleness gap; production fixed it in Feature 3 and the incremental layers
reuse the hardened path.)

Python-2 adaptations: none beyond the Feature-3 baseline (the incremental
code uses `heapq` (stdlib), `os.path`, and the existing module
infrastructure).  No new persisted files.

## 4. Independent oracle

- **Standalone suffix-order BWTs**: per-source exact counts; frequency ==
  number of sources with count > 0; top-k == ranked truncation.
- **Feature-4 sparse listing (already verified against standalone
  oracles)**: frequency == `len(nonzeroSources(P))` (spot-checked across
  categories); top-k == sorted sparse truncation.
- **Ranked-sparse truncation oracle**: independent sort by (-count,
  manifest-index) over the oracle sparse list, truncated at k — matches
  `topSources` for every pattern and every k in the test set.
- **Randomized read-derived differential (host)**: 30 cases, 3 seeds,
  3,000+ comparisons vs the same independent oracles.

## 5. Deterministic validation

Ten-source fixture: full pattern set for frequency and top-k; ties at
cutoff (equal-abundance sources appear in exact manifest order); k > support returns each nonzero source exactly once; k = 0; negative k
rejected; intervals retained in top-k; one-search probe; count-only
probe; alias identity; rich stats contracts; single-leaf package; edge
fixtures (unbalanced chain, duplicates, identical reads across sources,
N-heavy, `$` patterns).

## 6. Randomized validation

Level-3 differential (seed 20260811): 4 real datasets, 2-4 sources each,
REAL `pp`+`cfpp` + `GenericMerge`; 597 queries x frequency + k values,
0 mismatches.  Host read-derived differentials (3 seeds): 0 mismatches.

## 7. Performance / storage sanity (pinned py2 profile)

40 interval-level operations (20 frequency + 20 top-k) on the ten-source
package with warm rank caches: wall time ~0.01 s; no new persistent
storage.  No Cython/SIMD backends added (Feature 13 owns the whole-index
benchmark contract).

## 8. Limitations

- Tie order is provenance/input manifest order — deterministic per
  package, input-order-dependent across rebuilds.
- Top-k is exact but selects from materialized sparse candidates
  (Feature-4 baseline, per the candidate's engineering decision);
  specialized top-k indexes are explicitly deferred.
- `include_stats` changes the return type to a dict (documented
  contract).

## 9. Defect classification

- No CANDIDATE DEFECTS in the incremental layer.
- No MODERN2 BASELINE defects discovered.
- TEST/ORACLE defects found and fixed (test-side only): expected top-k
  must sort candidates by count before truncation; tie order derives from
  the manifest (input) order, not from name-sorted order; a module-level
  helper name collided with a local variable in the evidence generator.

## 10. Files added

- `packages/msbwt-modern2/tests/test_frequency_topk_py2.py` — Python-2
  suite (15 tests).
- `compat/tests/test_frequency_topk.py` — host suite (15 tests incl.
  evidence-record consistency).
- `packages/msbwt-modern2/validate/feature5-6-frequency-topk.sh` —
  validation driver.
- `packages/msbwt-modern2/validate/feature5_6_frequency_topk_evidence.py`
  — evidence generator.
- `packages/msbwt-modern2/evidence/feature5-6-frequency-topk.json` —
  executed evidence record (seed 20260811, mismatch_count 0).
- `docs/enhanced-modern2/FEATURE5_6_FREQUENCY_TOPK.md` — this document;
  `docs/enhanced-modern2/README.md` updated.

Changed: `MUS/MultiSourceQuery.py` extended (additive methods only);
nothing else.  `git diff --check` clean.

## 11. Verification gates (all executed)

- full modern2 Python-2 suite (251 + 15 Feature-5/6 = 266 tests): OK;
- host compat suite + Q1 harness: 499 tests + 22 subtests OK;
- Feature-1/2/3/4 validation drivers: OK (regression);
- fixture hashes: OK;
- full long Q1 rerun NOT required: additive pure-Python layer only.
