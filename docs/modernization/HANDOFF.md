# Modernization handoff

Status: fresh-prefix reconstruction and the nonuniform/gzip frozen-oracle
expansion are complete on branch `codex/modernization`; no modern2 or modern3
implementation port has started.

## Start here

The executable behavior and persisted bytes from the unmodified original source
are authoritative.  The frozen projection is 40 files from commit
`7503346ec072ddb89520db86fef85569a9ba093a`, verified by
`reference/original-0.3.0/environment/frozen-source.sha256`.  Never repair that
projection to make the oracle run; capture failures as legacy behavior.
The historical CRLF `README.md` is stored under the dedicated frozen reference
area and mapped back to root in disposable oracle copies, leaving the public
root `README.md` available for the modernization project.

Read the detailed evidence only as needed:

- `LEGACY_ORACLE_STATUS.md`: executed environment, results, and constraints.
- `COMPATIBILITY_TESTING.md`: characterization and reader/writer matrix.
- `BEHAVIORAL_SURFACE.md`: CLI, API, compiled modules, and persistent files.
- `ARCHITECTURE.md`: recommended two-distribution monorepo design.
- `RISKS_AND_OPEN_QUESTIONS.md` and `FORENSIC_AUDIT.md`: risks and source audit.

## Completed milestones

1. Repository, behavioral-surface, format, Cython, platform, security, and
   architecture audits are committed; root `AGENTS.md` holds non-negotiable
   rules.
2. Deterministic plain and gzip synthetic FASTQ fixtures, fixture hashes, a
   safe artifact manifest tool, and host-side regression tests are committed.
3. A genuine CPython-2.7 oracle was reconstructed on WSL2 without Docker,
   sudo, a password, or Windows-host packages.  The frozen source builds and
   imports through the historical-pyx route.
4. Two independent `uniform-multifile` oracle runs passed `pp -u` followed by
   `cfpp -p 1 -u`; preprocessing and build snapshots match byte-for-byte.
5. The committed reconstruction script rebuilt the verified profile in a new
   empty prefix without sudo or user/global Python state.  It hash-verifies and
   installs the pinned pip 20.3.4 wheel before processing the full wheel lock.
6. Two independent runs each of `nonuniform-prefix` and `gzip-input` passed all
   gates, matched byte-for-byte at preprocessing and build stages, and passed
   fixture-derived reader query/recovery checks on disposable copies.  Their
   exact artifacts, manifests, provenance, determinism reports, and strict
   tests are committed.

## Authoritative oracle environment

The verified profile is `py27-late-05a7d6d83862`.  Its complete artifact URLs,
SHA-256 values, ABI, compiler packages, activation flags, and deterministic
environment are in:

`compat/goldens/original-0.3.0/profiles/py27-late-05a7d6d83862.json`

Key identity: Ubuntu 26.04 LTS on WSL2 x86-64; CPython 2.7.18 `cp27mu`/UCS4;
GCC 7.3.0 targeting `x86_64-conda_cos6-linux-gnu`; binutils 2.34; NumPy
1.16.6; pysam 0.15.4; Cython 0.29.36; pip 20.3.4; setuptools 44.1.1; wheel
0.37.1.  This is a verified late-Python-2 oracle, not proof of the authors'
exact historical environment and not the future Cython-3 modern2 toolchain.

Reconstruct a new isolated prefix with the exact locks:

```bash
bash reference/original-0.3.0/environment/wsl/reconstruct-py27-late.sh \
  --micromamba /absolute/path/to/verified-micromamba-2.8.1 \
  --prefix /home/$USER/.local/share/msbwt-oracle/py27-late-05a7d6d83862
```

The script refuses an existing prefix and verifies micromamba plus all conda
and wheel hashes.  It needs network access, `curl`, `sha256sum`, and Python 3,
but no sudo.  A completely fresh-prefix execution of the committed script
passed the frozen-source, fixture, profile-version, import, and compatibility
checks without relying on an existing micromamba, pip, or user environment.

## Authoritative golden outputs

The first golden case is:

`compat/goldens/original-0.3.0/uniform-multifile/py27-late-05a7d6d83862/pyx-historical-cython/`

`pre/` contains eight files and `build/` contains nine.  Each stage's
`manifest.json` is the byte authority.  `determinism-run-b-v-run-c.json` proves
identical file sets, complete file hashes, raw NumPy header bytes, and payload
hashes.  The primary `msbwt.npy` is `|u1`, shape `(48,)`, SHA-256
`dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f`.
Python-2 NumPy v1 headers legitimately contain long literals such as `(48L,)`.

