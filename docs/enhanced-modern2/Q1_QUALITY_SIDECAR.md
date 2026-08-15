# ENHANCED-MODERN2 — Q1 (executed evidence): Exact lossless FASTQ quality sidecar (Point-12 specialization)

Status date: 2026-08-15

Branch: `enhanced-modern2` (Feature-12 commits `9b27ae9`, `1e1dbe7`,
`094468a`)

This milestone integrates research Q1 (candidate authority:
`research/feature-candidates/Q1 quality sidecar/`) as a strict semantic
specialization of the verified Feature-12 tag layer.  No core baseline
algorithm, persistent format, or CLI command was modified.

**Verdict: PASS.**  VERIFIED-CORRECT: the original FASTQ quality line is
preserved byte-for-byte (no Phred conversion, no quantization), aligned to
suffix-start BWT rows (terminal `$` rows carry sentinel 255), and follows
the exact Feature-12 lifecycle: leaf retrofit from original FASTQs (with
independent sequence verification), automatic two-way/balanced merge
preservation, merged retrofit without BWT reconstruction, and Feature-10
removal (`quality_reduced == quality_original[keep_mask]`
element-for-element).

## 1. Public API

New module `MUS/QualitySidecar.py` (pure Python/NumPy, Python-2.7
compatible):

- Reserved Point-12 tag `fastq_quality_ascii` (uint8, 1 byte/BWT row).
- `initialize_leaf_quality_from_records(bwt_dir, bwt,
  qualities_by_dollar_id, sequences_by_dollar_id=None, overwrite=False,
  verify_sequences=True)` — dollar-ordered records with optional
  independent sequence verification.
- `initialize_leaf_quality_from_fastqs(bwt_dir, bwt, fastq_paths,
  about_path=None, overwrite=False, verify_sequences=True,
  temp_parent=None)` — disk-backed FASTQ retrofit (plain and `.gz`,
  multiple origin files); `about.npy` or Feature-9 read provenance maps
  dollar IDs to `(origin_file_id, origin_read_id)`; FASTQ order need not
  match dollar order.
- `attach_quality_from_row_values(bwt_dir, values, overwrite=False,
  builder="row-values")` — precomputed row-aligned arrays.
- `retrofit_merged_quality_from_leaf_arrays(merged_dir, arrays_by_source,
  overwrite=False)` — replay saved provenance interleaves; BWT bytes
  unchanged.
- `preflight_quality_merge(left, right)` — fails BEFORE the BWT merge on
  incomplete/inconsistent Q1 state (one-sided quality merge forbidden).
- `merge_quality_sidecar_metadata(left, right, output)` — regenerates
  `quality_sidecar.json` after the ordinary Feature-12 tag interleave.
- `filter_quality_sidecar_metadata(input, output)` — regenerates
  metadata after Feature-10 filters the quality tag.
- `validate_quality_sidecar(bwt_dir, full=True)` — metadata + tag schema
  + terminal/base coverage (first `read_count` rows carry 255; no other
  row may).
- `quality_sidecar_exists(bwt_dir)`.
- `QualitySidecar(bwt_dir, mmap=True, validate=True)` —
  `quality_byte_for_row` / `quality_for_row` (sentinel -> None),
  `recover_quality(bwt, dollar_id)`, `recover_sequence_and_quality`,
  `record(bwt, dollar_id, read_provenance=None)`.
- `quality_ascii_to_phred(values, offset=33)` — analysis-only helper;
  persisted data remain exact.

Additions to `MUS/MultiSourceProvenance.py`: `merge_two_with_provenance`
runs the Q1 preflight before the BWT merge and regenerates the sidecar
metadata after the tag merge.

Additions to `MUS/MultiSourceQuery.py`:

- `MultiSourceBWT(..., quality_sidecar=None)`; `load()` auto-loads the
  sidecar when present.
- `hasQuality()`, `qualityForRow(row_index)`,
  `readQuality(dollar_id)`, `readSequenceAndQuality(dollar_id)`,
  `readFastqData(dollar_id)` (adds Feature-9 provenance when available),
  `qualityValues(seq, source=None, sources=None, group=None, where=None,
  ...)` (exact first-base quality over the FM interval; Feature-3/7
  selectors via the Feature-12 machinery), and
  `readsContaining(..., include_quality=True)` (every returned read gains
  its exact original quality line).

Additions to `MUS/SourceRemoval.py`: `retain_sources` regenerates the
sidecar metadata after filtering the quality tag; stats add
`quality_sidecar_preserved`.

New CLI tool: `packages/msbwt-modern2/tools/quality_sidecar.py`
(`init-leaf`, `retrofit-merged`, `validate`, `recover`).

## 2. Alignment semantics (the critical contract)

For the suffix/BWT row whose suffix starts at read position `p`:

    quality[row] = original FASTQ quality byte Q[p]

The terminal `$` suffix row stores 255 (reserved sentinel, never a
Point-12 missing value).  This suffix-first-base alignment means:

