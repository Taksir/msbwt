# Compression, decompression, and recovery characterization plan

Status: source-resolved execution plan with the verified-profile decompression
failure policy resolved; no compression/recovery golden has been promoted yet.

This plan is for the verified frozen profile `py27-late-05a7d6d83862` and the
historical-pyx route only.  Frozen execution and persisted bytes remain the
authority.  A relationship described as a promotion gate below is a claim to
test, not permission to change the oracle when the claim fails.

## Source conclusions

The frozen source defines three different compatibility areas and they must be
separate milestones:

1. Clean RLE construction/conversion: post-hoc `compress`, `decompress`, and
   uniform direct compressed construction.
2. Builder recovery: uniform direct-RLE checkpoints and nonuniform multimerge
   backups.  These are the only implemented restart detectors.
3. Non-resumable interruption: post-hoc compression, decompression, and the
   uniform byte builder have temporary state but no implemented resume entry.

Do not combine these into one promotion.  Complete milestone 1 before running
milestone 2.  Milestone 3 is failure evidence, not a successful recovery
contract.

The relevant dispatch and implementations are:

- `MUS/CommandLineInterface.py`: CLI parsing and dispatch;
- `MUS/MSBWTGen.py`: the actual CLI `compress` and `decompress` functions;
- `MUSCython/MSBWTCompGenCython.pyx`: direct uniform RLE construction and its
  checkpoint scan;
- `MUSCython/MultimergeCython.pyx`: nonuniform `backup.*.npy` restart;
- `MUSCython/MSBWTGenCython.pyx`: uniform byte construction, whose recovery is
  TODO/commented rather than implemented;
- `MUS/MultiStringBWT.py` and `MUSCython/RLE_BWTCython.pyx`: pure-Python and
  compiled RLE readers and their different derived indexes.

## Common command form and gates

Use the same external probe, environment sanitization, frozen 40-file check,
fixture hash checks, exact profile-version gate, extension build/import, and
CLI-version gate as the committed goldens.  Every directory below is a new
Linux-ext4 path.  `PYTHON` is the verified CPython 2.7 executable and `CLI` is:

```text
from MUS import CommandLineInterface; CommandLineInterface.mainRun()
```

Every CLI line below means:

```text
$PYTHON -c "$CLI" COMMAND ...
```

Use `-p 1` for canonical promotion runs.  Do not normalize artifact bytes.
Normalize only the documented timestamp field in logger text; retain raw
stdout/stderr outside Git.

## Milestone 1: clean RLE paths

### Starting artifacts

Use read-only source goldens only as copy sources.  Each run receives its own
ext4 copy.

| ID | Starting artifact |
|---|---|
| `U_BYTE` | `compat/goldens/original-0.3.0/uniform-multifile/py27-late-05a7d6d83862/pyx-historical-cython/build/artifacts/`; require existing build tree hash `842bfc80080ca553ee23f07eb3da7616df96822cee7d774d163c1c2058d0132e` and `msbwt.npy` SHA-256 `dd91d69ee2785c88652790c8c2b892a173e4e1f57b703bfc00f1a2938dc1a15f` |
| `N_BYTE` | `compat/goldens/original-0.3.0/nonuniform-prefix/py27-late-05a7d6d83862/pyx-historical-cython/build/artifacts/`; require existing build tree hash `ad4aa043feb549e0af861ffde0deca11f8ac0b030c5305183f61f04f5f4d8c0a` and `msbwt.npy` SHA-256 `da28963ca3726568dd7a26eccea35f107bd4cb8b295c909de628374db38dd4b2` |
| uniform FASTQ | committed `uniform-a.fastq` and `uniform-b.fastq`, with their existing fixture-manifest hashes |
| nonuniform FASTQ | committed `nonuniform.fastq`, with its existing fixture-manifest hash |

The copied byte sources must not contain query-derived indexes.  Refuse rather
than delete unexpected files.

### Exact command cases

Run the cases in this order.

1. Post-hoc uniform compression:

   ```text
   compress -p 1 U_BYTE U_RLE
   ```

2. Post-hoc nonuniform compression (the path explicitly recommended by the
   frozen CLI when direct nonuniform compression is requested):

   ```text
   compress -p 1 N_BYTE N_RLE
   ```

