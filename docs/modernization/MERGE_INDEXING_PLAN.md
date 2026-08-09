# Merge and reader-indexing characterization plan

Status: source-resolved execution plan with the merge compatibility policy
RESOLVED and the canonical baseline established through a narrowly scoped
SECONDARY REGENERATED-SOURCE ORACLE.  The frozen `merge` CLI cannot complete on
the verified profile using the committed generated C
(`MUSCython/GenericMerge.c`, Cython 0.23.4 provenance, deterministic SIGSEGV);
that failure is preserved as historical evidence.  Successful merge semantics
are characterized by regenerating the merge extension from the unchanged
frozen `.pyx` with the profile's pinned Cython 0.29.36 in a disposable build
location.  This plan records the intended experiment and its executed
evidence.  It is a prerequisite for `msbwt-modern2`, not a broad API survey.

## Resolved merge compatibility policy

Authoritative decision (reviewed and authorized):

1. The deterministic segfault in the committed historical
   `MUSCython/GenericMerge.c` is classified as a LEGACY GENERATED-CODE DEFECT
   for the characterized merge path.  It remains authoritative evidence about
   the exact historical frozen generated-C build, and that failure evidence
   must remain preserved.
2. The segfault is NOT the semantic behavior modern2 is required to reproduce.
   Merge semantics are established through a narrowly scoped SECONDARY
   REGENERATED-SOURCE ORACLE using: the exact unchanged frozen `.pyx`; the
   verified `py27-late-05a7d6d83862` environment; the already pinned Cython
   0.29.36 regeneration path demonstrated by the diagnostic; no semantic
   modifications to frozen `.pyx` source.
3. This exception applies ONLY to the merge extension/path blocked by the
   committed historical generated-C defect.  The primary frozen oracle is not
   redefined globally.
4. The source-level `-p 1` default-process bug
   (`UnboundLocalError: local variable 'numProcs' referenced before
   assignment`) is classified as a LEGACY SOURCE BUG.  Frozen source is not
   repaired.  modern2 is explicitly permitted to FIX it as a documented
   correctness/CLI compatibility deviation, making both `merge -p 1` and
   `merge -p 2` functional while matching the characterized successful merge
   semantics.

Promotion contract for the regenerated baseline:

1. The frozen `.pyx` used for regeneration is byte-identical to the committed
   frozen source (hash-verified against `frozen-source.sha256`).
2. The regeneration process is explicit, reproducible, pinned, and documented.
3. Repeated regenerated merge runs are deterministic.
4. The merged primary is byte-identical to the clean-from-scratch combined
   construction for the canonical fixture.
5. The independent host-side BWT oracle validates its semantics.
6. Frozen reader/query/recovered-string behavior validates it.
7. Lazy index/cache behavior is recorded as already characterized.
8. The original committed generated-C segfault remains preserved as historical
   failure evidence.
9. Tests clearly distinguish historical-generated-C behavior from
   regenerated-source semantic oracle behavior.

Do not replace or edit the historical frozen `GenericMerge.c`.  Do not alter
the frozen `.pyx`.  Regenerate/build only in disposable oracle/build locations
according to existing project conventions.

## Scope

One strong, deterministic, end-to-end merge baseline plus the minimum
reader/indexing behavior needed to load and query the merged output.  After
this milestone, unless a serious unresolved compatibility problem remains, the
next major step is implementation of `msbwt-modern2`.

The frozen authority is unchanged: profile `py27-late-05a7d6d83862`, route
`pyx-historical-cython`, the 40-file frozen projection from commit
`7503346ec072ddb89520db86fef85569a9ba093a`.  Do not modify frozen source.

## Why two uniform byte BWTs are the canonical merge case

The frozen CLI `merge` reaches `MUSCython.GenericMerge.mergeTwoMSBWTs` with
exactly two input directories.  The merge loads both inputs as byte BWTs,
solves a bit-packed interleave, and writes the merged `msbwt.npy` plus a
retained `inter0.npy`.

Source-derived constraint (verified host-side against committed goldens, no
oracle execution needed):

- The frozen uniform byte builder (`pp -u` + `cfpp -p 1 -u`,
  `MSBWTGenCython.createMsbwtFromSeqs`) produces the standard
  rotation-sorted MSBWT of the read multiset.  A pure host-side rotation-sort
  oracle reproduces the committed `uniform-multifile` primary byte-for-byte
  (payload SHA-256 `75134b4893420e725fe2766255545f26a29a9b6467eeb00678fb85d4a358989e`).
