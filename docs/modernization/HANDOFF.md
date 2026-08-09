# Modernization handoff

Status: Compression/Recovery Milestone 1 (clean RLE) is complete on branch
`codex/modernization`; the post-hoc and direct uniform routes plus the
nonuniform post-hoc route are promoted to separate route-specific goldens, the
uniform cross-route semantic equality and the decompression expected-failure
contract are verified under `py27-late-05a7d6d83862`, and the host-side safe RLE
decoder is committed.  Milestone 2 (builder recovery) has not started; no
modern2 or modern3 implementation port has started.

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
- `COMPRESSION_RECOVERY_PLAN.md`: source-resolved next commands, artifact
  policy, failpoints, stop conditions, and acceptance checklist.
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
  and fixture-derived reader smoke have golden coverage.  Compression/Recovery
  Milestone 1 (clean RLE) is now promoted: post-hoc and direct uniform plus
  nonuniform post-hoc routes have route-specific goldens, cross-route uniform
  semantic equality is verified, and the two decompression expected-failure
  cases and the two unsupported nonuniform direct cases have committed evidence.
  Builder recovery, merge, indexing, and broader API/CLI behavior remain.
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

## Completed Compression/Recovery Milestone 1

Clean RLE construction/conversion is fully characterized and promoted from one
verified WSL2 ext4 oracle run (`py27-late-05a7d6d83862`, `pyx-historical-cython`,
candidate `late-python2-candidate`).  The external harness relationship gate was
amended in commit `48f8ea6` to compare route-specific whole files, direct
split/wrapper whole files, and cross-route payload/decoded reports separately,
matching the policy resolved in `5ca132d`.  The run executed two canonical
`-p 1` groups, the two authoritative `-p 1` decompression failures per case,
one fresh `-p 2` successful-process comparison, the two unsupported nonuniform
direct cases, and the disposable compiled-reader evidence, then wrote
`raw-result.json` with `"status": "passed"`.

### Promoted goldens

Route-specific RLE primaries under
`compat/goldens/original-0.3.0/<case>/py27-late-05a7d6d83862/pyx-historical-cython/`
(each with `artifacts/`, `manifest.json`, `decoded-rle.json`, `provenance.json`,
and `reader-smoke.json`):

| Case | Files | `comp_msbwt.npy` SHA-256 | Raw shape | Runs | Decoded |
|---|---|---|---|---|---|
| `uniform-compress-posthoc` | `comp_msbwt.npy` | `53d82b388a9d565afa96ead611d5db964bee199869fd07f96b8c84258ba099a3` | `(22,)` | 22 | 48 |
| `nonuniform-compress-posthoc` | `comp_msbwt.npy` | `9d19222eaa78c1d89304e79ff14a8a0a5f0c21c3ae979d179f570f1d8d5c1e66` | `(16,)` | 16 | 30 |
| `uniform-direct-split` | `comp_msbwt.npy`, `about.npy`, `offsets.npy`, `seqs.npy.{0..5}.npy` | `0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372` | `(22L,)` | 22 | 48 |
| `uniform-direct-wrapper` | `comp_msbwt.npy`, `about.npy` | `0ca6329b54f0cdcec79a5f274fcafa226ee04095b7849ef6624edc630040a372` | `(22L,)` | 22 | 48 |

Shared uniform RLE payload SHA-256
`6aadcd547a785e10d8c24304b8084d31e2c5988d6349bef8ce64260f14fb7bcb`; decoded
BWT `ANNNCGTTAAAA$N$$$CCCC$AAAAGGGG$CCCCTTT$GTGGGTTT$` (SHA-256
`75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e`, equal to
the committed uniform byte primary).  Nonuniform decoded BWT SHA-256
`7a97b19addd3c41a79dbd6ce5e43609766eca78a971576e1ab2b32e3df80ca03`, equal to
the committed nonuniform byte primary.  Direct split and wrapper whole files
are byte-identical and byte-identical across `-p 1` and `-p 2`; each route is
byte-for-byte deterministic across `run-a`, `run-b`, and `run-p2`.

Cross-route relationship, determinism, coexistence loader preference, profile
provenance, the two decompression-failure records/manifests/canonical stderr,
and the two unsupported records are committed under
`compat/goldens/original-0.3.0/compression-milestone1/`.  Pure-Python pickle
contents, reader-mutated copies, invalid preallocated decompression outputs, and
raw run directories are NOT committed; their exact bytes are represented by the
safe manifests.

### Verified behavior

- Within-route determinism: identical retained file sets, whole-file SHA-256,
  raw NPY headers, dtype/shape, payload SHA-256, and decoded products across
  both `-p 1` runs and the `-p 2` run for all four routes.
- Cross-route uniform semantic equality: identical `|u1` logical shape `(22,)`,
  RLE payload bytes, 22-run sequence, decoded length 48, and decoded BWT;
  post-hoc whole file differs from direct only by the `(22,)` vs `(22L,)`
  NumPy shape literal.
- Safe RLE decoding (host-side, no NumPy/pickle): parses NPY v1 framing,
  rejects inconsistent dtype/shape/payload, reports every encoded base-32
  digit, run boundaries, symbol/count pairs, decoded length, and decoded-BWT
  hash over numeric symbol-index bytes.
