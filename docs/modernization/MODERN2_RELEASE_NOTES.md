# MODERN2 — Release notes: compatibility baseline (release candidate)

Distribution: `msbwt-modern2` version `0.3.0`
Baseline commit: `2f5c0a4` (Q1 audit) + release-candidate hygiene commits on
`codex/modern2`
Status: **release candidate** — prepared, validated, not yet tagged/published.

This baseline is frozen except for critical release-blocking fixes.  New
research features will be developed separately on a future
`enhanced-modern2` track.

## Preserved

- Original public MSBWT functionality: all 9 CLI commands (`cffq`, `pp`,
  `cfpp`, `merge`, `query`, `massquery`, `compress`, `decompress`,
  `convert`) and global flags (`-V`, `-h`, `-u`, `-c`, `-p`, `-d`, `-r`,
  `-i`).
- Public import surface: `MUS` (`CommandLineInterface`, `MSBWTGen`,
  `MultiStringBWT`, `TranscriptBuilder`, `util`) and `MUSCython` (11
  compiled modules + the `LCPGen` DEAD/PRIVATE stub).
- Persistent MSBWT formats and byte-level output where compatibility
  requires it (construction, post-hoc compression, merge, convert).
- Original algorithms, original authors, MIT license, scientific
  references, and repository history.

## Modernized

- Reproducible Python-2.7 environment: CPython 2.7.18 (`cp27mu`/UCS4),
  bootstrap script with hash-verified conda/wheel locks
  (`packages/msbwt-modern2/environment/`).
- Cython toolchain: exactly **Cython 3.0.12** (last Cython 3.0.x;
  Cython 3.1+ prohibited), `language_level=2`, generated C committed per
  the modern2 generated-C policy; historical Cython-0.23.4 generated C is
  no longer used.
- Independent distribution: `msbwt-modern2` (setup.py, MANIFEST.in,
  README/LICENSE/AUTHORS, `bin/msbwt` script), sdist + wheel built under
  the pinned environment.
- Packaging/build structure validated by fresh-prefix installs of both the
  sdist and the wheel.

## Fixed (proven defects only; see MODERN2_LEGACY_BUG_TRACKER.md)

- Decompression crash (`TypeError: slice indices must be integers...` at
  `MUS/MultiStringBWT.py:662`) caused by `<u8`/int → `float64` promotion.
- Multi-block decompression crash (line 630) for >1,000,000-symbol RLE
  inputs.
- Pure reader `refFM` index construction crashes during `loadBWT` /
  `constructIndexing`.
- Pure reader `getFullFMAtIndex` weighted-`bincount` fill defect
  (wrong FM rows).
- `merge -p 1` `UnboundLocalError: numProcs` (documented deviation,
  COMPATIBILITY.md entry 2).
- Historical `MUSCython/GenericMerge.c` deterministic SIGSEGV —
  eliminated by regenerating the migrated `GenericMerge.pyx` with
  Cython 3.0.12.

Preserved legacy quirks (documented, not fixed): `convert` newline
truncation and the masked invalid-symbol `TypeError` error path.

## Validated

- 125 legacy-compatibility host tests + 158 modern2 host tests = 283
  total compat suite, green.
- 133 modern2 Python-2 tests, green (inside the pinned environment; 132
  at the Q1 baseline + 1 multi-digit RLE regression added by the
  release-candidate hygiene pass).
- 24 Q1 audit-harness host tests, green.
- Q1 randomized differential audit (seed `20260810`, executed twice,
  byte-identical summaries): 225 generated collections (165 audited + 60
  merge-role), 18 input categories, 20 merge pairs; three-way
  frozen/modern2/oracle classification: 260 A, 0 B/C/D/E; zero modern2
  regressions; zero new legacy bugs.  (Process-count caveat: 45 of 165
  constructions exercised `-p 2`; see MODERN2_Q1_AUDIT.md §6.2/§6.3.)
- Frozen-source verification (40 hash-pinned files) and fixture
  verification pass.
- Fresh-install validation (release-candidate): sdist and wheel each
  clean-installed into brand-new bootstrapped Python-2.7 prefixes;
  imports resolve from site-packages only; all 9 CLI commands execute
  through the installed distributions; canonical workflow
  (`pp -> cfpp -> query -> compress -> RLE query -> decompress -> byte
  query`) and `merge -p 1`/`-p 2` and `convert` reproduce the committed
  golden hashes; isolated runs (clean environment, outside the
  repository) pass.

## Known limitations

- Python 2.7 baseline by design; no Python 3 support.
- Reference release validated on Linux x86-64 (Ubuntu 26.04 on WSL2)
  only; no other platform is claimed.
- `MUSCython.LCPGen` is an intentional DEAD/PRIVATE stub.
- No modern3 completion claim.
- Malformed/corrupt artifact handling is not exhaustively hardened.
- Committed RLE goldens contain only single-digit runs; multi-digit RLE
  coverage exists in the audit corpus and the Python-2 regression suite,
  but not as a committed golden.
- Nonuniform-route byte ordering is characterized semantically rather
  than byte-for-byte (the strongest invariant the frozen route supports).
- Artifact bytes are not timestamp-reproducible (archive metadata
  differs between builds); extracted contents are byte-identical (see
  `packages/msbwt-modern2/evidence/release-candidate.json`).

## Not included

No upcoming research features are part of this release.
