# Compatibility and testing plan

## Authority model

Use three simultaneous oracles:

1. frozen original execution for observable legacy behavior;
2. independent mathematical/reference implementations for correctness on tiny inputs;
3. byte manifests for persistent artifacts.

Legacy equivalence alone can preserve bugs; a mathematical oracle alone can accidentally break compatibility. When they disagree, classify and document the original defect before changing expected modern behavior.

## Phase 0: reconstruct the legacy oracle

Create a digest-pinned Linux container with Python 2.7 and a tested compiler. Attempt two builds independently:

- committed generated C without Cython, after recording the known `CompressToRLE.pyx` fallback defect rather than silently repairing the oracle;
- original `.pyx` with a historically compatible Cython version (source contains 0.18 and 0.23.4 output).

Resolve NumPy and pysam through empirical build/import/operation tests. Capture the full environment: base image digest, Python, pip/setuptools, NumPy, pysam, Cython, compiler/libc, flags, locale, timezone, CPU architecture, and package hashes. Freeze a runnable image and never mutate its source. If a minimal harness adapter is unavoidable, mount it externally and record it.

The first deliverable is not “all tests pass”; it is a machine-readable matrix of what builds, imports, runs, fails, and crashes.

## Fixture ladder

### Deterministic synthetic fixtures

Generate fixtures with a repository script and a checked seed; do not hand-maintain ambiguous binary files. Include:

- one read, duplicate reads, lexicographic ties across files, prefix-related reads, all six symbols, reverse complements, and paired identifiers;
- uniform and variable lengths, empty inputs, shortest practical reads, long homopolymers at RLE boundaries 1/31/32/33/1023/1024/1025, and total lengths around FM bin 2048;
- plain and gzip FASTQ, LF and CRLF, multiline/multiple-file FASTA, name-sorted tiny BAM, and malformed/invalid alphabet cases;
- two and three source datasets for merge behavior, including both byte and RLE inputs;
- controlled partial-build directories for each recovery mechanism.

Fixture FASTQ should use deterministic headers and qualities even though the original ignores them. Deterministic gzip generation must fix timestamp, filename header, compression level, and OS byte.

### Public biological fixtures

Select one small bacterial and one small viral read set from stable public archives. Record accession, exact URL/API query, source version/date, license/usage terms, original checksum, extraction command, selected read range, and committed derived-fixture checksum. Keep repository payloads small enough for normal CI; permit a separately downloaded extended benchmark tier.

Do not choose accessions from memory. Selection is an open task requiring live archive/licensing verification. Never commit private data or make it a CI prerequisite.

## Golden artifact protocol

For every legacy command/writer scenario, store inputs plus a manifest containing:

- command/API call, environment image ID, working-directory layout, process count, and expected exit/exception;
- recursive relative file list, classification (primary/provenance/derived/recovery), size, SHA-256, and whether success should retain it;
- for real `.npy`: magic/version, raw header bytes/hash, parsed dtype descriptor, shape, order, and payload hash;
- for raw files: declared dtype/endianness/record layout and payload hash;
- normalized stdout/stderr plus unnormalized capture; timestamps may be normalized only by an explicit rule;
- logical decoded sequences, BWT, total counts, FM samples, provenance mapping, and query results.

Goldens must be immutable review artifacts. Updating a hash requires either proof that the old golden was invalid or an approved `COMPATIBILITY.md` entry. Keep legacy-bug goldens alongside corrected-modern expectations when behavior intentionally changes.

## Mathematical tiny oracle

Implement a deliberately slow, clear reference for tiny strings:

1. validate/append one `$` per read according to the scenario;
2. enumerate rotations/suffix ordering using the legacy tie rule;
3. derive the multi-string BWT and dollar IDs;
4. implement straightforward substring counts, recovery, merge equivalence, RLE encode/decode, and FM values.

Use exhaustive alphabets on very small read sets and property-based/randomized cases with a recorded seed. Compare every practical query result and decoded persistent payload. Keep this oracle independent of production Cython.

## CLI characterization matrix

For all nine subcommands plus global/no-subcommand behavior, test:

- help/version text, aliases, defaults, ordering, exit codes, stdout/stderr, and logging;
- every valid mode (uniform/non-uniform, compressed/byte, process counts 1 and >1, stdin/file conversion, reverse-complement query, dump sequences);
- missing/extra paths, one/two/three merge inputs, existing empty/non-empty/hidden-only output directories, source=destination, invalid k-mers/process counts, and partial input;
- full artifact manifests on success and failure;
- equivalence claims such as `cffq` versus `pp` then `cfpp`, comparing both logical datasets and retained file sets.