- Frozen compiled reader: each route loaded as `RLE_BWT`, total size 48 (uniform)
  / 30 (nonuniform), matched all fixture-derived queries and recovered strings,
  and created exactly `totalCounts.npy`, `comp_fmIndex.npy`, `comp_refIndex.npy`
  on disposable copies.  Coexistence of byte and RLE primaries loaded as
  `ByteBWT`; after removing only the byte primary, loaded as `RLE_BWT` with the
  same logical results.
- Decompression expected failure (two fresh `-p 1` probes per case): exit `1`,
  stderr SHA-256 `227471aa531ec114ada93c2507f6b621df8109d70324b7217285efd518904ac4`,
  final exception
  `TypeError: slice indices must be integers or None or have an __index__ method`
  at `MUS/MultiStringBWT.py:662`.  Source-after gained exactly
  `totalCounts.p`, `comp_fmIndex.npy`, `comp_refIndex.npy`; destination retained
  one correctly shaped but all-zero preallocated `msbwt.npy`.  Both runs matched
  byte-for-byte.
- Unsupported nonuniform direct compression (`cfpp -p 1 -c`, `cffq -p 1 -c`):
  exit `0`, no `comp_msbwt.npy`, log-only failure preserved.

## Next milestone boundary

Milestone 1 is committed and green.  The next executable step is Milestone 2
(builder recovery) only, following `COMPRESSION_RECOVERY_PLAN.md`: add the exact
259-read `recovery-nonuniform-259` fixture, then run R1 (direct uniform RLE
checkpoint) and R2 (nonuniform multimerge backup) twice each with exit-86
failpoints, immutable partial snapshots, resume copies, and independent clean
controls.  Milestone 3 is non-resumable interruption evidence only.  Do not
begin modern2 or modern3 implementation first.

### Resolved compression policy

- Post-hoc `compress`, direct `cfpp -u -c`, and direct `cffq -u -c` each require
  a separate authoritative whole-file golden and two byte-identical `-p 1`
  executions.
- Each successful path requires one fresh `-p 2` execution byte-identical to
  its own `-p 1` primary.  Direct split and wrapper primaries must remain
  byte-identical to each other at both process counts.
- Across uniform routes, require identical RLE payload bytes, run boundaries,
  symbol/run-length sequence, decoded length and BWT, plus frozen-reader total
  size, symbol totals, queries, dollar IDs, and recovered strings.
- Safe decoding must parse NPY framing and the RLE payload independently; reader
  agreement alone does not prove persistent-byte interchangeability.  Reader
  checks run only on disposable copies and inventory their derived indexes.
- Promote each route independently only after same-route determinism, `-p 2`,
  safe decoding, reader validation, and the cross-route relationship report all
  pass.  Stop on any difference beyond the documented post-hoc/direct NPY shape
  header, or on any change to the resolved decompression failure contract.

### Resolved decompression policy

Two fresh uniform probes and two fresh nonuniform probes under
`py27-late-05a7d6d83862` and `pyx-historical-cython` all exited `1` at frozen
`MUS/MultiStringBWT.py:662` with exactly:

```text
TypeError: slice indices must be integers or None or have an __index__ method
```

The complete stderr was byte-identical across all four probes.  In each case
the disposable compressed source gained exactly `totalCounts.p`,
`comp_fmIndex.npy`, and `comp_refIndex.npy`, while the new destination retained
only a correctly shaped but unwritten all-zero `msbwt.npy`.  Two-run safe
manifests matched exactly within each case.  External type inspection showed
that the frozen `<u8` count and Python `int` addition produces NumPy `float64`
under this CPython-2.7/NumPy-1.16.6 profile, so the slice bound is invalid.

Treat this only as the narrow expected failure defined in
`COMPRESSION_RECOVERY_PLAN.md`: exact profile, route, frozen source, named
post-hoc compressed inputs, command, `-p 1`, exit, traceback, and partial
manifests.  Other profiles and `-p 2` decompression are uncharacterized.  The
milestone harness must capture and assert the failure, then continue; it must
not require exit zero, load the partial output, repair the oracle, or infer a
roundtrip contract.

The one observed successful post-hoc compression result for each input is not
yet promotable because compression has not been repeated.  Decompression
failure does not block independent compression promotion: after two canonical
compression runs match, the `-p 2` primary matches, safe RLE decoding passes,
and the frozen compiled reader validates fixture-derived behavior and side
effects, the post-hoc compression evidence may be promoted.

Do not start recovery execution until clean RLE milestone 1 is committed and
green.  Recovery then uses only the named external failpoints and immutable
partial snapshots in the plan.  Post-hoc compression, decompression, and the
uniform byte builder have no source-supported resume entry; characterize their
interruptions as failures rather than inventing recovery.  Do not begin modern2
or modern3 implementation first.

Finish every handoff with the commands below and a clean worktree.

```text
python -B compat/fixtures/synthetic/generate_fixtures.py --check
python -B reference/original-0.3.0/environment/verify_frozen_source.py --source .
python -B -m unittest discover -s compat/tests
git diff --check
```
