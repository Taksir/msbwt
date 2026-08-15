# ENHANCED-MODERN2 — Feature 7 (executed evidence): Source subsets / metadata groups / predicates

Status date: 2026-08-15

Branch: `enhanced-modern2` (Feature-5/6 commits `55fb817`, `a7ac109`,
`fbdd82f`)

This milestone integrates research Feature 7 (candidate authority:
`research/feature-candidates/7/`, modules `MultiSourceQuery(3).py` +
`SourceMetadata.py`) as a purely additive layer.  No core baseline
algorithm, persistent format, or CLI command was modified, and no
Feature-1/2/3/4/5/6 code was changed.

**Verdict: PASS.**  VERIFIED-CORRECT: for any selected source set `S` and
pattern `P`, `countSubset(P, S) == sum(Standalone_s.count(P) for s in S)`,
computed with ONE merged FM search and a provenance-tree descent with two
pruning modes (skip branches containing no selected source; complete-
subtree shortcut when every leaf below a node is selected).  Named groups
and metadata predicates are pure mechanisms for resolving `S`; the BWT
query semantics are unchanged.

## 1. Architecture rule

- Immutable stable source identity lives in `provenance.json`
  (AUTHORITATIVE, Features 1-2).
- Mutable biological/project labels (case/control, batch, tissue, cohort,
  project) live in `source_metadata.json` or any external JSON file
  supplied at load time — never in the BWT and never in `provenance.json`.
- Changing metadata NEVER requires rebuilding or re-merging the MSBWT;
  executed probe: editing groups and per-source metadata leaves
  `provenance.json` and `msbwt.npy` byte-identical.

## 2. Public API

New module `MUS/SourceMetadata.py`:

- `SourceMetadataCatalog(source_records, document=None)` with
  `from_file(path, source_records)`, `load(merged_bwt_dir, source_records,
  required=False)`, `save(merged_bwt_dir)` (atomic), `list_groups`,
  `define_group`, `delete_group`, `group_sources`, `set_source_metadata`,
  `source_metadata`, `select_where(**criteria)` (all criteria ANDed;
  list-valued metadata matched by scalar membership; expected iterables
  mean "actual equals any one of these"), `resolve_selection(sources,
  group, where)` (exactly one selector; none = all sources).
- `SourceMetadataError` for malformed/wrong-version/unknown-source
  documents; `KeyError` for unknown groups; `IOError` for missing files
  (when required).

Extended `MUS/MultiSourceQuery.py`:

- `MultiSourceBWT.__init__(bwt, source_index, source_metadata=None)`;
  `load(..., source_metadata_path=None)` auto-loads
  `source_metadata.json` from the merged directory when present.
- `countSubset(seq, sources=None, group=None, where=None, givenRange=None,
  include_stats=False)` -> exact aggregate count (rich dict with stats
  when requested).
- `querySubset(...)` -> `{sequence, merged_interval, merged_count,
  selected_source_ids, selected_source_count, count, sources}` where
  `sources` are only the nonzero selected constituents with exact counts
  (and optional constituent-local intervals).
- `countGroup` / `queryGroup` / `countWhere` / `queryWhere` — named
  conveniences over the same machinery.
- `MultiSourceQueryIndex.subset_count_interval(start, end, sources,
  include_stats=False)` and `subset_counts_interval(...)` — interval-level
  primitives with pruning + subtree-shortcut stats.

## 3. Persistence classification

- `source_metadata.json` — MUTABLE / REBUILDABLE user metadata (Feature 7).
  It never affects BWT bytes, `provenance.json`, or query semantics except
  through explicitly requested selection.  Missing file = empty catalog
  (not an error when `required=False`); corrupt/malformed file fails
  loudly with `SourceMetadataError`.  `save` is atomic (tmp + rename).
- No other new persisted files.

## 4. Candidate audit and defects

Candidate files audited: `POINT7_README.md`, `MultiSourceQuery(3).py`,
`SourceMetadata.py`, `source_metadata_10.json`,
`test_point7_subset_group_queries.py`, `test_point7_integration.py`,
`POINT7_SUBSET_BENCHMARK.json`.  The subset traversal with two pruning
modes, subtree-source indexing, selection resolution, and metadata catalog
semantics were preserved verbatim.

No CANDIDATE DEFECTS found in the incremental Feature-7 behavior.