- `recoverString(dollar_id, withIndex=True)` returns the suffix-row path
  in original read order, so exact quality recovery is ONE ordinary read
  traversal + direct tag gathers;
- a normal FM interval for pattern `P` directly indexes the quality byte
  of `P`'s first base at every occurrence.

Scope honesty: Q1 preserves exactly sequence, quality line, and (with
Feature 9) origin file/read identity.  FASTQ header text is NOT preserved;
byte-for-byte recreation of a complete original FASTQ file including
arbitrary headers is outside Q1.

## 3. Persisted files (classification)

- `bwt_tags/tag_<hash>.npy` (tag `fastq_quality_ascii`) — AUTHORITATIVE
  quality bytes (ordinary Feature-12 tag storage; mmap-able; no pickle).
- `quality_sidecar.json` — AUTHORITATIVE semantic metadata: format
  (`msbwt-fastq-quality-sidecar`, version 1), `tag_name`, `dtype`,
  `alignment` (`suffix-first-base`), `encoding`
  (`raw-fastq-quality-byte`), `exact_bytes`, `terminal_sentinel` (255),
  `bwt_rows`, `read_count`, `source_count`, optional `input_files`,
  `builder`, `child_builders`, semantics text.  Written atomically.
- Stale/corrupt behavior: wrong format/version/tag/alignment/encoding/
  sentinel, stale row/read counts, missing tag, wrong dtype/shape,
  missing-value policy declared on the quality tag, non-terminal 255, or
  missing terminal sentinels all raise `QualitySidecarError`.
- Relation to other files: quality is a Point-12 tag; its physical bytes
  are part of `bwt_tags/` storage (Feature 13A never double counts).

## 4. Candidate audit and defects

Candidate files audited: `Q1_QUALITY_SIDECAR_README.md`,
`Q1_STORAGE_MODEL.json`, `QualitySidecar.py`, `MultiSourceProvenance(3).py`,
`MultiSourceQuery(7).py`, `SourceRemoval(2).py`, `quality_sidecar.py`,
`test_q1_quality_sidecar.py`, `test_q1_integration.py`.  The alignment
contract, the disk-backed FASTQ archive, the sequence-verification gate,
and the strict one-sided merge policy were preserved.

CANDIDATE DEFECTS (fixed in production):

1. Python-2 incompatibilities: `pathlib.Path`,
   `write_text/read_text(encoding=...)`, `os.replace`, parenthesized
   multi-context `with` — adapted (os.path + atomic-binary-JSON + rename
   fallback + comma-form context managers).
2. Python-2 str/bytes semantics: `bytes([x])` list-repr traps in
   `_normalize_quality_bytes` and the FASTQ archive record reader, and
   `symbol == ord("$")` comparisons when iterating py2 `str` (never
   matched, silently treating `$` as a base) — fixed with version-aware
   helpers (`_one_byte`, `_is_dollar_symbol`) and `.tobytes()`.
3. One-sided merge error ordering: the generic Feature-12 tag preflight
   ran before the Q1 preflight, masking the semantic error; Q1 now runs
   first (clearer, correct failure before the BWT merge).

No MODERN2 BASELINE defects discovered.

## 5. Independent oracle

- Expected leaf quality arrays computed DIRECTLY from the naive suffix
  rows and the original reads (`Q[pos]` or 255), compared element-for-
  element for every row of every dataset (no Q1 code involved).
- Expected merged quality arrays by independent suffix-sort replay.
- Original FASTQ lines (plain and gz) as the byte-for-byte recovery
  oracle, including about.npy origin remapping where FASTQ order does
  not match dollar order.

## 6. Deterministic / randomized validation

- 10-source fixture: 191 rows, 0 alignment mismatches; every read's
  recovered quality equals its original line; leaf-record and FASTQ
  retrofit paths; gz + multiple origin files; sequence-mismatch
  rejection (with explicit opt-out); byte-255 rejection.
- Merges: two-way and balanced 10-source exact; one-sided merge rejected
  before the BWT merge; merged retrofit equals merge-produced values
  (BWT bytes unchanged).
- Removal: quality filtered with the exact keep mask; all 21 surviving
  reads recover their exact original quality lines; removed sources
  absent.
- Queries: `qualityValues` merged + all 10 sources + subset/group/where
  == independently projected rows; `readQuality` /
  `readSequenceAndQuality` / `readFastqData` exact;
  `readsContaining(include_quality=True)` exact.
- Randomized: seed 20260811, 18 cases, 0 mismatches; host differentials,
  seeds 20260811/20260812/20260813, 18 cases, 0 mismatches.

## 7. Test counts

- Python 2: 428 tests (was 408), all green.
- Host: 580 tests (was 566) + 22 subtests, all green.
- Q1 modernization harness: 24 tests, unchanged and green.

## 8. Storage

1 byte/BWT row (B biological bases + R terminal sentinels for a
collection of B+R rows).  This is a correctness/lifecycle baseline, not a
quality-compression algorithm; Q2-style compression is a separate future
direction with Q1 as the stable exact oracle.
