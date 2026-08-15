# ENHANCED-MODERN2 — Feature 9 (executed evidence): Exact read-level provenance

Status date: 2026-08-15

Branch: `enhanced-modern2` (starting commit `ce8e66b`)

This milestone integrates research Feature 9 (candidate authority:
`research/feature-candidates/9/`) as an additive layer over the verified
Feature-2 provenance tree and Feature-3 rank projection.  No core baseline
algorithm, persistent format, or CLI command was modified.

**Verdict: PASS.**  VERIFIED-CORRECT: for every BWT row `x`,
`read_provenance[bwt.getSequenceDollarID(x)]` holds the exact metadata of
the original read (source, source-local read ID, origin file/read IDs,
merged mate dollar ID) through leaf initialization, arbitrary balanced
merges, and retrofit; duplicate reads never collapse; every persisted
artifact is identity-bound and stale arrays fail loudly.

## 1. Public API

New module `MUS/ReadProvenance.py` (pure Python/NumPy, Python-2.7
compatible):

- `initialize_leaf_read_provenance(bwt_dir, records, source_metadata=None,
  overwrite=False)` — records in local dollar-ID order;
  `{"origin_file_id", "origin_read_id", "mate_source_read_id"}`.
- `initialize_leaf_read_provenance_from_about(bwt_dir, input_files=None,
  overwrite=False)` — legacy `about.npy` import (structured
  `(file_id, read_id)` or 2-D layouts); `input_files` restores the
  filename table.
- `merge_two_read_provenance(left_dir, right_dir, output_dir)` — merges
  child tables from the output root interleave prefix.
- `build_read_provenance_from_leaf_records(merged_dir, records_by_source,
  source_metadata_by_source=None, overwrite=False)` — retrofit without
  re-merging; replays only saved interleaves.
- `retrofit_read_provenance_from_leaf_dirs(merged_dir,
  leaf_dirs_by_source, input_files_by_source=None, overwrite=False)` —
  leaf Feature-9 provenance or legacy `about.npy`.
- `ReadProvenanceIndex(bwt_dir, mmap=True, validate=True,
  source_index=None)` — `read_count`, `record_bytes()`, `record(dollar_id)`
  (dict with `dollar_id`, `source_id`, `source_name`, `source_read_id`,
  `origin_file_id`, `origin_file`, `origin_read_id`, `mate_dollar_id`,
  `paired`), `records(ids)`, `find_dollar_id(source, source_read_id)`,
  `mate(dollar_id)`, `source_read_count(source)`, `source_metadata(source)`.

Additions to `MUS/MultiSourceQuery.py`:

- `MultiSourceQueryIndex.locate_row_source(row_index, trace=False)` —
  merged BWT row -> `(source_id, source_local_row)` via the provenance
  tree (row-level analogue of Feature-3 interval projection).
- `MultiSourceBWT(..., read_provenance=None)`; `load()` auto-loads
  Feature-9 provenance when present.
- `readProvenance(dollar_id)`, `rowReadProvenance(row_index,
  include_offset=False)`, `readMate(dollar_id)`,
  `readsContaining(seq, source=None, sources=None, group=None, where=None,
  givenRange=None, include_sequence=False, include_rows=False,
  max_occurrences=None)` — unique reads with exact per-read occurrence
  counts (duplicate identities preserved), one merged FM search,
  provenance-tree row prefiltering before LF walks for selected sources.

Additions to `MUS/MultiSourceProvenance.py`:

- `merge_two_with_provenance` now refuses one-sided read provenance
  (error BEFORE the BWT merge) and automatically merges read provenance
  when both children carry it.  `merge_many_balanced` inherits this.

New CLI tool: `packages/msbwt-modern2/tools/retrofit_read_provenance.py`
(`--merged`, repeated `--source ID=PATH`, optional `--input-files`,
`--overwrite`).

## 2. Persisted files (classification)

- `read_provenance.npy` — **AUTHORITATIVE** read identity.  Version 1,
  packed dtype `[("origin_file_id","<u4"),("origin_read_id","<u8"),
  ("mate_dollar_id","<u8")]` with `align=False`, exactly **20 bytes/read**
  (measured and enforced at import).  One record per read, ordered by
  current merged dollar ID (rows `[0, R)` of the merged suffix order are
  exactly the `$` rows; the first `R_left+R_right` interleave bits
  stable-merge the child tables).  Memory-mappable; load-time exact-size
  verification rejects truncated/tampered files.
- `read_provenance.json` — **AUTHORITATIVE** metadata: `format`
  (`msbwt-read-provenance`), `version` (1), `read_count`, `record_bytes`,
  `ordering` (`msbwt-dollar-id`), `fields`, per-source optional
  `source_metadata` (e.g. `input_files` name tables), and `bwt_sha256`
  bound to the validated `provenance.json` `msbwt_sha256` of the current
  BWT.
- Stale/corrupt behavior: wrong format/version/ordering/record size,
  NPY/JSON read-count mismatch, wrong dtype, truncated or appended array
  bytes, `$`-count mismatch, unknown source metadata, and copied foreign
  same-length arrays (BWT identity binding) all raise
  `ReadProvenanceError`; a replaced same-length BWT is caught by the
  Feature-2 manifest digest validation.  No silent incorrect read
  identity is possible.
- Atomic writes: JSON via tmp-file + fsync + rename; NPY via
  `np.save` after validation.
