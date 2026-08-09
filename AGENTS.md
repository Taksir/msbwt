# MSBWT modernization rules

These rules apply to every change in this repository.

## Sources of truth

- Treat executable behavior and persisted bytes from the frozen original implementation as the compatibility authority. Treat README text, comments, and package metadata as claims to verify.
- Preserve the original authors, MIT license, scientific references, and repository history. This is a maintenance fork.
- Start with [the forensic audit](docs/modernization/FORENSIC_AUDIT.md), [behavioral surface](docs/modernization/BEHAVIORAL_SURFACE.md), [architecture proposal](docs/modernization/ARCHITECTURE.md), [test plan](docs/modernization/COMPATIBILITY_TESTING.md), [legacy oracle status](docs/modernization/LEGACY_ORACLE_STATUS.md), and [risk register](docs/modernization/RISKS_AND_OPEN_QUESTIONS.md).

## Compatibility gates

- Do not port or refactor an operation until its practical CLI/API behavior and persistent artifacts have a legacy characterization test.
- Preserve existing CLI command names/options, public calls, and `MUS`/`MUSCython` import paths unless an approved compatibility entry documents why that is impossible.
- Treat every dataset filename, dtype, shape, byte order, NumPy header, encoding, and recovery artifact as a contract until tests prove otherwise.
- Require old-reader/new-writer and new-reader/old-writer tests for every writer change. Compare primary persistent files byte-for-byte when behavior is not intentionally changed.
- Never delete, weaken, skip, or xfail a legitimate regression solely to make a port pass. Diagnose the behavioral difference first.

## Bugs and security

- Correct genuine correctness or security defects; do not preserve them merely for byte equality.
- Record every intentional deviation in `COMPATIBILITY.md` with affected commands/APIs/files, old and new behavior, rationale, and reader/writer interoperability.
- Treat datasets and biological input as untrusted. Avoid pickle loading, unchecked array indexing, unsafe path cleanup, and non-atomic in-place mutation in new code.
- Preserve the original result as a named legacy oracle when a bug fix intentionally changes behavior.

## Two distributions

- `msbwt-modern2` targets Python 2.7 and a pinned Cython 3.0.x toolchain using `language_level=2` where required.
- `msbwt-modern3` targets the latest stable CPython first, then recent Python 3 versions where inexpensive.
- Keep distribution metadata/build systems independent. Share format specifications, fixtures, golden manifests, and differential-test logic. Do not force shared runtime source when Python/Cython semantics diverge.
- The distributions may expose the same legacy import packages and `msbwt` command, so test/install them in separate environments unless a future design explicitly solves co-installation.

## Cython and generated C

- Preserve algorithms during the first port. Separate semantic/Cython migration from algorithm redesign and performance optimization.
- Use explicit Cython language-level and compiler directives. Validate all `char *`, `bytes`, division, integer-width, bounds, and `nogil` assumptions.
- Do not hand-edit generated C. Follow the distribution-specific generated-C policy in the architecture document and verify regeneration in pinned environments.

## Tests, data, and performance

- Use deterministic tiny fixtures first, then checksum-pinned small public bacterial and viral data. Never commit or require private datasets.
- Record raw-file hashes and logical array metadata. Do not update goldens without an approved compatibility explanation.
- Establish correctness and reproducible baselines before optimization. Report wall time, CPU time, peak memory, disk I/O, process count, cache state, platform, compiler, and dataset hash.
- Do not claim a platform supported until its build and behavioral suite pass there. Python 2 requires a reproducible legacy Linux container as the reference.

## Repository hygiene

- Work on modernization branches, never directly on protected baseline/master. Do not rewrite upstream history.
- Keep commits focused and verified. Do not mix generated files, dependency changes, behavior changes, and test-golden updates without a documented reason.
- Do not remove legacy or apparently unreachable code until analysis/tests establish replacement or irrelevance and preserve historical information.
- Before committing, run the applicable tests plus `git diff --check` and verify the diff contains no private data or unrelated changes.