3. Uniform and nonuniform decompression expected-failure characterization.
   `U_RLE_SOURCE_COPY` and `N_RLE_SOURCE_COPY` must be disposable pristine
   copies because this command mutates its compressed source by constructing
   pure-Python indexes:

   ```text
   decompress -p 1 U_RLE_SOURCE_COPY U_ROUNDTRIP
   decompress -p 1 N_RLE_SOURCE_COPY N_ROUNDTRIP
   ```

4. Split direct uniform compressed construction:

   ```text
   pp -u U_DIRECT uniform-a.fastq uniform-b.fastq
   cfpp -p 1 -u -c U_DIRECT
   ```

5. Wrapper direct uniform compressed construction, which has a different
   cleanup boundary:

   ```text
   cffq -p 1 -u -c U_WRAPPED uniform-a.fastq uniform-b.fastq
   ```

Run the two post-hoc compression cases and the two direct-construction cases
twice independently at `-p 1`.  After those successful runs match, run one
additional fresh execution of each successful process-bearing command at
`-p 2`.  The `-p 2` primary bytes must match the canonical `-p 1` primary
bytes; a mismatch is a stop condition and is recorded as legacy process-count
behavior.

Run each decompression command twice independently at `-p 1` and require the
authoritative failure contract below.  Do not run it through a helper that
requires exit zero, and do not attempt reader or roundtrip validation on the
preallocated destination.  No `-p 2` decompression behavior has been executed;
it is outside this contract and is not a milestone-1 promotion gate.

### Authoritative verified-profile decompression failure

This is deterministic frozen behavior for the exact verified profile and
inputs below.  It is not a harness/invocation error: direct CLI execution
reached the frozen decompression worker in four fresh probes (two uniform and
two nonuniform), and all four produced the same traceback.  The type mechanism
was also inspected externally without changing the oracle: line 637 creates
`counts` with dtype `<u8`; at line 662, CPython 2.7 plus NumPy 1.16.6 evaluates
the Python `int` expression `s + counts[lInd]` as NumPy `float64` (`1.0` for
the first observed run), which has no `__index__` method and is invalid as a
slice bound.  Other interpreter/NumPy profiles have not been executed, so do
not generalize this result to them.

The narrow authoritative contract is:

1. Profile/route/source: `py27-late-05a7d6d83862`,
   `pyx-historical-cython`, frozen 40-file projection from
   `7503346ec072ddb89520db86fef85569a9ba093a`.
2. Invocation: exact CLI `decompress -p 1 SOURCE_COPY OUTPUT`; `SOURCE_COPY`
   is a fresh ext4 directory containing only the named post-hoc
   `comp_msbwt.npy`, with no derived caches, and `OUTPUT` does not exist before
   argument parsing.
3. Inputs: uniform `comp_msbwt.npy` SHA-256
   `53d82b388a9d565afa96ead611d5db964bee199869fd07f96b8c84258ba099a3`
   (`|u1`, shape `(22,)`), or nonuniform SHA-256
   `9d19222eaa78c1d89304e79ff14a8a0a5f0c21c3ae979d179f570f1d8d5c1e66`
   (`|u1`, shape `(16,)`).  These compression outputs have been produced only
   once each and are inputs to this failure decision, not yet promoted
   successful compression goldens.
4. Result: exit `1`; final exception exactly
   `TypeError: slice indices must be integers or None or have an __index__ method`
   at `MUS/MultiStringBWT.py:662`, reached through
   `CommandLineInterface.py:175`, `MSBWTGen.py:1203`,
   `MSBWTGen.py:1222`, and `MultiStringBWT.py:608`.  The complete raw stderr
   was byte-identical in all four probes, SHA-256
   `227471aa531ec114ada93c2507f6b621df8109d70324b7217285efd518904ac4`.
5. Partial state: the source primary remains unchanged and gains exactly
   `totalCounts.p`, `comp_fmIndex.npy`, and `comp_refIndex.npy`; the destination
   contains exactly one preallocated, unwritten `msbwt.npy`.  Exact per-case
   manifests are:

| Case | Source-after manifest content SHA-256 | Destination manifest content SHA-256 | Preallocated destination |
|---|---|---|---|
| uniform | `722451840cfca8ff03edfe11c80ba08fed3949636717febaaf8200f1efdd0bf5` | `2d33197387eafb59f1c9db2834f9da9f24d60a68ff01282f31f1787a0be0093a` | `msbwt.npy`: `|u1`, shape `(48,)`, whole-file SHA-256 `f9450ec830d3eca779fdb8a7df2127cb0117620b3ce3588a1c9d76625b96aa22`, 48 zero-byte payload SHA-256 `17b0761f87b081d5cf10757ccc89f12be355c70e2e29df288b65b30710dcbcd1` |
| nonuniform | `38e5d6b9d432215173d0c2f7fcb29b3b746ed7d6b5e72ed9c42259ba9c4567dd` | `e968933ebbd14dc2e73bf50171920cde2795eed23c1164b88268efbe7c5d3292` | `msbwt.npy`: `|u1`, shape `(30,)`, whole-file SHA-256 `df951972060da0644c1da6d1f7e2a318d26f6220c51fd2fccd5e374ebc7b83a3`, 30 zero-byte payload SHA-256 `0679246d6c4216de0daa08e5523fb2674db2b6599c3b72ff946b488a15290b62` |

For each case the two source-after manifests matched with no added, removed,
or changed entries, and the two destination manifests also matched exactly.
Record stdout after replacing the timestamp and disposable absolute paths;
retain its raw hash outside Git.  The traceback needs no normalization under
the specified working directory.

Commit two path-sanitized run records per case, source-before/source-after and
destination safe manifests, the two determinism comparison reports, one exact
canonical stderr record, profile/frozen-source/input provenance, and strict
tests for all values above.  Do not commit raw run directories, absolute-path
stdout, the pickle/cache files, or the invalid preallocated `msbwt.npy`; their
exact bytes, headers, payloads, file sets, and hashes are represented by the
safe manifests.

Regression execution must use an expected-failure capture path that asserts
exit `1`, the exact traceback/final exception, the unchanged compressed
primary, the exact three source side effects, the exact destination manifest,
and equality between two fresh runs.  It must then continue to the remaining
milestone-1 cases.  Never load the partial `msbwt.npy` or assert it as a
roundtrip output.

### Exact unsupported cases

These are failure-characterization records, not successful goldens:

```text
cfpp -p 1 -c N_PREPROCESSED_COPY
cffq -p 1 -c N_UNSUPPORTED nonuniform.fastq
```

`N_PREPROCESSED_COPY` is an exact ext4 copy of the committed nonuniform
preprocessing artifacts.  Source inspection predicts an error log, zero CLI
exit status, and no `comp_msbwt.npy`; `cffq` creates its output directory during
argument parsing.  Record the actual results.  Do not convert the log-only
failure into an exception or add `-u`.

### Artifact classification

| File/state | Classification and promotion rule |
|---|---|
| `comp_msbwt.npy` | Authoritative RLE primary.  Promote exact file bytes, NPY header, `|u1` shape, payload hash, decoded runs, and uncompressed logical length. |
| `msbwt.npy` in either named decompression destination | Deterministic invalid failure artifact: a correctly shaped but unwritten all-zero preallocation.  Manifest it exactly, but never classify or load it as a byte primary. |
| `about.npy` | Authoritative provenance where direct FASTQ construction produces it.  Post-hoc `compress`/`decompress` do not copy it. |
| `seqs.npy*` and `offsets.npy` | Authoritative preprocessing inputs retained by split `pp` + `cfpp`; the `cffq` wrapper deletes them on success.  Preserve that file-set difference. |
| `totalCounts.npy`, `fmIndex.npy`, `comp_fmIndex.npy`, `comp_refIndex.npy` | Derived compiled-reader indexes.  Exclude from pristine primary goldens; inventory exact side effects on disposable copies. |
| `totalCounts.p`, `comp_fmIndex.npy`, `comp_refIndex.npy` created by CLI `decompress` | Derived pure-Python source mutations.  Hash/inventory them without deserializing the pickle, but exclude them from the pristine compressed primary. |
| `comp_msbwt.npy.temp.<bin>.npy` | Compression temporary.  It must be absent after success and retained in any interrupted/failing evidence exactly as observed. |
| direct-builder `state.*`, `fmStarts.*`, `fmDeltas.*`, `inserts.*` | Checkpoint/temporary state.  It must be absent after clean success.  It belongs only in recovery evidence when interrupted. |

