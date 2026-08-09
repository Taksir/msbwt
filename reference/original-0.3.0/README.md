# Frozen original 0.3.0 oracle harness

This directory contains execution harness files only.  It is **not** a copy of
the MSBWT implementation and must never be used to repair it.  The canonical
oracle source is commit `7503346ec072ddb89520db86fef85569a9ba093a`.

Status: **the linux/amd64 base digest is resolved but not locally executed; no
candidate dependency combination has been verified yet.**  Every version in
`environment/probe-matrix.json` is an explicit candidate, not a claim that it
builds or reproduces legacy output.

The reference Dockerfile explicitly selects `linux/amd64`, matching its pinned
manifest.  An ARM host therefore needs an amd64-capable Docker builder/emulator
for this oracle; do not relabel an untested native image as the reference.

## Run an oracle probe

1. Verify that the source projection has not changed:

   ```powershell
   python reference/original-0.3.0/environment/verify_frozen_source.py --source .
   ```

2. The Dockerfile defaults to the resolved Docker-Hub linux/amd64 digest
   `python@sha256:c934af72b8bd03b9804d5bde2569c320926e70392d708d113a2e71bcf98c8a20`.
   It is not an evidence-backed successful build yet.  To test another
   architecture, pass an immutable replacement and retain it in the result:

   ```powershell
   docker build --build-arg PYTHON27_BASE='python@sha256:<resolved-digest>' --tag msbwt-original-0.3.0-oracle .
   ```

3. Run one disposable candidate container.  Mount the repository read-only;
   the probe copies only files listed in the frozen manifest to its scratch
   directory.  Results are written to the mounted `environment/results`
   directory, including exact stdout and stderr bytes for every command.

   ```powershell
   docker run --rm --mount "type=bind,src=$((Get-Location).Path),dst=/oracle-src,readonly" --mount "type=bind,src=$((Get-Location).Path)/reference/original-0.3.0/environment/results,dst=/results" msbwt-original-0.3.0-oracle --source /oracle-src --results /results --candidate historical-source-claims --route all --install-dependencies --run-first-goldens --fixture-root /oracle-src/compat/fixtures/synthetic
   ```

The process intentionally exits nonzero when an install or build fails, after
writing its report.  Add `--allow-failures` only when a caller needs to gather
all expected failures without failing the surrounding job.  A failed generated
C route is evidence: in frozen `setup.py`, `CompressToRLE` still points to a
`.pyx` file when Cython is absent.  Do not change that source to make the route
pass.

`--run-first-goldens` is opt-in and runs exactly one scenario: the two uniform
FASTQ files through `pp -u`, then `cfpp -p 1 -u`.  Before creating a run
directory, it validates the two input names, byte counts, and SHA-256 values
against `fixture-manifest.json`.  It requires `--install-dependencies`; any
failed base-package or route-specific Cython installation is recorded by
package name and blocks a passed case.  The case runs only if `setup.py build`,
`build_ext --inplace`, the compiled-extension import smoke, and CLI version
smoke all return zero.  Its two copied dataset trees contain only files the
oracle wrote; `case-result.json` lives beside them and records the route,
candidate, fixture hashes, command labels, and outcome.

These snapshots are **not goldens yet**.  After the container exits, run the
host-side `compat/tools/artifact_manifest.py inventory` command once for each
snapshot and write each manifest outside its snapshot directory.  Review those
host manifests before promoting any output to `compat/goldens`.

## Routes and results

- `generated-c-no-cython` removes Cython from the disposable container and
  invokes `python setup.py build` on an exact scratch copy.
- `pyx-historical-cython` installs the selected candidate Cython and performs
  the same build.  It does not regenerate or commit source files.
- `environment/results/<run-id>/` contains `environment.json`, `report.json`,
  a copy of the requested candidate matrix entry, and per-command `.stdout` /
  `.stderr` files.  Retain failed runs; do not overwrite or curate them.
- Opt-in first-case snapshots are under
  `environment/results/<run-id>/first-goldens/uniform-multifile-<route>/`.
  Their directory names include a content SHA-256 and are never overwritten.
  That name hashes sorted regular files as `file`, NUL, UTF-8 relative path,
  NUL, ASCII decimal byte length, NUL, then payload bytes.  The host artifact
  manifest remains the authoritative reviewed byte inventory.

`probe-matrix.json` separates the README-era source claims from a later
Python-2 candidate.  The script accepts only exact candidate values and records
what was actually importable.  Until a result directory records success, all
of these remain unverified.