- The frozen nonuniform builder (`MultimergeCython.interleaveLevelMerge`)
  produces a *different but equally valid* MSBWT byte ordering for the same
  multiset (verified by backward-search k-mer counts and LF recovery of the
  committed `nonuniform-prefix` primary).  The multimerge ordering is not the
  rotation-sort ordering.

Therefore a merge whose inputs are nonuniform-constructed, or a clean combined
control built through the nonuniform path, is not guaranteed to be byte-equal
to a rotation-sorted construction.  The canonical baseline therefore merges
two uniform byte BWTs, whose expected merged bytes are uniquely determined
(the rotation-sorted MSBWT of the union multiset), giving a strong byte-level
independent expectation:

| Logical input | Fixture | Reads | Symbols | Builder |
|---|---|---|---|---|
| `IN_A` | `uniform-a.fastq` | ACGTN, AAAAA, ACGTN, NACGT | 24 | `pp -u` + `cfpp -p 1 -u` |
| `IN_B` | `uniform-b.fastq` | ACGTN, CCCCC, GGGGG, TTTTT | 24 | `pp -u` + `cfpp -p 1 -u` |
| merged | union of the two | 8 reads | 48 | `merge -p 2 MERGED IN_A IN_B` |
| clean control | `uniform-a.fastq` + `uniform-b.fastq` | 8 reads | 48 | `pp -u` + `cfpp -p 1 -u` |

The union includes duplicate reads and the committed fixture's
"tie-across-file" `ACGTN` case, so the experiment exercises merge
multiplicity/tie handling while the merged BWT bytes remain uniquely
predictable.

## Authoritative CLI facts to record

1. `merge` with the default `-p 1` (or an explicit `-p 1`) raises
   `UnboundLocalError: local variable 'numProcs' referenced before assignment`
   (a `NameError` subclass) because frozen `MUS/CommandLineInterface.py` binds
   `numProcs` only inside the `args.numProcesses > 1` branch.  Record this as a
   legacy defect (it determines what `msbwt-modern2`'s `merge` default must
   do).
2. `merge -p N` for `N > 1` logs the "Multi-processing is not supported"
   warning, clamps to a single process, and runs deterministically.  The
   canonical invocation is therefore `merge -p 2`.
3. More than two inputs logs an error and exits 0 without work; one input
   indexes a nonexistent second input.  These are out of scope for this
   milestone; record only the `-p 1` NameError used to justify `-p 2`.

## Frozen merge file contract (source-derived)

- Output directory after success contains exactly `inter0.npy` and
  `msbwt.npy`.  `inter0.npy` is `|u1`, shape `(48/8+1,)` = `(7,)`, bit-packed:
  bit `x` = 0 means merged position `x` comes from BWT0 (`IN_A`), 1 from BWT1
  (`IN_B`).  `msbwt.npy` is `|u1`, shape `(48,)` with a Python-2 NumPy v1
  header, expected raw shape literal `(48L,)`.
- The merge itself does not write `totalCounts.npy` or `fmIndex.npy` into the
  output.  It *creates them lazily in the input directories* as a side effect
  of `loadBWT(..., useMemmap=True)`.
- The merged primary is the rotation-sorted MSBWT of the union multiset, and
  is expected to be byte-identical (whole file, header, payload) to the
  committed `uniform-multifile` byte golden and to a fresh clean build of the
  same union.  If that byte relationship fails, stop and report.

## Experiment

For each canonical run (`run-a`, `run-b`) in a fresh Linux-ext4 result parent:

1. Build `IN_A` from `uniform-a.fastq`; snapshot and parse its primary.
   Expect 24 symbols; expect the primary payload to equal the host-side
   rotation-sort oracle for the four reads.
2. Build `IN_B` from `uniform-b.fastq`; snapshot and parse its primary.
   Expect 24 symbols; same oracle relationship.
3. Build the clean control `CLEAN` from `uniform-a.fastq` + `uniform-b.fastq`;
   snapshot and parse its primary.  Expect it to equal the committed
   `uniform-multifile` byte golden (`dd91d69e...`, `|u1`, `(48L,)`).
4. `-p 1` NameError probe on disposable copies of the fresh inputs: expect
   exit 1, `UnboundLocalError: local variable 'numProcs' referenced before
   assignment`, a created-but-empty output directory, and unchanged inputs.
5. Canonical merge `merge -p 2 MERGED IN_A IN_B`: expect exit 0, output file
   set exactly `["inter0.npy", "msbwt.npy"]`, no derived files in the output,
   and the input directories gaining exactly `totalCounts.npy` and
   `fmIndex.npy`.
