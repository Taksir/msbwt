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
sources, all `MUSCython` `.pyx`/`.pxd` sources, the committed
Cython-3.0.12-generated `.c`, the `msbwt` script, and the
README/LICENSE/AUTHORS.

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

This release is the **compatibility-preserving baseline**.  It is frozen
except for critical release-blocking fixes.  New research features will be
developed separately (on a future `enhanced-modern2` track) and are not
part of this release.

## License and attribution

MIT License.  Original copyright (C) 2014 UNC-CH CS Dept. and original
authorship (James Holt, `holtjma@cs.unc.edu`) are preserved; see LICENSE
and AUTHORS.  This distribution is a maintenance/porting effort and does
not claim authorship of the original MSBWT algorithms.
