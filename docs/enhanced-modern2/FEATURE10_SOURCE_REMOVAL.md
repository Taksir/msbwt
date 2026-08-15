# ENHANCED-MODERN2 — Feature 10 (executed evidence): Source removal / unmerge without FASTQ rebuild

Status date: 2026-08-15

Branch: `enhanced-modern2` (Feature-9 commits `f5126ff`, `38a6d8c`,
`4d83f6a`)

This milestone integrates research Feature 10 (candidate authority:
`research/feature-candidates/10/`) as an additive layer.  No core baseline
algorithm, persistent format, or CLI command was modified.

**Verdict: PASS.**  VERIFIED-CORRECT: for every retained source set `K`,
`BWT(remove_sources(Merged, K))` is BYTE-FOR-BYTE equal to the BWT of the
collection containing exactly `K` (independent suffix sort of the retained
reads), every retained constituent recovers byte-for-byte to its original
standalone BWT, and all Features 3-9 semantics on the reduced package equal
a clean retained-source control.  The input package is never modified; the
output is atomically published only after complete validation.

## 1. Public API

New module `MUS/SourceRemoval.py` (pure Python/NumPy, Python-2.7
compatible):

- `remove_sources(input_dir, output_dir, sources=None, group=None,
  where=None, source_metadata_path=None, overwrite=False,
  build_rank_indexes=False, rank_stride_bytes=64, chunk_rows=8Mi)` —
  resolve exactly one selection (source IDs/names, named metadata group,
  or metadata predicate) and build a new package without the selected
  sources.  Returns a stats dict (`input_sources`, `retained_sources`,
  `removed_sources`, `input_bwt_rows`, `output_bwt_rows`, `rows_removed`,
  `subtrees_reused`, `subtrees_removed`, `leaves_removed`,
  `nodes_collapsed`, `nodes_rewritten`, `read_provenance_preserved`,
  `rank_indexes_built`, `retained_source_ids`, `removed_source_ids`).
- `retain_sources(input_dir, output_dir, keep_sources, ...)` — the core
  operation; `keep_sources` accepts stable source IDs or unique names.
- Rejections: input == output, remove every source, retain zero sources,
  empty remove selection, retain-all no-op, existing output without
  explicit `overwrite=True`.

Addition to `MUS/ReadProvenance.py`:

- `filter_read_provenance(input_dir, output_dir, keep_dollar_mask)` —
  filters the Feature-9 table by input dollar-ID order, translates mate
  dollar IDs into the output space (mates to removed reads become
  unpaired), prunes source metadata, and re-validates against the output
  package (`$` count, source table, BWT identity binding).

New CLI tool: `packages/msbwt-modern2/tools/remove_sources.py`
(`--input`, `--output`, exactly one of `--remove` / `--keep` / `--group` /
`--where KEY=VALUE...`, `--metadata`, `--overwrite`, `--build-ranks`,
`--rank-stride-bytes`).

## 2. Algorithm and provenance-tree pruning

The reduced BWT keeps surviving rows in their existing merged order
(Features 1-3 invariant: a merged BWT is a stable interleaving of its
constituent row orders).  The tree is pruned with four cases:

1. subtree fully retained -> original node + original interleave reused
   (file copied; digest unchanged);
2. subtree fully removed -> dropped;
3. one child survives -> merge node collapsed (no one-child node);
4. both children partially survive -> old interleave filtered by the
   survival masks to a new interleave (new node ID + content digest).

Only case-4 nodes get rewritten interleaves.  The BWT is written in
chunks via `open_memmap` (no whole-array in-memory copy; configurable
`chunk_rows`).  A single-root leaf package has no `inter0.npy`; a reduced
merge root copies its interleave to `inter0.npy`, preserving the
Feature-1/Holt convention.

## 3. Persisted files (classification)

Output files carry exactly the Feature-2/7/9 classifications:

- `msbwt.npy`, `provenance.json`, `provenance/interleaves/*`,
  `inter0.npy` (merge root only), `read_provenance.npy` +
  `read_provenance.json` (when the input has them) — AUTHORITATIVE.
  The output manifest binds `msbwt_sha256` (new BWT) and per-node
  `interleave_sha256`; retained source records keep their original
  `bwt_sha256`, so the single-source leaf case still validates (the
  filtered rows are byte-identical to the original standalone BWT).
- `source_metadata.json` — MUTABLE / REBUILDABLE (Feature 7), pruned to
  retained sources; groups are intersected with the retained collection.
