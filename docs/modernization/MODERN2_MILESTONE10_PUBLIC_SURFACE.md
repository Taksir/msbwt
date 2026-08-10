# MODERN2 — Milestone 10 (executed evidence): remaining public surface audit + closure

Status date: 2026-08-10

This milestone audits the remaining PUBLIC/REACHABLE surface of modern2,
classifies every questionable component, restores the one genuinely public
gap (`convert` / `MUSCython.CompressToRLE`), and proves the remaining
candidates are not release blockers.

**Verdict: PASS.**  `convert` is public and reachable; the unchanged frozen
`CompressToRLE.pyx` (semantic source authority) compiled under Cython 3.0.12
with only the `#cython: language_level=2` migration and produced output
byte-identical to the committed SECONDARY REGENERATED-SOURCE ORACLE on the
first execution (file route and stdin route, uniform and nonuniform).
`LCPGen` and `MSBWTGenCython.compressBWT` are NOT reachable from any public
path; both are classified and documented, no speculative fixes were made.
`massquery` (previously unvalidated) is now validated.  The only remaining
stub is `MUSCython.LCPGen`, intentionally retained and classified
DEAD/PRIVATE.

## 1. Public CLI command inventory (complete)

The frozen parser is preserved in modern2 (`MUS/CommandLineInterface.py`
differs only by the documented `numProcs = 1` merge fix, COMPATIBILITY.md
entry 2).  Nine subcommands plus global flags:

| Command | Options/positionals | Dispatch implementation | Status |
|---|---|---|---|
| `pp` | `[-u] OUT FASTQ...` | `MultiStringBWT.preprocessFastqs` (uniform) / `Multimerge.preprocessFastqs` | validated (m1, m8) |
| `cffq` | `[-p N] [-u] [-c] OUT FASTQ...` | uniform: `MultiStringBWT.createMSBWT(Comp)?FromFastq`; nonuniform: `Multimerge.createMSBWTFromFastq`; `-c` nonuniform logs an error | validated (m2, m8) |
| `cfpp` | `[-p N] [-u] [-c] DIR` | `MSBWTGenCython.createMsbwtFromSeqs` / `MSBWTCompGenCython.createMsbwtFromSeqs` (uniform) / `Multimerge.interleaveLevelMerge` (nonuniform) | validated (m1, m2, m8) |
| `merge` | `[-p N] OUT IN...` | `GenericMerge.mergeTwoMSBWTs` (`-p 1` fix, COMPATIBILITY.md entry 2) | validated (m9) |
| `query` | `[-d] DIR KMER` | `MultiStringBWT.loadBWT` + `findIndicesOfStr` + `recoverString` | validated (m5–m7, m9) |
| `massquery` | `[-r] DIR KMER_FILE OUT` | `loadBWT` + `countOccurrencesOfSeq` + `reverseComplement` | **validated (m10)** |
| `compress` | `[-p N] SRC DST` | `MSBWTGen.compressBWT` (pure Python) | validated (m2) |
| `decompress` | `[-p N] SRC DST` | `MSBWTGen.decompressBWT` (pure Python) | validated (m3, m4) |
| `convert` | `[-i TEXT_BWT] DST` | `CompressToRLE.compressInput` (migrated Cython) | **validated (m10)** |
| global | `-V/--version`, `-h` | argparse; `0.3.0 in MSBWT 0.3.0` | validated (m1, m10) |

Aliases preserved: `-u/--uniform`, `-c/--compressed`, `-d/--dump-seqs`,
`-r/--rev-comp`, `-i`, `-p`, `-V/--version`.  Installed console script:
`bin/msbwt` -> `MUS.CommandLineInterface.mainRun()`.  Every command listed
above is reachable and validated; no command is broken or stubbed; no CLI
command is intentionally unsupported except the historical nonuniform
`-c` paths, which log the frozen error message by design.

## 2. Public import/API inventory relevant to release

`MUS` and `MUSCython` initializers are empty (frozen); the documented
module surface is unchanged.  The full symbol matrix is enforced by the new
public import/export smoke tests (host-side static + Python-2 runtime):

- `MUS.CommandLineInterface`, `MUS.MSBWTGen`, `MUS.MultiStringBWT`,
  `MUS.TranscriptBuilder`, `MUS.util` — pure Python, frozen sources with the
  documented deviations only;
