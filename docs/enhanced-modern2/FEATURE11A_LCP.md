# ENHANCED-MODERN2 — Feature 11A (executed evidence): Exact post-construction LCP retrofit

Status date: 2026-08-15

Branch: `enhanced-modern2` (Q1 commits `0afc94f`, `7c240cd`, `8ed9ac1`)

This milestone integrates research Feature 11A (candidate authority:
`research/feature-candidates/11A/`) as an additive layer.  No core baseline
algorithm, persistent format, or CLI command was modified.  11B (LCP-
preserving removal), 11C (RMQ/applications), and merge-time LCP
construction are NOT implemented.

**Verdict: PASS.**  VERIFIED-CORRECT: for the 10-source fixture every
adjacent LCP boundary (190/190) equals the independent explicit-suffix
oracle with distinct-virtual-terminator semantics (duplicate reads never
gain an extra terminator symbol; two terminal suffixes have LCP 0), the
BWT is never rebuilt or re-merged (no FASTQ required), and adding LCP
changes no BWT / provenance / Point-12 tag / Q1 quality bytes.

## 1. Public API

New module `MUS/LCP.py` (pure Python/NumPy, Python-2.7 compatible):

- `construct_lcp_from_bwt(bwt_dir, bwt=None, overwrite=False, mmap=True,
  temp_parent=None, validate=True)` — exact post-construction LCP:
  recover every read through the existing BWT API
  (`recoverString(dollar_id, withIndex=True)`), induce generalized suffix
  coordinates (O(N) temporary mmap arrays), generalized Kasai pass,
  atomic install of `lcps.npy` + `lcp.json`.  No FASTQ, no BWT rebuild,
  no re-merge.
- `validate_lcp(bwt_dir, full=True)` — length, unsigned dtype, metadata
  row/read/array counts, max-LCP consistency, LCP <= max read length,
  zero terminator-prefix boundaries, and the BWT identity binding.
- `load_lcp_metadata(bwt_dir)`, `lcp_exists(bwt_dir)`.
- `LCPIndex(bwt_dir, mmap=True, validate=True)` —
  `adjacent(left_row)` (stored convention), `boundary(row)` (canonical
  `LCP[0] = 0`), `between_rows(left, right)` (RMQ identity
  `min(lcps[i:j])`, direct minimum scan), `max_lcp`, `read_count`.

Additions to `MUS/MultiSourceQuery.py`:

- `MultiSourceBWT(..., lcp_index=None)`; `load()` auto-loads the LCP
  index when present.
- `hasLCP()`, `lcpAt(row)`, `lcpAdjacent(left_row)`,
  `lcpBetweenRows(left_row, right_row)`.

Additions to `MUS/SourceRemoval.py`:

- `retain_sources(..., drop_lcp=False)` / `remove_sources(...,
  drop_lcp=False)`: an LCP layer is adjacency data and cannot be filtered
  row-for-row, so removal from an LCP-enabled input FAILS with an
  explicit Feature-11B message unless `drop_lcp=True` explicitly requests
  a reduced package without the LCP layer.

New CLI tools: `tools/lcp.py` (`construct`, `validate`, `inspect`);
`tools/remove_sources.py` gains `--drop-lcp`.

## 2. Persisted files (classification)

- `lcps.npy` — AUTHORITATIVE adjacency array: length `N - 1`,
  `lcps[i] = LCP(SA[i], SA[i+1])` (the upstream Holt loader already
  consumes this filename), uint32 unless a read length requires uint64,
  ordinary mmap-able `.npy`.  Installed atomically (array then metadata);
  a partial install is removed on failure.
- `lcp.json` — AUTHORITATIVE metadata: format/version/algorithm, array
  dtype/length, BWT row count, read count, max read length, max LCP,
  terminator semantics (`virtual-distinct-ordered-dollar-excluded-from-
  lcp`), stored/canonical conventions, construction info, and `bwt_sha256`
  (the validated manifest digest of the current BWT, so a same-length
  replaced BWT or a copied stale layer is always rejected).
- No parallel `lcp.npy` is written.

## 3. Algorithm

