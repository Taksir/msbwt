# MSBWT Modernization

This repository is a modernization fork of the original [`holtjma/msbwt`](https://github.com/holtjma/msbwt) project.

MSBWT is a bioinformatics package for building, merging, compressing, decompressing, and querying **multi-string Burrows-Wheeler transforms (MSBWTs)** from sequencing data. The original implementation was written for Python 2.7 and includes substantial Cython code.

The purpose of this fork is **not to redesign MSBWT from scratch**. The goal is to preserve the original algorithms, command-line interface, public APIs, import paths, and on-disk MSBWT formats as closely as possible while making the project maintainable on modern systems.

> **Status: the `msbwt-modern2` compatibility baseline is COMPLETE and release-ready.**
> `msbwt-modern3` has not been started.

## Project status

### `msbwt-modern2` — complete (release candidate)

The Python-2.7 / Cython-3.0.12 compatibility baseline is feature-complete,
regression-tested, and validated as an independently installable
distribution:

- all 9 public CLI commands (`cffq`, `pp`, `cfpp`, `merge`, `query`,
  `massquery`, `compress`, `decompress`, `convert`) restored and validated;
- uniform and nonuniform construction, plain and gzip input, byte and RLE
  readers, compression, decompression (including >1M-symbol multi-block
  inputs), merge, and convert;
- public `MUS` / `MUSCython` import surface with no unexplained stubs
  (`LCPGen` is a classified DEAD/PRIVATE stub);
- persistent outputs byte-equal to the committed frozen oracle goldens
  where compatibility requires it;
- proven historical defects corrected and documented (see
  `docs/modernization/MODERN2_LEGACY_BUG_TRACKER.md`);
- randomized Q1 differential audit: 225 generated collections, 18 input
  categories, 20 merge pairs, three-way frozen/modern2/oracle
  classifications — 260 A-classifications, zero disagreements, zero
  modern2 regressions (`docs/modernization/MODERN2_Q1_AUDIT.md`);
- sdist and wheel built under the pinned environment, fresh-installed into
  brand-new Python-2.7 prefixes, and validated end-to-end through the
  installed CLI (see `packages/msbwt-modern2/README.md` and
  `packages/msbwt-modern2/evidence/release-candidate.json`).

The modern2 baseline is **frozen** except for critical release-blocking
fixes. New research features will be developed separately on a future
`enhanced-modern2` track.

### `msbwt-modern3` — not started

The Python 3 track is planned (current stable CPython, modern Cython/NumPy/
pysam, modern build tooling) but **no implementation work has begun**. Do
not treat anything in this repository as a Python 3 release.

## Repository structure

```text
reference/original-0.3.0/   frozen historical oracle (40 hash-pinned files)
packages/msbwt-modern2/     COMPLETE: Python-2.7/Cython-3.0.12 compatibility
                            baseline, independently installable distribution
                            (setup.py, MUS/, MUSCython/, bin/msbwt,
                            environment/ locks, tests/, validate/, evidence/)
packages/msbwt-modern3/     future separate modernization track (not created)
compat/                     shared fixtures, goldens, manifests, compatibility
                            tests, and the Q1 audit harness
docs/modernization/         handoff, milestone reports, bug tracker, audit doc
MUS/ MUSCython/ setup.py    frozen-original sources kept for oracle reference
```

Key entry points:

- package README: `packages/msbwt-modern2/README.md` (installation, quick
  start, CLI, compatibility, fixed bugs, validation, limitations);
- current handoff: `docs/modernization/HANDOFF.md`;
- legacy defect tracker: `docs/modernization/MODERN2_LEGACY_BUG_TRACKER.md`;
- Q1 randomized differential audit: `docs/modernization/MODERN2_Q1_AUDIT.md`;
- milestone reports: `docs/modernization/MODERN2_MILESTONE*.md`;
- release notes: `docs/modernization/MODERN2_RELEASE_NOTES.md`.

## Verified legacy baseline

The frozen oracle profile used for goldens is `py27-late-05a7d6d83862`
(Ubuntu 26.04 LTS under WSL2 x86-64, CPython 2.7.18, GCC 7.3.0, NumPy
1.16.6, pysam 0.15.4, Cython 0.29.36). The modern2 reference profile is
`modern2-python27-3.0.12` (same host family, Cython exactly 3.0.12). Exact
artifact URLs and hashes are in `reference/original-0.3.0/environment/` and
`packages/msbwt-modern2/environment/`.

The first promoted golden case runs the original CLI:

```bash
msbwt pp -u OUTPUT uniform-a.fastq uniform-b.fastq
msbwt cfpp -p 1 -u OUTPUT
```

For the resulting primary BWT:

```text
msbwt.npy
dtype:  |u1
shape:  (48,)
SHA256: dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f
```

A frozen-reader smoke test returned:

```text
ACGTN = 3
AAAAA = 1
CCCCC = 1
AGCTA = 0
```

These values and the promoted artifact hash are part of the committed golden contract, and modern2 reproduces them byte-for-byte.

## What is not done yet

This fork should **not** be treated as a finished replacement for every
historical MSBWT use case. Remaining work:

- `msbwt-modern3` (Python 3) implementation and validation;
- publishing `msbwt-modern2` to a public package index (the release
  artifacts are built and validated locally; publication is a separate,
  manual step);
- native Windows/macOS support (only the Linux x86-64 reference profile is
  executed);
- CI, benchmark baselines, and performance optimization (deliberately
  deferred until after compatibility is established);
- broadening malformed/corrupt-artifact hardening.

## Compatibility philosophy

1. **The original implementation is an oracle, not something to silently repair.**  
   Existing behavior must first be characterized before changing the corresponding implementation.
2. **Golden outputs are immutable evidence.**  
   A modern implementation producing different bytes is not enough reason to update the expected output.
3. **Correctness and security fixes are allowed to change behavior.**  
   Such changes must be documented explicitly, including their compatibility impact.
4. **Algorithms are preserved during initial migration.**  
   Refactoring and optimization come after behavioral parity and benchmark baselines.
5. **Platform support must be demonstrated.**  
   A platform is not considered supported merely because it can run Python.

These principles are part of the current handoff and compatibility contract.

## Installation

Do **not** expect `pip install msbwt-modern2` from a public index — the
distribution has not been published there. To install, follow the verified
procedure in [`packages/msbwt-modern2/README.md`](packages/msbwt-modern2/README.md):
bootstrap the pinned Python-2.7 environment with
`packages/msbwt-modern2/environment/bootstrap-modern2.sh`, then
`pip install` the built wheel or sdist (`--no-deps`) into that environment.

The original Python-2/Cython-0.x source tree in this repository is kept for
oracle/reference work only and is not a normal installation target.

## Documentation

Modernization design and evidence live under `docs/modernization/`:

- `HANDOFF.md` — current project state and exact next milestone;
- `MODERN2_LEGACY_BUG_TRACKER.md` — proven legacy defects and their status;
- `MODERN2_Q1_AUDIT.md` — randomized differential + invariant audit;
- `MODERN2_RELEASE_NOTES.md` — release notes for this baseline;
- `MODERN2_MILESTONE*.md` — per-milestone executed evidence;
- `LEGACY_ORACLE_STATUS.md`, `BEHAVIORAL_SURFACE.md`, `ARCHITECTURE.md`,
  `COMPATIBILITY_TESTING.md`, `FORENSIC_AUDIT.md`, `RISKS_AND_OPEN_QUESTIONS.md`
  — audit and design records.

## Provenance and attribution

This work is based on the original MSBWT implementation by **James Holt**
and collaborators at UNC-Chapel Hill. The original algorithms, authorship,
scientific publications, and MIT license remain credited and preserved
(see `LICENSE` and `AUTHORS`).

This fork is a modernization and maintenance effort; it does not claim
authorship of the original MSBWT algorithms or implementation.

## References

Holt, James, and Leonard McMillan.  
**"Merging of multi-string BWTs with applications."**  
*Bioinformatics* (2014): btu584.

Holt, James, and Leonard McMillan.  
**"Constructing Burrows-Wheeler transforms of large string collections via merging."**  
*Proceedings of the 5th ACM Conference on Bioinformatics, Computational Biology, and Health Informatics.* ACM, 2014.

The original README also cites the MSBWT construction approach described by Bauer et al. in **"Lightweight BWT construction for very large string collections."**

## License

The original project is distributed under the MIT License. Original copyright, license, attribution, and scientific references are preserved in this fork.
