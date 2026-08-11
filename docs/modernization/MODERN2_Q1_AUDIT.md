# MODERN2 — Quality Audit Q1 (executed evidence): randomized differential + invariant stress

Status date: 2026-08-10

Branch: `codex/modern2`

This is NOT a feature milestone.  It stress-tests the feature-complete
modern2 baseline (Milestones 1–10) with a deterministic RANDOMIZED
differential-testing harness:

    many generated cases
    + independent mathematical oracles
    + differential comparison (frozen / modern2 / oracle)
    + deterministic reproducibility from recorded seeds.

No production source was modified.  No packaging or modern3 work was
started.  Any new genuine defect found by this audit is recorded as a
candidate finding (NEWLY DISCOVERED — UNRESOLVED) in
`MODERN2_LEGACY_BUG_TRACKER.md`-adjacent audit evidence, never auto-fixed.

## 1. Harness inventory

All new files live under `compat/audit/modern2-q1/`:

| File | Role |
|---|---|
| `audit_core.py` | deterministic corpus generator + independent oracle (rotation BWT, symbol totals, backward search, LF recovery, FM ranks, NPY v1 parser, base-32 RLE decoder, deterministic gzip) — pure stdlib Python 3 |
| `analyze_audit.py` | three-way classification A/B/C/D/E, family checks, deterministic summary |
| `run_audit.py` | host/WSL orchestrator: git gates, corpus/ops/fastq generation, provisioning, execution, evidence |
| `wsl/execute.py` | WSL-side executor: runs the msbwt CLI (frozen or modern2) for every family, records raw results JSON |
| `wsl/reader_probe.py` | Python-2.7 reader probe: char-at, FM rows, queries, recovery, derived-file inventory, cache regeneration |
| `wsl/provision.sh` | disposable WSL execution trees: hash-verified frozen 40-file projection built through the pyx-historical-cython route (Cython 0.29.36) + byte-verified modern2 tree (Cython 3.0.12 extensions) |
| `minimize_reproducer.py` | deterministic failure minimizer (delta debugging over reads, length trimming, dedup) |
| `tests/test_audit_q1_harness.py` | host-side regression tests for the harness (24 tests) |
| `evidence/<tag>/` | per-run evidence: corpus.json, results.json, summary.json, report.txt |

## 2. Oracle policy

Three-way reasoning is used wherever practical:

    A. legacy == modern2 == oracle            PASS
    B. legacy == modern2 != oracle            probable previously unknown legacy bug
    C. legacy != modern2 and modern2 == oracle possible intended modern2 fix / migration difference
    D. legacy != modern2 and legacy == oracle probable modern2 regression
    E. all three differ                       STOP — ambiguous / harness issue / deeper defect

For uniform collections (historically uniquely-ordered rotation-sort BWT)
the strongest invariant — byte payload equality against the independent
rotation-sort oracle — is required.  For nonuniform collections, where the
historical multimerge ordering has a documented representation nuance, the
strongest correct semantic invariant is used instead: symbol totals +
backward-search counts over every read substring + LF-recovered read
multiset, all compared against the independent oracle.

No outcome of B/C/D/E is auto-fixed; each is preserved with its exact seed
and case.

## 3. Corpus design

Seed: `20260810` (a second independent seed `20260811` is used for the
determinism gate; see section 14).

Generated collection inventory (regenerable from
`python3 compat/audit/modern2-q1/audit_core.py` via `generate_corpus`):

- 150 small collections (2–12 reads, 1–24 nt, ≤ ~300 total symbols);
- 15 medium collections (10–40 reads, 1–50 nt, ≤ ~2200 symbols);
- 60 merge-case collections (20 merge pairs × A/B/union roles).

Categories (each with deterministic generators; every category appears
~9–10 times across the corpus):

    uniform-reads, nonuniform-reads, duplicates, all-identical,
    prefix-sharing, suffix-sharing, many-dollars (14–26 short reads),
    full-alphabet, n-heavy (30–60% N), single-base, short-reads,
    moderate-reads, odd-length, even-length, mixed-length,
    repeated-motifs, revcomp-pairs, lexicographic-similar.