The default `merge` crash and log-only unsupported modes must first be captured as legacy behavior, then corrected under explicit compatibility entries.

## API characterization matrix

Test every importable module and public name listed in `BEHAVIORAL_SURFACE.md`. For each callable, record signature/defaults, accepted positional/keyword forms, text/bytes/path types, return type/value/dtype, exceptions, warnings/logs, filesystem mutations, and behavior on byte/RLE/LZW readers where applicable.

Priority groups:

1. load/detection, exact counts/ranges, character/FM access, iteration, dollar-ID mapping, string recovery;
2. all builders/preprocessors/merge/compress/decompress/cleanup functions;
3. regex/error-tolerant/k-mer/pileup/LCP-assisted searches and RLE deletion;
4. FASTA/BAM utilities, alignment functions, profile functions, transcript assembly;
5. low-level pool workers only where external invocation is practical or they define recovery formats.

Explicitly test loader behavior with mixed primary files, missing logger, read-only files, stale/wrong-shaped auxiliaries, absent LCP, invalid symbols, out-of-range indexes, zero-length sequences, and corrupted/truncated headers. Crashes belong in isolated subprocess tests.

## Cross-version reader/writer matrix

Run each dataset exchange in fresh processes/environments:

| Writer | Original reader | modern2 reader | modern3 reader |
|---|---:|---:|---:|
| original | baseline | required | required |
| modern2 | required where format supports it | required | required |
| modern3 | required where format supports it | required | required |

For each cell, test byte BWT, RLE BWT, preprocessing artifacts consumed by `cfpp`, provenance, merge interleave, optional LCP, and any available LZW specimens. Delete derived indexes before read to prove reconstruction. Then retain indexes created by one implementation and load them with the others. Exercise both primary-file preference orders.

“Readable” means load plus query/recovery/decoded-payload checks, not merely `np.load` success. Any unsupported reverse direction needs a format-specific explanation and migration tool/guide.

## Determinism and bit-level checks

For each writer repeat runs:

- at least three times in the same environment;
- with process counts 1, 2, and a practical larger count;
- under different `PYTHONHASHSEED` values where supported;
- on at least Linux x86-64 and every claimed Tier 1 platform;
- with warm and cold-ish filesystem cache trials separated from correctness hashes.

Compare recursive file sets and raw SHA-256. Also compare decoded values so a header-only delta is obvious. If a modern NumPy header differs, first implement stable legacy header emission or pin the writer; do not relax the test to payload-only without an intentional compatibility decision.

## Recovery, corruption, and security tests

- terminate builds at named checkpoints, copy the directory, resume, and compare with clean output;
- inject stale/partial recovery files and verify deterministic refusal or documented recovery;
- corrupt magic, header, dtype, shape, symbol values, RLE digits, index lengths, and offsets;
- use object-dtype `.npy` and malicious pickle sentinels to prove modern readers never execute deserialization code;
- test path traversal-like names only through in-scope directory APIs, symlinks where platforms support them, read-only inputs, disk-full simulation, and interrupted in-place deletion;
- fuzz parsers/decoders in subprocesses with time and memory limits, especially unchecked Cython surfaces and regex expansion.

## Test organization and CI

Use pytest for modern3 and shared black-box orchestration. Modern2 may use the last pytest supporting Python 2 or a small unittest/pytest-compatible runner; do not force unsupported lint/build tools into its runtime. Scenarios and expected JSON/manifests should remain language-neutral.

Suggested CI layers:

1. fast static/docs/format checks and tiny modern3 tests on each change;
2. modern2 container plus modern3 differential tiny suite;
3. platform wheel build/install/import and reader/writer exchange;
4. scheduled public-data, recovery, fuzz, security, and extended compatibility runs;
5. release workflow that rebuilds from tag, tests wheel and sdist, verifies generated C policy, and publishes attestations/checksums.

Coverage should report Python and Cython lines/branches where tooling permits, but coverage percentage must not replace behavioral inventory completion.

## Benchmark baseline

Benchmark only after correctness fixtures are stable. Measure separately:

- FASTQ preprocessing; uniform byte build; direct RLE build; variable-length multimerge;
- two-BWT merge across input representations; compress/decompress; LCP generation; RLE deletion;
- load with and without derived indexes; exact/regex/error/pileup queries; recovery and iteration;
- alignment and transcript operations on fixed inputs.

Record wall time, CPU time, peak RSS, bytes read/written, peak disk footprint, output hashes, process/thread count, cache state, storage type, CPU, RAM, OS/kernel, Python, NumPy, Cython, compiler/flags, and dataset hash. Use repeated trials and report distributions. Establish per-operation baselines before proposing regression limits; never accept a faster result with different output as a performance win.