- compiled `MUSCython` modules: `AlignmentUtil`, `BasicBWT`,
  `ByteBWTCython`, `CompressToRLE` (migrated m10), `GenericMerge` (m9),
  `LZW_BWTCython`, `MSBWTCompGenCython`, `MSBWTGenCython`,
  `MultiStringBWTCython`, `MultimergeCython` (m8), `RLE_BWTCython` — 11
  extensions built by Cython 3.0.12;
- `MUSCython.LCPGen` — the one intentional stub (see stub policy below).

## 3. Candidate classification (the four milestone targets)

| Candidate | Reachability proof | Classification |
|---|---|---|
| `CompressToRLE.compressInput` | imported at module level by `MUS/CommandLineInterface.py:15`; dispatched by the `convert` subcommand (`:242`) | **A. PUBLIC + REACHABLE** — migrated and validated |
| `convert` CLI | `sp.add_parser('convert')` (`:96`) | **A. PUBLIC + REACHABLE** — validated |
| `LCPGen.lcpGenerator` / `linearLcpGenerator` | repository-wide search: only the frozen `setup.py` references `LCPGen`; no Python/Cython module imports it; no CLI subcommand dispatches to it | **C. HISTORICAL/PRIVATE/DEAD** — stub retained with documented classification |
| `MSBWTGenCython.compressBWT` | `compress` CLI dispatches to the pure-Python `MSBWTGen.compressBWT`; no module imports or calls the Cython `compressBWT` (self-referential only) | **C. exported-but-unreachable historical internal** — executed probe, no fix |

No category-D items were found; no stop condition triggered.

## 4. `convert` — public/reachable — exact result

Semantics established from frozen source BEFORE any modern2 change via the
committed secondary regenerated-source oracle harness
(`reference/original-0.3.0/environment/convert_oracle_milestone10.sh`,
oracle profile `py27-late-05a7d6d83862`, Cython 0.29.36 regeneration of the
unchanged frozen `CompressToRLE.pyx`, two independent full runs producing
byte-identical trees):

- accepted source: raw text BWT, symbols `$ACGNT`, newlines ignored;
  `-i` file or stdin (`-i` absent);
- destination: exactly `dstDir/comp_msbwt.npy`, `|u1`, NumPy v1
  handcrafted header (header_len 86, payload offset 96), RLE payload;
- RLE encoding identical to the post-hoc `compress` contract (3 LSB
  letter, 5 MSB count, base-32): converted payloads equal the committed
  post-hoc payloads (`6aadcd54...` uniform, `5566aa4e...` nonuniform);
- canonical artifacts: uniform `121ffb41838b...` (118 B, shape (22,)),
  nonuniform `5fb4520471...` (112 B, shape (16,)); deterministic across
  run-a/run-b and the stdin route, byte-identical across two independent
  oracle executions;
- reader semantics: converted output loads as `RLE_BWT` (total 48/30,
  dollars 8/7), all fixture-derived queries and recovered strings match,
  derived side effects `comp_fmIndex.npy`, `comp_refIndex.npy`,
  `totalCounts.npy` on disposable copies;
- two documented legacy quirks captured as failure contracts:
  (a) everything after the FIRST newline is silently dropped (exit 0;
  `invalid_after_newline` probe, payload `6a9cc3bd...`); (b) an invalid
  symbol before the first newline reaches the raise site but surfaces as
  masked `TypeError: cannot concatenate 'str' and 'int' objects` at
  `MUSCython/CompressToRLE.pyx:77` (exit 1; `invalid_before_newline`
  probe).  Both are preserved byte-for-byte by modern2.

modern2 result: the migrated module (`frozen pyx` + `#cython:
language_level=2`, diff exactly one line) compiled first try under Cython
3.0.12 and produced byte-identical output to the oracle on the first
execution for both cases and both routes.  **No source fix, no
COMPATIBILITY.md deviation, no new policy decision.**

Evidence: `compat/goldens/original-0.3.0/convert-milestone10/`
(convert-evidence.json, determinism, regeneration, profile-provenance,
relationship-convert-vs-posthoc, relationship-reader,
failure-contract-probes, inputs/, uniform/ + nonuniform/
secondary-regenerated-source/ with manifests and artifacts).

