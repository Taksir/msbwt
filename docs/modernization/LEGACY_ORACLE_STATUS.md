# Legacy oracle reconstruction status

Status date: 2026-08-09

## Current result

The frozen original source now builds and runs under genuine CPython 2.7 in an
isolated WSL2 Linux environment.  `uniform-multifile`, `nonuniform-prefix`, and
`gzip-input` preprocessing and uncompressed-build artifacts are committed under
`compat/goldens/original-0.3.0/`.

Two independent fully green runs per case produced identical file sets,
whole-file SHA-256 values, raw NumPy header bytes, logical dtype/shape, and
payload hashes.  Frozen-reader smokes on disposable copies returned exact
fixture-derived substring counts and recovered strings.  Each load's created
`totalCounts.npy` and `fmIndex.npy` files were inventoried separately.

This establishes a verified late-Python-2 oracle profile.  It does not prove
the exact dependency environment originally used by the authors.

## Frozen source and verified profile

- Source authority: the 40 implementation/package files from commit
  `7503346ec072ddb89520db86fef85569a9ba093a`; every run passed the frozen
  SHA-256 projection check.  No frozen file was repaired or modified.
- Profile: `py27-late-05a7d6d83862`, defined by the version-and-artifact-hash
  record in `compat/goldens/original-0.3.0/profiles/`.
- Runtime: CPython 2.7.18 `h42bf7aa_3`, `cp27mu`/UCS4, Python SSL using
  OpenSSL 1.1.1s.
- Dependencies: NumPy 1.16.6, pysam 0.15.4, Cython 0.29.36, pip 20.3.4,
  setuptools 44.1.1, and wheel 0.37.1 from exact hash-pinned PyPI wheels.
- Build: GCC 7.3.0/crosstool-NG targeting
  `x86_64-conda_cos6-linux-gnu`, binutils 2.34, with the archived conda
  compiler activation flags and sysroot recorded in the profile.
- Host: Ubuntu 26.04 LTS on WSL2 x86-64, kernel
  `6.18.33.2-microsoft-standard-WSL2`, host glibc 2.43.  Builds and results
  stayed on WSL ext4; no sudo or Windows-host package installation was used.

## Golden contract

The committed case used the exact frozen CLI parser:

1. `pp -u OUTPUT uniform-a.fastq uniform-b.fastq`
2. `cfpp -p 1 -u OUTPUT`

Both commands, dependency imports/versions, source verification, extension
build/import, and CLI version gates returned zero in both promotable runs.
The build snapshot contains the preprocessing files plus `msbwt.npy` (`|u1`,
shape `(48,)`).  The snapshots deliberately retain Python-2 NumPy v1 headers,
including long-integer shape syntax such as `(8L,)`.

Use the committed stage manifests as the byte authority.  The probe's
`oracle_tree_sha256` values use a separate canonical tree framing and are also
retained in `provenance.json`; they are not interchangeable with the manifest
content hashes.

The completed expansion used these exact additional commands without `-u`:

1. `pp OUTPUT nonuniform.fastq`; `cfpp -p 1 OUTPUT`.
2. `pp OUTPUT uniform-a.fastq.gz nonuniform.fastq.gz`; `cfpp -p 1 OUTPUT`.

Both cases passed twice in fresh ext4 result parents.  Their preprocessing/build
tree hashes, artifact manifests, reader results, and derived-file inventories
are recorded under their case/profile/route golden directories.

## Reproducible reconstruction

The committed `reconstruct-py27-late.sh` was exercised against a genuinely new
empty prefix.  It used bundled/ensurepip pip only to bootstrap, fetched the
already-pinned pip 20.3.4 wheel, verified its SHA-256, installed it locally with
no dependency resolution or user site, asserted `python -m pip --version`, and
then processed the unchanged wheel lock.  Reconstruction and the subsequent
frozen-source, fixture, profile, import, and compatibility checks passed without
sudo or an existing micromamba/pip/user environment.

## Diagnosed reconstruction constraints

- Ubuntu 26.04 repositories contain no Python 2 runtime/dev packages, so an
  apt-only reconstruction is impossible.  The working route used a user-local
  micromamba environment and required no sudo.
- `pysam 0.7.4` has no surviving PyPI release file.  Its unmodified Google Code
  archive hashes to
  `4a3a013ad36436aa61779b93ddd68b34f1e12990be0d16467e1a2e03df3f309e`.
  Its setup first attempted an obsolete HTTP bootstrap for distribute 0.6.34;
  that endpoint now returns HTTP 403 because HTTPS is required.
- The historical NumPy 1.10.1/Cython 0.23.4 imports succeeded, but a complete
  historical profile was not established.  Initial compiler failures were
  traced to missing archived conda activation/sysroot variables, not frozen
  MSBWT source.  Do not label that profile impossible without a clean rerun
  using the corrected WSL runner.
- The committed generated C has mixed Cython 0.18/0.23.4 provenance, and frozen
  `setup.py` has a generated-C fallback defect.  Preserve its observed failure
  when that route is probed; do not repair the oracle to make it pass.

## Next compatibility work

1. Define exact command order and acceptance criteria for compressed build,
   compression/decompression, and recovery before running or porting them.
2. Characterize query/index side effects separately: first load creates
   `totalCounts.npy` and `fmIndex.npy`, so smoke tests must use snapshot copies.
3. Probe the historical dependency candidate in a clean activated environment
   only if historical-version comparison is needed; never replace the verified
   late-Python-2 goldens silently.
4. Use the committed goldens for modern2/modern3 reader tests before adding
   writer comparisons.
5. Keep raw WSL run directories external to Git; commit only reviewed,
   path-sanitized evidence and exact golden artifacts.
