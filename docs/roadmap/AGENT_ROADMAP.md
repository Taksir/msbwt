# Agent roadmap: state, setup, and backlog (easy → hard)

Last updated: 2026-10-02, after Taksir/msbwt#3 (11B, 11C, 8B.0, FMD screen,
input-validation fix, 0.5.0 release prep).

This is the entry point for any agent starting new feature work on the
Python 3 line (`packages/msbwt-modern3`, published as `pymsbwt`). Read it
first, then follow the links. The research rationale behind the ordering is
the August 2026 roadmap ("MSBWT Roadmap and Research Plan"). Its step
numbers (11B, 13B.0, …) are used here.

**Required reading before any change, in this order:**

1. `AGENTS.md`: non-negotiable rules (compatibility, goldens, security).
2. `Mistakes.md`: lookup table of past errors. M22–M24 are from the most
   recent session and apply to construction and test fixtures.
3. This file.
4. `COMPATIBILITY.md`: the most recent entries are `M3-F11B`, `M3-F11C`,
   `M3-8B0`, `M3-FMD-SCREEN` and `M3-S2-INPUT`.

`docs/modernization/HANDOFF.md` is **historical**. It describes the
legacy-oracle work done before the Python 3 port and is not the current
state.

---

## 1. Current state

| Area | State |
|---|---|
| Released | `pymsbwt` 0.4.0 on PyPI |
| Prepared, not released | 0.5.0 (`MUS/util.py`), release notes in `docs/modernization/PYMSBWT_0.5.0_RELEASE_NOTES.md` |
| Python 2.7 line (`msbwt-modern2`) | **Frozen by the owner. Never change it.** Shared tests branch on capability so they still pass against it |
| Test suite | `pytest compat/tests`: 817 passed, 2 skipped (CPython 3.14, NumPy 2.5, Cython 3.2, extensions built in place) |
| CI | `.github/workflows/release.yml`: compat suite on Linux; wheels plus `ci/smoke_test.py` on Linux x86-64/ARM64, Windows, macOS |
| Wiki | Separate repo `Taksir/msbwt.wiki`. Changes ship as `docs/wiki/wiki-refresh.patch` for the owner to apply (see `docs/wiki/WIKI_AUDIT.md`). Agents do not push to the wiki |
| Network | Outbound access to NCBI (`eutils.ncbi.nlm.nih.gov`) was **denied** in the last cloud environment. Real-data work needs the owner to allow hosts first |

### Roadmap progress

```text
done   1-7, 8A, 9, 10, 12, 13A harness, Q1          (before 0.4.0)
done   11A.1 exact LCP                                (0.4.0)
done   11B  LCP-preserving source removal             (0.5.0)
done   11C  LCP intervals, maximal/supermaximal repeats, source support (0.5.0)
done   8B.0 bidirectional correctness gate (2BWT)    (0.5.0, experimental)
done   FMD screen; checkpoint record                  (0.5.0, experimental)
open   Step 4 real-data 13A campaign  <- blocked on network/data
open   Steps 5-8 research screens
open   13B.0 Move-LF feasibility
open   ARCHITECTURE CHECKPOINT (needs steps 4-10)
open   13B.1+ compressed backend, 13C, 8B.1+, 13D, research branches
```

### Module map (modern3, `packages/msbwt-modern3/MUS/`)

