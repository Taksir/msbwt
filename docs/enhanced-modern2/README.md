# enhanced-modern2 — research feature track

This tree documents research features developed on top of the published
`msbwt-modern2` compatibility baseline (release commit `370c726`, branch
`codex/modern2`).  The baseline itself is frozen; each feature here is an
additive layer with its own milestone document, tests, and executed evidence,
and is developed on the `enhanced-modern2` branch.

## Rules

- Baseline modern2 behavior is authoritative for everything Feature layers
  do not explicitly extend.  Feature work never modifies the published
  `codex/modern2` release branch.
- Core baseline algorithms (construction, readers, FM search, merge,
  compression/decompression) are not modified unless executed evidence
  proves a required correctness fix, and any such fix requires a STOP +
  report first.
- Every feature keeps the CPython 2.7.18 / Cython 3.0.12 / NumPy 1.16.6
  contract and validates against the pinned Python-2 environment plus the
  host-side compat suite.
- Every feature records executed evidence: seeds, corpora, oracle
  definitions, comparison counts, and any defect classification
  (CANDIDATE DEFECT vs MODERN2 DEFECT).

## Feature index

| # | Feature | Status | Doc | Evidence |
|---|---|---|---|---|
| 1 | Two-source rank-aware queries (`MUS.SourceIndex`, one merged FM search + provenance rank over `inter0.npy`) | VERIFIED-CORRECT (production-deployable) | [FEATURE1_TWO_SOURCE_RANK.md](FEATURE1_TWO_SOURCE_RANK.md) | `packages/msbwt-modern2/evidence/feature1-two-source-rank.json` |
| 2 | Persistent multi-source provenance / source indexing (`MUS.MultiSourceProvenance`: identity-preserving multi-stage merges of any number of sources, `provenance.json` manifest + per-merge interleave store, digest-validated, Feature-1 compatible) | VERIFIED-CORRECT (production-deployable) | [FEATURE2_MULTI_SOURCE_PROVENANCE.md](FEATURE2_MULTI_SOURCE_PROVENANCE.md) | `packages/msbwt-modern2/evidence/feature2-multi-source-provenance.json` |

## Layout

- `docs/enhanced-modern2/` — milestone documents and this index.
- `packages/msbwt-modern2/MUS/SourceIndex.py` — Feature-1 production module
  (pure Python, additive).
- `packages/msbwt-modern2/MUS/MultiSourceProvenance.py` — Feature-2
  production module (pure Python, additive).
- `packages/msbwt-modern2/tests/test_source_index_py2.py` — Feature-1
  Python-2 tests (real merges).
- `packages/msbwt-modern2/tests/test_multisource_provenance_py2.py` —
  Feature-2 Python-2 tests (real merges).
- `compat/tests/test_feature1_source_index.py` — Feature-1 host tests
  (rank/cache/API, evidence-record consistency).
- `compat/tests/test_multisource_provenance.py` — Feature-2 host tests
  (format/corruption/randomized differential, evidence-record consistency).
- `packages/msbwt-modern2/validate/feature1-two-source-rank.sh` +
  `feature1_two_source_evidence.py` — Feature-1 validation driver and
  evidence generator.
- `packages/msbwt-modern2/validate/feature2-multi-source-provenance.sh` +
  `feature2_multi_source_evidence.py` — Feature-2 validation driver and
  evidence generator.

## Roadmap

- Feature 3 (query layer: per-source rank projection over the Feature-2
  provenance tree) is NOT implemented; Feature 2 exposes only provenance.
- Features 3+ are future milestones on this branch.
