# ENHANCED-MODERN2 — Feature 1 (executed evidence): Two-source rank-aware queries

Status date: 2026-08-11

Branch: `enhanced-modern2` (descends from the modern2 release baseline
`370c726`)

This milestone integrates research Feature 1 into the published
`msbwt-modern2` baseline as a purely additive, pure-Python layer.  No core
baseline algorithm, persistent format, or CLI command was modified.

**Verdict: PASS.**  The Feature-1 claim is VERIFIED-CORRECT: for every query
Q against a real two-way `GenericMerge` output,

    count_source0(Q) == standalone_A.countOccurrencesOfSeq(Q)
    count_source1(Q) == standalone_B.countOccurrencesOfSeq(Q)
    count_source0(Q) + count_source1(Q) == merged.countOccurrencesOfSeq(Q)

holds across the canonical fixtures, a 12-class deterministic edge corpus,
and a 50-case deterministic randomized suite (seed `20260811`) — 63 source
pairs, 9,320 queries, 27,960 comparisons, zero mismatches.  Provenance bits
were verified against an independent rotation-sort oracle (every
unambiguous bit exact; tied blocks by per-source multiplicity), and the
rank cache identity mechanism provably detects a same-length replaced
`inter0.npy` (never serves stale counts).

## 1. Purpose

`GenericMerge.mergeTwoMSBWTs` retains `inter0.npy` in the merged BWT
directory.  It is a bitvector aligned with the merged BWT rows recording,
for every merged row, which input BWT supplied that row's symbol.  Feature 1
adds source-aware queries: one merged FM search per query, then rank over
the provenance bitvector to split the merged interval into per-source
counts.  Standalone source BWTs are oracles for testing only — they are
never queried at runtime.

## 2. Provenance semantics (established from code + execution)

From `packages/msbwt-modern2/MUSCython/GenericMerge.pyx` (unchanged frozen
semantics, migrated with `language_level=2` only):

- `setBit_p` / `getBit_p` pack bits **little-endian within each byte**:
  `bit i within byte = 1 << (i & 7)` (lines 575–585).
- `interleaveTwoBwts` reads the bit at merged row `x` to choose the symbol:
  bit 1 → second input BWT, bit 0 → first input BWT (lines 202–217).
  Therefore **bit position x corresponds to merged BWT row x**, and
  **bit 0 → first input, bit 1 → second input**.
- The byte capacity is `(bwtLen1 + bwtLen2) / 8 + 1`; the final byte may
  contain padding bits.  Padding bits are initialized to 1 and are never
  touched by the merge iterations (all writes stay below `bwtLen`), but
  Feature 1 never reads them: the valid bit count always comes from the
  merged `msbwt.npy` length.

Independent reconstruction (canonical uniform merge, `compat/tools/
bwt_oracle.py` + the Feature-1 evidence generator): the merged `msbwt.npy`
is byte-identical to the rotation-sort of the union read multiset; every
one of the 30 unambiguous rows matched the predicted source bit exactly
(0 mismatches); the 18 tied rows (identical reads present in both sources)
contain exactly the predicted per-source multiplicity; per-source totals
equal the standalone BWT lengths (24 + 24).  Row alignment is additionally
confirmed by the merged row symbols matching the rotation-order prediction
at every position (0 mismatches).

## 3. Mathematical invariant

For a merged BWT that is the BWT of the union read multiset (verified for
modern2 merges) with row provenance `bit(x)` ∈ {0, 1}:

    rank_source(s, l, h) = #{ x in [l, h) : bit(x) == s }

and for `[l, h) = merged.findIndicesOfStr(Q)`:

    rank_source(0, l, h) == count of Q in source 0
    rank_source(1, l, h) == count of Q in source 1
    (h - l) == merged total count of Q

Each merged row belongs to exactly one read, hence exactly one source, so
counting rows by provenance within the FM interval counts occurrences per
source.  Tied rows (identical reads in both sources) can be interleaved
arbitrarily by the merge; rank counts are unaffected because the per-source
multiplicity is what is counted.

## 4. Public API (`MUS.SourceIndex`, pure Python, no new Cython)

    from MUS.SourceIndex import TwoSourceBWT

    merged = TwoSourceBWT.load(merged_dir, source_names=("sample-A", "sample-B"))
    result = merged.countOccurrencesBySource("ACGT")
    # {"sequence": b"ACGT", "interval": (l, h), "total": h-l,
    #  "sample-A": n0, "sample-B": n1}

Public surface (all four retained from the candidate):

- `TwoSourceInterleaveIndex` — rank/access over packed `inter0.npy`
  (`from_directory`, `rank1`, `rank0`, `source_at`, `counts`,
  `count_source`, `save_rank_index`).
- `TwoSourceBWT` — merged-BWT wrapper (`load`, `findIndicesOfStr`,
  `countOccurrencesOfSeq`, `countOccurrencesBySource`).
