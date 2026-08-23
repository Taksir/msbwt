# msBWT

Multi-string Burrows–Wheeler Transform (MSBWT) tools for genomic strings:
building, merging, compressing, decompressing, and querying **multi-string
Burrows–Wheeler transforms** built from sequencing data.

This repository is a maintenance fork of the original
[`holtjma/msbwt`](https://github.com/holtjma/msbwt) project (James Holt,
Leonard McMillan, and collaborators at UNC-Chapel Hill).  It preserves the
original algorithms, command-line interface, public APIs, import paths,
and on-disk formats, while making the project maintainable on modern
systems and adding verified source-aware features on top.

> **Status:** the `msbwt-modern2` compatibility baseline is **complete and
> release-ready**; the `enhanced-modern2` feature track (source-aware
> queries, provenance, source removal, tags, quality, LCP, benchmarking)
> is **complete and release-ready** on branch `enhanced-modern2`.
> `msbwt-modern3` (Python 3) is the **active line**: a verified release
> candidate (0.3.0) exists on branch `enhanced-modern3` — CPython >=3.14,
> Windows x86-64 + Linux x86-64 compiled wheels plus sdist.  See
> [`packages/msbwt-modern3/README.md`](packages/msbwt-modern3/README.md).

## What this version adds

- **`msbwt-modern3`** — the Python 3 modernization (CPython >=3.14,
  NumPy >=2.5): the full legacy CLI plus the enhanced feature stack
  (provenance, read provenance, source removal, tags, lossless quality
  sidecar, LCP, benchmarking) on compiled 64-bit wheels for Windows and
  Linux x86-64.  BAM input is explicitly unsupported in this line; see
  [`packages/msbwt-modern3/README.md`](packages/msbwt-modern3/README.md)
  for the supported surface and known limitations.
- **`msbwt-modern2`** — a reproducible Python-2.7 / Cython-3.0.12
  modernization of the original package: all nine legacy CLI commands
  restored, persistent outputs byte-equal to the committed frozen goldens
  where compatibility requires it, documented historical defects fixed,
  and an independently installable distribution (sdist + wheel).
- **`enhanced-modern2`** — additive, verified features that keep the
  legacy surface untouched:

  - **source-aware queries**: one merged FM search answers per-source
    counts, sparse nonzero-source listing, source frequency, and exact
    top-k sources;
  - **multi-source provenance**: persistent, identity-preserving merges
    of any number of sources (`provenance.json`);
  - **read-level provenance**: exact owning-read identity for every BWT
    row (`read_provenance.npy`);
  - **source removal / unmerge**: drop selected sources from a merged
    index without rebuilding from FASTQ;
  - **metadata groups and predicates** (`source_metadata.json`), separate
    from immutable source identity;
  - **BWT-aligned tag arrays** and a **lossless FASTQ quality sidecar**
    (byte-exact quality ASCII, no Phred quantization);
  - **post-construction LCP** retrofit (`lcps.npy`), no FASTQ or rebuild;
  - **whole-index benchmarking** and a machine-readable **backend
    contract** (accounting only — no new compressed backend).