- Relation to other files: source/local read identity is NOT persisted —
  it is derived from `provenance.json` + `provenance/interleaves` +
  `inter0.npy` via `locate_row_source` (Features 1-3).  BWT bytes are
  never modified by Feature 9.

## 3. Candidate audit and defects

Candidate files audited: `POINT9_README.md`,
`POINT9_STORAGE_AND_QUERY_MODEL.json`, `ReadProvenance.py`,
`MultiSourceProvenance(1).py`, `MultiSourceQuery(5).py`,
`retrofit_read_provenance.py`, `test_point9_read_provenance.py`,
`test_point9_integration.py`.  The candidate's read-provenance design
(20-byte packed record, interleave-prefix stable merge, retrofit by
interleave replay, `readsContaining` with provenance prefilter) was
preserved.

CANDIDATE DEFECTS (fixed in production):

1. Python-2 incompatibility: the candidate used `pathlib.Path` /
   `write_text(encoding=...)` / `read_text(encoding=...)` throughout —
   rewritten with the repository's `os.path` + atomic-binary-JSON pattern
   (Python 2.7 has no `pathlib`).
2. Weak identity binding: the candidate bound read provenance only to the
   `$` row count and source-metadata keys, so a copied same-length array
   from another index would silently load.  Production adds the
   `bwt_sha256` binding (reusing the manifest's already-validated digest;
   no extra hashing) and load-time exact file-size verification.
3. Truncated-array hazard: `np.load(..., mmap_mode="r")` defers I/O, so a
   truncated `.npy` could pass loading and fault only at element access.
   Production verifies the on-disk length against the .npy header
   immediately, and maps load errors to `ReadProvenanceError`.

No MODERN2 BASELINE defects discovered.  Two baseline facts were
confirmed and documented: (a) legacy `about.npy` is only produced by the
uniform (Bauer) preprocessing route — the nonuniform (Multimerge) route
writes no `about.npy`, so explicit `initialize_leaf_read_provenance`
records are the supported path there; (b) Holt's `recoverString`
returns the full rotation starting at `$` (`'$' + read`), which the
`include_sequence` results therefore carry.

## 4. Independent oracle

- Read-derived fixtures: every merged row -> `(source, local row)` by
  DIRECT bit-array counting through the verified `unpack_interleave`
  (no sampled rank index, no Feature-9 code); dollar rows are rows
  `[0, R)` of the merged order, so every global dollar ID maps to an
  exact (source, original read) identity; `getSequenceDollarID` and
  `recoverString` are reimplemented from `naive_suffix_rows.json`.
- Per-read expected `readsContaining` counts computed by naive
  overlapping string search on the original read lists.
- Real integration: leaves built from `uniform-a.fastq` / `uniform-b.fastq`
  by real pp/cfpp (legacy `about.npy`), real GenericMerge merges; every
  dollar ID's source checked against Holt's real `getSequenceDollarID`
  LF walk; recovered read multiset == original FASTQ reads; per-read
  occurrence maps vs recovered reads; source-filtered totals ==
  standalone counts.

## 5. Deterministic / randomized validation

- Ten-source fixture (30 reads, 191 BWT rows): 185 patterns; 2,653
  comparisons, 0 mismatches; every dollar ID exact; mate links; one-sided
  merge rejection; retrofit byte-identity of BWT/provenance.json.
- Real integration: 655 comparisons, 0 mismatches (about.npy import,
  LF-walk agreement, exact read recovery, per-read maps, kmer sweep
  1-3 over ACGTN).
- Randomized: seed 20260811, 3 real datasets (2-4 sources each, real
  construction + real merges), 1,022 comparisons, 0 mismatches.
- Host randomized differentials: seeds 20260811/20260812/20260813,
  36 datasets, per-dollar identity + per-pattern read maps.
- Performance sanity: pattern `A` on the ten-source fixture — 47 merged
  occurrences; source-filtered query does 5 LF walks instead of 47
  (89.4% reduction; row-source prefiltering still visits all 47 rows).
  Correctness-first: `readsContaining` remains output-sensitive by design.

## 6. Feature-10 contract preparation (documented, not implemented)

- `read_provenance.npy` rows are ordered by current merged dollar ID;
  rows of a removed source are exactly the dollar rows projected to that
  source (`project_interval(source, 0, R)`), so a removal can filter the
  array by provenance-tree projection and renumber `mate_dollar_id`
  references within the surviving set.
- `origin_file_id` / `origin_read_id` / `source_metadata` must remain
  byte-stable after removal; only `mate_dollar_id` (a dollar-ID pointer)
  needs renumbering, and unpaired/unknown values stay `UINT64_UNKNOWN`.

## 7. Files added / changed

- Added: `MUS/ReadProvenance.py`, `tools/retrofit_read_provenance.py`,
  `tests/test_read_provenance_py2.py` (48 tests),
  `compat/tests/test_read_provenance.py` (29 tests),
  `validate/feature9-read-provenance.sh`,
  `validate/feature9_read_provenance_evidence.py`,
  `evidence/feature9-read-provenance.json` (seed 20260811,
  mismatch_count 0), this doc + README update.
- Changed (additive): `MUS/MultiSourceProvenance.py` (one-sided rejection
  + automatic merge), `MUS/MultiSourceQuery.py`
  (`locate_row_source`, `read_provenance` support, read-level query
  methods).  `git diff --check` clean.

## 8. Test counts

- Python 2: 345 tests (was 297), all green.
- Host: 530 tests (was 501) + 22 subtests, all green.
- Q1 modernization harness: 24 tests, unchanged and green.
