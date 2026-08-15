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
| 3 | Query one constituent inside a multi-merged MSBWT (`MUS.MultiSourceQuery`: one merged FM search + rank projection down the source's root-to-leaf path; exact standalone interval/count identity; lazy rank loading; identity-bound derived rank caches) | VERIFIED-CORRECT (production-deployable) | [FEATURE3_QUERY_ONE_CONSTITUENT.md](FEATURE3_QUERY_ONE_CONSTITUENT.md) | `packages/msbwt-modern2/evidence/feature3-query-one-constituent.json` |
| 4 | Sparse nonzero-source listing with exact counts (`MUS.MultiSourceQuery.nonzeroSources` / `listSourcesWithOccurrences`: ONE merged FM search + single provenance-tree descent with rank0/rank1 projection and empty-child pruning; exact counts/intervals, deterministic order, traversal stats) | VERIFIED-CORRECT (production-deployable) | [FEATURE4_SPARSE_SOURCE_LISTING.md](FEATURE4_SPARSE_SOURCE_LISTING.md) | `packages/msbwt-modern2/evidence/feature4-sparse-source-listing.json` |
| 8A | Source-aware left/right sequence extensions (`MUS.MultiSourceQuery.extend` / `extendLeft` / `extendRight`: NO reverse FM-index; left = 1 full search + |alphabet| incremental `givenRange` backward steps; right = |alphabet| full searches, asymmetry explicit; default alphabet `ACGNT`, `$` right-only; source/subset/group/where selection per candidate) | VERIFIED-CORRECT (production-deployable) | [FEATURE8A_EXTENSIONS.md](FEATURE8A_EXTENSIONS.md) | `packages/msbwt-modern2/evidence/feature8a-extensions.json` |
| 7 | Source subsets / metadata groups / predicates (MUS.SourceMetadata: mutable labels in source_metadata.json / external files, never in the BWT; countSubset/querySubset/countGroup/queryGroup/countWhere/queryWhere — one merged FM search + provenance descent with unselected-branch pruning and complete-subtree shortcut) | VERIFIED-CORRECT (production-deployable) | [FEATURE7_SUBSET_GROUPS.md](FEATURE7_SUBSET_GROUPS.md) | packages/msbwt-modern2/evidence/feature7-subset-groups.json |
| 5&6 | Sample frequency + top-k exact sources (`MUS.MultiSourceQuery.sourceFrequency` / `countSourcesWithOccurrences` — count-only traversal without listing materialization; `topSources` / `topSourcesByAbundance` — exact top-k from Feature-4 sparse candidates, bounded heap selection, deterministic (-count, provenance-order) ties; one merged FM search per operation) | VERIFIED-CORRECT (production-deployable) | [FEATURE5_6_FREQUENCY_TOPK.md](FEATURE5_6_FREQUENCY_TOPK.md) | `packages/msbwt-modern2/evidence/feature5-6-frequency-topk.json` |
| 9 | Exact read-level provenance (`MUS.ReadProvenance`: one packed 20-byte record per read — origin file/read IDs + merged mate dollar ID — indexed by `getSequenceDollarID` dollar ID; automatic merge preservation and one-sided rejection; retrofit without BWT rebuild; `ReadProvenanceIndex`; `readsContaining` with duplicate preservation and source-prefiltered LF walks; BWT-identity-bound persistence) | VERIFIED-CORRECT (production-deployable) | [FEATURE9_READ_PROVENANCE.md](FEATURE9_READ_PROVENANCE.md) | `packages/msbwt-modern2/evidence/feature9-read-provenance.json` |
| 10 | Source removal / unmerge without FASTQ rebuild (`MUS.SourceRemoval`: `remove_sources` / `retain_sources` — surviving rows kept in existing order, provenance tree pruned with reuse/collapse/filter cases, output BYTE-equal to independent retained rebuild, read-provenance filtering with mate remapping, metadata pruning with group intersection, atomic temp-build publish, digest-bound output manifest, never copies stale rank caches) | VERIFIED-CORRECT (production-deployable) | [FEATURE10_SOURCE_REMOVAL.md](FEATURE10_SOURCE_REMOVAL.md) | `packages/msbwt-modern2/evidence/feature10-source-removal.json` |
| 12 | Generic BWT-aligned tag arrays (`MUS.BWTTags`: `bwt_tags.json` + `bwt_tags/tag_<hash>.npy`, hash-safe filenames, primitive-dtype policy, missing-value one-sided merge policy failing before the BWT merge, automatic stable-interleave merge, out-of-core chunked retrofit and Feature-10 mask filtering, `listTags`/`tagSchema`/`rowTag`/`tagInterval`/`tagValues`/`tagValueCounts`) | VERIFIED-CORRECT (production-deployable) | [FEATURE12_BWT_TAGS.md](FEATURE12_BWT_TAGS.md) | `packages/msbwt-modern2/evidence/feature12-bwt-tags.json` |
| Q1 | Exact lossless FASTQ quality sidecar (`MUS.QualitySidecar`, strict Point-12 specialization: reserved uint8 tag `fastq_quality_ascii`, suffix-first-base alignment with terminal-`$` sentinel 255, byte-exact no-Phred storage, disk-backed FASTQ retrofit with independent sequence verification, strict one-sided merge rejection, merge/removal lifecycle, `readQuality`/`readSequenceAndQuality`/`readFastqData`/`qualityValues`/`readsContaining(include_quality=True)`) | VERIFIED-CORRECT (production-deployable) | [Q1_QUALITY_SIDECAR.md](Q1_QUALITY_SIDECAR.md) | `packages/msbwt-modern2/evidence/q1-quality-sidecar.json` |
| 11A | Exact post-construction LCP retrofit (`MUS.LCP`: `lcps.npy` + `lcp.json` in the upstream Holt convention `lcps[i] = LCP(SA[i], SA[i+1])`, distinct-virtual-terminator semantics (duplicates never gain +1), read recovery + generalized Kasai with O(N) mmap working storage, no FASTQ/no BWT rebuild, BWT-identity-bound staleness rejection, `lcpAt`/`lcpAdjacent`/`lcpBetweenRows` RMQ queries, Feature-10 LCP fail-safe with explicit `drop_lcp`) | VERIFIED-CORRECT (production-deployable) | [FEATURE11A_LCP.md](FEATURE11A_LCP.md) | `packages/msbwt-modern2/evidence/feature11a-lcp.json` |

## Layout

- `docs/enhanced-modern2/` — milestone documents and this index.
- `packages/msbwt-modern2/MUS/SourceIndex.py` — Feature-1 production module
  (pure Python, additive).
- `packages/msbwt-modern2/MUS/MultiSourceProvenance.py` — Feature-2
  production module (pure Python, additive).
- `packages/msbwt-modern2/MUS/MultiSourceQuery.py` — Feature-3 production
  module (pure Python, additive).
- `packages/msbwt-modern2/tests/test_source_index_py2.py` — Feature-1
  Python-2 tests (real merges).
- `packages/msbwt-modern2/tests/test_multisource_provenance_py2.py` —
  Feature-2 Python-2 tests (real merges).
- `packages/msbwt-modern2/tests/test_multisource_query_py2.py` — Feature-3
  Python-2 tests (real merges).
- `packages/msbwt-modern2/tests/test_sparse_source_listing_py2.py` —
  Feature-4 Python-2 tests (real merges).
- `packages/msbwt-modern2/tests/test_frequency_topk_py2.py` — Feature-5/6
  Python-2 tests (real merges).
- `compat/tests/test_feature1_source_index.py` — Feature-1 host tests
  (rank/cache/API, evidence-record consistency).
- `compat/tests/test_multisource_provenance.py` — Feature-2 host tests
  (format/corruption/randomized differential, evidence-record consistency).
- `compat/tests/test_multisource_query.py` — Feature-3 host tests
  (naive/synthetic differentials, cache hardening, evidence-record
  consistency).
- `compat/tests/test_sparse_source_listing.py` — Feature-4 host tests
  (sparse/naive differentials, pruning stats, evidence-record
  consistency).
- `compat/tests/test_frequency_topk.py` — Feature-5/6 host tests
  (frequency/top-k differentials, tie rule, evidence-record
  consistency).
- `packages/msbwt-modern2/validate/feature1-two-source-rank.sh` +
  `feature1_two_source_evidence.py` — Feature-1 validation driver and
  evidence generator.
- `packages/msbwt-modern2/validate/feature2-multi-source-provenance.sh` +
  `feature2_multi_source_evidence.py` — Feature-2 validation driver and
  evidence generator.
- `packages/msbwt-modern2/validate/feature3-query-one-constituent.sh` +
  `feature3_query_one_constituent_evidence.py` — Feature-3 validation
  driver and evidence generator.
- `packages/msbwt-modern2/validate/feature4-sparse-source-listing.sh` +
  `feature4_sparse_source_evidence.py` — Feature-4 validation driver and
  evidence generator.
- `packages/msbwt-modern2/validate/feature5-6-frequency-topk.sh` +
  `feature5_6_frequency_topk_evidence.py` — Feature-5/6 validation driver
  and evidence generator.
- `packages/msbwt-modern2/MUS/ReadProvenance.py` + `tools/retrofit_read_provenance.py` —
  Feature-9 production module and retrofit CLI (pure Python, additive).
- `packages/msbwt-modern2/tests/test_read_provenance_py2.py` — Feature-9
  Python-2 tests (real merges).
- `compat/tests/test_read_provenance.py` — Feature-9 host tests
  (independent oracle, persistence safety, randomized differentials,
  evidence-record consistency).
- `packages/msbwt-modern2/validate/feature9-read-provenance.sh` +
  `feature9_read_provenance_evidence.py` — Feature-9 validation driver and
  evidence generator.
- `packages/msbwt-modern2/MUS/SourceRemoval.py` + `tools/remove_sources.py` —
  Feature-10 production module and removal CLI (pure Python, additive).
- `packages/msbwt-modern2/tests/test_source_removal_py2.py` — Feature-10
  Python-2 tests (real merges).
- `compat/tests/test_source_removal.py` — Feature-10 host tests
  (byte equality, clean-control equivalence, safety, randomized
  differentials, evidence-record consistency).
- `packages/msbwt-modern2/validate/feature10-source-removal.sh` +
  `feature10_source_removal_evidence.py` — Feature-10 validation driver
  and evidence generator.
- `packages/msbwt-modern2/MUS/BWTTags.py` + `tools/bwt_tags.py` —
  Feature-12 production module and tag CLI (pure Python, additive).
- `packages/msbwt-modern2/tests/test_bwt_tags_py2.py` — Feature-12
  Python-2 tests (real merges).
- `compat/tests/test_bwt_tags.py` — Feature-12 host tests
  (row-identity oracle, one-sided policies, retrofit/removal alignment,
  query lifecycle, randomized differentials, evidence-record
  consistency).
- `packages/msbwt-modern2/validate/feature12-bwt-tags.sh` +
  `feature12_bwt_tags_evidence.py` — Feature-12 validation driver and
  evidence generator.
- `packages/msbwt-modern2/MUS/QualitySidecar.py` + `tools/quality_sidecar.py` —
  Q1 production module and quality CLI (strict Point-12 specialization;
  pure Python, additive).
- `packages/msbwt-modern2/tests/test_quality_sidecar_py2.py` — Q1
  Python-2 tests (real merges).
- `compat/tests/test_quality_sidecar.py` — Q1 host tests
  (suffix-start alignment oracle, FASTQ retrofit, merge/removal
  lifecycle, query APIs, randomized differentials, evidence-record
  consistency).
- `packages/msbwt-modern2/validate/q1-quality-sidecar.sh` +
  `q1_quality_sidecar_evidence.py` — Q1 validation driver and evidence
  generator.
- `packages/msbwt-modern2/MUS/LCP.py` + `tools/lcp.py` — Feature-11A
  production module and LCP CLI (pure Python, additive).
- `packages/msbwt-modern2/tests/test_lcp_py2.py` — Feature-11A
  Python-2 tests (real merges).
- `compat/tests/test_lcp.py` — Feature-11A host tests
  (explicit-suffix oracle, terminator semantics, staleness, query API,
  randomized differentials, evidence-record consistency).
- `packages/msbwt-modern2/validate/feature11a-lcp.sh` +
  `feature11a_lcp_evidence.py` — Feature-11A validation driver and
  evidence generator.

## Roadmap

- Features 3, 4, 5&6, 7, 8A, 9, 10, 12, Q1, and 11A (query layer, sparse
  listing, frequency + top-k, subsets/groups/predicates, left/right
  extensions, read-level provenance, source removal, BWT-aligned tags,
  exact FASTQ quality sidecar, post-construction LCP) are implemented
  and verified on this branch.
- Feature 13A (whole-index benchmark harness + backend contract) is the
  final milestone on this branch.