6. Reader evidence on disposable copies of `MERGED` only (never the pristine
   output): frozen `loadBWT` returns `ByteBWT`, total size 48, dollar count 8,
   all fixture-derived substring counts match, recovered strings match the
   multiset.  Inventory every created file.  Run the derived-index
   classification probes: deleting `totalCounts.npy`/`fmIndex.npy` and
   reloading reproduces identical reader results (they are derived and
   regenerable); deleting `inter0.npy` and reloading still works (it is
   retained merge provenance, not a reader-required file).
7. CLI `query` on a disposable copy: `query COPY ACGTN` prints 3; `query -d
   COPY ACGTN` dumps three recovered strings (set equality only; dollar IDs
   are tie-order-dependent and are recorded, not asserted across builds).

Require `run-a` and `run-b` to be identical in: retained file sets, whole-file
SHA-256, raw NPY headers, dtype/shape, payload bytes, derived index files,
reader/query results, and recovered sequence results, for both inputs, the
clean control, and the merged output.

## Independent semantic validation (host-side)

After the two runs pass, promote only after:

1. The rotation-sort oracle is re-validated against the committed
   `uniform-multifile` primary payload.
2. The merged primary payload equals the oracle prediction for the 8-read
   union multiset.
3. Merged == clean == committed golden byte-for-byte (whole file).
4. Symbol multiset counts match (A=9, C=9, G=9, N=4, T=9, $=8).
5. Backward-search k-mer counts over the merged payload equal the expected
   substring counts of the 8-read multiset for every substring.
6. LF recovery of the merged payload reproduces exactly the 8-read multiset.
7. `inter0.npy` invariants: the number of 0 bits is 24 and 1 bits is 24; at
   every position whose rotation is unambiguously from `IN_A` or `IN_B`, the
   bit matches the oracle source prediction; at tied positions (rotations of
   `ACGTN`) the bit count matches the multiplicity (2 from A, 1 from B).

## Derived-file classification

| File | Classification |
|---|---|
| `msbwt.npy` | Authoritative persistent byte primary of the merged output. |
| `inter0.npy` | Persistent merge provenance retained by the frozen merge; not required by the reader (verified by removal+reload). |
| `totalCounts.npy`, `fmIndex.npy` | Lazy reader-derived indexes created in the directory being loaded; deletable and regenerated identically on reload. |
| derived files in input dirs after merge | Same lazy reader indexes created by the merge's own `loadBWT`; side effects of the merge, not output artifacts. |

Do not promote disposable reader caches as primary artifacts.  Record them in
the derived-index inventory only.

## Promotion

Promote under `compat/goldens/original-0.3.0/merge-milestone1/`:

- `profile-provenance.json`;
- `determinism-run-a-run-b.json`;
- `relationship-merge-vs-clean.json` (merged vs clean vs committed golden);
- `relationship-independent-oracle.json` (oracle validation, prediction,
  counts, LF recovery, interleave invariants);
- `relationship-reader.json` (reader/query/recovered results, side-effect
  inventory, derived-index classification);
- `relationship-nameerror-p1.json` (the `-p 1` defect record);
- promoted `msbwt.npy` and `inter0.npy` artifacts with a safe byte manifest;
- reader evidence JSON and derived-index inventories.

Do not commit raw run directories, reader-mutated copies, or any disposable
cache.  Do not alter previously committed goldens.

## Tests

Add strict regression tests protecting: fixture-set definition, runner
contract, oracle validation, merged/clean/golden byte relationship, symbol
counts, backward-search counts, LF recovery, interleave invariants,
reader results, derived-index classification, and the `-p 1` NameError
record.

## Stop conditions

Stop and report rather than inventing policy if: repeated runs are
nondeterministic; merged semantics differ from the expected multiset;
reader/query behavior is inconsistent; merged and clean construction differ;
a persistent-format difference appears; integer width/platform behavior
becomes ambiguous; regeneration requires changing the frozen `.pyx`; more than
the affected generated merge extension must be semantically changed; the
previously observed successful diagnostic cannot be reproduced under the
pinned procedure; the `inter0.npy` format is unclear; or a new compatibility
ambiguity appears.  Ordinary harness/build/path issues may be fixed
mechanically.

## Executed blocking finding (resolved)

Executed twice on the verified profile (`py27-late-05a7d6d83862`,
`pyx-historical-cython`, fresh Linux-ext4 result parents) plus repeated
independent probes.  The frozen `merge` CLI does not complete for ANY uniform
byte input under the verified profile when built from the committed generated
C.  This is the LEGACY GENERATED-CODE DEFECT resolved by the policy above; the
failure evidence below is preserved as historical.

