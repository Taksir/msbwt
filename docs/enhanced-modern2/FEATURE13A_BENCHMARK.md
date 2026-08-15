# ENHANCED-MODERN2 — Feature 13A (executed evidence): Whole-index benchmark harness + backend contract

Status date: 2026-08-15

Branch: `enhanced-modern2` (Feature-11A commits `a56aa9c`, `82ea6e6`,
`f6e71f1`)

This is the FINAL milestone of this program.  Feature 13A deliberately does
NOT implement a new backend; it measures and formalizes the completed
enhanced system so the next backend decision is evidence-based.

**Verdict: PASS.**  VERIFIED-CORRECT: storage accounting is exact against
an independent filesystem-traversal oracle, structural metrics (N, r,
r/N, provenance logical bits, read/tag/quality/LCP bytes) are exact
against independent array-level oracles, the Q1 quality payload is
reported semantically without double counting, query/build benchmarks are
reproducible for engineering comparison, and the machine-readable backend
contract covers every verified enhanced feature.

## 1. Public API

New module `MUS/Benchmarking.py` (pure Python/NumPy, Python-2.7
compatible):

- `bwt_run_metrics(index_dir, chunk_rows=8Mi)` — N, r, r/N, mean run
  length, symbol counts, dtype, payload (sequential mmap scan).
- `disk_breakdown(index_dir)` — per-file physical/payload bytes and
  per-layer buckets (`bwt`, `root_interleave_compat`,
  `provenance_manifest`, `provenance_interleaves`, `provenance_ranks`,
  `read_provenance`, `source_metadata`, `bwt_tags_registry`,
  `bwt_tags_arrays`, `quality_sidecar_metadata`, `lcp`,
  `test_oracle_fixture`, `other`); totals: physical (all files),
  production (excludes test-oracle fixtures), intrinsic (additionally
  excludes the root `inter0.npy` compatibility copy).
- `provenance_metrics` — sources, leaves, internal nodes, depth,
  logical interleave bits/bytes, bits per row, weighted depth, rank-cache
  file count/bytes.
- `read_provenance_metrics` — read count, 20-byte records, payload,
  physical, bytes/read, reads/row.
- `tag_metrics` — per-tag dtype/shape/payload/physical/bytes-per-row and
  totals.
- `quality_metrics` — Q1 semantics (alignment, encoding, sentinel, read
  count, payload) with an explicit note that the payload is ALREADY
  included in Point-12 tag totals (never double counted).
- `lcp_metrics` — Feature-11A `lcps.npy` (stored boundaries N-1, dtype,
  payload, physical, bytes/row, max LCP).
- `naive_run_encoding_model` — r*5 / r*9 byte models with ratios
  (explicitly NOT an r-index size prediction).
- `inspect_index(index_dir)` — full structural report with environment
  snapshot and decision summary (BWT fraction, auxiliary bytes/ratio,
  naive-u32-RLE smaller?, largest layers, LCP present).
- `benchmark_queries(msbwt, patterns, warmup, repeats, source, top_k,
  tag_name, include_read_listing)` — median/mean/p95/min/max microseconds
  per operation (count, find_interval, source_count, sparse_sources,
  source_frequency, top_sources, tag_values, read_listing) plus the
  framework contract.
- `benchmark_build_operation(name, builder, repeats)` — caller-supplied
  construction hook.
- `compare_reports(reports)` — compact backend-selection table.
- `save_report(path, report)` (atomic), `full_benchmark_document(...)`.

New module `MUS/BackendContract.py`:

- `BACKEND_PRIMITIVES` — total_size, find_interval, count,
  backward_extend, access, rank (13B.1); lf, sequence_dollar_id,
  recover_string (13B.2); locate (13B.3).
- `FRAMEWORK_CAPABILITIES` — source_count (F3), sparse_sources (F4),
  source_frequency (F5), top_sources (F6), subset_count/group_count (F7),
  left/right_extension (F8A), read_listing (F9), tag_values/tag_counts
  (F12), quality_recovery/quality_query (Q1), lcp_access (F11A),
  grouped into stages 13C/13D.
