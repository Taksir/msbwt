# ENHANCED-MODERN2 — Feature 3 (executed evidence): Query one constituent inside a multi-merged MSBWT

Status date: 2026-08-15

Branch: `enhanced-modern2` (descends from the modern2 release baseline
`370c726`; Feature-1 commits `a4c34c3`, `bbe467b`, `25102b4`; Feature-2
commits `d0878b2`, `5182096`, `3cc8b3a`)

This milestone integrates research Feature 3 (candidate authority:
`research/feature-candidates/3/`, module `MultiSourceQuery.py`) into the
published `msbwt-modern2` baseline as a purely additive, pure-Python query
layer on top of the verified Feature-2 provenance tree.  No core baseline
algorithm, persistent format, or CLI command was modified, and no
Feature-1 / Feature-2 code was changed.

**Verdict: PASS.**  The Feature-3 claim is VERIFIED-CORRECT: one merged FM
search followed by rank projection down the requested source's root-to-leaf
path reproduces the exact standalone constituent FM interval and count for
every queried source, for balanced and unbalanced trees, with lazy
rank-index loading, a hardened rank-cache identity contract, and a fully
independent naive bit-array projection oracle in agreement at every step.

## 1. Feature claim

For a pattern `P`, the merged FM search gives `[l, r)`.  Projecting that
interval down the requested source's path in the Feature-2 provenance tree:

    at a left edge:   [l, r) -> [rank0(l), rank0(r))
    at a right edge:  [l, r) -> [rank1(l), rank1(r))

At the leaf the interval length is the exact source count.  For balanced
trees with F sources a constituent query costs one merged FM search plus
O(log F) rank projections.  The projected interval is expected to equal the
standalone constituent FM interval exactly because every two-way merge is a
stable interleaving of the child suffix/BWT orders (verified in Features
1-2).

## 2. Public API (production `MUS/MultiSourceQuery.py`)

High level (`MultiSourceBWT`, construct with `MultiSourceBWT.load(dir)` or
wrap an existing BWT + index):

- `findIndicesForSource(pattern, source, givenRange=None)` -> local
  interval `(l, r)`;
- `countOccurrencesForSource(pattern, source, givenRange=None)` -> exact
  count `r - l`;
- `querySource(pattern, source, givenRange=None, include_trace=False)` ->
  rich result dict: `sequence`, `source_id`, `source_name`,
  `source_interval`, `count`, `present`, `merged_interval`,
  `merged_count`, `fraction_of_merged_occurrences`, `path_depth`, optional
  `projection_trace`;
- `findIndicesOfStr(seq, givenRange=None)` -> legacy merged search
  delegation (unchanged semantics).

Low level (`MultiSourceQueryIndex`):

- `project_interval(source, l, r, trace=False)`,
  `count_interval(source, l, r)`,
  `source_path(source)` (root-to-leaf `(node_id, branch)` list),
  `resolve_source(source)` (stable ID or unambiguous display name;
  ambiguous names raise `MultiSourceQueryError`, unknown raise `KeyError`),
  `source_record(source)`, `list_sources()`,
  `source_count`, `loaded_rank_node_count`,
  `save_loaded_rank_indexes()`.

Sources may be addressed by stable Feature-2 ID or by an unambiguous
display name.  `MultiSourceQuery = MultiSourceBWT` (PEP-8 alias), matching
the Feature-1 alias convention.

## 3. Resource behavior

- One merged FM search per source query (instrumented in the fixture suite
  and on a real BWT: exactly one `findIndicesOfStr` call per
  `countOccurrencesForSource` / `querySource`).
- No constituent BWT is reconstructed at query time.
- Rank indexes are loaded lazily along only the queried source path: for
  the ten-source balanced package a single query loads at most 4 internal
  nodes (never all 9).
- Touched rank samples can be persisted with
  `save_loaded_rank_indexes()` under
  `provenance/ranks/<node-id>.npz` and reloaded when valid.

## 4. Persistence classification

- `provenance.json`, `provenance/interleaves/<node-id>.npy`, `inter0.npy`,
  `msbwt.npy` — AUTHORITATIVE (Features 1-2; Feature 3 only reads them and
  does not modify them).
