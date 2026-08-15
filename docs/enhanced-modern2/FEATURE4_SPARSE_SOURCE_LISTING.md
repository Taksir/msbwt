# ENHANCED-MODERN2 — Feature 4 (executed evidence): Sparse nonzero-source listing with exact counts

Status date: 2026-08-15

Branch: `enhanced-modern2` (Feature-3 commits `216d4a2`, `f207e56`,
`d7e92bd`)

This milestone integrates research Feature 4 (candidate authority:
`research/feature-candidates/4/`) as a purely additive extension of the
verified Feature-3 query layer (`MUS.MultiSourceQuery`).  No core baseline
algorithm, persistent format, or CLI command was modified, and no
Feature-1/2/3 code was changed.

**Verdict: PASS.**  The Feature-4 claim is VERIFIED-CORRECT: one merged FM
search per pattern followed by a single provenance-tree descent with
rank0/rank1 projection at every internal node and empty-child pruning
returns exactly the set of sources with positive counts, with exact counts,
constituent-local intervals, deterministic manifest-order output, and
sum-of-counts == merged count, for the ten-source fixture (402 patterns), a
real canonical two-source merge, a real 5-source balanced merge, and a
deterministic randomized Level-3 differential — 0 mismatches.

## 1. Feature claim

Given one merged interval `[l, r)`, recursively descend the provenance
tree: at each merge node project to both children (`rank0` / `rank1`);
prune any child whose projected interval is empty; at a leaf report the
exact count `r - l`.  Only leaves with positive counts are returned.  This
shares traversal work and prunes empty subtrees instead of calling Point 3
once per source.

## 2. Public API (additions to `MUS/MultiSourceQuery.py`)

- `MultiSourceBWT.nonzeroSources(seq, givenRange=None,
  include_intervals=False, include_stats=False)` -> list of
  `{"source_id", "source_name", "count"}` records (plus
  `"source_interval"` when requested) in provenance/input order; with
  `include_stats=True` returns `{"sequence", "merged_interval",
  "merged_count", "sources", "stats"}` where stats carries
  `root_interval_size`, `internal_nodes_visited`, `branches_pruned`,
  `leaves_reported`, `rank_nodes_loaded_before/after/for_query`,
  `merged_interval`, `merged_count`, `sources_reported`.
- `listSourcesWithOccurrences` — alias for `nonzeroSources` (same function
  object).
- `MultiSourceQueryIndex.nonzero_sources_interval(start, end,
  include_intervals=False, include_stats=False)` — interval-level primitive
  (no BWT search; works on any merged interval).

## 3. Efficiency invariant

- ONE merged FM search per pattern (instrumented: 5 probe queries on a
  counter-wrapped oracle make exactly 5 searches; the full 402-pattern
  evidence loop also verifies one search per sparse query).
- Zero rank nodes loaded for globally absent patterns (empty root interval
  returns before any node is touched).
- Pruning behavior on the ten-source fixture: average internal nodes
  visited = 1.95 over all 402 patterns (4.64 for nonempty patterns only)
  vs the 36-edge naive all-source projection baseline → 94.6% fewer
  visited internal nodes (candidate's reported fixture numbers: 1.80 /
  4.35 / 95.0% — same order, small difference from dict-order leaf input
  sequence).  These are fixture-specific descriptive statistics, not a
  general performance guarantee.

## 4. Candidate audit and defects

Candidate files audited: `POINT4_README.md`, `MultiSourceQuery.py`,
`test_sparse_source_listing_10.py`, `test_sparse_source_listing_integration.py`,
`POINT4_PRUNING_BENCHMARK.json`.  The sparse-descent algorithm, stats
contract, alias, and interval-level API were preserved verbatim in
semantics.

No CANDIDATE DEFECTS found in the incremental Feature-4 behavior.  The
candidate's copy of the Feature-3 module still carries the Feature-3
rank-cache staleness gap; production already fixed that in Feature 3 (the
incremental layer reuses the hardened cache path, which also protects
sparse-descent rank loads).

Python-2 adaptations: none required beyond the Feature-3 module baseline
(the incremental code uses only `os.path`, `np`, and the existing
`ProvenanceError` path).  No new persisted files.