## 5. `CompressToRLE` — public/reachable — exact result

Migrated (section 4).  `setup.py` now builds 11 extensions;
`MUSCython/CompressToRLE.py` stub deleted; `CompressToRLE.c` regenerated by
Cython 3.0.12 (banner-pinned, committed per the modern2 generated-C policy;
SHA-256 `e0a9b3eedcc0...`, intentionally different from both the committed
Cython-0.23.4 C and the Cython-0.29.36 oracle regeneration
`1e770078d8ba...`).

## 6. `LCPGen` — NOT public/reachable — result

Classified **C. HISTORICAL/PRIVATE/DEAD**: nothing in the frozen or modern2
codebase imports it (the frozen `setup.py` built it only because the
historical package compiled every `.pyx`), no CLI subcommand reaches it,
and the readers merely *consume* an `lcps.npy` if one exists — no supported
path creates one.  Per milestone policy it was NOT implemented.  The stub
remains importable (preserving the legacy import surface) with a documented
DEAD/PRIVATE classification; calling either function raises
NotImplementedError intentionally.

## 7. `MSBWTGenCython.compressBWT` — NOT public/reachable — result

Classified **exported-but-unreachable historical internal**: the public
`compress` command uses the pure-Python `MUS.MSBWTGen.compressBWT`
(validated m2); nothing calls the Cython duplicate.  Per milestone policy
it was NOT fixed speculatively.  An executed probe (m10 driver + py2
tests) nevertheless proves the unexercised code is consistent with the
established RLE contract under Cython 3.0.12 + `language_level=2`:

- `-p 1` and `-p 2` outputs byte-identical (the `-p 2` route executes the
  typed-division combine site `prevTotal / (numPower**power)` — chunk
  boundary characters match for the uniform input);
- uniform whole-file `0ca6329b54...` == the committed uniform-direct-split
  golden; nonuniform whole-file `07692b30...`; payloads == the post-hoc
  payloads;
- **typed-division execution result**: compiles to correct integer
  behavior under Cython 3.0.12; no arithmetic change was needed (`/` was
  not replaced with `//`).

## 8. `massquery` — public/reachable — validated (m10)

CSV contract on the canonical uniform dataset: `k-mer,counts` lines
(`ACGTN,3 / AAAAA,1 / AGCTA,0 / AA,4`) and with `-r` the
`k-mer,counts,revCompCounts` form (`ACGTN,3,1 / AAAAA,1,1 / AGCTA,0,0 /
AA,4,4`, reverse-complement counts independently verified); two runs
byte-identical.

## 9. Stub policy — final state

| Stub | Classification |
|---|---|
| `MUSCython.LCPGen` (`lcpGenerator`, `linearLcpGenerator`) | DEAD/PRIVATE — intentionally not migrated; importable stub raising NotImplementedError; documented in the stub docstring, this document, and the host/py2 tests |

Unexplained stubs remaining: **none**.  No public CLI or normal public
import contract exposes a functional-looking symbol that silently resolves
to NotImplementedError.

## 10. Legacy bug tracker

`docs/modernization/MODERN2_LEGACY_BUG_TRACKER.md` created with the proven
entries: decompression uint64/int → float64 slice crash (fixed, m3),
multi-block decompression refFM index crash (fixed, m4), pure reader refFM
index crashes (fixed, m5/m7), pure `getFullFMAtIndex` weighted-bincount
casting bug (fixed, m6), `merge -p 1` uninitialized `numProcs` (fixed, m9),
historical `GenericMerge` generated-C segfault (generated-code defect,
preserved, m9), convert newline truncation quirk (documented legacy quirk,
m10), convert masked-TypeError error path (documented legacy quirk, m10).

## 11. Source identity / diff whitelist status

- Frozen sources untouched: `MUSCython/CompressToRLE.pyx` `1ef40aba...`,
  `MUS/CommandLineInterface.py` `5265558e...`, `MUS/MultiStringBWT.py`
  `95ac0b86...` (driver-gated).
- modern2 `CompressToRLE.pyx` vs frozen: exactly `#cython:
  language_level=2` added, nothing removed.
- Existing whitelists unchanged: CLI one-line `numProcs = 1` fix;
  MultiStringBWT 7 added / 6 removed.