- `provenance/ranks/<node-id>.npz` — DERIVED / REBUILDABLE rank samples
  (new in Feature 3).  Schema (uncompressed npz of .npy members):

  | member | dtype | meaning |
  |---|---|---|
  | `rank_prefix` | uint64[N+1] | sampled 1-bit counts at rank-block boundaries |
  | `total_bits` | uint64[1] | node row count |
  | `rank_stride_bytes` | uint64[1] | sampling stride |
  | `interleave_sha256` | S64[1] | sha256 of the full stored interleave array bytes (cache identity) |
  | `interleave_total_ones` | uint64[1] | total 1 bits over valid storage bytes |

  A cache is used only when `total_bits` and stride match AND the digest
  and ones-count match the current authoritative interleave AND the prefix
  is internally consistent.  Stale, corrupt, truncated, wrong-stride, or
  legacy (pre-identity) caches are silently rebuilt from the authoritative
  interleave; they can never produce wrong counts.

## 5. Candidate audit and defects

Candidate files audited: `POINT3_README.md`, `MultiSourceQuery.py`,
`test_multisource_query_10.py`, `test_multisource_query_integration.py`,
`build_saved_10source_fixture.py`.  The candidate's core algorithm
(interval projection via rank0/rank1 over the Feature-2 tree, lazy loading,
trace, source resolution) was preserved.

CANDIDATE DEFECT (fixed in production):

1. **Rank-cache staleness gap**: the candidate's `save_loaded_rank_indexes`
   persisted only `rank_prefix` / `total_bits` / `rank_stride_bytes`, and
   `_load_saved_rank` validated only length+stride.  A same-length replaced
   internal interleave would silently reuse the stale cache and produce
   WRONG source counts.  Production adds the Feature-1-style content
   identity (`interleave_sha256` + `interleave_total_ones`) and prefix
   consistency validation; the mandatory probe (same-length replaced
   interleave with a valid updated manifest) is executed and detected.

Python-2 adaptations (mechanical, semantics unchanged): the candidate's
`pathlib.Path` (absent in the Python 2.7 standard library) -> `os.path`;
`Path.mkdir(exist_ok=)` -> guarded `os.makedirs`; the candidate's lax
sequence normalization -> the strict verified Feature-1 contract
(`TypeError` for non-string queries, ASCII-only encoding).  No f-strings,
annotations, or other Python-3-only syntax; the file clears the baseline
py3-syntax scan.

## 6. Independent oracle

- **Standalone constituent BWT**: every source's projected interval and
  count are compared against the independently constructed standalone
  suffix-order oracle (read-derived fixtures) and, in the Level-3 real
  tests, against real standalone `pp`+`cfpp` BWTs loaded with the compiled
  reader.  >=350 patterns x 10 sources with EXACT interval identity
  (>=3,500 comparisons, 4,020 executed).
- **Naive bit-array projection**: a fully independent projection that walks
  the provenance tree with Feature-2's `unpack_interleave` and counts
  selected rows with plain NumPy prefix sums — no sampled-rank code shared.
  It agrees with the rank projection and the standalone intervals on every
  probe (4,020 naive comparisons executed).
- **Synthetic-tree differential (host)**: random provenance trees (1-8
  leaves, random valid interleaves, seeds 20260811/20260812/20260813) with
  random intervals; rank projection == naive projection; full-interval
  projection gives each leaf its exact length; per-source interval lengths
  sum to the merged interval length (1,200+ comparisons).

## 7. Deterministic validation

- Ten-source balanced package: depth <= 4; every source path ends at the
  correct leaf; rich query fields; one merged FM search per query; lazy
  loading (path-depth nodes only); rank-cache round trip + reload;
  portable package after deleting all leaves and intermediates;
  projection traces (one step per tree edge); empty-interval projections
  (equal bounds; `[0,0)` -> `(0,0)`); interval bounds errors.
- Edge fixtures: unbalanced 3-source chain, duplicate reads within
  sources, identical reads across all sources, all-identical reads, N-heavy
  and nonuniform reads, single-leaf (no-merge) identity projection,
  `$` patterns, duplicate display names (must use stable IDs), unknown
  source errors, BWT-length mismatch rejection, sequence-normalization
  contract (bytes/str/unicode/TypeError/non-ASCII).
- REAL integration: canonical uniform-a + uniform-b merge — every query
  per-source count == standalone, projected interval == standalone
  interval, sum == merged total, committed Feature-1 totals unchanged;
  real 5-source balanced merge; real 4-source unbalanced chain;
  `givenRange` delegation (legacy semantics preserved, interval equality
  against standalone `GT`); one-search instrumentation on the real BWT.

## 8. Randomized validation