1. For every dollar ID: `recoverString(dollar_id, withIndex=True)` with
   strict validation (recovery begins with `$`, terminal row == dollar
   ID, no boundary crossing, every BWT row assigned to exactly one read
   cycle, full permutation coverage).
2. Generalized suffix coordinates: concatenated read text with byte 0 as
   a virtual distinct terminator per read (never counted as an LCP
   symbol), with `sa_coord[row]` and `rank_by_coord[coord]` mmap arrays.
3. Generalized Kasai scan with `h` reset at every read boundary.

Complexity (honest): O(N) time with O(N) temporary working disk;
resident RAM dominated by one recovered read plus OS page cache.  This
baseline is the exact oracle for any later succinct BWT-only
construction.

## 4. Candidate audit and defects

Candidate files audited: `POINT11A_LCP_README.md`, `LCP.py`,
`test_point11a_lcp.py`, `test_point11a_integration.py`.  The convention,
terminator semantics, generalized-Kasai design, and validation invariants
were preserved.

CANDIDATE DEFECTS (fixed in production):

1. Python-2 incompatibilities: `pathlib.Path`, `write_text(encoding=...)`,
   `os.replace`, `time.perf_counter` (py2.7 lacks it), `raise ... from`
   — adapted (os.path, atomic-binary-JSON, rename fallback, monotonic
   helper, plain raise).
2. Python-2 str/bytes traps: `sequence[0] != ord("$")` never matched on
   py2 (1-char strings) and `text[coord] = bases[pos]` assigned a string
   to a uint8 array — fixed with byte-value helpers.
3. Missing BWT identity binding: the candidate's `lcp.json` could not
   reject a same-length replaced BWT (only row/read counts were bound).
   Production binds `bwt_sha256` to the validated manifest digest, so a
   stale/copied LCP layer always fails loudly.

No MODERN2 BASELINE defects discovered.  The legacy compiled loader
(`ByteBWTCython`/`LZW_BWTCython`) already consumes `lcps.npy` when
present, confirming format compatibility.

## 5. Independent oracle

For every adjacent pair of explicitly sorted suffix rows, the LCP is
computed character-by-character and stops before the terminator.  Every
stored boundary is compared — no aggregates.  The merged suffix order is
the fixture's own sorted rows (stable-merge semantics), so the oracle is
fully independent of the generalized-Kasai implementation.

## 6. Deterministic / randomized validation

- 10-source fixture: 190/190 exact, max LCP 5, uint32, canonical
  `LCP[0] = 0`; metadata conventions verified.
- Terminator semantics: `ACG$/ACG$` -> 3 (never 4); 5 identical `AAAA`
  reads -> max LCP 4 (never 5); all-terminal boundaries zero;
  prefix/suffix-related, N-heavy, mixed-length, 1-base, single-read
  packages.
- No FASTQ / no rebuild: BWT bytes unchanged; Point-12 tag and Q1
  quality bytes unchanged when LCP is added on top.
- Construction on a post-Feature-10 reduced package (drop_lcp output)
  matches the oracle.
- Query API: `lcpAt`/`lcpAdjacent` exact; `lcpBetweenRows` RMQ identity
  verified exhaustively on small ranges.
- Stale/corrupt: same-length replaced BWT, wrong length, wrong dtype,
  wrong version, corrupt metadata, stale max_lcp all rejected loudly.
- Removal fail-safe: LCP removal rejected before any output; `drop_lcp`
  produces a clean, validated, LCP-free reduced package.
- Randomized: seed 20260811, 18 collections, all boundaries vs oracle,
  0 mismatches; host differentials, seeds 20260811/20260812/20260813,
  18 cases, 0 mismatches.

## 7. Test counts

- Python 2: 451 tests (was 428), all green.
- Host: 591 tests (was 580) + 22 subtests, all green.
- Q1 modernization harness: 24 tests, unchanged and green.

## 8. Storage

`(N - 1) * sizeof(unsigned)` payload (190 * 4 = 760 bytes for the
fixture).  This is an exact baseline, not a compressed LCP
representation; the later backend work may replace it while keeping this
implementation as the correctness oracle.