Per-case queries are generated deterministically: all five length-1
symbols, `$`, 6 random substrings, up to 3 complete reads, 4 absent
strings, 3 N-containing strings, 3 repeated-symbol strings (medium cases
+8 longer substrings).  Sample positions are deterministic.

Every generated case satisfies the oracle self-consistency gate before
execution (symbol totals, LF recovery, query counts on the rotation BWT).

## 4. Execution environment

Two disposable WSL execution trees provisioned on Linux-native storage
(`~/.local/share/msbwt-audit-q1/`), both hash-verified:

- `frozen/` — the exact frozen 40-file projection (verified against
  `reference/original-0.3.0/environment/frozen-source.sha256`), built via
  the committed pyx-historical-cython route with the oracle profile's
  pinned Cython 0.29.36; 12 compiled modules.
- `modern2/` — `packages/msbwt-modern2` including its in-tree Cython
  3.0.12 extensions (11 modules), .so files hash-verified against the
  repository copies.

Preflight gates (executed before the corpus sweep):

- `uniform-multifile` golden: `msbwt.npy` SHA-256
  `dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f`
  reproduced byte-for-byte by BOTH trees;
- `nonuniform-prefix` golden: `da28963ca3726568dd7a26eccea35f107bd4cb8b295c909de628374db38dd4b2` (shape (30,)) — both trees;
- `gzip-input` golden: `da40d02ef42d4cf61d7b4814a2bc2c44c48f3516a53d6111a19bf2fdba8ff33b` (shape (54,)) — both trees;
- `-p 2 == -p 1` on uniform and nonuniform canonical inputs — both trees;
- single-base uniform reads and tiny (2 reads × 2 nt) collections accepted
  by both trees.

## 5. Test families executed

| Family | Scope | Checks |
|---|---|---|
| 1 construction | all 165 non-merge collections × both trees | byte equality (uniform) / semantic signature (nonuniform), `$` count, symbol totals, payload vs oracle, queries, recovery |
| 2 cffq wrapper | subset (~40) | `cffq -p 1/-p 2` vs `pp+cfpp` route; byte equality observation + oracle semantics |
| 3 gzip | subset (~30) | deterministic `.gz` inputs; gzip construct == plain construct (both trees) |
| 4 compression round trip | subset (~40) | `compress -p 1/-p 2`, independent RLE decode == original, `decompress -p 1/-p 2` == original; frozen decompression expected-failure contract |
| 5 reader/FM | all collections × both trees | getCharAtIndex == payload, getFullFMAtIndex == independent FM rank, countOccurrencesOfSeq == independent backward search |
| 6 recovery | all collections × both trees | recoverString at every dollar position; multiset == input reads (duplicates preserved) |
| 7 merge | 20 pairs × both trees | construct A, construct B, merge; merged == clean union construction (uniform: byte equality; nonuniform: semantics); modern2 p1 == p2; frozen merge -p 2 (the -p 1 UnboundLocalError is a preserved legacy bug) |
| 8 metamorphic | subsets | input-order permutations; process-count invariance (p1 == p2); compression invariance; merge equivalence; cache regeneration (delete derived files, reload, byte-identical) |

Counts are recorded in `summary.json` (`family_counts`).

## 6. Results

Executed twice with the same seed (`20260810`); both runs produced
byte-identical `summary.json` (SHA-256
`225af784cc284d3a38c8b250ea30e4ea7a0ca27a7eaa0bade43761cf15de98c3`).

### 6.1 Three-way classification totals (both runs identical)

| Outcome | Count | Meaning |
|---|---|---|
| A (legacy == modern2 == oracle) | 260 | all construction/gzip/cffq/merge three-way checks PASS |
| B / C / D / E | 0 | no legacy/modern2/oracle disagreement found |

The 260 A-classifications break down as: 165 constructions + 33 gzip
equivalences + 42 cffq routes + 20 merges.

### 6.2 Family check counts

