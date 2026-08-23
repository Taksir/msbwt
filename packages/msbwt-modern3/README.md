# msbwt-modern3

Python 3 distribution of the MSBWT multi-string Burrows–Wheeler transform
tooling: construction, compression, merging, and querying of multi-string
BWT indexes, with persistent source provenance, per-read provenance, row
tags, exact FASTQ quality sidecars, and LCP (longest-common-prefix) layers.

This distribution is intentionally separate from the frozen Python 2.7
oracle (`packages/msbwt-modern2/`) and from the frozen legacy root at the
repository top level. The two distributions expose the same `MUS` /
`MUSCython` import namespaces, so they must be installed in **separate
environments**.

## Requirements

- CPython 3.14 (the validated release environment; the metadata floor is
  `>=3.14`)
- NumPy >= 2.5, < 3
- A C compiler when building from source (the wheel is self-contained)

## Installation

```bash
pip install msbwt_modern3-0.3.0-cp314-cp314-win_amd64.whl   # Windows
pip install msbwt_modern3-0.3.0-cp314-cp314-linux_x86_64.whl # Linux
```

## Supported functionality

All of the following are exercised by the compatibility suite on native
Windows and Linux:

- Uniform and non-uniform index construction from FASTA/FASTQ (compiled
  paths; non-uniform input uses the Multimerge engine)
- Byte (uncompressed) and RLE (compressed) indexes: build, load, query,
  recovery, compression, decompression
- GenericMerge pairwise merging and balanced/unbalanced multi-way merges,
  with persistent source provenance manifests and interleaves
- FM queries (`findIndicesOfStr`, occurrence counts) and rank/Occurrence
  access
- Source removal / retention without FASTQ reconstruction
- Per-read provenance, row tags, exact FASTQ quality sidecars (255 marks
  terminal-`$` rows), LCP construction/validation
- Storage accounting, run statistics, benchmark hooks, backend capability
  reporting

## Command line

```bash
msbwt pp -u OUT uniform-a.fastq uniform-b.fastq
msbwt cfpp -p 1 -u OUT
msbwt cffq -p 1 -u OUT uniform-a.fastq uniform-b.fastq
msbwt merge -p 1 OUT.merged A_DIR B_DIR
msbwt query OUT ACGTN
msbwt compress -p 1 OUT OUT.rle
msbwt decompress -p 1 OUT.rle OUT.byte
```

Additional tool entry points: `msbwt-bwt-tags`, `msbwt-lcp`,
`msbwt-quality-sidecar`, `msbwt-remove-sources`,
`msbwt-retrofit-read-provenance`, `msbwt-benchmark-index`.

## Explicit limitations

- **BAM/SAM input is not supported.** The legacy pysam-based ingestion
  entry points raise `NotImplementedError`; pysam is not a dependency.
- **LZW-compressed indexes cannot be created** by this release (no encoder),
  and LZW round-trip behavior is unvalidated; loading an existing LZW
  container may work but carries no validation claim.
- A single read longer than 2^32 bases is unsupported by the Multimerge
  engine (total index sizes beyond 2^32 symbols are fully supported).
- The legacy pure-Python fallbacks (`MUS.MSBWTGen.compressBWT`,
  `MUS.MultiStringBWT.createMSBWTFromFastq`/`createFromSeqs` chain) are
  retained for reference and are not part of the supported cross-platform
  contract; the compiled paths are the supported surface.

## License

MIT (see `LICENSE`; Copyright (C) 2014 UNC-CH CS Dept.).
