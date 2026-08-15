# ENHANCED-MODERN2 — Feature 12 (executed evidence): Generic BWT-aligned tag arrays

Status date: 2026-08-15

Branch: `enhanced-modern2` (Feature-10 commits `1ad26e6`, `6153291`,
`4e9cc4a`)

This milestone integrates research Feature 12 (candidate authority:
`research/feature-candidates/12/`) as an additive engineering layer.  No
core baseline algorithm, persistent format, or CLI command was modified.

**Verdict: PASS.**  VERIFIED-CORRECT: for any attached tag `T` and every
final BWT row `x`, `T[x]` is the exact value that traveled with `BWT[x]`
from its constituent source row through attach, retrofit, two-way and
balanced merges, source/group-filtered queries, and Feature-10 removal
(`T_reduced == T_original[keep_mask]` element-for-element).

## 1. Public API

New module `MUS/BWTTags.py` (pure Python/NumPy, Python-2.7 compatible):

- `attach_tag(bwt_dir, name, values, description=None,
  missing_value=<unset>, overwrite=False)` — attach/replace one
  row-aligned tag without changing the BWT.
- `remove_tag(bwt_dir, name)` — remove a tag (registry + array).
- `BWTTagStore(bwt_dir, mmap=True, validate=True)` — validated mmap
  access: `list_tags()`, `has_tag(name)`, `schema(name)`, `array(name)`,
  `interval(name, start, end)`, `value_counts(name, start, end)`,
  `release()`.
- `validate_tag_merge_compatibility(left, right)` — pre-merge schema
  preflight returning a merge plan; fails BEFORE the BWT merge on
  one-sided tags without a declared missing value or on incompatible
  schemas.
- `merge_two_tag_arrays(left, right, output, plan=None, chunk_rows=...)`
  — stable-interleave all compatible tags using the exact same
  ``inter0.npy`` bits (out-of-core: mmap inputs, `open_memmap` outputs,
  shared decoded interleave chunks).
- `filter_tag_arrays(input, output, keep_mask, chunk_rows=...)` —
  Feature-10 survival-mask filtering of every tag (chunked).
- `build_tag_from_leaf_arrays(merged_dir, name, arrays_by_source,
  description=None, missing_value=<unset>, overwrite=False,
  chunk_rows=...)` — retrofit one tag onto an already-merged package by
  replaying saved interleaves out-of-core; atomic install; BWT bytes
  unchanged.
- `build_tags_from_leaf_arrays(merged_dir, tags, overwrite=False)`.

Additions to `MUS/MultiSourceProvenance.py`: `merge_two_with_provenance`
runs the tag preflight before the BWT merge and automatically merges tags
afterwards; `merge_many_balanced` inherits both.

Additions to `MUS/MultiSourceQuery.py`:

- `MultiSourceBWT(..., bwt_tags=None)`; `load()` auto-loads the tag
  store when `bwt_tags.json` exists.
- `listTags()`, `tagSchema(name)`, `rowTag(row_index, name)`,
  `tagInterval(name, start, end)` (direct array slice),
  `tagValues(seq, name, source=None, sources=None, group=None, where=None,
  givenRange=None, include_rows=False, max_rows=None)` (whole-collection
  interval is a direct slice; selected sources gather rows through the
  provenance tree), `tagValueCounts(seq, name, ...)` (exact scalar-value
  frequencies; vector tags rejected).

Additions to `MUS/SourceRemoval.py`: `retain_sources` filters every tag
with the exact BWT survival mask; stats add `bwt_tags_preserved` and
`bwt_tag_count`.

New CLI tool: `packages/msbwt-modern2/tools/bwt_tags.py` (`list`,
`validate`, `attach`, `retrofit`, `remove`).

## 2. Persisted files (classification)

- `bwt_tags.json` — AUTHORITATIVE registry: `format`
  (`msbwt-bwt-tags`), `version` (1), and per-tag `filename` (SHA-256
  prefix of the logical name — user-controlled names never become
  filesystem paths), `dtype`, `tail_shape`, `description`, `missing`
  policy.  Written atomically (tmp + fsync + rename).
- `bwt_tags/tag_<hash>.npy` — AUTHORITATIVE row-aligned array; ordinary
  mmap-able `.npy`, no pickle.  `T.shape[0] == msbwt.npy length` exactly
  (validated on every load).