| Family | Checks | Result |
|---|---|---|
| construction | 165 | byte-equal (uniform) / semantic-equal (nonuniform) to the independent oracle on both trees |
| process-count invariance (`-p 1` == `-p 2`) | 165 | all equal on both trees |
| gzip equivalence | 33 | gzip construct == plain construct on both trees |
| cffq wrapper | 42 | direct wrapper == `pp`+`cfpp` route + oracle semantics |
| compression round trip | 53 cases | RLE decode == original payload; modern2 decompress == original; frozen decompression expected-failure contract checked 106 times (all matched the documented `MultiStringBWT.py:662` TypeError contract, tracker #1) |
| merge | 20 pairs | merged == clean union construction (uniform byte-equal; nonuniform semantic-equal); modern2 `-p 1` == `-p 2`; frozen `-p 2` matches |
| permute (input-order invariance) | 56 | uniform: byte-equal across permutations; nonuniform: semantic-equal |
| reader/FM | 165 | getCharAtIndex == payload at sampled positions; getFullFMAtIndex == independent FM ranks; countOccurrencesOfSeq == independent backward search for ~21–29 generated queries per case |
| recovery | 165 | recovered multiset == input read multiset (duplicates preserved) |
| RLE reader cross-check | 10 | byte-reader queries == RLE-reader queries |
| cache regeneration | 12 | delete derived files, reload, byte-identical derived artifacts |

### 6.3 Metamorphic properties

- input-order invariance: PASS (56 permutations);
- process-count invariance: PASS (165 cases);
- compression invariance: PASS (53 cases; RLE decode + decompress both
  reproduce the byte BWT exactly);
- merge equivalence: PASS (20 pairs);
- cache regeneration: PASS (12 cases, compiled reader).

## 7. New findings

**None.**  No classification B/C/D/E outcome occurred, no new legacy bug
was discovered, and no modern2 regression was discovered.  The audit's
only corrected defect was inside its own harness (see section 8: the RLE
digit-order misreading), which the committed goldens could not expose.

No production source was modified.  The legacy bug tracker has no new
candidate entries.

## 8. Test blind spots identified

Derived from the committed test inventory (283 compat tests + 132 modern2
Python-2 tests) and the executed evidence, not speculation:

- **RLE multi-digit runs are unexercised by the committed suite.**  Every
  committed compressed golden (`uniform-compress-posthoc`,
  `nonuniform-compress-posthoc`, `uniform-direct-split`,
  `uniform-direct-wrapper`) contains only single-digit runs (all run
  lengths ≤ 32).  The audit's own first decoder draft misread the
  little-endian digit order precisely because no committed artifact could
  falsify it; the fix is protected by `RleDigitOrderTests`.  The committed
  py2 helper `_decode_rle_counts` (test_reader_init_py2.py) carries the
  same latent ordering assumption and is only ever exercised on
  single-digit-run inputs (unexercised-risk, not a defect).
- **Query lengths in committed tests**: only lengths {2, 5, 6, 8} appear
  in the committed query tables; length 3/4/7/9+ and broad absent-string
  and N-heavy query coverage are new in this audit.
- **Collection sizes**: committed fixtures cover {4, 7, 8, 259} reads and
  {30, 48, 54, 1110, 1M} symbols; tiny 2–3 read collections, 14–26 read
  many-dollar collections, and 10–40 read medium collections were not
  covered before this audit.
- **Category breadth**: duplicates beyond the fixture's one triplicate,
  all-identical collections, suffix-sharing, N-heavy, mixed-length,
  repeated-motif, revcomp-pair, odd/even-length and lexicographic-similar
  collections are new.
- **Process counts**: only 4 committed files exercise `-p 2`; generated
  construction `-p 2` equality was not covered before.
- **Input-order permutations and compiled-reader cache regeneration** are
  new metamorphic coverage.

## 9. Static Cython sanity audit (read-only)

Scan of the 11 active migrated `.pyx` modules (frozen-identical except the
documented diffs):

- All 11 carry `#cython: boundscheck=False` / `wraparound=False` (frozen
  directives preserved); the resulting unchecked-index sites are all on
  executed paths (construction, reader, merge, compression) — classified
  `executed-safe` for exercised inputs; `unexercised-risk` only for
  out-of-contract inputs (malformed artifacts), which are outside audit
  scope.
- `char *` views (`AlignmentUtil`, `BasicBWT`, `RLE_BWTCython`,
  `GenericMerge`, `MultimergeCython`, ...) are all exercised by the py2
  suite and this audit — `executed-safe`.
- Integer-coordinate divisions are float `math.ceil` sampling-size
  computations in the readers — `executed-safe`.
- No `malloc`/`calloc`/`free` anywhere — no manual ownership hazards.
- Migrated `.pyx` identity: 10/11 byte-identical to frozen after the
  `language_level=2` header; `RLE_BWTCython.pyx` carries exactly the
  documented `int()` promotion fix (line 375) — `executed-safe`, covered
  by the reader-boundary tests and this audit's reader probes.
- `proven-defect`: none.

## 10. How to reproduce

```bash
# provision (once):
bash compat/audit/modern2-q1/wsl/provision.sh \
  --repo /mnt/.../msbwt --work ~/.local/share/msbwt-audit-q1 \
  --oracle-python <py27-oracle>/bin/python \
  --modern2-python <py27-modern2>/bin/python

# full audit (host or WSL):
python3 -B compat/audit/modern2-q1/run_audit.py --seed 20260810 --tag q1

# host-side harness tests:
python -B -m unittest discover -s compat/audit/modern2-q1/tests
```

## 11. Baseline verification

Executed before finalization (all green):

```text
python -B compat/fixtures/synthetic/generate_fixtures.py --check
    -> fixture bytes match
python -B reference/original-0.3.0/environment/verify_frozen_source.py --source .
    -> OK frozen source projection: 40 files
python -B -m unittest discover -s compat/tests
    -> Ran 283 tests ... OK
python -B -m unittest discover -s compat/audit/modern2-q1/tests
    -> Ran 24 tests ... OK
git diff --check
    -> clean
packages/msbwt-modern2 Python-2 suite
    -> Ran 132 tests ... OK
```

The randomized audit was executed twice with identical seeds and produced
byte-identical `summary.json` (section 6).

## 12. Runtime

Each full sweep (both trees, all families, 225 collections) completed in
approximately 50–85 minutes of wall time on the WSL2 reference host
(frozen uniform constructions dominate at ~40 s each; nonuniform
constructions ~1 s).  Two full sweeps were executed (q1 and q1-verify).
Exact per-run timing is not part of the deterministic evidence; the
corpus and results are regenerable.

## 13. Overall confidence assessment

HIGH for the exercised surface.  The modern2 implementation is
byte-identical to the frozen oracle on every generated uniform input and
semantically identical on every generated nonuniform input, against an
independent mathematical oracle, across construction, direct-wrapper,
gzip, compression, decompression (modern2), merge, reader/FM/query,
recovery, and cache-regeneration paths, at `-p 1` and `-p 2`, over 225
generated collections (165 audited + 60 merge-role) covering 18 category
families.

## 14. Top remaining quality risks

1. The frozen oracle corpus is necessarily small; the audit's semantic
   invariants are ordering-independent, so byte-ordering nuances of the
   nonuniform multimerge route remain characterized only by the committed
   goldens and by semantic (not byte) equality here.
2. The frozen decompression path is unexercisable (documented legacy
   contract); only modern2 decompression round trips were validated.
3. `LCPGen` remains a classified DEAD/PRIVATE stub (Milestone 10);
   unexercised by construction.
4. Static Cython findings are all `executed-safe` on exercised paths;
   out-of-contract malformed artifacts (e.g., truncated `.npy`) remain
   unexercised-risk for the compiled readers.
5. The RLE multi-digit-run path is now covered by the audit corpus and
   harness tests, but the committed golden set still has no multi-digit
   golden; a future golden refresh could close that gap.
