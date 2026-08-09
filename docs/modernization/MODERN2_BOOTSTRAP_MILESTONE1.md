# MODERN2 — Bootstrap Milestone 1 (executed evidence)

Status date: 2026-08-09

This milestone proves the msbwt-modern2 implementation stack is real: an
independent, installable Python-2.7 distribution that builds with the pinned
Cython 3.0.x toolchain and reproduces a committed legacy golden
byte-for-byte.

All evidence below is from two consecutive full validation runs of
`packages/msbwt-modern2/validate/bootstrap-milestone1.sh` (the second run's
evidence JSON is committed under
`packages/msbwt-modern2/evidence/bootstrap-milestone1.json`).  The frozen
oracle environment was not modified; the modern2 environment is a separate
prefix.

## Scope of this milestone

- Independent package: `packages/msbwt-modern2/` with its own `setup.py`,
  lock files, bootstrap/build/validation scripts, tests, and evidence.
- Python 2.7 runtime: CPython 2.7.18 (cp27mu/UCS4) in an isolated conda
  prefix created by `environment/bootstrap-modern2.sh`.
- Cython 3.0.x toolchain: **exactly Cython 3.0.12** (the last 3.0 series
  release; Requires-Python `>=2.7`).  Cython 3.1+ and 0.29.x are prohibited
  for modern2.  `language_level=2` is applied explicitly in `setup.py` and as
  a per-module `#cython: language_level=2` header.
- Migrated compiled modules (8): `AlignmentUtil`, `BasicBWT`,
  `ByteBWTCython`, `MSBWTCompGenCython`, `MSBWTGenCython`,
  `MultiStringBWTCython`, `RLE_BWTCython`, `LZW_BWTCython` (the exact
  transitive closure required by the uniform-multifile slice).
- Not-yet-migrated compiled modules (4) are explicit importable stubs that
  raise `NotImplementedError`: `CompressToRLE`, `GenericMerge`,
  `MultimergeCython`, `LCPGen`.  Merge, compression, non-uniform
  construction, LCP, and convert are out of scope for this milestone.
- Pure-Python `MUS` package is carried byte-identical (LF-normalized `.py`
  sources only; the historical `__init__.pyc` cache file is intentionally
  excluded): the full public `import MUS` surface including
  `CommandLineInterface`, `MultiStringBWT`, `MSBWTGen`, `TranscriptBuilder`,
  `util`.
- `bin/msbwt` CLI entrypoint is preserved; `msbwt -V` reports
  `msbwt 0.3.0 in MSBWT 0.3.0`.

## Environment

See `packages/msbwt-modern2/environment/modern2-profile.json` and the lock
files.  Summary:

- Python 2.7.18 `h42bf7aa_3`, `cp27mu`/UCS4 (same conda artifact as the
  verified oracle profile).
- Cython 3.0.12 (universal `py2.py3-none-any` wheel, hash-pinned).
- NumPy 1.16.6, pysam 0.15.4, pip 20.3.4, setuptools 44.1.1, wheel 0.37.1
  (hash-pinned wheels, identical to the oracle profile except Cython).
- Compiler: GCC 7.3.0 `x86_64-conda_cos6-linux-gnu` (conda toolchain,
  byte-identical artifact set to the oracle profile), binutils 2.34,
  libgcc 15.2.0.
- Host: Ubuntu 26.04 LTS on WSL2 x86-64, kernel
  `6.18.33.2-microsoft-standard-WSL2`.
- The modern2 environment was created fresh by the committed bootstrap
  script in a separate prefix (`/home/<user>/.local/share/msbwt-modern2/`);
  the legacy oracle environment was not altered or reused.

Bootstrap (offline conda install from verified artifacts + hash-verified
wheels):

```bash
bash packages/msbwt-modern2/environment/bootstrap-modern2.sh \
  --micromamba /absolute/path/to/verified-micromamba-2.8.1 \
  --prefix /home/$USER/.local/share/msbwt-modern2/python27-modern2
```

Build and validate:

```bash
bash packages/msbwt-modern2/environment/build-modern2.sh \
  --prefix /home/$USER/.local/share/msbwt-modern2/python27-modern2 \
  --source /path/to/msbwt/packages/msbwt-modern2

bash packages/msbwt-modern2/validate/bootstrap-milestone1.sh \
  --prefix /home/$USER/.local/share/msbwt-modern2/python27-modern2 \
  --package /path/to/msbwt/packages/msbwt-modern2 \
  --repository /path/to/msbwt \
  --build --install \
  --evidence /path/to/msbwt/packages/msbwt-modern2/evidence/bootstrap-milestone1.json
```

## Migration approach

- Implementation source of truth: the migrated `.pyx` files in
  `packages/msbwt-modern2/MUSCython/`.  Historical generated C remains
  historical oracle evidence only; modern2 generated C comes from the pinned
  Cython 3.0.12 toolchain.
- Each `.pyx` received an explicit `#cython: language_level=2` header.  No
  algorithm code was changed.
- Source line endings were LF-normalized in the modern2 tree (the frozen
  files are CRLF); content is otherwise byte-identical.
- No `cdivision`/`boundscheck`/`wraparound` semantic defaults were changed;
  the existing per-module directives were preserved.
- Cython 3.0 integer-division result typing (`/` and `%` on C integer
  operands with `cdivision=False` now produce Python-level semantics) did not
  require source changes; behavior is proven by the byte-exact golden
  comparison below.  The legacy files contain typed-division sites in
  `MSBWTGenCython.pyx` (e.g. `compressBWT` bin arithmetic) that are not on
  this milestone's slice; they remain unexercised and will be validated when
  compression is migrated.
