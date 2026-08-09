# MSBWT Modernization

> **Status: active modernization work — not production-ready and not yet released.**

This repository is a modernization fork of the original [`holtjma/msbwt`](https://github.com/holtjma/msbwt) project.

MSBWT is a bioinformatics package for building, merging, compressing, decompressing, and querying **multi-string Burrows-Wheeler transforms (MSBWTs)** from sequencing data. The original implementation was written for Python 2.7 and includes substantial Cython code. The original package supports creation and merging of MSBWTs and k-mer querying over the resulting data structure.

The purpose of this fork is **not to redesign MSBWT from scratch**. The goal is to preserve the original algorithms, command-line interface, public APIs, import paths, and on-disk MSBWT formats as closely as possible while making the project maintainable on modern systems.

## Project goals

The intended end state is two separately installable distributions:

- **`msbwt-modern2`**
  - Python 2.7
  - Cython 3.0.x
  - newest practical dependencies that still support Python 2.7
  - intended mainly for legacy compatibility and reproducibility

- **`msbwt-modern3`**
  - current stable Python 3
  - current stable Cython, NumPy, pysam, and modern build tooling
  - intended to become the primary maintained implementation

Both distributions are intended to preserve, wherever technically possible:

- the existing `msbwt` CLI commands and options;
- existing public API behavior;
- existing `MUS` and `MUSCython` import paths;
- readability of datasets produced by the original implementation;
- readability of modern datasets by older implementations where the format permits it;
- bit-for-bit identical persistent output files for unchanged behavior.

Correctness and security take precedence over preserving known bugs. Any intentional behavioral or format deviation will be documented.

## Current status

**Estimated overall modernization progress: ~30–35%.**

This percentage is only a project-planning estimate, not a release-readiness score. The repository audit and the first authoritative legacy baseline are complete, but the actual `modern2` and `modern3` implementation ports have **not started yet**. The current handoff explicitly records that no modern2 or modern3 port has begun.

### Completed

- [x] Forked and preserved the original Git history and attribution.
- [x] Audited the Python, Cython, build, CLI, API, persistence, dependency, platform, and security surfaces.
- [x] Identified the public CLI/API compatibility surface.
- [x] Documented persistent MSBWT file formats and legacy inconsistencies.
- [x] Designed a monorepo architecture for separate `modern2` and `modern3` distributions with shared compatibility tests.
- [x] Created deterministic synthetic FASTQ fixtures.
- [x] Created safe binary/NumPy artifact-manifest tooling.
- [x] Reconstructed a genuine CPython 2.7 legacy oracle under WSL2 without modifying the frozen original implementation.
- [x] Locked the verified legacy environment using exact package/artifact hashes.
- [x] Verified all 40 frozen implementation/package files against original commit `7503346`.
- [x] Generated and committed genuine Python-2 golden outputs for the first uniform, uncompressed construction path.
- [x] Repeated the oracle build independently and confirmed bit-for-bit identical preprocessing and build artifacts.
- [x] Verified that the frozen reader can load the promoted dataset and return expected query results.
- [x] Added regression tests protecting the frozen source, fixtures, golden bytes, NumPy headers, and artifact manifests.

The completed handoff records two independent successful `uniform-multifile` runs, exact environment locks, committed goldens, and a 28-test host-side verification suite.

## Verified legacy baseline

The current verified oracle profile uses:

- Ubuntu 26.04 LTS under WSL2 x86-64
- CPython 2.7.18
- GCC 7.3.0
- NumPy 1.16.6
- pysam 0.15.4
- Cython 0.29.36
- pip 20.3.4
- setuptools 44.1.1
- wheel 0.37.1

This is a **verified late-Python-2 environment**, not a claim that it exactly reproduces the dependency stack originally used by the MSBWT authors.

The first promoted golden case runs the original CLI:

```bash
msbwt pp -u OUTPUT uniform-a.fastq uniform-b.fastq
msbwt cfpp -p 1 -u OUTPUT
```

Two independent runs produced identical file sets, raw NumPy headers, payload hashes, and whole-file SHA-256 values.

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

These values and the promoted artifact hash are part of the committed golden contract.

## What is not done yet

This fork should **not** currently be treated as a finished replacement for the original MSBWT package.

Major work still remains:

- [ ] Verify the committed Python-2 reconstruction script from a completely fresh environment/prefix.
- [ ] Add non-uniform FASTQ preprocessing/build goldens.
- [ ] Add gzip FASTQ goldens.
- [ ] Characterize compressed construction.
- [ ] Characterize compression and decompression.
- [ ] Characterize query/index side effects and derived index files.
- [ ] Characterize merge behavior.
- [ ] Characterize interruption/recovery behavior.
- [ ] Expand API and CLI regression coverage.
- [ ] Characterize multiprocessing and determinism across process counts.
- [ ] Establish additional public biological fixtures.
- [ ] Build `msbwt-modern2` using Python 2.7 + Cython 3.0.x.
- [ ] Validate `modern2` against legacy golden outputs.
- [ ] Build the Python 3 / modern Cython implementation.
- [ ] Validate old-reader/new-writer and new-reader/old-writer compatibility.
- [ ] Add native Windows support and CI.
- [ ] Add Linux/HPC CI.
- [ ] Add macOS support and CI where feasible.
- [ ] Add wheel/sdist release workflows.
- [ ] Fix confirmed correctness and security issues with documented compatibility entries.
- [ ] Establish benchmark baselines.
- [ ] Optimize performance only after compatibility is established.
- [ ] Publish separately installable `msbwt-modern2` and `msbwt-modern3` releases.

Only the uniform uncompressed build path and a small reader smoke currently have golden coverage; nonuniform/gzip, compressed build, compression/decompression, recovery, merge, indexing, and broader API/CLI behavior remain open.

## Next milestone

The immediate next step is **additional frozen-oracle characterization**, not source modernization.

The next two synthetic cases are:

1. **Non-uniform FASTQ**
   ```bash
   msbwt pp OUTPUT nonuniform.fastq
   msbwt cfpp -p 1 OUTPUT
   ```

2. **Gzip FASTQ**
   ```bash
   msbwt pp OUTPUT uniform-a.fastq.gz nonuniform.fastq.gz
   msbwt cfpp -p 1 OUTPUT
   ```

Each successful legacy case must be executed independently at least twice and produce identical retained files, whole-file hashes, raw NumPy headers, logical dtypes/shapes, and payload hashes before its outputs are promoted as authoritative goldens.

Compression/decompression and recovery characterization follow after these cases.

## Compatibility philosophy

Modernization work follows several rules:

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

## Repository direction

The planned architecture is a single repository containing two independent distributions and shared compatibility infrastructure:

```text
reference/original-0.3.0/   frozen legacy oracle
packages/msbwt-modern2/     Python 2.7 distribution
packages/msbwt-modern3/     modern Python 3 distribution
compat/                     fixtures, goldens, manifests, differential testing
tests/                      shared and target-specific tests
benchmarks/                 reproducible performance tests
docs/                       architecture, compatibility, migration, security
```

The two planned distributions will keep independent build metadata/environments while sharing format specifications, fixtures, goldens, and differential tests.

## Installation

### Modernized packages

**Not available yet.**

Do not expect either of these to work yet:

```bash
pip install msbwt-modern2
pip install msbwt-modern3
```

They are planned distribution names, not current releases.

### Original implementation

The repository still contains the original MSBWT source for compatibility and oracle work, but it depends on a legacy Python 2/Cython ecosystem and should not be considered a normal modern installation target.

If you need the historical package today, refer to the original project:

- https://github.com/holtjma/msbwt

The original README targeted Python 2.7 and documented old NumPy/pysam-era installation instructions.

## Original MSBWT functionality

The original package provides tools for:

- constructing MSBWTs from sequencing data;
- preprocessing FASTQ data;
- merging MSBWT datasets;
- querying k-mers;
- bulk/mass queries;
- run-length compression;
- decompression;
- conversion from raw text BWTs;
- Python/Cython APIs for interactive querying and analysis.

The original README documents these operations through `cffq`, `pp`, `cfpp`, `merge`, `query`, `massquery`, `compress`, `decompress`, and `convert`.

## Known modernization risks

The audit has identified several areas requiring careful treatment:

- Python 2 integer-division semantics;
- Python 2 `str` versus Python 3 text/bytes behavior;
- Cython 0.x/3.x semantic differences;
- NumPy `.npy` header differences across versions;
- files with `.npy` names that are not always ordinary NumPy containers;
- Python/C integer-width assumptions, especially on Windows;
- binary files historically opened using text-mode C I/O;
- unsafe legacy pickle/object-array loading;
- unchecked Cython memory accesses on malformed data;
- mutation of derived indexes during reads;
- multiprocessing and filesystem-order determinism;
- legacy and overlapping construction algorithms.

These are why the project is using strict characterization and golden-output testing rather than a direct automated Python-2-to-Python-3 translation.

## Documentation

Modernization design and evidence live under `docs/modernization/`.

Important documents include:

- `HANDOFF.md` — current project state and exact next milestone;
- `LEGACY_ORACLE_STATUS.md` — executed legacy environment and oracle results;
- `FORENSIC_AUDIT.md` — source/build/platform/security audit;
- `BEHAVIORAL_SURFACE.md` — CLI, API, and persistent-file inventory;
- `COMPATIBILITY_TESTING.md` — regression and reader/writer test strategy;
- `ARCHITECTURE.md` — proposed modern2/modern3 repository architecture;
- `RISKS_AND_OPEN_QUESTIONS.md` — unresolved compatibility and engineering risks.

## Project maturity

This repository is currently best described as:

> **an evidence-driven modernization effort with a verified legacy baseline, not yet a modernized release.**

The project has deliberately spent significant effort establishing what the original implementation actually does before changing it. This makes progress appear slower than a direct Python-2-to-Python-3 translation, but it is necessary to preserve scientific reproducibility and binary compatibility.

Contributions and review are welcome, but users should not yet depend on this fork as a production replacement for the original package.

## Provenance and attribution

This work is based on the original MSBWT implementation by **James Holt** and collaborators at UNC-Chapel Hill. The original algorithms, authorship, scientific publications, and MIT license remain credited and preserved.

This fork is a modernization and maintenance effort; it does not claim authorship of the original MSBWT algorithms or implementation.

## References

Holt, James, and Leonard McMillan.  
**“Merging of multi-string BWTs with applications.”**  
*Bioinformatics* (2014): btu584.

Holt, James, and Leonard McMillan.  
**“Constructing Burrows-Wheeler transforms of large string collections via merging.”**  
*Proceedings of the 5th ACM Conference on Bioinformatics, Computational Biology, and Health Informatics.* ACM, 2014.

The original README also cites the MSBWT construction approach described by Bauer et al. in **“Lightweight BWT construction for very large string collections.”**

## License

The original project is distributed under the MIT License. Original copyright, license, attribution, and scientific references are preserved in this fork.