- `provenance/ranks/*` — DERIVED / REBUILDABLE.  NEVER copied from the
  input: stale rank caches cannot survive a removal.  Rebuilt lazily by
  Feature-3 queries, or eagerly with `build_rank_indexes=True` (writes
  one identity-bound cache per surviving internal node).
- Stale/corrupt behavior: any inconsistency fails loudly via the
  standard manifest/read-provenance validation; a failed removal
  publishes nothing.

## 4. Atomicity

The output is built in a temporary sibling directory; only after the BWT
write, provenance write, manifest validation, read-provenance filtering,
metadata filtering, and optional rank construction succeed is the package
renamed to the requested path.  A failed removal (e.g. corrupt input read
provenance) leaves no output directory and no temp leftovers.  The input
package bytes are never modified (hash-verified in tests).

## 5. Candidate audit and defects

Candidate files audited: `POINT10_README.md`,
`POINT10_STRUCTURAL_BENCHMARK.json`, `SourceRemoval.py`,
`ReadProvenance(1).py` (filter addition), `remove_sources.py`,
`test_point10_source_removal.py`, `test_point10_integration.py`.  The
pruning/mask design and the atomic publish flow were preserved.

CANDIDATE DEFECTS (fixed in production):

1. Python-2 incompatibility: `pathlib.Path`, `write_text(encoding=...)`,
   `open(encoding=...)`, and `os.replace` on directories — rewritten with
   the repository's `os.path` + atomic-binary-JSON + rename-fallback
   patterns (Python 2.7 has no `pathlib` and no `os.replace`).
2. Missing production digest contract: the candidate's output manifest
   lacked `msbwt_sha256` and rewritten nodes lacked `interleave_sha256`
   (its snapshot predates the Feature-2 digest identity contract), and
   `_deep_copy_node` dropped `interleave_sha256` from reused nodes.
   Production writes both digests, so same-length replaced BWTs and
   interleaves in reduced packages are always detected.
3. One-sided-safety gap in the candidate's `os.replace` publish: on
   Python 2 the fallback `os.rename` is used (same-filesystem sibling
   temp dir), preserving atomicity.

No MODERN2 BASELINE defects discovered.  Baseline facts confirmed:
nonuniform (Multimerge) preprocessing writes no `about.npy` (Feature-9
doc), and the uniform route's `about.npy` read order is the sorted-read
order the dollar rows follow (verified again in the real integration
section).

## 6. Independent oracle

- BYTE-FOR-BYTE oracle: independent global suffix sort of the retained
  reads by `(suffix, source_order, read_id, pos)` — the exact
  stable-merge semantics of the fixture machinery — compared against the
  reduced `msbwt.npy`.
- Original standalone BWTs: retained constituents recover byte-for-byte;
  single-source output equals the original leaf bytes.
- CLEAN retained-source control index (built from the retained leaves in
  the same source order): byte-equal BWT plus record-for-record equal
  read provenance, and equal sparse/frequency/top-k/subset semantics.
- Real integration: real pp/cfpp leaves with legacy `about.npy`, real
  GenericMerge merges; reduced counts == retained standalone counts for
  ~190 patterns; retain-one byte equality; about-based read provenance
  survival.

## 7. Deterministic / randomized validation

- Removal shapes: first / last / middle / two nonadjacent / contiguous
  group / all odd sources / retain panel / retain one — 6+ shapes,
  byte-for-byte equal, manifest-validated.
- Read provenance: filtered, mates remapped, equal to clean control;
  `readsContaining` on the reduced package == naive retained counts with
  no removed source present.
- Metadata: named-group removal (groups intersected: removed group
  becomes `[]`), predicate removal, external metadata file, missing
  metadata rejection.
- Safety: input bytes unchanged; failed removal leaves nothing; no stale
  rank caches; eager rank build == internal node count; all rejections.
- Randomized: seed 20260811, 18 cases (read-derived), byte + read
  provenance checks, 0 mismatches; host differentials, seeds
  20260811/20260812/20260813, 18 cases, 0 mismatches.
- Real integration: 400+ comparisons, 0 mismatches.

## 8. Test counts

- Python 2: 378 tests (was 345), all green.
- Host: 551 tests (was 530) + 22 subtests, all green.
- Q1 modernization harness: 24 tests, unchanged and green.

## 9. Feature-12/13 contract notes

- The reduced package keeps the same Feature-1..9 interfaces, so later
  tag/quality/LCP work can operate on either the original merged
  collection or a reduced collection without special query semantics.
- Feature 10 does NOT maintain a parallel compressed/RLBWT
  representation; compressed-backend integration belongs with Feature 13A
  backend work.