- Level-3 differential (seed 20260811): 6 real datasets, 2-4 sources each,
  REAL `pp`+`cfpp` construction and REAL `GenericMerge` merges; every query
  per-source count and interval compared against standalone BWTs and the
  naive oracle; 3,512 queries, 0 mismatches.
- Host read-derived differential (seeds 20260811/20260812/20260813): 30
  cases, 2-6 sources, exact interval identity, 5,000+ comparisons, 0
  mismatches.
- Host synthetic-tree differential: 120 trees, 1,200+ comparisons, 0
  mismatches.

## 9. Performance / storage sanity (pinned py2 profile)

- 10-source package (275 rows): rank cache for one path (4 nodes)
  5,560 B; projection wall time for 60 steps ~0.01 s; rank nodes touched
  by 60 projections = 5.
- Costs: one merged FM search per query + O(depth) rank projections of
  O(1) sampled work each.  No Cython/SIMD backends were added (Feature 13
  owns the whole-index benchmark contract).

## 10. Limitations

- The projected interval equals the standalone interval only when the
  merge preserves child row order (verified for the real `GenericMerge`
  and the stable read-derived merges).  Count equality is the guaranteed
  invariant; interval identity is the stronger verified property.
- Rank caches are only as fresh as their identity binding; without the
  identity fields (legacy caches) they are treated as absent and rebuilt.
- The ten-source and edge fixtures are tiny deterministic corpora, not
  replacements for compiled Holt/McMillan integration; Level-3 real
  coverage is provided by the canonical two-source merge, real 5-source
  balanced, real 4-source chain, and the 6 randomized real datasets.
- Real-scale benchmarking remains Feature-13 territory.

## 11. Defect classification

- CANDIDATE DEFECT: rank-cache staleness gap (fixed in production, section
  5).
- No MODERN2 BASELINE defects discovered.
- TEST/ORACLE defects found and fixed during this milestone (all test-side,
  no production change): empty-interval projection assertion assumed
  `(0,0)` for all empty intervals (projection maps to equal bounds
  `(k,k)`); the stale-cache probe initially used an interleave complement
  on a maximally symmetric fixture where old and new projections coincide
  (switched to a deterministic seeded shuffle with a guaranteed-differing
  probe selection).

## 12. Files added

- `packages/msbwt-modern2/MUS/MultiSourceQuery.py` — production module
  (pure Python, additive).
- `packages/msbwt-modern2/tests/test_multisource_query_py2.py` — Python-2
  suite (30 tests).
- `compat/tests/test_multisource_query.py` — host suite (30 tests incl.
  evidence-record consistency).
- `packages/msbwt-modern2/validate/feature3-query-one-constituent.sh` —
  validation driver.
- `packages/msbwt-modern2/validate/feature3_query_one_constituent_evidence.py`
  — evidence generator.
- `packages/msbwt-modern2/evidence/feature3-query-one-constituent.json` —
  executed evidence record (seed 20260811, mismatch_count 0).
- `docs/enhanced-modern2/FEATURE3_QUERY_ONE_CONSTITUENT.md` — this
  document; `docs/enhanced-modern2/README.md` updated (feature index).

Changed: none in baseline production code, none in Feature-1/Feature-2
code.  `git diff --check` clean.

## 13. Verification gates (all executed)

- full modern2 Python-2 suite (207 baseline + 30 Feature-3 = 237 tests):
  OK;
- host compat suite: 445 tests + 22 subtests OK (includes the baseline
  py3-syntax scan over all `MUS/*.py`);
- Feature-1 validation driver: OK (63 source pairs, 27,960 comparisons,
  0 mismatches);
- Feature-2 validation driver: OK (44 randomized datasets, 6 deterministic
  cases, 12 edge classes, 0 mismatches);
- fixture hashes (`uniform-a.fastq`, `uniform-b.fastq`): OK;
- Q1 audit harness (host): 24 tests OK; full long Q1 rerun NOT required —
  Feature 3 adds only additive pure-Python modules and does not alter
  baseline merge/FM/construction/compression/decompression code.

## 14. Semantic contract for modern3 / later features

modern3 and later features must preserve: the `MUS.MultiSourceQuery` public
API; the one-search-per-query and lazy-loading resource contract; the
`provenance/ranks` identity-bound cache format (derived, rebuildable); the
strict sequence-normalization contract; and the mathematical invariant
`countOccurrencesForSource(P, s) == standalone_s.count(P)` with
`sum_s == merged.count(P)`.  Features 4+ (sparse source listing, frequency,
top-k, subsets) build on this interval-projection layer.