## 5. Independent oracle

- **Point-3 count oracle**: for every pattern and source,
  `countOccurrencesForSource(P, s)` (Feature 3, itself verified against
  standalone BWTs); the Feature-4 result must equal exactly the filtered
  positive subset.  402 patterns x sources, sparse comparisons 402.
- **Standalone suffix-order BWT**: constituent-local intervals in
  `include_intervals` results must equal the independent standalone
  interval (340 interval comparisons executed).
- **Independent DFS counter**: traversal statistics (internal nodes
  visited, branches pruned, leaves reported) equal a separate recursive
  bit-array counter sharing no code with the sparse implementation.
- **Synthetic random trees (host)**: sparse listing == naive per-leaf
  bit-array projection counts for random intervals on 60 random trees
  (seeds 20260811/20260812/20260813, 960 comparisons).
- **Read-derived random differential (host)**: 30 cases, 3 seeds, 3,000+
  comparisons vs standalone oracles.

## 6. Deterministic validation

Ten-source fixture: full pattern set with exact counts/ordering/sum;
intervals; one-search probe; zero-rank-load for absent patterns; pruning
categories (zero/one/all/few sources); stats vs independent DFS; interval
API without BWT search; alias identity; `givenRange` delegation (real
merge); single-leaf package; edge fixtures (unbalanced chain, duplicates,
identical reads across sources, N-heavy, `$` patterns).

## 7. Randomized validation

Level-3 differential (seed 20260811): 4 real datasets, 2-4 sources each,
REAL `pp`+`cfpp` + `GenericMerge`; 597 queries, 0 mismatches.  Host
synthetic-tree and read-derived differentials: 0 mismatches.

## 8. Performance / storage sanity (pinned py2 profile)

40 sparse queries on the ten-source package: average 2-3 internal nodes
per query, wall time ~0.01 s; no new persistent storage (rank caches are
the Feature-3 derived files).  No Cython/SIMD backends added (Feature 13
owns the whole-index benchmark contract).

## 9. Limitations

- Output ordering is the provenance manifest (input) order — deterministic
  per package, but a different merge input order yields a different (still
  exact) listing order.
- Recursive descent depth equals tree depth; a degenerate chain tree has
  depth F-1 (bounded by the Python recursion limit for extremely large
  chains).
- `include_stats` changes the return type to a dict (documented contract).

## 10. Defect classification

- No CANDIDATE DEFECTS in the incremental Feature-4 layer.
- No MODERN2 BASELINE defects discovered.
- TEST/ORACLE defects found and fixed during this milestone (test-side
  only): sparse expected order must follow the manifest source table
  (not `sorted()` names); py2 unbound-method wrapping requires
  `im_func`/`__func__` for the alias-identity check; the independent DFS
  counter must treat the empty interval as visiting nothing.

## 11. Files added

- `packages/msbwt-modern2/tests/test_sparse_source_listing_py2.py` —
  Python-2 suite (14 tests).
- `compat/tests/test_sparse_source_listing.py` — host suite (15 tests incl.
  evidence-record consistency).
- `packages/msbwt-modern2/validate/feature4-sparse-source-listing.sh` —
  validation driver.
- `packages/msbwt-modern2/validate/feature4_sparse_source_evidence.py` —
  evidence generator.
- `packages/msbwt-modern2/evidence/feature4-sparse-source-listing.json` —
  executed evidence record (seed 20260811, mismatch_count 0).
- `docs/enhanced-modern2/FEATURE4_SPARSE_SOURCE_LISTING.md` — this
  document; `docs/enhanced-modern2/README.md` updated.

Changed: `MUS/MultiSourceQuery.py` extended (additive methods only);
nothing else.  `git diff --check` clean.

## 12. Verification gates (all executed)

- full modern2 Python-2 suite (237 + 14 Feature-4 = 251 tests): OK;
- host compat suite + Q1 harness: 484 tests + 22 subtests OK;
- Feature-1/2/3 validation drivers: OK (regression, see Feature-3 doc);
- fixture hashes: OK;
- full long Q1 rerun NOT required: additive pure-Python layer only.