| Module | Feature | Notes |
|---|---|---|
| `MultiSourceProvenance.py` | F2 merges | `merge_many_balanced(leaves, out)`; default merge is the real Holt merge |
| `MultiSourceQuery.py` | F3–F9, 11A, 11C query surface | `MultiSourceBWT` is the user API; `MultiSourceQueryIndex` does interval projections (`count_interval`, `source_frequency_interval`, `subset_count_interval`, …) |
| `SourceRemoval.py` | F10 + 11B | `retain_sources` / `remove_sources`; all layers filtered inside one atomic temp-dir publish |
| `LCP.py` | 11A + 11B | `construct_lcp_from_bwt`, `LCPIndex`, `filter_lcp_for_removal` |
| `LCPIntervals.py` | 11C | stack enumeration, children, maximality, spelling |
| `Bidirectional.py` | 8B.0 + FMD | `BidirectionalIndex(forward, partner, complement)`; builders for the reverse companion and the FMD index |
| `BackendContract.py` | 13A | `TIERS`: `13B.1-search-core`, `13B.2-navigation`, `13B.3-locate`; `assert_backend_tier` |
| `Benchmarking.py` | 13A | `bwt_run_metrics`, `inspect_index`, `benchmark_queries`, `full_benchmark_document` |
| `ReadProvenance.py`, `BWTTags.py`, `QualitySidecar.py`, `SourceMetadata.py` | F9, F12, Q1, F7 | row-aligned layers; removal filters them with the same mask |

Compiled code is in `MUSCython/*.pyx`. Generated `.c` files are **not
committed** for modern3; CI regenerates them.

---

## 2. Setting up a session (verified recipe)

```bash
SP=<your scratch dir>
uv venv -p 3.14 $SP/venv
uv pip install -p $SP/venv/bin/python "numpy>=2.5,<3" "Cython>=3.2,<3.3" setuptools wheel pytest pip
cd packages/msbwt-modern3 && $SP/venv/bin/python setup.py build_ext --inplace && cd ../..
$SP/venv/bin/python -m pytest compat/tests -q -p no:cacheprovider < /dev/null   # record the baseline first
```

Rules learned the hard way:

- **Clean up before ending a session.** `build_ext --inplace` leaves
  untracked `MUSCython/*.c`, `*.so` and `build/`. Delete them; the repo's
  stop hook flags untracked files. Never commit them.
- **multiprocessing (M16, M20, M22).** Every compiled constructor uses
  `multiprocessing`, and Python 3.14 uses `forkserver` on Linux. Run
  construction from a script **file** with a `__main__` guard, or from
  pytest. Never use `python - <<EOF`. Use `timeout -k` and `< /dev/null`.
  Afterwards check `ps -eo cmd | grep '[f]orkserver import main'` for
  orphaned workers.
- **Construction input (M23, M3-S2-INPUT).** Reads must be uppercase
  `ACGNT`, and in-memory APIs need a trailing `$`. Write anything that
  could hang as a subprocess test with a timeout.
- **Test fixtures (M24).** `compat/tests/test_multisource_query.py` builds
  naive in-Python BWTs whose LF cycles span several reads. Use the oracle
  adapters (`test_lcp.OracleBackedAdapter`,
  `test_read_provenance.OracleBWTAdapter`) for per-read identity, or build
  real indexes with `MultimergeCython.createMSBWTFromSeqs` plus
  `merge_many_balanced`.
- **Python 3.14 detail.** `Pool.imap(..., chunksize>1)` returns a plain
  generator, so call `next(it)`, not `.next()`.

### The per-feature protocol used so far (keep it)

1. Run the baseline suite and note the counts.
2. Write a short plan doc in `docs/roadmap/`: what, why now, contract,
   oracle, and what is not done.
3. Implement in modern3 only, reusing existing interval and provenance
   paths.
4. Write tests against an **independent oracle** built from read strings,
   explicit suffix sorts or direct search, never from the code under test.
   Use seeded randomized cases.
5. **Mutation check.** Break the core logic two ways and confirm the new
   tests fail, then restore the code.
6. Add a `COMPATIBILITY.md` entry (affected APIs and files, old and new
   behavior, interoperability) and a Mistakes entry for any new pitfall.
7. Run the full suite and `git diff --check`, then commit one feature per
   commit and push.

---

## 3. Backlog, ordered easy → hard

Size: **S** < 1 session, **M** about 1 session, **L** several sessions,
**XL** a research project. "Model" is a recommendation (see §4).

