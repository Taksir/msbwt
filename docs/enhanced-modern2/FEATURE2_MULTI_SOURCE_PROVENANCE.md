# ENHANCED-MODERN2 — Feature 2 (executed evidence): Persistent multi-source provenance / source indexing

Status date: 2026-08-11

Branch: `enhanced-modern2` (descends from the modern2 release baseline
`370c726`; Feature-1 commits `a4c34c3`, `bbe467b`, `25102b4`)

This milestone integrates research Feature 2 (candidate authority:
`research/feature-candidates/2/`) into the published `msbwt-modern2`
baseline as a purely additive, pure-Python layer.  No core baseline
algorithm, persistent format, or CLI command was modified, and no
Feature-1 code was changed.

**Verdict: PASS.**  The Feature-2 claim is VERIFIED-CORRECT: multi-stage
merges of real `GenericMerge.mergeTwoMSBWTs` outputs preserve the identity
of every ORIGINAL source through arbitrary merge-tree shapes (balanced and
unbalanced), the persisted provenance survives save/reload, a stale or
corrupt provenance file can never silently produce a wrong source
assignment, and the two-source behavior agrees with the Feature-1
`inter0.npy` interpretation at every row and in every per-query count.

Executed scope: 44 randomized datasets (40 with 3-8 sources + 4 explicit
10-source, seed `20260811`) plus 6 deterministic multi-stage cases plus 12
edge classes — 252 real merges, every constituent BWT recovered bit-for-bit,
independent rotation-sort oracle exact on every unambiguous row and tied
blocks by per-source multiplicity, 0 mismatches.

## 1. Feature claim

Feature 1 established two-source provenance: `GenericMerge` leaves
`inter0.npy`, a bitvector aligned with the merged BWT rows (bit 0 → left
input, bit 1 → right input, packed little-endian per byte).  Feature 2
generalizes this to any number of original input sources by composing the
repository's existing two-way merge into multi-stage trees and persisting
every per-merge interleave together with a provenance manifest:

    A --\
         AB --\
    B --/      \
                ABCD
    C --\      /
         CD --/
    D --/

Every BWT row has exactly one source label (the original leaf identity).
For a merged MSBWT built from source collections S0..S(k-1):

    number_of_provenance_rows == len(merged BWT)
    count(rows with provenance == s) == len(standalone BWT for source s)
    sum_s source_row_count[s] == len(merged BWT)

Duplicate reads and repeated strings are preserved: provenance is attached
to rows, and a row's label survives every merge stage because each merge
level's interleave records which child supplied each row.

Feature 2 does NOT implement query-by-source semantics.  Feature 3 is the
query layer; this milestone exposes only the provenance/index API Feature 3
needs.  `extract_constituent_bwt` is a correctness/regression oracle (it
materializes a whole constituent BWT); Feature 3 will project query
intervals with rank instead.

## 2. Source-ID semantics

- Source identity is a **stable string ID** (candidate semantics, preserved
  as sound).  IDs are user-specified at leaf initialization
  (`initialize_leaf_provenance(source_id=...)` or `merge_many_balanced(
  source_ids=[...])` in input order), or a generated UUID when omitted.
  ASCII ids are recommended (stored verbatim in the JSON manifest).
- IDs are assigned by **user-specified input order** at the leaf level;
  the manifest `sources` table preserves left-to-right leaf order through
  every merge and is the authoritative identity record.
- IDs are **stable within the built index and across save/reload**
  (tested); rebuilding with the same explicit `source_ids` reproduces the
  same IDs.  Internal merge-node UUIDs are file names only and carry no
  identity semantics.
- Optional human-readable **source names** are a display label that
  defaults to the ID; the ID remains the authoritative identity (names are
  never the identity key).
- Duplicate IDs across inputs are rejected BEFORE any merge runs
  (tested: the merge function is not called).

## 3. Provenance persistence

A standalone leaf gets `provenance.json` (stable identity + BWT digest).  A
multi-merged package contains:

    msbwt.npy                        baseline authoritative merged BWT
    inter0.npy                       baseline authoritative root interleave
                                     (Feature-1 compatible, unchanged)
    provenance.json                  AUTHORITATIVE manifest
    provenance/interleaves/<uuid>.npy  AUTHORITATIVE interleave copies
                                     (one per internal merge node)

The final package copies every internal interleave, so constituent identity
does not depend on keeping intermediate merge directories (tested: deleting
all originals and intermediates, then extracting every constituent exactly).

