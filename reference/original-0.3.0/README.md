# Frozen original 0.3.0 oracle harness

This directory contains execution harness files plus collision-safe frozen
source overrides.  It is **not** a second editable MSBWT implementation and
must never be used to repair the oracle.  The canonical source is commit
`7503346ec072ddb89520db86fef85569a9ba093a`.  Its original CRLF `README.md`
bytes live under `frozen-source/` because the public root README documents the
modernization project; the manifest restores those bytes to root only in each
disposable oracle copy.

Status: **the direct WSL runner has verified the late-Python-2 candidate and
produced the first committed synthetic goldens.**  See
`../../../docs/modernization/LEGACY_ORACLE_STATUS.md` and
`../../../compat/goldens/original-0.3.0/`.  The other matrix entries remain
candidate-only; success of this profile is not a claim about the authors'
original dependency environment.  The resolved Docker base remains an
unexecuted secondary reference because this host uses WSL directly.

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
package name and blocks a passed case.  The case runs only if the exact
candidate-version gate, `setup.py build`, `build_ext --inplace`, the
compiled-extension import smoke, and CLI version smoke all return zero.  Its
two copied dataset trees contain only files the oracle wrote;
`case-result.json` lives beside them and records the route, candidate, fixture
hashes, command labels, and outcome.

These snapshots are **not goldens yet**.  After the container exits, run the
host-side `compat/tools/artifact_manifest.py inventory` command once for each
snapshot and write each manifest outside its snapshot directory.  Review those
host manifests before promoting any output to `compat/goldens`.

## Run directly in WSL

Use this route when a Linux Python-2 environment has already been provisioned
inside WSL.  The runner does not call `sudo`, install a system package, source
a shell initialization file, or call a Windows executable.  It requires all
six explicit arguments and sets a Linux-only PATH, UTC, deterministic hash
seed, and single-thread numerical environment before invoking the probe.

From the repository directory as seen inside WSL, run (replace the example
paths with the actual isolated Python-2 environment and Linux-native results
directory):

```bash
bash reference/original-0.3.0/environment/wsl/run-wsl-probe.sh \
  --python /home/USER/.local/legacy-python2/bin/python \
  --source /mnt/d/path/to/msbwt \
  --results /home/USER/msbwt-oracle-results \
  --candidate late-python2-candidate \
  --route pyx-historical-cython \
  --fixture-root /mnt/d/path/to/msbwt/compat/fixtures/synthetic
```

Keep `--results` on Linux-native storage; the source can be a mounted
read-only checkout.  The runner clears inherited build variables and, when
present, sources only the binutils/GCC/G++ activation scripts shipped inside
the selected conda prefix.  Those scripts provide the compiler sysroot and
exact flags required by archived conda toolchains.  For a non-conda
environment it selects compiler wrappers from that prefix, then an
already-installed Linux `gcc`/`g++`.  It records the selected values in
`environment.json`; it never asks for or stores a password.

Reconstruct the verified profile with
`environment/wsl/reconstruct-py27-late.sh`.  It requires a new absolute target
prefix plus the official micromamba 2.8.1 Linux x86-64 artifact from
`https://github.com/mamba-org/micromamba-releases/releases/download/2.8.1-0/micromamba-linux-64`,
whose SHA-256 must be
`9689782d863c05a1bf5d2d371ba527104e7a4eb4310c1637d8653b751aed9c82`.
The script enforces that bootstrap hash, downloads the 32 exact conda artifacts
in `environment/wsl/locks/`, verifies every SHA-256 before installation, and
then installs the six exact wheel URLs under pip `--require-hashes` with source
fallback disabled.  It uses a temporary isolated mamba root and no apt package,
system Python-2 package, sudo call, shell initialization, or existing target.

The golden path rejects any interpreter other than CPython 2.7 before creating
a result directory.  The exact-version gate imports NumPy, pysam, and Cython (and pip, setuptools,
or wheel when the matrix names them) after dependency installation.  Their
resolved versions must exactly match every non-null matrix value.  A missing
module, failed import, or version mismatch produces a nonzero recorded command
and blocks `case-result.json` from reporting `passed`.  The generated-C route
intentionally removes Cython, so its candidate version gate is expected to
show that conflict rather than silently treating the route as a success.

Candidate-only evidence is a result directory with a failed gate or build.
Actual successful legacy evidence requires a retained result directory whose
`report.json` is `passed`, whose relevant candidate-version gate returned zero,
and whose first-golden case reports `passed`; only then may its output be
reviewed for promotion to `compat/goldens`.

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

`environment.json` records the WSL/Linux OS release, uname/architecture,
glibc and OpenSSL as seen by Python, Python version/prefix/unicode width,
compiler sysconfig flags, and only the selected inherited build variables.
`PATH` is explicitly marked host-specific.  The command record separately
captures `uname`, `/etc/os-release`, `ldd --version`, and `openssl version -a`.
If the selected Python is a conda environment, it also records package
name/version/build/channel/URL/checksums from `conda-meta/*.json`; URLs with
credentials, queries, or fragments are redacted rather than persisted.

`probe-matrix.json` separates the README-era source claims from a later
Python-2 candidate.  The script accepts only exact candidate values and records
what was actually importable.  The late-Python-2 candidate now has two passing
golden runs; the historical dependency candidates remain unverified.