- `countOccurrencesBySource(msbwt, source_index, seq, ...)` — functional
  API.
- `count_occurrences_by_source` — snake_case alias.

`countOccurrencesBySource` performs exactly **one** `findIndicesOfStr` call
(verified with an instrumented real ByteBWT: 4 queries → 4 calls) and never
queries standalone BWTs.  The `givenRange` parameter is delegated verbatim
to the legacy `findIndicesOfStr`, preserving its exact semantics
(`givenRange` is the FM interval of the already-searched suffix; verified:
`findIndicesOfStr('G', givenRange=interval('T')) == findIndicesOfStr('GT')`
and Feature-1 returns the same interval and the correct source split).

The default `rank_stride_bytes = 64` samples one uint64 rank count every 64
packed bytes: `rank1` is O(stride) popcount-table tail + O(1) prefix lookup;
`counts` is two rank queries; storage is `ceil(bytes/64)+1` uint64 values.

## 5. Sequence normalization contract (Python-2 explicit)

The legacy MSBWT query API expects byte strings.  `_normalize_sequence`
defines, without silent encoding surprises:

- `bytes` — returned unchanged (in Python 2, `str` is `bytes`);
- `str` (Python 3) / `unicode` (Python 2) — encoded ASCII; non-ASCII raises
  `UnicodeEncodeError`;
- anything else — `TypeError`.

Verified identically under CPython 2.7.18 and Python 3.

## 6. Cache semantics (`inter0_rank.npz`)

`inter0_rank.npz` is **DERIVED / REBUILDABLE** data.  Deleting it never
destroys information; it rebuilds deterministically from `inter0.npy` plus
the merged BWT length.  Schema (uncompressed zip of .npy members):

| field | dtype | meaning |
|---|---|---|
| `rank_prefix` | uint64[n_blocks+1] | sampled source-1 counts at block boundaries |
| `total_bits` | uint64 | valid row count (merged BWT length) |
| `rank_stride_bytes` | uint64 | sampling stride |
| `inter0_sha256` | S64 hex | content digest of the full stored `inter0.npy` array (cache identity) |
| `inter0_total_ones` | uint64 | total 1 bits over the valid storage bytes (identity + prefix consistency) |

A saved cache is used only when ALL of the following hold, otherwise it is
silently rebuilt (never used to return wrong counts):

1. `total_bits` matches the merged BWT length;
2. `rank_stride_bytes` matches the request;
3. `inter0_sha256` equals the digest of the current `inter0.npy` content —
   this detects a **replaced or modified `inter0.npy` with the same byte
   length** and a **stale cache transplanted from another merge of the same
   size** (both tested, mandatory same-length-replacement case included);
4. `inter0_total_ones` matches the recomputed 1-bit count;
5. the prefix is internally consistent (`prefix[0] == 0`, nondecreasing,
   `prefix[-1] == inter0_total_ones`).

Corrupt, truncated, or incompatible caches (including pre-identity
candidate-era caches without the digest fields) fall back to a rebuild.
The identity mechanism is a small deterministic content digest — no complex
format was introduced.

## 7. Validation / oracle methodology

Three layers, all executed:

1. **Independent rank oracle** (host + py2): unpack valid bits explicitly,
   `rank1(pos) = sum(bits[:pos])`; `source_at` / `rank1` / `rank0` /
   `counts` / `count_source` validated at EVERY position for 0, 1, 8, 9,
   63/64/65-bit vectors, multiple rank blocks, all-zero, all-one,
   alternating, random vectors, and padding bits deliberately set to 1 —
   plus 200 randomized vectors in the host suite.
2. **Real-merge differential**: 63 source pairs (canonical fixtures +
   12-class edge corpus + 50 randomized, seed `20260811`) built with the
   real modern2 CLI (`pp`/`cfpp`, uniform and nonuniform routes) and merged
   with the real `GenericMerge`; every query compared four ways (Feature-1
   source0, source1, sum, legacy merged count).  Edge classes: unequal
   sizes, duplicates inside A/B, same reads in both, all-identical,
   prefix-sharing, suffix-sharing, N-heavy, single-base, mixed lengths,
   repeated motifs, lexicographically similar.  Queries: single symbols
   including `$`, short and longer present queries, absent queries,
   only-A / only-B / both queries, $-adjacent strings, all read substrings.
   Any mismatch is dumped with seed, reads, query, interval, provenance
   bits, and expected/observed counts.
3. **Provenance bit oracles per case**: for uniform-route inputs the
   rotation-sort block oracle is applied (every unambiguous bit exact, tied
   blocks by multiplicity); for nonuniform inputs (documented
   different-but-valid ordering) the order-independent oracles apply:
   per-symbol joint provenance counts equal to the standalone symbol
   counts, LF-recovered read multiset equal to the union, and per-source
   totals equal to the standalone BWT lengths.