Manifest schema (version 1, `format: "msbwt-multisource-provenance"`):

| field | type | meaning |
|---|---|---|
| `format` | str | format name |
| `version` | int | 1 |
| `bwt_length` | int | merged BWT row count |
| `msbwt_sha256` | S64 hex | sha256 of the merged `msbwt.npy` array bytes (identity) |
| `sources` | list | source records, left-to-right leaf order |
| `root` | node | provenance tree |

Source record: `id` (stable string), `name` (display label), `length`
(standalone BWT rows), `bwt_sha256` (sha256 of the original standalone BWT
array bytes; verified when the manifest's root is a leaf, recorded for
merged trees).

Merge node: `type: "merge"`, `node_id` (UUID file name), `length`
(== left.length + right.length), `interleave` (relative path into
`provenance/interleaves/`), `interleave_sha256` (sha256 of the stored
interleave array bytes), `left`, `right` (child nodes).  Leaf node:
`type: "leaf"`, `source_id`, `length`.

## 4. Merge-tree propagation

Provenance propagates through ANY binary tree of two-way merges.  At each
merge, the root node's interleave records which child supplied each row;
`extract_constituent_bwt` filters the final BWT down through the tree using
the saved interleaves.  Correctness never depends on the tree being
balanced:

- balanced (`merge_many_balanced`, ~`k -> k/2 -> ... -> 1`, source path
  depth O(log k)); for 8 sources: depth 3; for 10 sources: depth 4;
- unbalanced chains `((A+B)+C)+D` (repeated `merge_two_with_provenance`),
  depth k-1.

Both shapes were executed with REAL `GenericMerge` merges, and every
original source BWT was recovered bit-for-bit from the final package
(3-source chain, 4-source balanced, 4-source unbalanced, 5-source balanced,
10-source balanced).  The final labels refer to ORIGINAL sources, never to
the immediate merge children.

## 5. Relation to Feature 1

- `inter0.npy` at the package root is untouched; `MUS.SourceIndex` reads it
  exactly as before (no change to `SourceIndex.py` or its four public
  symbols).
- For a two-source merge the Feature-2 root interleave copy is byte-identical
  to `inter0.npy`, and the Feature-2 row labels equal Feature-1
  `source_at(row)` at EVERY row (48/48 for the canonical merge); every
  canonical query splits identically per source (49 queries, 0 mismatches;
  `countOccurrencesBySource` vs Feature-2 interval counting vs standalone
  BWT counts).
- Architecturally there is ONE provenance system: `inter0.npy` semantics
  are shared; Feature 2 keeps the root interleave in place and stores
  additional per-merge interleaves beside it.  No duplicated source-index
  logic was introduced.
- Feature 1's evidence numbers are unchanged by this milestone (canonical
  oracle: 30 exact rows / 18 tied rows / 24+24 totals, identical to the
  committed Feature-1 record).

## 6. Authoritative vs derived files

- `provenance.json` — **AUTHORITATIVE**.  It is the only record of source
  identity and merge-tree structure.  It is written atomically (tmp file →
  flush → fsync → rename) and validated on every load.
- `provenance/interleaves/*.npy` — **AUTHORITATIVE** within the package:
  the only copies of intermediate per-merge interleaves; needed to recover
  constituents; not rebuildable from inside the package alone.
- `msbwt.npy`, `inter0.npy` — baseline authoritative (unchanged).
- Feature 2 introduces **no derived/cache files**: there is no equivalent
  of Feature 1's rebuildable `inter0_rank.npz`; every Feature-2 file is
  validated with content digests on load, and any inconsistency raises
  `ProvenanceError` (loud failure, never silent).

## 7. Corruption / staleness behavior

A stale or corrupt provenance file can NEVER silently produce a wrong
source assignment.  `validate_manifest` (run on every `load_manifest` by
default) rejects:

- non-JSON / truncated `provenance.json` (wrapped as `ProvenanceError`);
- wrong `format` or unsupported `version`;
- missing identity fields (`msbwt_sha256`, `bwt_sha256`,
  `interleave_sha256`) — pre-digest manifests are unsupported;
- `bwt_length` mismatch with `msbwt.npy`;
- **same-length replaced `msbwt.npy`** (content digest mismatch) — the
  mandatory same-length-replacement case, executed;