### Tier 0: chores (S)

| ID | Task | Entry points | Done when | Model |
|---|---|---|---|---|
| E1 | Release 0.5.0 (owner action) | `docs/RELEASING.md` | tag `v0.5.0` pushed; TestPyPI checked; PyPI approved | owner |
| E2 | Apply the wiki patch (owner action) | `docs/wiki/WIKI_AUDIT.md` | wiki at a commit containing the new pages | owner |
| E3 | Give the pure-Python `MUS.MSBWTGen.writeSeqsToFiles` the same input validation as the Cython path (it raises `IndexError` today) | `MUS/MSBWTGen.py`, `MUSCython/MSBWTGenCython.pyx::_validateSeqBytes` | same `ValueError` text; byte-identical valid output; test | Sonnet, medium |
| E4 | Decide empty-read handling (a lone `$`) on the uniform/Bauer byte layout; characterize first | `MSBWTGenCython.writeSeqsToFiles` | characterization test plus a COMPATIBILITY note | Sonnet, medium |

### Tier 1: measurements and research screens (S–M each; most need real data)

Do these **before** any compressed backend; they decide which backend to
build. Data rule: public, checksum-pinned, small bacterial or viral read
sets only. Record raw hashes. Never commit private data (`AGENTS.md`).

| ID | Roadmap | Task | Key point | Model |
|---|---|---|---|---|
| S1 | Step 4 | Real-data 13A campaign: N, r, r/N, per-layer bytes, query and build latency, on ≥10 real sources, then 100 and 1000 sources | Harness exists (`MUS.Benchmarking.full_benchmark_document`, `tools/benchmark_index.py`). Also rerun `compat/screens/fmd_vs_2bwt.py` on real reads: the synthetic result was 15–21% fewer runs for FMD | Sonnet, high to run; Opus, high to interpret at the checkpoint |
| S2 | Step 5 R-DEL | Deletion run-stability | **Caution:** F10 verified that Point-10 output is byte-equal to an independent suffix sort of the retained reads, so filtering adds no excess runs relative to the *standard* order. The meaningful baseline is an *optimal-order* BWT (Cenzato et al., SAP-interval reordering). Implement a small optimal-r reference first | Opus, high |
| S3 | Step 7 R-SEP | Separator cost: share of runs touching `$` rows, r with and without terminators | Pure NumPy over `msbwt.npy`; easy once data exists | Sonnet, high |
| S4 | Step 6 R-REL | Pairwise source-BWT similarity, LCS fraction, clustering | Per-source BWTs come from the provenance leaves | Opus, high |
| S5 | Step 8 R-ADAPT | Upper bound on run reduction from context-adaptive ordering | Small datasets only; treat as a screen | Opus, xhigh |

### Tier 2: moderate engineering (M)

| ID | Roadmap | Task | Oracle / gate | Pitfalls | Model |
|---|---|---|---|---|---|
| M1 | 13B.0 | **Move-LF feasibility.** Build the run table and move structure from `msbwt.npy`; check `moveLF(i) == LF(i)` for **every** row | Compiled LF: `getOccurrenceOfCharAtIndex(BWT[i], i)` (see `BasicBWT.getSequenceDollarID`) | `$` rows and Holt multi-terminator order; run splitting for the move balance property | Opus, high |
| M2 | 11C follow-up | Compile the 11C stack loop (Cython) | Must equal the Python `iter_lcp_intervals` output on the existing tests | Keep the Python version as the oracle; add the Cython one beside it | Sonnet, high |
| M3 | 11C optional | Suffix–prefix overlaps between reads (roadmap 11C "optional") | Brute-force overlap oracle from read strings | Terminator semantics; read identity via F9 | Opus, high |
| M4 | 8B.3 prototype | MEM/SMEM on the 8B.0 `BidirectionalIndex`, not yet production | Naive MEM enumeration from strings | Do not claim novelty (roadmap §8); the roadmap places production 8B after 13B, so ship as experimental | Opus, high |
| M5 | design only | **Strand model** needed before any FMD primary mode: provenance, mates, Q1 reversal, tags, removal of both strands | Design doc reviewed by the owner | Read `CHECKPOINT_FMD_VS_2BWT.md` first | Opus, xhigh |

