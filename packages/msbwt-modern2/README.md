# msbwt-modern2

`msbwt-modern2` is an independently installable, Python-2.7-compatible
modernization of the historical [MSBWT] 0.3.0 package.  It preserves the
original public surface — the `MUS` / `MUSCython` import namespaces and the
`msbwt` command-line interface — and is built with a reproducible, pinned
toolchain instead of the obsolete generated-C/Cython-0.x stack the original
distribution depended on.

```python
import MUS
import MUSCython
```

```
msbwt -V        # -> msbwt 0.3.0 in MSBWT 0.3.0
```

This distribution also carries the **enhanced-modern2** feature layers
(multi-source provenance and queries, source removal, BWT-aligned tags,
exact FASTQ quality, LCP, benchmarking) as additive `MUS.*` modules with
six additional command-line tools; see section 11.

[MSBWT]: https://github.com/holtjma/msbwt

## 1. What is msbwt-modern2?

- A modernization of the historical MSBWT 0.3.0 package (Holt & McMillan,
  UNC-Chapel Hill).
- **Python 2.7 compatibility is preserved**: the reference runtime is
  CPython 2.7.18 (`cp27mu`/UCS4).
- The Cython toolchain is modernized to **Cython exactly 3.0.12** (the last
  Cython 3.0.x series; Cython 3.1+ is intentionally prohibited) with
  `language_level=2` semantics applied explicitly.
- The original `MUS` / `MUSCython` namespaces, the `msbwt` CLI, the
  persistent on-disk MSBWT formats, and the original algorithms are
  preserved.
- This is **not** a Python 3 package.  Python 3 is the separate
  `msbwt-modern3` track and is not part of this release.

## 2. Why this release exists

The historical package shipped Cython-0.23.4-era generated C, a frozen
`setup.py` whose compressed-construction fallback was defective, and
depended on a Python-2/Cython-0.x ecosystem that is no longer buildable on
modern systems.  This release makes the original Python-2 implementation
reproducibly buildable from a pinned environment (Cython 3.0.12 generated
extensions, committed alongside the `.pyx` sources), with compatibility and
correctness characterized *before* any change:

- every public CLI command and import path was inventoried and validated;
- persistent outputs were compared byte-for-byte against committed frozen
  oracle goldens;
- a randomized differential audit compared frozen behavior, modern2
  behavior, and independent mathematical oracles;
- proven historical defects were corrected only where documented (see
  "Legacy bugs fixed").

## 3. Installation

The **verified reference environment** is Ubuntu 26.04 LTS on WSL2 x86-64
with the pinned `modern2-python27-3.0.12` profile:

| Component | Version |
|---|---|
| CPython | 2.7.18 (`cp27mu`, UCS4) |
| Cython | exactly 3.0.12 |
| NumPy | 1.16.6 |
| pysam | 0.15.4 |
| pip / setuptools / wheel | 20.3.4 / 44.1.1 / 0.37.1 |
| compiler | GCC 7.3.0 `x86_64-conda_cos6-linux-gnu` (crosstool-NG 1.23.0.450-d54ae), binutils 2.34 |

Exact artifacts and SHA-256 values are locked in `environment/`
(`modern2-profile.json`, `locks/`).

### 3.1 Bootstrap the pinned Python-2.7 environment

```bash
bash packages/msbwt-modern2/environment/bootstrap-modern2.sh \
  --micromamba /absolute/path/to/micromamba-2.8.1 \
  --prefix /new/absolute/prefix
```

This creates a brand-new conda prefix with CPython 2.7.18, the GCC 7.3.0
toolchain, and the pinned wheel set (Cython 3.0.12, NumPy 1.16.6, pysam
0.15.4), verifying every artifact hash.  It never touches other
environments.

### 3.2 Install the built artifacts

The release artifacts are a platform-specific wheel
(`msbwt_modern2-0.3.0-cp27-cp27mu-linux_x86_64.whl`) and a source
distribution (`msbwt-modern2-0.3.0.tar.gz`).  They are not published on a
public package index; install them from the built files:

```bash
<prefix>/bin/pip install --no-deps msbwt_modern2-0.3.0-cp27-cp27mu-linux_x86_64.whl
# or, from the sdist (compiles the extensions in the pinned environment):
<prefix>/bin/pip install --no-deps msbwt-modern2-0.3.0.tar.gz
```