### Required relationships

All relationships below are required promotion gates for successful outputs:

1. Uniform post-hoc `U_RLE`, split direct `U_DIRECT`, and wrapper direct
   `U_WRAPPED` must have byte-identical `comp_msbwt.npy`.  The two construction
   algorithms emit the same source-defined RLE representation; any observed
   mismatch is conflicting legacy semantics and requires a stop/report.
2. Split and wrapper `about.npy` must match.  Their complete retained file sets
   must not be forced to match because wrapper cleanup is source-defined.
3. On separate disposable copies, the compiled RLE reader must return the same
   total size, symbol totals, fixture-derived substring counts, dollar IDs, and
   recovered strings as the matching committed byte reader evidence.
4. A disposable coexistence directory containing both byte and RLE primaries
   must load as `ByteBWT`; after removing only the disposable byte primary, it
   must load as `RLE_BWT` with the same logical results.  This records loader
   preference and does not create a writer golden.
5. RLE decode must be checked independently with a tiny safe decoder: low
   three bits are the symbol; consecutive bytes with the same symbol are
   least-significant-first base-32 run digits in the upper five bits.

Do not compare pure-Python and compiled derived index files as primary bytes.
The source computes different cache types (`totalCounts.p` versus
`totalCounts.npy`) and has an FM sample-shape difference at exact multiples of
2048.  Compare reader behavior instead and retain each side-effect inventory.

### Milestone 1 determinism and promotion

For every run, inventory the complete source-before, source-after, destination,
and reader-copy trees with the safe artifact tool.  Require identical retained
file sets, whole-file SHA-256, raw NPY headers, logical dtype/shape, and payload
SHA-256 across the two canonical `-p 1` runs.  Require exact primary equality
for the additional `-p 2` run.

Successful post-hoc compression is independently promotable despite the
authoritative decompression failure after its two canonical runs match, its
`-p 2` primary matches, the safe decoder validates it, and the frozen compiled
RLE reader passes fixture-derived behavior and side-effect inventory checks.
The uniform cross-algorithm relationship report remains required once the
direct outputs exist, but decompression success is not a prerequisite for
post-hoc compression promotion.

Promote only reviewed successful artifacts, manifests, decoded-RLE reports,
relationship reports, reader-side-effect inventories, the named failure
records/manifests, and path-sanitized provenance.  Never promote raw run
directories, reader-mutated copies, pure-Python pickle contents, invalid
preallocated decompression outputs, or compression temp files from a
successful case.

## Milestone 2: implemented builder recovery

Recovery must be induced by an external failpoint adapter; do not patch the
frozen files.  The adapter runs in a new process session, calls the same frozen
function used by CLI dispatch, supplies a logger that recognizes one exact
completed-checkpoint message, flushes a failpoint record, and calls
`os._exit(86)`.  The outer harness then terminates any remaining process-group
children.  Commit and hash the adapter as harness infrastructure.

This is preferable to sleep/timeout killing: file existence alone does not
prove that an NPY header or raw state file has finished writing.

### Recovery case R1: direct uniform RLE checkpoint

1. Create and verify fresh preprocessing:

   ```text
   pp -u R1_PARTIAL uniform-a.fastq uniform-b.fastq
   ```

   Its preprocessing manifest must match the committed uniform preprocessing
   manifest before failure injection.
2. Invoke frozen `MSBWTCompGenCython.createMsbwtFromSeqs(R1_PARTIAL, 1,
   failpoint_logger)` externally.  Exit at the logger message beginning
   `Finished iteration 2 in`.
3. Require exit 86.  Inventory the untouched partial tree.  At minimum it must
   contain six `state.<symbol>.2.dat` files plus `fmStarts.2.npy` and
   `fmDeltas.2.npy`; retain every matching `inserts.*.2.npy` actually present.