1. Deterministic segfault: `merge -p 2` (the only working invocation; `-p 1`
   raises `UnboundLocalError`) exits `-11` (SIGSEGV, shell status 139) for
   6+6, 12+6, 24+6, 6+24, 24+24, and 48+48 symbol inputs.  The crash happens
   inside the first `GenericMerge.targetedIterationMerge2` call, after
   `loadBWT` lazily creates `totalCounts.npy` and `fmIndex.npy` in the two
   input directories.  No `msbwt.npy` or `inter0.npy` is produced and stderr
   is empty.
2. Root cause: the `pyx-historical-cython` route compiles the COMMITTED
   generated C files in the 40-file frozen projection.  The committed
   `MUSCython/GenericMerge.c` is `/* Generated by Cython 0.23.4 */` (other
   modules are mixed Cython 0.18/0.23.4).  The segfault is a codegen artifact
   of that historical C, not of the frozen `.pyx` algorithm.
3. Diagnostic (now the secondary-oracle basis): force-regenerating only
   `GenericMerge` from the frozen `.pyx` with the profile's pinned Cython
   0.29.36 (all other modules unchanged) makes `merge -p 2` succeed.  The
   merged `msbwt.npy` is byte-identical to the committed `uniform-multifile`
   byte golden (whole-file SHA-256 `dd91d69e...`, payload
   `75134b489342...`), the retained file set is exactly
   `["inter0.npy", "msbwt.npy"]`, and a frozen-reader smoke on a disposable
   copy passes all fixture-derived queries and recovered strings with derived
   `totalCounts.npy`/`fmIndex.npy` regenerable byte-identically and
   `inter0.npy` confirmed not required by the reader.
4. `-p 1` defect (LEGACY SOURCE BUG): the default path raises
   `UnboundLocalError: local variable 'numProcs' referenced before assignment`
   (a `NameError` subclass).  stderr SHA-256
   `186d471d861c4eaf8ef200076742e259182b6e3c050ebe26540fbdf1e7eb3a4c`; the
   output directory is created but empty and the inputs are unchanged.
5. Source-derived companion finding (host-side, no oracle execution): the
   frozen nonuniform builder produces a valid MSBWT byte ordering that differs
   from the rotation-sort ordering (both pass all backward-search k-mer counts
   and LF-recover the same read multiset from the committed
   `nonuniform-prefix` primary).  This is why the canonical case uses uniform
   inputs, where the expected merged bytes are uniquely determined.

## Canonical regenerated-source oracle procedure

The successful merge baseline is executed as follows in each fresh WSL run
family, all in disposable locations:

1. Verify the frozen 40-file projection in the built source copy (including
   the exact `MUSCython/GenericMerge.pyx` bytes, hash-pinned in the manifest).
2. Build the two inputs and the clean control through the unchanged frozen
   builder path; verify the clean primary equals the committed uniform golden.
3. Capture the `-p 1` UnboundLocalError probe (LEGACY SOURCE BUG) and the
   `merge -p 2` SIGSEGV probe (LEGACY GENERATED-CODE DEFECT) on disposable
   copies using the committed build.
4. Regenerate and rebuild ONLY `MUSCython.GenericMerge` in the disposable
   built source copy:
   - `python -c "from Cython.Build import cythonize; import numpy; cythonize('MUSCython/GenericMerge.pyx', include_path=[numpy.get_include()], force=True)"`
   - `python setup.py build_ext --inplace`
   - Cython version pinned at 0.29.36 in the verified
     `py27-late-05a7d6d83862` environment.
   - Record the committed and regenerated `GenericMerge.c` hashes and prove
     the `.pyx` hash is unchanged.
5. Run the canonical `merge -p 2` twice (run-a/run-b) on the regenerated
   build; require identical retained file sets, whole-file SHA-256, raw NPY
   headers, dtype/shape, payload bytes, derived index files, reader/query
   results, and recovered sequence results.
6. Run the frozen reader smoke (with derived-index classification) and CLI
   query probes on disposable copies of both merged outputs.
7. Host-side: validate with `compat/tools/bwt_oracle.py`, compare the merged
   primary byte-for-byte with the clean control and the committed uniform
   golden, and verify the `inter0.npy` source-label invariants.

The promoted golden/evidence lives under
`compat/goldens/original-0.3.0/merge-milestone1/`, with the successful
artifacts under `secondary-regenerated-source/` and every evidence record
carrying `oracle_class` so the two oracle classes can never be conflated.