A frozen-reader smoke on a disposable build copy loaded 48 symbols and returned
`ACGTN=3`, `AAAAA=1`, `CCCCC=1`, and `AGCTA=0`.  Loading creates derived
`totalCounts.npy` and `fmIndex.npy`, so never run reader tests in a pristine
golden directory.

The next two golden cases are under the same profile and route:

- `nonuniform-prefix`: preprocessing tree `71f549690de7b78b8b2979692f0594966cb33618e1f7e48c098a17ecc3ea31a7`,
  build tree `ad4aa043feb549e0af861ffde0deca11f8ac0b030c5305183f61f04f5f4d8c0a`,
  and `msbwt.npy` shape `(30,)`.
- `gzip-input`: preprocessing tree `e8e2d8d4c7f40019a3e20acdaba515514f00cdc06cba47056240628a678018c9`,
  build tree `188acea4cac12486c4c1a0d97ef618e807d3142e28cc266c56dda141d621bc8f`,
  and `msbwt.npy` shape `(54,)`.

Both were executed twice in fresh WSL ext4 result parents with one process.
Their raw manifests and reader-smoke JSON matched exactly across runs.  Reader
loading was performed only on disposable copies and created the inventoried
`totalCounts.npy` and `fmIndex.npy` files without mutating promoted snapshots.

## Decisions that remain in force

- Use one monorepo with separately installable `msbwt-modern2` and
  `msbwt-modern3` distributions, independent build metadata/environments, and
  shared format specifications, fixtures, goldens, and differential tests.
- Characterize an operation before porting it.  Preserve algorithms during the
  initial Python/Cython migration; optimize only after compatible baselines.
- Preserve CLI commands/options, public APIs, `MUS`/`MUSCython` imports, and
  persistent bytes unless a documented correctness/security fix requires an
  intentional deviation.
- Never regenerate legacy goldens with Python 3 or update them merely because a
  modern implementation differs.
- Do not claim platform or old/new reader-writer compatibility without executed
  build and behavioral evidence.

## Unresolved issues

- The NumPy 1.10.1, pysam 0.7.4, Cython 0.23.4 historical candidate is not a
  verified complete profile.  Ubuntu 26.04 has no apt Python 2; pysam 0.7.4 is
  archive-only and its setup uses an obsolete distribute bootstrap.
- The committed generated C has mixed Cython provenance, and frozen `setup.py`
  has a `CompressToRLE.pyx` fallback defect.  Preserve the generated-C route's
  observed failure; do not patch the oracle.
- Uniform and nonuniform uncompressed preprocessing/build plus plain/gzip input
  and fixture-derived reader smoke now have golden coverage.  Compressed build,
  compression, decompression, recovery, merge, indexing, and broader API/CLI
  behavior remain.
- Reader side effects, recovery files, multiprocessing behavior, filesystem
  ordering, and cross-platform byte determinism need operation-specific tests.

## Completed exact milestone

The frozen-oracle synthetic baseline was expanded, without changing the frozen
implementation, for these two cases in order:

1. `nonuniform-prefix`: `pp OUTPUT nonuniform.fastq`, then
   `cfpp -p 1 OUTPUT`.
2. `gzip-input`: `pp OUTPUT uniform-a.fastq.gz nonuniform.fastq.gz`, then
   `cfpp -p 1 OUTPUT`.

The external harness is manifest-driven and contains no modernized behavior or
oracle-failure special case.  All acceptance criteria below passed.

### Completed acceptance evidence

1. Before every run, the genuine CPython-2.7 gate, exact profile-version gate,
   extension build/import, CLI version, fixture hashes, and frozen 40-file
   projection all pass; no frozen source file changes.
2. Run each case twice in fresh Linux-ext4 result directories with deterministic
   environment variables and one process.  Preserve nonzero exits or partial
   artifacts as legacy results rather than working around them.
3. If both runs succeed, require identical retained file sets, whole-file
   SHA-256, raw `.npy` headers, logical dtype/shape, and payload SHA-256 for both
   preprocessing and build stages before promotion.
4. On disposable copies only, load each successful build with the frozen reader,
   assert fixture-derived query/recovery results, and inventory every derived
   side-effect file.  Do not mutate promoted snapshots.
5. Path-sanitized provenance, artifacts/manifests, determinism reports, reader
   side-effect inventories, and strict tests are committed.

## Next milestone boundary

Compression and recovery are the next documented compatibility area.  The
repository does not yet resolve their exact command sequence, case order, or
promotion acceptance criteria.  Stop for that policy decision before running
or changing the oracle.  Do not begin modern2 or modern3 implementation first.

Finish every handoff with the commands below and a clean worktree.

```text
python -B compat/fixtures/synthetic/generate_fixtures.py --check
python -B reference/original-0.3.0/environment/verify_frozen_source.py --source .
python -B -m unittest discover -s compat/tests
git diff --check
```