4. Copy the partial tree to `R1_RESUME`; never resume the evidence snapshot.
5. Resume through the exact CLI path:

   ```text
   cfpp -p 1 -u -c R1_RESUME
   ```

6. Build `R1_CLEAN` from an independent identical preprocessing copy with the
   same CLI command and no failpoint.
7. Require resumed and clean complete trees and `comp_msbwt.npy` bytes to match;
   require the resumed log to contain `Resuming previous run from 2`.

Repeat the interrupt/snapshot/resume sequence twice.  The two partial manifests
must match exactly at the named checkpoint, and both resumed results must match
the clean control.  Any missing/extra checkpoint accepted by the reader or any
leftover checkpoint after success is a stop condition; do not clean it away.

### Recovery case R2: nonuniform multimerge backup

The current seven-read fixture never reaches a backup because the first merge
groups up to 256 reads.  Add one deterministic recovery fixture before running:

```text
recovery-nonuniform-259.fastq = exact bytes of nonuniform.fastq repeated 37 times
byte_count = 9102
sha256 = 8606e2b580afeafee17600ce6c33db67d14f2cc22235edfa51100811ad6d65b9
```

The repeated headers are intentional and harmless because the frozen FASTQ
preprocessor ignores headers.  Add the fixture through the existing generator
and fixture manifest; verify the rule and hash in tests before oracle execution.

1. Run:

   ```text
   pp R2_PARTIAL recovery-nonuniform-259.fastq
   ```

2. Invoke frozen `MultimergeCython.interleaveLevelMerge(R2_PARTIAL, 1, False,
   failpoint_logger)` externally and exit at the exact message
   `Backup creation finished.`
3. Require exit 86 and a complete `backup.256.npy`; inventory the whole partial
   tree, including `msbwt.npy` and any `msbwt.temp.*`/`inter*` files present.
4. Resume only a copy:

   ```text
   cfpp -p 1 R2_RESUME
   ```

5. Require the log to contain `Backup located, resuming...`, and compare the
   final tree/primary bytes and reader results to an independent clean build.

Repeat twice and require identical partial manifests and identical resumed
results.  The restart code selects the numerically largest backup but validates
no checksum, shape, or completeness; do not add such validation to the oracle.

### Recovery evidence retention

For each interruption retain the expected exit, failpoint identifier, exact
argv/API call, normalized and raw-log hashes, complete partial file manifest,
and pre/post tree hashes.  Partial primaries, checkpoints, inserts, backups,
temp files, and derived indexes are evidence even when truncated or invalid.
Never load a partial `msbwt.npy`/`comp_msbwt.npy` as a valid dataset unless the
frozen restart path itself does so.

Successful resumed outputs may be promoted only beside their clean controls and
relationship report.  Partial trees belong under named recovery evidence, not
under a pristine successful artifact directory.

## Milestone 3: non-resumable interruption evidence

Source inspection does not establish a safe restart contract for these paths:

- uniform byte construction has only TODO/commented recovery code;
- `compressBWT` writes `comp_msbwt.npy.temp.<bin>.npy` but never scans it;
- `decompressBWT` preallocates `msbwt.npy` and never scans completed chunks;
- CLI `newDirectory` rejects a nonempty destination, so an interrupted
  compression/decompression destination cannot be passed back to the CLI.

Do not describe rerunning any of these as recovery.  The smallest deterministic
evidence experiment is an external failpoint wrapper around the original worker
function at `-p 1`:

1. For compression, call the original `compressBWTPoolProcess` once, then exit
   86 before the parent joins temp files.  Record the complete temp file and
   absence/partial state of the final primary.
2. For decompression, first create an evidence-only `msbwt.npy` longer than
   1,000,000 symbols by repeating a committed valid byte payload.  Compress it
   cleanly.  Call the original `decompressBWTPoolProcess` for the first tuple,
   then exit 86 before the second tuple.  This leaves a preallocated primary
   with one completed region and one unwritten region.
3. Invoke the unchanged CLI against copies of each nonempty interrupted
   destination and record the parser refusal.  Do not empty, rename, or delete
   files to make restart succeed.

These probes are failure characterization only.  Do not promote their partial
bytes as successful goldens or define a resumable contract until execution
shows a source-supported continuation path.