- Stale/corrupt behavior: corrupt registry JSON, missing array file,
  wrong dtype, wrong tail shape, wrong row count, wrong format/version
  all raise `BWTTagError`; `allow_pickle=False` everywhere.
- Deletion semantics: `remove_tag` removes array + registry entry
  (registry deleted when empty); overwrite removes the old array only
  after the new root is fully built (retrofit).
- Relation to other files: tags are BWT-row-aligned only; they never
  affect `provenance.json`, `read_provenance.npy`, or BWT bytes.

## 3. Candidate audit and defects

Candidate files audited: `POINT12_README.md`,
`POINT12_STORAGE_AND_LIFECYCLE_MODEL.json`, `BWTTags.py`,
`MultiSourceProvenance(2).py`, `MultiSourceQuery(6).py`,
`SourceRemoval(1).py`, `bwt_tags.py`, `test_point12_bwt_tags.py`,
`test_point12_integration.py`.  The schema/hash-filename/missing-value
design, the shared-interleave merge, the chunked mask filter, and the
out-of-core retrofit were preserved.

CANDIDATE DEFECTS (fixed in production):

1. Python-2 incompatibilities: `pathlib.Path`,
   `write_text/read_text(encoding=...)`, `os.replace`,
   `bytes.fromhex`, `value.hex()`, `raise ... from exc` — all adapted
   (os.path + atomic-binary-JSON + rename fallback + py2 hex helpers).
   Tag names are normalized to text (unicode on py2, str on py3) so
   registry keys, lookups, and hash filenames are consistent across
   versions.
2. Unicode-path handling: on Python 2 the registry round-trip returns
   unicode `filename` values; `_open_leaf_tag_value` treated unicode as
   an array (0-d string) — fixed to accept unicode paths.
3. Windows mmap-lock hazards: removing or renaming a tag array while a
   `BWTTagStore` still maps it fails on Windows.  Production drops
   memmap references (`release()`, `del` + `gc.collect()`) and uses a
   bounded GC-retry file removal so lifecycle operations work on both
   platforms.

No MODERN2 BASELINE defects discovered.

## 4. Independent oracle

- The strongest row-identity tag `row_id`: `tag[x]` is the independently
  known unique identity of BWT row `x` (`source_order * 10000 +
  local_row`), tracked through merges/removals by direct bit-array
  counting through the verified `unpack_interleave` (never derived from
  the BWTTags implementation).
- Expected merged tag arrays computed by independent suffix sort replay.
- Naive per-row counting for value frequencies; independently projected
  row sets for source/subset/group/where tag selection.

## 5. Deterministic / randomized validation

- 10-source fixture (191 rows): every merged `row_id` value matches the
  independent walk; two-way and balanced merges exact; retrofit equals
  the merge-produced tag element-for-element with BWT bytes unchanged;
  removal `T_reduced == T_original[keep_mask]`; single-source removal
  equals the original leaf array.
- One-sided tags: rejection before the BWT merge without a missing
  value; exact filling of missing-source rows with a declared value;
  incompatible schemas rejected before the merge.
- Query lifecycle: whole-index interval == `T[l:r]`; source/subset/
  group/where selection == projected rows; `tagValueCounts` == naive
  counting; vector-tag counts rejected; missing-tag-layer and row-bound
  errors.
- Dtype/shape policy: object/structured rejected; bool/int/float/S
  dtypes, vector tags `(N,k)`, mmap loading, hash filenames for
  `/`, `\`, `..`, spaces, unicode names; NUL rejected.
- Randomized: seed 20260811, 18 cases (random tagged merges + removals),
  0 mismatches; host differentials, seeds 20260811/20260812/20260813,
  18 cases, 0 mismatches.

## 6. Test counts

- Python 2: 408 tests (was 378), all green.
- Host: 566 tests (was 551) + 22 subtests, all green.
- Q1 modernization harness: 24 tests, unchanged and green.

## 7. Notes for downstream features

- Q1 (quality sidecar) is implemented as a specialization of this
  layer; LCP (11A) reuses these lifecycle conventions for its own
  adjacency semantics (LCP is NOT an ordinary row tag).
- Out-of-core claims are honored: merge/retrofit/filter use mmap inputs
  and `open_memmap` outputs with bounded chunks; final arrays remain
  ordinary mmap-able `.npy` files.