## 8. Python-2 compatibility

The module runs under CPython 2.7.18 / NumPy 1.16.6 (verified) and Python 3
(host tests).  Audited items: `np.load(..., allow_pickle=False)` (supported
since NumPy 1.16.3), `np.savez`, `np.uint64`/`np.uint8` handling,
`zipfile.BadZipFile` vs `BadZipfile` version difference (both handled),
integer floor division (`//`), memmap reads, exception types, `os.path`
behavior.  No f-strings, no annotations, no keyword-only arguments.

## 9. Measured complexity / performance sanity

On the pinned profile (WSL2 reference host, Python 2.7.18):

- canonical merged index (48 rows): `rank1` ≈ 6.9 µs, `counts` ≈ 9.4 µs;
- synthetic 1 Mbit provenance: `rank1` ≈ 0.96 µs per query, rank prefix
  storage ≈ 16 KB (one uint64 per 64 packed bytes).

No popcount/SIMD/Cython backends were added (future optimization
possibilities only).

## 10. Safety / validation

- `TwoSourceBWT` rejects a BWT whose row count differs from
  `source_index.total_bits`.
- `TwoSourceInterleaveIndex` rejects wrong dtype, wrong dimensions, an
  interleave shorter than `ceil(total_bits/8)`, negative `total_bits`,
  non-positive stride, out-of-range positions/intervals, and invalid source
  ids; malformed `msbwt.npy` / `inter0.npy` files fail loudly.
- Longer byte capacity with valid padding is accepted; padding bits never
  affect any rank result.
- Baseline compatibility is untouched: the full modern2 Python-2 suite
  (167 tests), the host compat suite, the Q1 audit harness suite, fixture
  and frozen-source gates all pass; `git diff --check` is clean.  The full
  Q1 randomized rerun is NOT required (additive pure-Python change only;
  no baseline algorithm was modified).

## 11. Defect classification

No production defect was found in the candidate's core rank algorithm (its
unit tests all pass).  One CANDIDATE DEFECT was found and fixed in the
Feature-1 layer itself:

- **CANDIDATE DEFECT — stale cache undetected**: the candidate's
  `inter0_rank.npz` carried only `rank_prefix` / `total_bits` /
  `rank_stride_bytes`, so a replaced or modified `inter0.npy` with the same
  length (or a cache transplanted from another same-size merge) would
  silently serve stale source counts.  Fixed with the content-digest +
  total-ones identity described in section 6; the mandatory
  same-length-replacement test and cross-merge transplant test pass.
  Classification: CANDIDATE DEFECT (research prototype weakness), not a
  MODERN2 DEFECT.

One test-authoring error was corrected in this milestone's own tests (an
incorrect expected count), and the rotation-sort bit oracle was restricted
to uniform-route inputs after the evidence run showed nonuniform-route
BWTs use the documented different-but-valid ordering (the order-independent
oracles above cover them).

## 12. Limitations

- The merged BWT must be a two-way `GenericMerge` output (uniform or
  nonuniform inputs); `inter0.npy` must exist.  Multi-way merges are a
  different feature.
- Tied blocks (identical reads in both sources) have an
  order-ambiguous internal arrangement by the merge design; per-source
  counts remain exact because they depend only on multiplicities.
- The rotation-sort bit oracle applies only to uniform-route inputs;
  nonuniform inputs are covered by the order-independent oracles.
- Performance numbers are sanity measurements on the reference profile,
  not a benchmark.
- `inter0_rank.npz` is derived data; it is not part of the authoritative
  MSBWT format.

## 13. Files added/changed

Added:

- `packages/msbwt-modern2/MUS/SourceIndex.py` — production module.
- `packages/msbwt-modern2/tests/test_source_index_py2.py` — Python-2 suite
  (34 tests).
- `compat/tests/test_feature1_source_index.py` — host suite (73 tests).
- `packages/msbwt-modern2/validate/feature1-two-source-rank.sh` —
  validation driver.
- `packages/msbwt-modern2/validate/feature1_two_source_evidence.py` —
  evidence generator.
- `packages/msbwt-modern2/evidence/feature1-two-source-rank.json` —
  executed evidence record.
- `docs/enhanced-modern2/README.md` — feature index.
- `docs/enhanced-modern2/FEATURE1_TWO_SOURCE_RANK.md` — this document.

Changed: none in baseline production code.  `git diff --check` clean.

## 14. Semantic contract for modern3

modern3 must preserve: `MUS.SourceIndex` public API (the four symbols
above), the `inter0.npy` provenance semantics (bit 0 → first input, bit 1 →
second input, little-endian byte packing, row-aligned), the mathematical
source-count invariants, one merged FM search per source-aware query, and
the derived-cache safety rule (a stale `inter0_rank.npz` must never
silently produce wrong source counts — rebuild instead).