Full details, milestone documents, and executed evidence live under
`docs/enhanced-modern2/`; user documentation is on the
[project wiki](https://github.com/Taksir/msbwt/wiki).

## Enhanced feature overview

| Capability | What it provides | Primary interface |
|---|---|---|
| Source-aware counts | Exact per-source occurrence counts from one merged FM search | `MUS.SourceIndex.TwoSourceBWT`, `MUS.MultiSourceQuery.MultiSourceBWT` |
| Multi-source provenance | Persistent identity-preserving merges of any number of sources | `MUS.MultiSourceProvenance.merge_many_balanced` |
| Constituent queries | Query one source inside a multi-merged MSBWT | `MultiSourceBWT.countOccurrencesForSource` |
| Sparse source listing | List only sources with nonzero counts, with exact counts | `MultiSourceBWT.nonzeroSources` |
| Source frequency | Number of distinct sources containing a sequence | `MultiSourceBWT.sourceFrequency` |
| Top-k sources | Highest-count sources with deterministic ordering | `MultiSourceBWT.topSources` |
| Metadata/subset queries | Named groups and key/value predicates over sources | `MUS.SourceMetadata`, `countGroup` / `countWhere` |
| Sequence extensions | Source-aware left (`cP`) and right (`Pc`) base extension | `MultiSourceBWT.extendLeft` / `extendRight` |
| Read provenance | Exact owning read, origin file/read IDs, mates | `MUS.ReadProvenance.ReadProvenanceIndex`, `readsContaining` |
| Source removal | Unmerge selected sources without FASTQ rebuild | `MUS.SourceRemoval.remove_sources` / `retain_sources` |
| BWT-aligned tags | Arbitrary row-aligned arrays surviving merge/removal | `MUS.BWTTags.BWTTagStore`, `attach_tag` |
| FASTQ quality sidecar | Lossless byte-exact quality, row-aligned | `MUS.QualitySidecar`, reserved tag `fastq_quality_ascii` |
| LCP retrofit | Exact adjacent LCP over the final BWT | `MUS.LCP.construct_lcp_from_bwt`, `LCPIndex` |
| Benchmarking/backend contract | Storage, run, structural, and query accounting | `MUS.Benchmarking`, `MUS.BackendContract` |

Each enhanced capability is an additive pure-Python `MUS.*` module with
its own milestone document, tests, and executed evidence; none of them
modify the legacy construction, merge, reader, FM, or
compression/decompression code.

## Installation

There are two independent distributions; install them in **separate
environments** (they expose the same `MUS`/`MUSCython` import names and
the same `msbwt` command).

**Python 3 (current line):** install `msbwt-modern3` from the built
artifacts — a CPython 3.14 wheel for Windows x86-64 or Linux x86-64, or
the sdist (requires a C compiler); see
[`packages/msbwt-modern3/README.md`](packages/msbwt-modern3/README.md).

**Python 2.7 (frozen legacy line):** do not expect
`pip install msbwt-modern2` from a public index — the distribution has
not been published there.  To install, follow the verified procedure in
[`packages/msbwt-modern2/README.md`](packages/msbwt-modern2/README.md):
bootstrap the pinned Python-2.7 environment with
`packages/msbwt-modern2/environment/bootstrap-modern2.sh`, then
`pip install` the built wheel or sdist (`--no-deps`) into that
environment.

The modern2 verified reference profile is Ubuntu 26.04 LTS on WSL2
x86-64 with CPython 2.7.18, Cython exactly 3.0.12, NumPy 1.16.6,
pysam 0.15.4 (pip/setuptools/wheel 20.3.4/44.1.1/0.37.1); native 64-bit
Windows is also supported for that line.

Installing the distribution also installs the legacy `msbwt` command and
six enhanced console scripts: `msbwt-bwt-tags`, `msbwt-lcp`,
`msbwt-quality-sidecar`, `msbwt-remove-sources`,
`msbwt-retrofit-read-provenance`, `msbwt-benchmark-index`.

## Building an MSBWT

```bash
# preprocess FASTQ, then build (uniform read lengths)
msbwt pp -u OUT uniform-a.fastq uniform-b.fastq
msbwt cfpp -p 1 -u OUT

# or build directly from FASTQ
msbwt cffq -p 1 -u OUT uniform-a.fastq uniform-b.fastq

# merge two existing MSBWTs
msbwt merge -p 1 OUT.merged A_DIR B_DIR

# compress to RLE and decompress back to byte
msbwt compress -p 1 OUT OUT.rle
msbwt decompress -p 1 OUT.rle OUT.byte

# convert an external raw BWT text file to RLE
msbwt convert -i raw.txt OUT
```

## Querying

```bash
# single k-mer count (last line of output is the count)
msbwt query OUT ACGTN

# many k-mers from a file, results as CSV
printf 'ACGTN\nAAAAA\nAA\n' > kmers.txt
msbwt massquery OUT kmers.txt counts.csv
```

## Enhanced usage examples

```python
from MUS.MultiSourceQuery import MultiSourceBWT

# one merged index over many samples, queried per source
wrapped = MultiSourceBWT.load("data/merged10")

wrapped.countOccurrencesForSource("ACGT", "sample07")   # one constituent
wrapped.nonzeroSources("ACGT")                          # sparse listing
wrapped.sourceFrequency("ACGT")                         # distinct sources
wrapped.topSources("ACGT", k=3)                         # exact top-k
wrapped.countGroup("ACGT", "case")                      # metadata group
wrapped.readsContaining("ACGT", include_quality=True)   # reads + quality
```

```bash
# drop the control sources from a merged index, without FASTQ rebuild
msbwt-remove-sources --input data/merged10 --output data/merged7 \
    --remove sample00,sample02 --drop-lcp

# retrofit the exact LCP layer onto an existing merged BWT
msbwt-lcp construct --input data/merged10

# inspect whole-index storage accounting
msbwt-benchmark-index inspect --input data/merged10
```

More examples (provenance, metadata, tags, quality, LCP, benchmarking)
are on the [wiki](https://github.com/Taksir/msbwt/wiki) and in
[`packages/msbwt-modern2/README.md`](packages/msbwt-modern2/README.md).

## Persistent index files / metadata

| File | What it is |
|---|---|
| `msbwt.npy` | authoritative byte MSBWT (BWT column, `|u1`) |
| `comp_msbwt.npy` | RLE-compressed primary (3-bit letter, 5-bit run digits, LSB first) |
| `fmIndex.npy`, `comp_fmIndex.npy`, `comp_refIndex.npy` | derived reader indexes (reconstructible) |
| `inter0.npy`, `inter0_rank.npz` | two-source merge interleave / saved rank cache |
| `provenance.json`, `provenance/interleaves/*.npy` | multi-source merge tree + interleaves (F2) |
| `source_metadata.json` | user-editable source labels/groups (F7) |
| `read_provenance.npy`, `read_provenance.json` | 20-byte/read owning-read records (F9) |
| `bwt_tags.json`, `bwt_tags/tag_*.npy` | generic BWT-aligned tags (F12) |
| `quality_sidecar.json` + reserved tag `fastq_quality_ascii` | lossless quality (Q1) |
| `lcps.npy`, `lcp.json` | adjacent-LCP array, `lcps[i] = LCP(SA[i], SA[i+1])` (F11A) |

See the wiki's [Persistent Files and Compatibility](https://github.com/Taksir/msbwt/wiki/Persistent-Files-and-Compatibility)
page for a careful classification (authoritative vs derived vs optional)
and what is safe to reconstruct.

## Command-line tools

Legacy (preserved): `cffq`, `pp`, `cfpp`, `merge`, `query`, `massquery`,
`compress`, `decompress`, `convert`; global flags `-V`, `-h`, `-u`,
`-c`, `-p`, `-d`, `-r`, `-i`.

Enhanced (installed console scripts): `msbwt-bwt-tags`, `msbwt-lcp`,
`msbwt-quality-sidecar`, `msbwt-remove-sources`,
`msbwt-retrofit-read-provenance`, `msbwt-benchmark-index` — each supports
`--help`.

## Compatibility and scope

- The frozen original implementation is the compatibility authority;
  modern2 preserves the original CLI, APIs, import paths, algorithms, and
  on-disk formats, and reproduces committed golden outputs byte-for-byte
  where the legacy contract is byte-level.
- Proven historical defects were corrected only where documented (see
  `docs/modernization/MODERN2_LEGACY_BUG_TRACKER.md`); intentional
  deviations are recorded in `COMPATIBILITY.md`.
- Enhanced layers are additive and never change legacy semantics or
  formats.
- **Out of scope (not implemented, not claimed):** Feature 8B, Feature
  11B/11C, a new compressed backend, and any performance superiority
  claim.  Feature-13A's benchmark tool measures the index as it is; the
  naive u32 RLE encoding model it reports was *larger* than the raw BWT
  payload on the toy fixture — that negative result is documented, not
  hidden.
- Verified for modern2 on the Linux x86-64 Python-2.7 reference profile
  and native 64-bit Windows; macOS support is not claimed.  Modern3 is
  verified on Windows x86-64 and Linux x86-64 with CPython 3.14; no
  other Python version, platform, or architecture is claimed.

## Project status

- `msbwt-modern2` — complete, release candidate: all nine CLI commands,
  uniform/nonuniform/gzip construction, byte and RLE readers,
  compression, decompression (including >1M-symbol multi-block inputs),
  merge, convert; 283 host + 133 Python-2 tests plus a 24-test Q1 audit
  harness; randomized differential audit (225 collections, 18
  categories): 260 A-classifications, zero disagreements; sdist/wheel
  built under the pinned environment and fresh-installed end-to-end.
- `enhanced-modern2` — complete, release candidate: features F1–F13A +
  Q1 verified against independent oracles with executed evidence under
  `packages/msbwt-modern2/evidence/`; integrated gate runs all features
  in one package plus a Feature-10-reduced package.
- `msbwt-modern3` — complete, release candidate (0.3.0) on branch
  `enhanced-modern3`: legacy + enhanced feature parity against the
  modern2 oracle, cross-platform persistence evidence, three-way
  randomized audit, and validated sdist/Windows-wheel/Linux-wheel
  artifacts with installed-distribution smoke gates.

## Verified legacy baseline

The frozen oracle profile used for goldens is `py27-late-05a7d6d83862`
(Ubuntu 26.04 LTS under WSL2 x86-64, CPython 2.7.18, GCC 7.3.0, NumPy
1.16.6, pysam 0.15.4, Cython 0.29.36).  The modern2 reference profile is
`modern2-python27-3.0.12` (same host family, Cython exactly 3.0.12).
Exact artifact URLs and hashes are in
`reference/original-0.3.0/environment/` and
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

These values and the promoted artifact hash are part of the committed
golden contract, and modern2 reproduces them byte-for-byte.

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

These principles are part of the current handoff and compatibility
contract.

## What is not done yet

This fork should **not** be treated as a finished replacement for every
historical MSBWT use case.  Remaining work:

- publishing either distribution to a public package index (the release
  artifacts are built and validated locally; publication is a separate,
  manual step);
- macOS/ARM support and non-3.14 CPython versions for `msbwt-modern3`
  (only Windows x86-64 + Linux x86-64 on CPython 3.14 are executed);
- a literal production-scale (>1 GB) GenericMerge run for modern3;
- CI, benchmark baselines, and performance optimization (deliberately
  deferred until after compatibility is established);
- broadening malformed/corrupt-artifact hardening.

## Documentation / Wiki

User documentation is maintained on the
[project wiki](https://github.com/Taksir/msbwt/wiki):

- **Getting started** — MSBWT primer, installation, construction, CLI
  queries, Python API, BasicBWT API, RLE conversion.
- **Enhanced features** — source-aware and multi-source queries,
  provenance and metadata, read provenance, source removal, BWT-aligned
  tags, the lossless FASTQ quality sidecar, LCP retrofit, benchmarking
  and the backend contract.
- **Reference** — persistent files and compatibility.

Engineering documentation (design, evidence, bug tracker) lives in the
repository under `docs/modernization/` and `docs/enhanced-modern2/`:

- `docs/modernization/MODERN2_LEGACY_BUG_TRACKER.md` — proven legacy
  defects and their status;
- `docs/modernization/MODERN2_RELEASE_NOTES.md` and
  `docs/modernization/MODERN2_ENHANCED_RELEASE_NOTES.md` — release notes;
- `docs/modernization/MODERN3_RELEASE_NOTES.md` — modern3 release notes;
- `docs/enhanced-modern2/README.md` — feature index with per-feature
  milestone documents and evidence.

## Repository structure

```text
reference/original-0.3.0/   frozen historical oracle (40 hash-pinned files)
packages/msbwt-modern2/     the installable distribution: MUS/, MUSCython/,
                            bin/msbwt, tools/, environment/ locks, tests/,
                            validate/, evidence/, README, setup.py
packages/msbwt-modern3/     the Python 3 distribution (current line):
                            MUS/, MUSCython/ .pyx sources, tools/,
                            pyproject.toml/setup.py, README, LICENSE
compat/                     shared fixtures, goldens, manifests, compatibility
                            tests, and the Q1 audit harness
docs/modernization/         handoff, milestone reports, bug tracker, audit doc
docs/enhanced-modern2/      enhanced-modern2 feature milestone docs + index
MUS/ MUSCython/ setup.py    frozen-original sources kept for oracle reference
```

## References

Holt, James, and Leonard McMillan.  
**"Merging of multi-string BWTs with applications."**  
*Bioinformatics* (2014): btu584.

Holt, James, and Leonard McMillan.  
**"Constructing Burrows-Wheeler transforms of large string collections via merging."**  
*Proceedings of the 5th ACM Conference on Bioinformatics, Computational Biology, and Health Informatics.* ACM, 2014.

The original README also cites the MSBWT construction approach described
by Bauer et al. in **"Lightweight BWT construction for very large string
collections."**

## License / attribution

The original project is distributed under the MIT License.  Original
copyright, license, attribution, and scientific references are preserved
in this fork (see `LICENSE` and `AUTHORS`).

This fork is a modernization and maintenance effort by Taksir
(`https://github.com/Taksir/msbwt`); it does not claim authorship of the
original MSBWT algorithms or implementation.