- modern2 `CompressToRLE.c` regenerated by Cython 3.0.12 (committed);
  generated-C byte equality is not a compatibility requirement.

## 12. Tests added

- `packages/msbwt-modern2/tests/test_public_surface_py2.py` (Python-2
  suite): import/export smoke matrix, no-unexplained-stub scan, LCPGen
  classification, `convert` byte-identity vs the oracle (uniform,
  nonuniform, stdin, repeated-run determinism), converted-output reader
  semantics, both failure contracts, `massquery` CSV contracts +
  determinism, `compressBWT` p1/p2 probe vs the committed goldens.
- `packages/msbwt-modern2/tests/test_bootstrap_py2.py` updated:
  CompressToRLE moved from stub assertions to migrated-module assertions;
  LCPGen stub test asserts the DEAD/PRIVATE classification.
- `compat/tests/test_modern2_public_surface.py` (host suite): CLI
  inventory/dispatch wiring, import/export matrix, CompressToRLE migration
  whitelists, convert oracle golden consistency (artifacts, evidence,
  relationships, regeneration, harness), LCPGen classification +
  unreachability, compressBWT classification, milestone docs and evidence
  records.
- `compat/tests/test_modern2_bootstrap.py` updated: CompressToRLE moved
  from STUB_MODULES to MIGRATED_MODULES; LCPGen stub assertions updated to
  the classification contract.

## 13. Test counts

- Legacy compatibility suite: 125 tests (unchanged, green).
- Modern2-specific host suite: 132 + 26 = 158 (total compat suite 257 + 26
  = 283, green).
- Modern2 Python-2 suite: 114 + 17 + 1 (bootstrap stub test split) = 132
  tests, green.

## 14. Stop conditions

None triggered: convert semantics were established from executed frozen
behavior (no ambiguity); LCPGen is provably dead/private (not implemented);
`compressBWT` required no arithmetic-policy decision (executed p1 == p2 and
byte-equal to the committed goldens); no existing validated functionality
regressed (all prior evidence untouched); frozen source was not modified;
branch remained `codex/modern2` throughout.

## 15. Files changed

- `packages/msbwt-modern2/MUSCython/CompressToRLE.pyx` — migrated module
  (frozen pyx + `#cython: language_level=2`).
- `packages/msbwt-modern2/MUSCython/CompressToRLE.c` — generated by Cython
  3.0.12 (committed per policy).
- `packages/msbwt-modern2/MUSCython/CompressToRLE.py` — deleted (stub
  replaced by the real module).
- `packages/msbwt-modern2/MUSCython/LCPGen.py` — stub docstring updated to
  the DEAD/PRIVATE classification.
- `packages/msbwt-modern2/setup.py` — `CompressToRLE` added to
  EXTENSION_NAMES (11 extensions).
- `packages/msbwt-modern2/validate/public-surface-milestone10.sh` —
  milestone-10 validation driver.
- `packages/msbwt-modern2/tests/test_public_surface_py2.py` — Python-2
  regression tests.
- `packages/msbwt-modern2/tests/test_bootstrap_py2.py` — stub/migrated
  assertions updated.
- `compat/tests/test_modern2_public_surface.py` — host-side regression
  tests.
- `compat/tests/test_modern2_bootstrap.py` — module lists and stub
  assertions updated.
- `reference/original-0.3.0/environment/convert_oracle_milestone10.sh` —
  committed convert oracle harness.
- `compat/goldens/original-0.3.0/convert-milestone10/` — committed oracle
  evidence (two byte-identical full executions).
- `docs/modernization/MODERN2_MILESTONE10_PUBLIC_SURFACE.md` — this
  document.
- `docs/modernization/MODERN2_LEGACY_BUG_TRACKER.md` — legacy defect
  tracker (8 proven entries).
- `packages/msbwt-modern2/evidence/public-surface-milestone10.json` —
  executed evidence record (byte-identical across two consecutive full
  driver runs).
- `packages/msbwt-modern2/README.md` — stub list updated (minimal).

## 16. Next slice

Modern2 now covers both construction routes, plain and gzip input, the
full reader stack, compression, decompression, the public merge CLI, the
public convert CLI, massquery, and the full public import surface with no
unexplained stubs.  Natural next milestones: release hardening (packaging
exercises for the public commands, sdist verification, install/import from
site-packages), or modern3.