The wheel is specific to the Python-2.7/Linux x86-64 reference profile
(`cp27mu`); it is not a universal wheel.  The sdist contains the MUS
sources (including the enhanced-modern2 feature modules), all `MUSCython`
`.pyx`/`.pxd` sources, the committed Cython-3.0.12-generated `.c`, the
`msbwt` script, the `tools/` enhanced CLI package, and the
README/LICENSE/AUTHORS.  Installing the wheel or the sdist also installs
the six enhanced console scripts (`msbwt-bwt-tags`, `msbwt-lcp`,
`msbwt-quality-sidecar`, `msbwt-remove-sources`,
`msbwt-retrofit-read-provenance`, `msbwt-benchmark-index`).

### 3.3 Building from source (validated path)

```bash
bash packages/msbwt-modern2/environment/build-modern2.sh \
  --prefix /absolute/prefix --source /absolute/packages/msbwt-modern2
```

Build commands used for the release artifacts:

```bash
python setup.py sdist
python setup.py bdist_wheel
```

## 4. Quick start

```bash
# build a uniform MSBWT from FASTQ
msbwt pp -u OUT uniform-a.fastq uniform-b.fastq
msbwt cfpp -p 1 -u OUT

# query
msbwt query OUT ACGTN
# -> 3

# compress to RLE, then decompress back to byte
msbwt compress -p 1 OUT OUT.rle
msbwt decompress -p 1 OUT.rle OUT.byte

# merge two MSBWTs
msbwt merge -p 1 OUT.merged A_DIR B_DIR
```

## 5. CLI commands

| Command | Purpose |
|---|---|
| `pp` | pre-process FASTQ files before BWT creation |
| `cffq` | create an MSBWT directly from FASTQ files |
| `cfpp` | create an MSBWT from pre-processed sequences/offsets |
| `merge` | merge many MSBWTs into a single MSBWT |
| `query` | search for a sequence in an MSBWT |
| `massquery` | search for many sequences in an MSBWT |
| `compress` | compress an MSBWT from byte/base to RLE |
| `decompress` | decompress an MSBWT from RLE to byte/base |
| `convert` | convert a raw text BWT input to RLE |

Global flags preserved: `-V/--version`, `-h/--help`; per-command
`-u/--uniform`, `-c/--compressed`, `-p N`, `-d/--dump-seqs`, `-r/--rev-comp`,
`-i`.

## 6. Compatibility

- The frozen original behavior is the compatibility authority; modern2
  preserves the original CLI commands/options, public APIs, `MUS` /
  `MUSCython` import paths, and algorithms.
- Persistent artifacts are byte-compatible where the legacy contract is
  byte-level: construction (`pp`/`cfpp`/`cffq`), post-hoc `compress`,
  `merge`, and `convert` outputs match the committed frozen goldens
  byte-for-byte (verified on the canonical fixtures, and on 165 generated
  uniform collections in the Q1 audit).