### Architecture checkpoint (decision, not code)

Needs S1–S5, M1 and 8B.0 (done). Write the decision doc the roadmap asks for
(Outcome A/B/C/D) and **stop for owner approval** before Tier 3. Model:
Opus, xhigh.

### Tier 3: hard backend work (L each, sequential)

All of these must pass the existing semantic suite as oracle, and implement
the `BackendContract.TIERS` capabilities listed.

| ID | Roadmap | Task | Contract tier | Model |
|---|---|---|---|---|
| H1 | 13B.1 | RLBWT/move exact-search backend | `13B.1-search-core` | Opus, xhigh |
| H2 | 13B.2 | Generalized run samples `(dollar_id, offset)` | `13B.2-navigation` | Opus, xhigh |
| H3 | 13B.3 | Move-r-style locate | `13B.3-locate` | Opus, xhigh |
| H4 | 8B.1 | Production 2BWT on the new backend (reuse the `BidirectionalIndex` logic) | — | Opus, high |
| H5 | 13C | Compressed source-aware queries (Points 3–7 without occurrence enumeration) | — | Opus, xhigh |
| H6 | 8B.2 | Source/group-aware bidirectional state | — | Opus, high |
| H7 | 13D.1 | Static compressed rebuild after Point-10 removal | — | Opus, xhigh |

### Tier 4: research (XL)

R-BIDIR (source-aware approximate search), R-MOVE (source-deletable Move-r),
R-RUN (only if S2 shows degradation), 13D.2 full compressed lifecycle, 8B.4
b-move, R-BMOVE. Each needs a novelty audit before any claim (roadmap §26).
Model: Opus at max effort, starting with a written plan.

---

## 4. Which model and how much thinking

These recommendations come from what went wrong in past sessions, not from
benchmarks.

| Work type | Model | Effort | Why |
|---|---|---|---|
| Owner chores, docs, wiki patches, version bumps, adding tests to an existing pattern | **Sonnet 5.5** | medium | Clear oracle, low ambiguity; cheaper and fast |
| Running measurement scripts; mechanical ports with an oracle (E3, M2, S3) | **Sonnet 5.5** | high | Careful but well specified |
| New algorithms with subtle invariants (Move-LF, LCP and terminator semantics, bidirectional offsets, MEMs, optimal-r) | **Opus 5.5** | high | Past bugs here were subtle: multi-read LF cycles, a `[-1]` index under `wraparound=False`, ASCII vs symbol-code tables, a forkserver hang. Each needed diagnosis rather than pattern-following |
| Architecture checkpoint, strand model, compressed backends (Tier 3) | **Opus 5.5** | xhigh | Cross-cutting design with persisted-format consequences |
| Research branches (Tier 4) | **Opus 5.5** | max | Open problems and novelty audits |

When in doubt, use Opus at high effort for anything touching `MUSCython/`,
persisted formats, or suffix-order semantics, and Sonnet at medium for
everything else.

---

## 5. Open issues to know about

- `MUS.MSBWTGen` (pure Python) raises `IndexError` rather than the new
  `ValueError` on invalid symbols (E3).
- `MultimergeCython.createMSBWTFromSeqs([])` raises `ZeroDivisionError`.
  This is characterized legacy behavior, pinned by
  `test_m3_r64_w4_merge.py`.
- The 11C enumeration is pure Python (about 1 µs per visited boundary).
- `build_reverse_companion` and `build_fmd_index` hold all recovered reads
  in memory. Fine for the prototype; not for 10⁹-base cohorts.
- The FMD vs 2BWT numbers are synthetic only (S1 should confirm or refute
  them).
