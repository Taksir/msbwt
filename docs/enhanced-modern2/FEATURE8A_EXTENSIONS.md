# ENHANCED-MODERN2 — Feature 8A (executed evidence): Source-aware left/right sequence extensions without a reverse FM-index

Status date: 2026-08-15

Branch: `enhanced-modern2` (Feature-7 commits `83300c8`, `a65322c`,
`373541a`)

This milestone integrates research Feature 8A (candidate authority:
`research/feature-candidates/8a/`) as a purely additive layer.  No core
baseline algorithm, persistent format, or CLI command was modified, and no
Feature-1..7 code was changed.  Feature 8B (reverse-index backend) is NOT
implemented.

**Verdict: PASS.**  VERIFIED-CORRECT: for every tested pattern `P`,
candidate base `c`, and selection `S`: `ExtendLeft(P, c, S) ==
ExactCount(cP, S)` (via ONE full FM search + incremental `givenRange`
backward steps) and `ExtendRight(P, c, S) == ExactCount(Pc, S)` (via
ordinary full searches).  The search asymmetry is explicit and
instrumented: left = 1 full search + 5 incremental steps; right = 5 full
searches + 0 incremental steps.

## 1. Public API (additions to `MUS/MultiSourceQuery.py`)

- `extend(seq, direction="left", alphabet=None, source=None, sources=None,
  group=None, where=None, include_zero=True, include_intervals=False,
  include_stats=False)` -> `{pattern, direction, alphabet,
  selection_mode, extensions}` where each extension record is
  `{base, sequence, count}` plus optional `merged_interval`,
  `merged_count`, `source_interval`; stats carry `full_fm_searches`,
  `incremental_extension_calls`, `candidate_extensions`,
  `extensions_returned`, `parent_interval`.
- `extendLeft(seq, **kwargs)` / `extendRight(seq, **kwargs)`.
- Default alphabet `ACGNT`; custom alphabets allowed (`$` only for right
  extension; left `$` raises `ValueError`); symbols validated, deduped,
  non-empty; direction validated; exactly one selection selector
  (source/sources/group/where) or merged.
- Python-2 adaptation: `bytes([v])` is Python-3-only (on py2 it is the
  list repr) — replaced by an explicit `_byte_symbol` helper.

## 2. Search instrumentation

Verified on a counter-wrapped oracle: one `extendLeft("ACGT")` performs
exactly 6 `findIndicesOfStr` calls (1 full + 5 givenRange steps); one
`extendRight("ACGT")` performs exactly 5 (all full).  No reverse index is
introduced; the API/cost model honestly preserves the asymmetry
(left ~ k+5 vs right ~ 5(k+1) FM-symbol steps).

## 3. Candidate audit and defects

Candidate files audited: `POINT8A_README.md`, `MultiSourceQuery(4).py`,
`test_point8a_sequence_extensions.py`, `test_point8a_integration.py`,
`POINT8A_DIRECTION_COST_MODEL.json`.  Semantics preserved verbatim.

No CANDIDATE DEFECTS in the incremental layer, but one Python-2 semantic
trap was fixed in production: `bytes([base_value])` produces the list
repr under Python 2 (`str([65]) == "[65]"`), silently corrupting
extension bases; replaced with a version-aware one-byte-string helper.
Also fixed: `frozenset(b"ACGNT")` membership must be normalized to byte
ordinals because Python 2 iterates `str` as 1-char strings.

## 4. Independent oracle

- Direct exact searches of `cP` / `Pc` on the merged naive oracle
  (left/right equality, 165 patterns x 5 bases);
- standalone suffix-order BWTs for all ten sources (per-source counts);
- sums of standalone counts for subset/group/where selections;
- naive FM backward step implemented with `C(c) + rank_c(l/r)` counting
  (the true LF-mapping semantics; the naive oracle's
  `givenRange` support was added with these semantics);
- randomized read-derived differentials (host, 3 seeds, 2,000+
  comparisons) and Level-3 real differential (seed 20260811).

## 5. Deterministic / randomized validation

Ten-source fixture: left/right == direct searches; per-source ==
standalone for all ten sources; subset/group/where sums; source intervals
exact; asymmetry instrumentation; include_zero filtering; right `$`
extension; left `$` rejected; invalid direction/symbol/empty-pattern/
empty-alphabet/multi-selector rejected.  Real canonical two-source merge
(200 queries) and 3 randomized real datasets: 0 mismatches.

## 6. Defect classification

- No CANDIDATE DEFECTS (one py2 adaptation trap fixed, section 3).
- No MODERN2 BASELINE defects discovered.
- TEST/ORACLE defect fixed (test-side): the initial naive
  `givenRange` implementation used raw row indices instead of the
  LF-mapping `C(c) + rank_c` semantics; corrected and cross-checked
  against direct searches.

## 7. Files added

- `packages/msbwt-modern2/tests/test_sequence_extensions_py2.py` (12
  tests), `compat/tests/test_sequence_extensions.py` (10 tests),
  `validate/feature8a-extensions.sh`, `validate/feature8a_extension_evidence.py`,
  `evidence/feature8a-extensions.json` (seed 20260811, mismatch_count 0),
  this doc + README update.
- Changed: `MUS/MultiSourceQuery.py` extended (additive); the naive
  fixture oracle in the two test helper modules gained `givenRange`
  support (test-side).  `git diff --check` clean.

## 8. Verification gates (all executed)

- full modern2 Python-2 suite (285 + 12 = 297 tests): OK;
- host compat suite + Q1 harness: 525 tests + 22 subtests OK;
- Feature-1..7 validation drivers: OK (regression);
- fixture hashes: OK; full long Q1 rerun NOT required (additive layer).