Python-2 adaptations: candidate `SourceMetadata.py` used the Python-3-only
`Path` type (absent in the Python 2.7 standard library) and non-atomic
`write_text`; production uses `os.path`, atomic save, and wraps JSON decode
failures as `SourceMetadataError`.  `MultiSourceQuery(3).py` adaptations
match the Feature-3 baseline (pathlib -> os.path, hardened rank caches,
strict normalization).

## 5. Independent oracle

- **Standalone suffix-order BWTs**: subset aggregate == sum of standalone
  exact counts over the selected sources; groups/predicates resolved
  independently through the catalog then summed.
- **Feature-3 exact source counts**: `querySubset` aggregate == sum of
  `countOccurrencesForSource` over the selection (Level-3 real tests).
- **Feature-4 filtered listing**: `querySubset` records ==
  `nonzeroSources` filtered to the selection.
- **Randomized read-derived differentials (host)**: 24 cases, 3 seeds,
  3,000+ comparisons.

## 6. Deterministic validation

Ten-source fixture: 6 subset shapes x >=350 patterns (2,000+ comparisons);
groups even/odd/case/control; predicates (cohort/batch AND, membership);
querySubset record/intervals equality; empty group; no-selector == all
sources; duplicate source removal; unknown group/source rejection; one
merged FM search per query (instrumented); complete-subtree shortcut for
the 8-source left-subtree group (stats verify `subtree_shortcuts > 0`);
metadata isolation (byte-identical provenance/BWT after edits); catalog
validation matrix; atomic save/reload; corrupt-file rejection; external
metadata files.

## 7. Randomized validation

Level-3 differential (seed 20260811): 4 real datasets, 2-4 sources each,
REAL `pp`+`cfpp` + `GenericMerge`, groups and predicates vs standalone
counts, 300+ queries, 0 mismatches.  Host read-derived differentials
(3 seeds): 0 mismatches.

## 8. Performance / storage sanity (pinned py2 profile)

20 subset-count interval queries on the ten-source package with warm rank
caches: wall time ~0.01 s.  Subtree-source sets are indexed once per load
(O(F) memory); subtree-shortcut stats show the structural benefit for
groups aligned with the merge tree (all-10 group: root shortcut; left8
group: full left-subtree shortcut).  No Cython/SIMD backends added.

## 9. Limitations

- `select_where` supports equality/membership predicates only (ANDed); no
  range/negation operators (candidate contract).
- Group membership is canonicalized to provenance order at definition
  time; redefining a group replaces its membership.
- The subtree-source index is built eagerly at load (O(F) sets); for very
  large source counts this is a one-time cost.
- `include_stats` changes return types to rich dicts (documented).

## 10. Defect classification

- No CANDIDATE DEFECTS in the incremental Feature-7 layer.
- No MODERN2 BASELINE defects discovered.
- TEST/ORACLE defects found and fixed (test-side only): the list-valued
  membership contract (`tissue="liver"` matches a list value; an expected
  iterable against a list actual is list-identity, not membership).

## 11. Files added

- `packages/msbwt-modern2/MUS/SourceMetadata.py` — production module
  (pure Python, additive).
- `packages/msbwt-modern2/tests/test_subset_group_py2.py` — Python-2 suite
  (19 tests).
- `compat/tests/test_subset_group.py` — host suite (16 tests incl.
  evidence-record consistency).
- `packages/msbwt-modern2/validate/feature7-subset-groups.sh` — validation
  driver.
- `packages/msbwt-modern2/validate/feature7_subset_group_evidence.py` —
  evidence generator.
- `packages/msbwt-modern2/evidence/feature7-subset-groups.json` — executed
  evidence record (seed 20260811, mismatch_count 0).
- `docs/enhanced-modern2/FEATURE7_SUBSET_GROUPS.md` — this document;
  `docs/enhanced-modern2/README.md` updated.

Changed: `MUS/MultiSourceQuery.py` extended (additive methods only);
nothing else.  `git diff --check` clean.

## 12. Verification gates (all executed)

- full modern2 Python-2 suite (266 + 19 Feature-7 = 285 tests): OK;
- host compat suite + Q1 harness: 515 tests + 22 subtests OK;
- Feature-1/2/3/4/5/6 validation drivers: OK (regression);
- fixture hashes: OK;
- full long Q1 rerun NOT required: additive pure-Python layer only.