- The **decompression** output is the documented modern2 fix contract
  (the frozen decompressor crashes on every input; see "Legacy bugs
  fixed"); the decompressed *payload* equals the authoritative byte BWT.
- Reader/writer interoperation: modern2-created primaries load with the
  frozen reader and vice versa (executed on committed goldens and in the
  Q1 audit).
- Python-2 reference profile only (section 3).  Formats are the
  historical NumPy `.npy`-based MSBWT files; the RLE byte layout
  (3-bit letter, 5-bit base-32 run-length digits, least-significant digit
  first) is unchanged.

## 7. Legacy bugs fixed

Authority: `docs/modernization/MODERN2_LEGACY_BUG_TRACKER.md`.  Only
proven defects are listed; frozen source is never modified.

**Fixed in modern2** (documented deviations):

- decompression crash: `uint64`/Python-int run counts promoted to NumPy
  `float64`, producing `TypeError: slice indices must be integers...` at
  `MUS/MultiStringBWT.py:662` on every RLE input — decompression now
  succeeds and its output payload is byte-equal to the authoritative
  byte-BWT golden;
- multi-block decompression: the same float64 promotion crashed
  `decompressBlocks` at line 630 for >1,000,000-symbol RLE inputs —
  multi-block decompression now succeeds byte-identically across
  `-p 1`/`-p 2`;
- pure reader `refFM` index construction: float64 index promotion crashed
  `loadBWT`/`constructIndexing` — the pure reader now builds
  `totalCounts.npy`/`fmIndex.npy` byte-identically to the compiled
  reader;
- pure reader `getFullFMAtIndex`: float64 weighted-`bincount` fill
  produced wrong FM rows — corrected to byte-match the compiled reader;
- `merge -p 1`: `UnboundLocalError: local variable 'numProcs' referenced
  before assignment` — `numProcs = 1` is now bound unconditionally and
  `merge -p 1`/`-p 2` produce byte-identical output.

**Historical generated-code defect eliminated by regeneration**:

- the committed historical `MUSCython/GenericMerge.c` (Cython 0.23.4
  provenance) segfaulted deterministically (exit -11) on the canonical
  merge route; modern2 builds the migrated `GenericMerge.pyx` under
  Cython 3.0.12 and merge succeeds.

**Documented historical quirks preserved** (not fixed, by design):

- `convert` silently drops everything after the first newline of the
  input (exit 0) — preserved byte-for-byte;
- `convert` reports an invalid symbol before the first newline as a
  masked `TypeError: cannot concatenate 'str' and 'int' objects` (exit 1)
  — the intended exception is masked by Python-2 `str + int` semantics;
  preserved byte-for-byte.

## 8. Validation

- Fixed compatibility/golden suite: **283 host tests** (125 legacy
  compatibility + 158 modern2 host) plus **133 modern2 Python-2 tests**
  (132 at the Q1 baseline + 1 multi-digit RLE regression), plus a
  **24-test Q1 audit-harness suite** — all green on the release
  baseline.
- Deterministic repeated executions: fixture checks, frozen-source
  verification (40 files, hash-pinned), and `git diff --check` are part
  of the standard gates.
- **Q1 randomized differential audit** (seed `20260810`, executed twice,
  byte-identical results): 225 generated collections (165 audited + 60
  merge-role) across 18 input categories, 20 generated merge pairs,
  three-way frozen/modern2/oracle classifications: **260 A-classifications
  (legacy == modern2 == oracle), zero B/C/D/E outcomes, zero modern2
  regressions, zero new legacy bugs**.
  - 165 constructions byte-equal (uniform) / semantic-equal (nonuniform)
    to the independent oracle; 45 of them additionally exercised `-p 2`
    (all succeeded; see the audit doc for the process-count subset
    caveat); 20 merges with modern2 `-p 1` == `-p 2` recorded true; 53
    compression round trips; reader/FM/recovery checks on all 165
    collections; gzip/cffq/permutation/cache-regeneration families.
- Fresh-install validation (this release): sdist and wheel each cleanly
  installed into brand-new bootstrapped Python-2.7 prefixes, all 9 CLI
  commands executed through the installed distributions, and the canonical
  workflow (`pp -> cfpp -> query -> compress -> RLE query -> decompress ->
  byte query`, plus `merge -p 1`/`-p 2` and `convert`) reproduced the
  committed golden hashes — all checks passed, with no dependency on the
  repository checkout.
- Enhanced-modern2 validation (this distribution): each feature milestone
  has executed evidence (`packages/msbwt-modern2/evidence/`), the final
  integrated gate builds one all-feature package plus a Feature-10-reduced
  package and verifies both against independent oracles
  (`validate/enhanced-integration-gate.sh`), and the installed-distribution
  release gate re-runs the whole enhanced chain from the wheel and from the
  sdist in fresh prefixes (`validate/enhanced-release-candidate.sh`,
  evidence `evidence/enhanced-release-candidate.json`).

## 9. Known limitations

- Python 2.7 baseline by design; there is no Python 3 support.
- The reference release is validated on the Linux x86-64 profile
  (Ubuntu 26.04 on WSL2); no other platform is claimed.
- `MUSCython.LCPGen` is an intentional DEAD/PRIVATE stub (no public
  CLI/API path reaches it); it is not part of the public release
  contract.
- No modern3 completion claim is made by this distribution.
- Malformed/corrupt artifact handling (truncated `.npy`, out-of-contract
  inputs) is not exhaustively hardened; the compiled readers' unchecked
  index sites are executed-safe for exercised inputs only.
- The committed golden RLE artifacts contain only single-digit runs; the
  multi-digit RLE path is covered by the audit corpus and regression
  tests, but not by a committed golden artifact.
- Nonuniform-route byte ordering is characterized semantically (symbol
  totals, backward-search counts, recovered read multiset) rather than
  byte-for-byte against the frozen oracle, which is the strongest
  invariant the frozen route supports.

## 10. Relationship to enhanced/new-feature work

This distribution is the **compatibility-preserving baseline** extended by
the **enhanced-modern2** feature track (same repository, branch
`enhanced-modern2`).  The original CLI, the `MUS` / `MUSCython` legacy
surface, and all persistent legacy formats are untouched by the feature
layers; every feature is an additive, pure-Python layer with its own
persisted artifacts, tests, and executed evidence (see
`docs/enhanced-modern2/` in the repository and
[the feature index](docs/enhanced-modern2/README.md)).

## 11. Enhanced features (enhanced-modern2)

All enhanced features ship inside this same `msbwt-modern2` distribution;
the import namespaces are unchanged (`MUS.*`), and each feature persists
its own sidecar artifacts inside the BWT directory without rewriting the
legacy `msbwt.npy`, `provenance` formats, or indexes.

| Feature | What it does | Example / use case | Main API / module | Persisted artifact |
|---|---|---|---|---|
| Multi-source provenance | Identity-preserving merges of any number of sources; every BWT row knows its source | Merge per-sample indexes and keep which sample each row came from | `MUS.MultiSourceProvenance` (`merge_many_balanced`) | `provenance.json` + per-merge `interleave` bit store |
| Source-aware queries | One merged FM search; exact per-source counts/intervals for a pattern | "How many occurrences in sample07?" | `MUS.MultiSourceQuery` (`countOccurrencesForSource`) | — (reads existing artifacts) |
| Sparse source listing | Which sources contain a pattern, with exact counts, in one descent | "Which samples carry this k-mer?" | `MUS.MultiSourceQuery` (`nonzeroSources`) | — |
| Sample frequency / top-k | Number of distinct sources containing a pattern; exact top-k sources | "Which 3 samples have the most copies of this motif?" | `MUS.MultiSourceQuery` (`sourceFrequency`, `topSources`) | — |
| Metadata groups / subsets | Arbitrary source subsets, named groups, and key/value predicates | "Count occurrences in the `case` cohort only" | `MUS.SourceMetadata` + `countGroup` / `countWhere` | `source_metadata.json` |
| Sequence extensions | Source-aware left/right base extension with exact counts | "What bases can extend this seed in sample05?" | `MUS.MultiSourceQuery` (`extendLeft` / `extendRight`) | — |
| Read-level provenance | Exact owning read, origin file/read IDs, and mate links for every occurrence | "Which reads contain this variant?" | `MUS.ReadProvenance` (`ReadProvenanceIndex`, `readsContaining`) | `read_provenance.npy` + `read_provenance.json` |
| Source removal / unmerge | Remove or retain sources without rebuilding from FASTQ; BWT bytes equal an independent retained rebuild | "Drop the control samples from the merged index" | `MUS.SourceRemoval` (`remove_sources` / `retain_sources`) | rewritten package (same formats) |
| Generic BWT-aligned tags | Arbitrary row-aligned tag arrays attached to the merged BWT | "Annotate each BWT row with a read position" | `MUS.BWTTags` (`attach_tag`, `BWTTagStore`) | `bwt_tags.json` + `bwt_tags/tag_<hash>.npy` |
| Lossless FASTQ quality | Byte-exact original FASTQ quality for every occurrence, suffix-start aligned | "Recover read + quality for a matched row" | `MUS.QualitySidecar` (`qualityValues`, `readFastqData`) | `bwt_tags/` reserved tag `fastq_quality_ascii` |
| Post-construction LCP | Exact adjacent LCP over the final BWT, no FASTQ / no rebuild | "LCP between rows 10 and 20" | `MUS.LCP` (`construct_lcp_from_bwt`, `LCPIndex`) | `lcps.npy` + `lcp.json` |
| Benchmarking / backend contract | Whole-index structural/disk/query accounting and a machine-readable backend contract | "How many bytes does this index really cost per layer?" | `MUS.Benchmarking` (`inspect_index`, `full_benchmark_document`), `MUS.BackendContract` | benchmark report JSON (user-written) |

Feature documentation and evidence are committed under
`docs/enhanced-modern2/` (13 milestone docs, each with executed evidence in
`packages/msbwt-modern2/evidence/`).  The final integrated gate builds ONE
package carrying every feature layer, then a Feature-10-reduced package,
and verifies both against independent oracles
(`packages/msbwt-modern2/validate/enhanced-integration-gate.sh`).

### 11.1 Enhanced command-line tools

The enhanced feature layers install six additional commands (console-script
entry points), available after installation on the same `PATH` as `msbwt`:

| Command | Feature | Example |
|---|---|---|
| `msbwt-bwt-tags` | F12 tags | `msbwt-bwt-tags list --input /data/merged10` |
| `msbwt-lcp` | F11A LCP | `msbwt-lcp construct --input /data/merged10` |
| `msbwt-quality-sidecar` | Q1 quality | `msbwt-quality-sidecar validate --input /data/merged10` |
| `msbwt-remove-sources` | F10 removal | `msbwt-remove-sources --input /data/merged10 --output /data/merged7 --remove sample00,sample02 --drop-lcp` |
| `msbwt-retrofit-read-provenance` | F9 provenance | `msbwt-retrofit-read-provenance --merged /data/merged10 --source sample00=/data/sample00` |
| `msbwt-benchmark-index` | F13A benchmark | `msbwt-benchmark-index inspect --input /data/merged10` |

Each tool supports `--help`.  Source-tree invocation (`python tools/<name>.py`)
also remains supported in the repository checkout.

### 11.2 Enhanced multi-source example

```python
from MUS.MultiSourceProvenance import initialize_leaf_provenance, merge_many_balanced
from MUS.MultiSourceQuery import MultiSourceBWT
from MUS.SourceMetadata import SourceMetadataCatalog

# leaves: standalone BWT directories (built with msbwt pp/cfpp)
for sid in ("sample00", "sample01"):
    initialize_leaf_provenance("data/" + sid, source_id=sid)
merge_many_balanced(["data/sample00", "data/sample01"], "data/merged")

wrapped = MultiSourceBWT.load("data/merged")
print(wrapped.countOccurrencesForSource("ACGT", "sample00"))
print(wrapped.nonzeroSources("ACGT"))
print(wrapped.topSources("ACGT", k=2))
```

### 11.3 Quality / provenance / removal example

```python
from MUS.MultiSourceQuery import MultiSourceBWT

wrapped = MultiSourceBWT.load("data/merged")
reads = wrapped.readsContaining("ACGT", include_quality=True)
for rec in reads["reads"]:
    print(rec["source_id"], rec["sequence"], rec["quality"])
```

```bash
msbwt-remove-sources --input data/merged --output data/merged-minus \
    --remove sample09 --drop-lcp
```

Removal keeps surviving rows in their existing order; the reduced
`msbwt.npy` is byte-equal to an independent retained-source rebuild
(verified for every removal shape in the Feature-10 evidence).

### 11.4 Compatibility policy for the enhanced layers

- The legacy surface (section 6) is authoritative; feature layers never
  change legacy formats, construction, merge, readers, FM search, or
  compression/decompression semantics.
- Every feature persisted artifact is self-describing and digest-bound to
  the BWT it annotates: stale or foreign sidecars are rejected on load.
- Feature layers are additive pure-Python code inside `MUS/`; they are
  exercised against independent oracles (naive suffix rows, direct
  bit-array walks, explicit adjacent-LCP computation, raw filesystem byte
  sums) rather than only against each other.
- The benchmark layer reports exact accounting; Feature-13A's naive u32
  RLE run-encoding model on the toy fixture was **larger** than the raw
  BWT payload.  No compression win is claimed from that result, and no new
  compressed backend is part of this release.

### 11.5 Known limitations of the enhanced layers

- Enhanced features are validated on the same Linux x86-64 Python-2.7
  profile as the baseline; no other platform is claimed.
- Feature-10 removal drops the Feature-11A LCP layer unless explicitly
  handled (LCP-preserving removal requires the future Feature 11B).
- Read-provenance one-sided merges are rejected before the BWT merge
  (documented Feature-9 policy).
- The baseline `MUSCython.LCPGen` stub and all other baseline limitations
  from section 9 apply unchanged.

## License and attribution

MIT License.  Original copyright (C) 2014 UNC-CH CS Dept. and original
authorship (James Holt, `holtjma@cs.unc.edu`) are preserved; see LICENSE
and AUTHORS.  This distribution is a maintenance/porting effort and does
not claim authorship of the original MSBWT algorithms.