Also capture a uniform byte-builder interruption at `Finished iteration 2 in`.
A subsequent `cfpp -p 1 -u` invocation starts construction again; it does not
scan a checkpoint.  Record whether the final output happens to match a clean
build, but label it restart-from-scratch, not resume.

## Source-visible stop conditions and legacy failures

Medium must stop and report rather than work around any of these:

1. Direct compressed nonuniform requests log an error but can exit zero after
   creating/retaining a directory.  Preserve the exit/log/file set.
2. Post-hoc CLI compression/decompression dispatches to pure Python even though
   near-duplicate Cython functions exist.  Test the actual CLI target only;
   the two named `-p 1` decompressions must match the authoritative failure
   contract above rather than stop the milestone.
3. CLI decompression mutates its compressed source with pure-Python caches,
   including pickle.  Always use a disposable source and do not suppress it.
4. Direct RLE recovery trusts checkpoint existence, scans columns from zero,
   and has no atomic marker/checksum.  Stale or partial checkpoint behavior is
   evidence, not permission to select a different checkpoint.
5. Multimerge trusts the largest numeric backup without validation.  Preserve
   failures or divergent resumed bytes.
6. CLI same-directory decompression is rejected by destination parsing for a
   nonempty source even though the API comment says source and destination may
   match.  Do not reinterpret the CLI contract.
7. Pure and compiled RLE readers produce different cache types and may choose
   different FM-index shapes at a total length exactly divisible by 2048.
   Treat caches as derived and compare observable reads.
8. Raw direct-RLE state uses C `fopen(..., "w+")` text mode.  This milestone is
   Linux-oracle evidence only and establishes no Windows byte claim.

Any primary mismatch between clean algorithms, successful process counts, or
resume/control is a compatibility-policy stop.  Any decompression result that
differs from the narrow expected-failure contract is also a stop.  Commit
failure evidence only after review; never update an existing golden or repair
frozen source.

## Exact acceptance checklist for Medium

1. Verify clean branch/worktree, all existing locks/profile/goldens, fixture
   check, frozen 40-file projection, exact CPython-2 profile, extension import,
   and CLI version before each run family.
2. Add only manifest-driven case definitions and external failpoint tooling;
   tests must prove exact argv/options and failpoint messages before execution.
3. Execute milestone 1 in the listed order: two fresh `-p 1` runs per
   successful case, two fresh `-p 1` runs per named decompression failure, then
   one fresh `-p 2` process-count comparison for successful commands only; run
   both unsupported nonuniform cases as named failure evidence.
4. Require both decompression cases to match the exact exit, traceback, source
   side effects, destination preallocation, manifests, and two-run determinism
   contract above.  Do not load partial outputs or require a roundtrip.
5. Require exact uniform RLE equality across post-hoc, split, wrapper, and
   successful process-count paths.  Stop on any mismatch.
6. Run fixture-derived compiled-reader query/recovery checks on disposable RLE
   and coexistence copies; inventory all source and reader side effects without
   mutating pristine promoted artifacts.
7. Promote milestone 1 only after safe manifests prove identical file sets,
   whole-file hashes, raw headers, dtype/shape, payload hashes, decoded RLE, and
   canonical tree hashes; commit path-sanitized provenance and strict tests.
8. Add and verify the exact 259-read recovery fixture, then execute R1 and R2
   twice each using exit-86 failpoints, immutable partial snapshots, resume
   copies, and independent clean controls.
9. Require partial-manifest repeatability, explicit frozen resume log markers,
   byte-identical resumed/clean primaries, equal reader behavior, and clean
   success-time checkpoint removal.  Stop on any divergence or leftover.
10. Run milestone 3 only as named failure experiments.  Preserve every partial
   file and parser/exit result; make no recovery or successful-golden claim.
11. Rerun fixture generation checks, frozen-source verification, all compatibility
    tests, WSL shell syntax checks, and `git diff --check`; make separate focused
    commits for harness, clean RLE goldens, recovery evidence, and documentation.

After this plan is committed, the exact next executable milestone is milestone
1 only.  Do not begin recovery execution, modern2, or modern3 in the same
change set.