- **manifest copied from another index** (digest mismatch), executed;
- **same-length same-count replaced interleave** (digest mismatch; the
  count check alone cannot catch a rearrangement), executed;
- wrong-dtype / multi-dimensional / too-short interleave arrays;
- missing interleave files;
- merge-node length != child total; interleave zero/one counts != child
  lengths; duplicate source IDs; source-table/leaf-order disagreement.

Interleave-copy collisions (UUID namespace) require byte-identical content
or fail loudly (digest equality, not mere size).

## 8. Atomic persistence

`save_manifest` writes to `<manifest>.tmp`, flushes, fsyncs (best effort),
then atomically renames over the final file (`os.replace` on Python 3,
`os.rename` on Python 2 — both atomic on the same POSIX filesystem).  A
half-written authoritative manifest is never left looking valid.  Executed
probe: repeated saves produce byte-identical manifests and leave no
`.tmp` files.

## 9. Python-2 compatibility

The module runs under CPython 2.7.18 / NumPy 1.16.6 (verified) and Python 3
(host tests).  Candidate adaptations (semantics unchanged):

- `pathlib` → `os.path` helpers (Path type absent in Python 2.7);
- `os.replace` → guarded `hasattr(os, "replace")` with `os.rename` fallback
  (atomic on POSIX);
- `os.fsencode` → guarded `hasattr(os, "fsencode")` (Python 2 `str` is
  already bytes);
- `open(..., encoding=...)` → binary-mode JSON I/O: `json.dumps` with
  `ensure_ascii` escapes produces pure-ASCII bytes written/read in `"wb"` /
  `"rb"` mode on both versions;
- Cython keyword rejection: the adapter retries the positional
  `mergeTwoMSBWTs(dir1, dir2, out, numProcs, logger)` signature on an
  argument-signature `TypeError` only (`takes no keyword arguments` under
  Python 2); non-signature `TypeError`s propagate;
- no f-strings, annotations, dataclasses, or keyword-only arguments.

The whole file clears the baseline py3-syntax scan
(`test_modern2_bootstrap.py::test_no_python3_only_runtime_syntax`).

## 10. Independent oracle

For uniform-route inputs the row labels produced from the persisted
interleave tree are compared against a fully independent source-tagged
rotation oracle:

- every rotation of every read (with the `$` terminator) is generated and
  tagged with its source;
- rotations are sorted in the **circular order** used by the merged BWT
  (comparison wraps around the end of each rotation; this matters when
  rotations of different-length reads share a prefix — a plain string sort
  disagrees with the real merge order, which was discovered and corrected
  during this milestone);
- blocks are circular-equivalence classes: a class belonging to exactly one
  source must label every row in its block with that source (exact rows);
  classes shared by several sources are order-ambiguous by design and are
  verified by per-source multiplicity inside the block.