- Generated C is committed per the ARCHITECTURE.md modern2 generated-C
  policy (Python 2 build isolation).  The committed C regenerates cleanly in
  the pinned environment; regeneration elsewhere may differ only in comment
  references to the Cython install path.

## Selected compatibility slice

`uniform-multifile` construction/read/query — the smallest real end-to-end
path that exercises compiled preprocessing, the compiled column builder, the
compiled reader, and queries, with a committed golden for every artifact:

1. `pp -u OUT uniform-a.fastq uniform-b.fastq`
2. `cfpp -p 1 -u OUT`
3. reader smoke + CLI queries on a disposable copy

## Validation results (both runs identical)

### Environment gates

- `python` is CPython 2.7.18 (cp27mu/UCS4, maxunicode 1114111).
- `Cython.__version__` = `3.0.12`.
- `numpy` 1.16.6, `pysam` 0.15.4.
- Compiler activation: `x86_64-conda_cos6-linux-gnu-cc` 7.3.0.

### Build gate

`python setup.py build_ext --inplace` compiles all 8 extensions with
Cython 3.0.12 and `language_level=2` (warnings only, no errors).

### Python-2 test suite

11/11 tests pass under the modern2 environment
(`packages/msbwt-modern2/tests/test_bootstrap_py2.py`): environment pins,
`import MUS`, `import MUSCython`, all compiled modules, stub
`NotImplementedError` behavior, CLI `-V`, and the full golden slice.

### Golden comparison (byte-exact)

Both stages verified with `compat/tools/artifact_manifest.py verify` against
the committed legacy manifests:

- `pre` stage: identical 8-file set; every file's size and SHA-256 match the
  committed manifest (`about.npy`, `offsets.npy`, `seqs.npy.0.npy` …
  `seqs.npy.5.npy`).
- `build` stage: identical 9-file set; every file's size, SHA-256, raw NPY
  header, dtype/shape, and payload match the committed manifest.

Primary contract (exact):

- `msbwt.npy`: 176 bytes, whole-file SHA-256
  `dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f`
  (equal to the committed golden).
- Raw NPY header text:
  `{'descr': '|u1', 'fortran_order': False, 'shape': (48L,), }` — including
  the Python-2 NumPy v1 `(48L,)` long-literal shape.
- Payload SHA-256
  `75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e`.
- Two independent runs produce identical whole-directory tree hashes
  (determinism confirmed).

Reader/query (on disposable copies only):

- `loadBWT` returns `MUSCython.ByteBWTCython.ByteBWT`, total size 48.
- Counts: `AAAAA=1`, `ACGTN=3`, `CCCCC=1`, `AGCTA=0` — identical to the
  legacy reader smoke.
- Reader side effects are exactly `totalCounts.npy` + `fmIndex.npy`
  (derived indexes), matching the legacy contract.
- CLI `query`: `ACGTN` → 3, `AAAAA` → 1, `AGCTA` → 0.

### Install gate

`pip install --no-build-isolation --no-deps .` builds
`msbwt_modern2-0.3.0-cp27-cp27mu-linux_x86_64.whl` and installs cleanly.
The installed `msbwt` CLI reports version 0.3.0, imports resolve to the
installed `.so` modules, and an installed-package `pp`+`cfpp` slice produces
the identical primary SHA-256.

## Files added

- `packages/msbwt-modern2/` — package root (setup.py, MANIFEST.in, bin/,
  MUS/, MUSCython/ with migrated `.pyx`/`.pxd` + generated `.c` + stubs).
- `packages/msbwt-modern2/environment/` — bootstrap-modern2.sh,
  build-modern2.sh, locks/ (conda explicit + SHA-256, wheel lock),
  modern2-profile.json.
- `packages/msbwt-modern2/tests/test_bootstrap_py2.py` — Python-2 test suite.
- `packages/msbwt-modern2/validate/bootstrap-milestone1.sh` — validation
  driver.
- `packages/msbwt-modern2/evidence/bootstrap-milestone1.json` — executed
  evidence record.
- `compat/tests/test_modern2_bootstrap.py` — host-side regression tests.
- Root `.gitignore` — modern2 build-output ignore rules.

## Migration status table

| MUSCython module | Bootstrap 1 status |
|---|---|
| `BasicBWT` (+`BasicBWT.pxd`) | migrated, compiled, exercised |
| `ByteBWTCython` | migrated, compiled, exercised |
| `MultiStringBWTCython` | migrated, compiled, exercised |
| `MSBWTGenCython` | migrated, compiled, exercised |
| `MSBWTCompGenCython` | migrated, compiled, imported (not exercised) |
| `RLE_BWTCython` | migrated, compiled, imported (not exercised) |
| `LZW_BWTCython` | migrated, compiled, imported (not exercised) |
| `AlignmentUtil` | migrated, compiled, imported (not exercised) |
| `MultimergeCython` | stub, not migrated |
| `GenericMerge` | stub, not migrated |
| `CompressToRLE` | stub, not migrated |
| `LCPGen` | stub, not migrated |

## Open items for later milestones

- Cython 3.0 typed-division verification on the compression path
  (`MSBWTGenCython.compressBWT` etc.) when compression is migrated.
- Migration of `MultimergeCython`, `GenericMerge` (with the documented
  `merge -p 1` fix), `CompressToRLE`, `LCPGen`, and the non-uniform /
  compressed / LZW / merge / LCP routes.
- Generated-C regeneration check in the pinned container (clean-diff CI).
- Modern2 profile promotion to a formal `compat/goldens/modern2-*` area is
  intentionally deferred; the evidence JSON is the milestone record.