- `TIERS` — 13B.1-search-core, 13B.2-navigation, 13B.3-locate.
- `LegacyBWTAdapter` — adapts Holt-style method names to the contract
  with feature detection; `inspect_backend`, `inspect_framework`,
  `assert_backend_tier`, `contract_document()`.

New CLI tool: `tools/benchmark_index.py` (`inspect`, `compare`, `query`,
`contract`).

## 2. Storage accounting rules

- Every file is classified into exactly one layer; totals are summed
  once per file.
- The Q1 quality array is a Point-12 tag: counted once in
  `bwt_tags_arrays`; `quality_metrics` reports its semantics without
  adding to totals.
- The root `inter0.npy` compatibility copy is reported in the production
  total and separately excluded in the intrinsic total.
- `test_oracle_fixture` files (naive rows etc.) are excluded from
  production totals.
- The independent filesystem oracle: total physical bytes summed by a
  separate filesystem traversal == reported `physical_total_bytes`
  exactly.

## 3. Measurement results (toy fixture, deliberate negative result)

10-source fully-layered package (provenance + read provenance + row_id
tag + Q1 quality + LCP): N = 191, r = 144, r/N = 0.754, mean run length
1.33; naive uint32 RLE = 720 bytes vs 191 raw BWT bytes (3.8x) — the toy
BWT is NOT repetitive enough to justify a compressed backend.  7-source
reduced package: N = 133.  These numbers are correctness fixtures only;
real-dataset tiers (Tier 1+: small public biological datasets, 100/1000
sources, realistic repetitive cohorts) are required before any backend
selection, and no such real dataset is available in this environment
(state explicitly: none was used).

## 4. Candidate audit and defects

Candidate files audited: `POINT13A_README.md`, `Benchmarking.py`,
`BackendContract.py`, `benchmark_index.py`, `test_point13a_benchmarking.py`,
the four JSON fixture/contract documents, and the later Q1-folder
`Benchmarking(1).py`/`BackendContract(1).py` snapshots (quality/LCP
additions).

CANDIDATE DEFECTS (fixed in production):

1. Python-2 incompatibilities: `pathlib.Path`, `write_text/read_text`,
   `time.perf_counter`, `os.cpu_count`, and the `statistics` module
   (py2.7 has none of the last three) — adapted (os.path + atomic JSON +
   monotonic/cpu-count/median/mean helpers).
2. The candidate's LCP recognition used `lcp.npy` (pre-11A filename);
   production recognizes the actual Feature-11A files `lcps.npy` +
   `lcp.json` and reports the stored-boundary (N-1) convention with the
   validated LCP layer.
3. The candidate's fixture-oracle exclusion list did not include
   `quality_sidecar.json` in any layer; production classifies it as
   `quality_sidecar_metadata`.
4. Framework contract completeness: the candidate's 13-folder snapshot
   lacked the Feature-11A LCP capability; production adds `lcp_access`
   and the Q1 capabilities (`quality_recovery`, `quality_query`).

No MODERN2 BASELINE defects discovered.

## 5. Independent oracle

- N/r/r/N: independent direct scan of the raw BWT array.
- Storage: independent filesystem traversal sum, compared exactly.
- Provenance logical bits: independent tree walk.
- Read/tag/quality/LCP bytes: direct array-size accounting
  (`shape * itemsize`), physical = file sizes.
- Naive RLE model: arithmetic checked independently.

## 6. Deterministic validation

- 10-source package: run/disk/provenance-bits/read/tag/quality/LCP
  oracles all exact; quality payload single-counted; decision summary
  negative result asserted; comparison table across 10-source and
  Feature-10-reduced packages; query benchmark runs 8 operations with
  the framework contract; build hook and full document round-trip.
- Contract: search-core tier satisfied by the legacy adapter; locate
  honestly absent; framework contract lists all 14 capabilities.

## 7. Test counts

- Python 2: 464 tests (was 451), all green.
- Host: 603 tests (was 591) + 22 subtests, all green.
- Q1 modernization harness: 24 tests, unchanged and green.

## 8. Backend-contract status

The machine-readable contract (version 1) is complete for every
implemented enhanced feature and is exported by
`tools/benchmark_index.py contract` and embedded in every full benchmark
document.  No backend implementation, r-index, move-r, RLBWT replacement,
or new locate structure was introduced.