Order-independent oracles run for every case (uniform and nonuniform):
per-symbol joint provenance counts (rows labeled s with symbol c ==
standalone s's count of c), LF-recovered read multiset == union read
multiset, per-source totals == standalone BWT lengths, and bit-for-bit
constituent extraction vs the standalone `msbwt.npy` files.

Executed oracle results: canonical 2-source 30 exact / 18 tied; 3-source
chain 57 / 18; 4-source balanced 66 / 36; 4-source unbalanced 110 / 0;
5-source balanced 108 / 18; 10-source balanced 230 / 45; edge classes
111 / 24 across the 4 oracle-applicable classes.

## 11. Randomized validation

40 deterministic random datasets (seed `20260811`, source counts 3-8) plus
4 explicit 10-source datasets (seed `20260811 + 1000`): REAL standalone
construction (`pp` + `cfpp`), REAL `GenericMerge` merges via
`merge_many_balanced` (34 datasets) and unbalanced chains (10 datasets).
Every dataset records seed, source count, reads per source, merge tree,
final BWT length, expected and observed per-source totals, reload status,
and mismatches.  Totals: 44 datasets, 0 mismatches, all reloads OK.

## 12. Performance / storage sanity (pinned py2 profile)

- canonical 2-source package (48 rows): `provenance.json` 983 B,
  interleaves 135 B → 23.29 B/row metadata; load 1.6 ms; validate 1.4 ms;
  one-constituent extraction 1.8 ms.
- 10-source package (275 rows): provenance 5,874 B, interleaves 1,277 B →
  29.34 B/row for the full package (8,069 B total).
- Costs are O(rows × depth) for extraction/validation; digests are computed
  once per manifest write.  No Cython/SIMD backends were added (Feature 13
  owns the whole-index benchmark contract).

## 13. Limitations

- Provenance packages must be built through the Feature-2 API so manifests
  and interleave copies exist; a bare `GenericMerge` output has
  two-source provenance only (Feature 1).
- Tied rows (identical rotations in several sources) have an
  order-ambiguous internal arrangement; per-source counts/extraction remain
  exact because they depend only on multiplicities.
- Zero-length BWTs are not supported by the underlying merge and are not
  exercised.
- `validate_manifest` and `extract_constituent_bwt` are O(rows × depth);
  for very large indexes they are validation/regression tools, not the
  Feature-3 query path.
- The rotation oracle applies to uniform-route inputs; nonuniform inputs
  are covered by the order-independent oracles and exact extraction.
- Digest computation reads each BWT/interleave once (O(n)); documented as
  the price of stale-data safety.

## 14. Defect classification

Two CANDIDATE DEFECTS were found and fixed in the Feature-2 layer (both
research-prototype weaknesses, not MODERN2 DEFECTS):

1. **No content identity in the candidate format**: a same-length replaced
   `msbwt.npy`, a manifest copied from another index, or a same-length
   same-count replaced interleave could pass the candidate's validation
   silently.  Fixed with sha256 digests (`msbwt_sha256`,
   `interleave_sha256`, per-source `bwt_sha256`); all mandatory probes
   executed and detected.
2. **Interleave-copy collision guard compared only file sizes**: a
   same-size different-content collision would silently reuse the existing
   file.  Fixed with digest equality.
3. **Oracle order bug (test-side, fixed in this milestone's own
   validation)**: the initial rotation oracle sorted rotation strings
   plainly; rotations of different-length reads that share a prefix sort
   differently under the circular order the merged BWT actually uses.
   The oracle now sorts circularly and groups by circular-equivalence
   class; all 252 real merges verify with 0 mismatches.

Python-2 adaptation items (pathlib, os.replace, os.fsencode,
open(encoding=), Cython keyword rejection) are mechanical adaptations, not
semantic changes.

## 15. Files added

- `packages/msbwt-modern2/MUS/MultiSourceProvenance.py` — production
  module (pure Python, additive).
- `packages/msbwt-modern2/tests/test_multisource_provenance_py2.py` —
  Python-2 suite (39 tests).
- `compat/tests/test_multisource_provenance.py` — host suite (46 tests,
  incl. evidence-record consistency).
- `packages/msbwt-modern2/validate/feature2-multi-source-provenance.sh` —
  validation driver.
- `packages/msbwt-modern2/validate/feature2_multi_source_evidence.py` —
  evidence generator.
- `packages/msbwt-modern2/evidence/feature2-multi-source-provenance.json` —
  executed evidence record.
- `docs/enhanced-modern2/FEATURE2_MULTI_SOURCE_PROVENANCE.md` — this
  document; `docs/enhanced-modern2/README.md` updated (feature index).

Changed: none in baseline production code, none in Feature-1 code.
`git diff --check` clean.

## 16. Verification gates (all executed)

- full modern2 Python-2 suite (incl. Feature-1 and Feature-2): OK;
- host compat suite: 415 tests OK (includes the baseline py3-syntax scan
  over all `MUS/*.py`);
- fixture hashes (`uniform-a.fastq`, `uniform-b.fastq`): OK;
- frozen-source gate (`verify_frozen_source.py`): OK;
- full Q1 randomized rerun NOT required: Feature 2 adds only additive
  pure-Python modules and does not alter baseline
  merge/FM/construction/compression/decompression code (documented
  condition in section 23 of the milestone brief).

## 17. Semantic contract for modern3

modern3 must preserve: the `MUS.MultiSourceProvenance` public API; the
`provenance.json` v1 schema (including the identity digests); the
`provenance/interleaves` layout; `inter0.npy` semantics (bit 0 → left,
bit 1 → right, little-endian packing, row-aligned); the mathematical
source-count invariants; the authoritative/digest validation rule (a stale
or corrupt provenance file must fail loudly, never silently assign wrong
sources); atomic manifest writes; and the Feature-1 four-symbol API
(`TwoSourceInterleaveIndex`, `TwoSourceBWT`, `countOccurrencesBySource`,
`count_occurrences_by_source`).  Feature 3 must consume this tree via rank
projection without materializing constituent BWTs.
