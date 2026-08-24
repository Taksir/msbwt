# msbwt-modern3 0.3.0 — Release Notes (release candidate)

Branch: `enhanced-modern3`.  Release-candidate packaging validated at
the final repaired HEAD (M3-FINAL-R1, following M3-14/M3-14C).  Nothing
has been pushed, tagged, or published.

## What it is

`msbwt-modern3` is the Python 3 modernization of the MSBWT multi-string
Burrows–Wheeler transform tooling: construction, compression,
decompression, merging, and FM querying of multi-string BWT indexes,
plus the enhanced feature stack carried over from `enhanced-modern2`:
persistent source provenance, per-read provenance, BWT-aligned tags,
lossless FASTQ quality sidecars, LCP construction/validation, source
removal, and storage/run accounting with a backend capability contract.

It exposes the same `MUS` / `MUSCython` import namespaces and the same
`msbwt` command as the frozen Python-2.7 line (`msbwt-modern2`).  The
two distributions must be installed in **separate environments**.

## Release contract

```text
Distribution name   msbwt-modern3          version 0.3.0
Import packages     MUS, MUSCython (+ tools)
Python              CPython >=3.14 (validated: 3.14 on Windows and Linux)
Platforms           Windows x86-64, Linux x86-64 (compiled wheels;
                    no macOS/ARM/universal wheel exists or is claimed)
Runtime dependency  numpy >=2.5,<3 only
Build (sdist)       setuptools>=64, wheel==0.48.0, Cython>=3.2,<3.3,
                    numpy>=2.5,<3, and a C compiler
License             MIT (original UNC-CH copyright preserved)
```

## Artifacts

```text
msbwt_modern3-0.3.0-cp314-cp314-win_amd64.whl
msbwt_modern3-0.3.0-cp314-cp314-linux_x86_64.whl
msbwt_modern3-0.3.0.tar.gz
```

The sdist ships `.pyx`/`.pxd` sources and excludes generated C; all 11
extensions are regenerated during the build.  The authoritative SHA256
digests of the final validated candidates are maintained in
`release-candidate/SHA256SUMS.txt`; superseded M3-14/M3-14C digests are
historical audit records only.

## Validation evidence

- Source-tree compatibility suite at the M3-SOL-R1 repaired HEAD:
  Windows `743 passed / 1 skipped` and clean-layout Linux
  `742 passed / 2 skipped` (22 subtests each).  Both counts are +15 over
  the accepted pre-SOL-R1 baseline (728/727): exactly the new
  length-domain/oracle-integrity regressions.  The single Windows skip is
  the documented memmap/file-lifecycle platform case; the second Linux
  skip is the frozen-modern2 built-artifact check taking its no-artifacts
  branch in a clean layout.  The earlier "722 passed / 7
  environment-dependent failures" summary came from a checkout polluted by
  legacy root-level binaries and is superseded historical evidence only.
- Fresh-environment installs of both wheels and the sdist pass the
  installed battery on both platforms (construction from FASTQ, byte/RLE
  round trips, provenance-preserving merge, query/-d semantics, exact LCP
  construct/validate, source removal with input immutability, BAM
  rejection, and the >2^32 compiled length-boundary probes).
- Cross-platform persistence spot check: a package built by the
  installed Windows wheel consumed by the installed Linux wheel
  (and reverse) preserves payload hashes, recovery results, RLE bytes,
  provenance manifests, quality, LCP, and interleave semantics.
- Installed CLI: all seven console entry points verified on both
  platforms.

## Known limitations

- **BAM/SAM input is explicitly unsupported.**  The legacy pysam-based
  ingestion entry points raise `NotImplementedError`; pysam is not a
  dependency.  Build indexes from FASTA/FASTQ instead.
- **LZW-compressed indexes cannot be created** by this release (no
  encoder exists), and LZW behavioral round-trip validation is absent;
  the legacy reader remains present but carries no validation claim.
- Multimerge does not support a single read longer than 2^32 bases
  (total index sizes beyond 2^32 symbols are supported).
- GenericMerge's disk-backed branch above its internal ~1 GB in-memory
  threshold is parity-tested via lowered-threshold probes; a literal
  production-scale >1 GB run has not been executed.
- Importing the compiled reader submodules directly on a cold
  interpreter (`MUSCython.ByteBWTCython`, `RLE_BWTCython`,
  `LZW_BWTCython`) raises `ImportError` due to a pre-existing circular
  initialization order; import `MUSCython.MultiStringBWTCython` first
  or use `MultiStringBWT.loadBWT`.
- The legacy pure-Python fallbacks (`MUS.MSBWTGen.compressBWT`,
  `MUS.MultiStringBWT.createMSBWTFromFastq`/`createFromSeqs`) are
  reference-only: the pure-Python compressor retains an extreme-single-
  run `<u4` exposure beyond roughly 4 GiB, and the pure-Python
  construction chain cannot complete normally on native Windows
  (open-memmap blocks an intermediate deletion).  The compiled paths
  are unaffected.

## Relationship to modern2

Modern3 reproduces the established legacy semantics against the frozen
`enhanced-modern2` oracle and reads/writes the established persisted
formats (byte identity where the contract requires it, semantic
portability elsewhere).  Modern2 remains available, unchanged, as the
frozen Python-2.7 line; see `MODERN2_RELEASE_NOTES.md` and
`MODERN2_ENHANCED_RELEASE_NOTES.md`.
