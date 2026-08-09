# Legacy oracle reconstruction status

Status date: 2026-08-08

## Evidence established

- The oracle source projection is the 40 implementation/package files from
  audited commit `7503346ec072ddb89520db86fef85569a9ba093a`.  The SHA-256
  projection manifest passes, and every worktree file has the same Git blob as
  that commit.  Harness and documentation files are external to the projection.
- The reference container is pinned to the Docker Hub linux/amd64 manifest
  `python@sha256:c934af72b8bd03b9804d5bde2569c320926e70392d708d113a2e71bcf98c8a20`.
  This reference is resolved but has not been built or run on the current host.
- Three dependency probes are explicitly candidate-only: the README-era
  NumPy/pysam plus Cython 0.23.4 combination, a separate Cython 0.18 probe, and
  a late-Python-2 combination.  No candidate is a verified lock yet.
- Deterministic uniform and nonuniform FASTQ inputs, including deterministic
  gzip variants, have fixed byte counts and SHA-256 hashes.  Host-side capture
  tooling records exact artifacts, safe `.npy` header/payload metadata, raw
  command bytes, and failure runs without importing NumPy or loading pickles.

## Current hard stop

This Windows host has no Python 2 interpreter, installed WSL distribution,
Docker, Podman, or other Linux container runtime.  `wsl.exe --status` reports
that WSL is not installed (exit 50).  Therefore the pinned Linux image and all
Python-2 dependency/build candidates remain unexecuted here.

No synthetic MSBWT output is designated as a golden yet.  Input fixture hashes,
static source verification, or output produced by a translated/stubbed Python 3
execution would not be a substitute for the frozen Python-2 oracle.

## Resume procedure

1. Provide a Docker-compatible linux/amd64 runtime, or run the documented
   commands on a separate Docker-capable host with this exact commit checked
   out.  Do not install or alter a host runtime without explicit authorization.
2. Build the pinned reference Dockerfile and retain its image ID.  Run the
   generated-C route and preserve its expected-or-unexpected failure without
   changing frozen `setup.py`.
3. Probe the historical Cython candidates first, then the late-Python-2
   candidate.  Promote a dependency set only after build, extension import,
   CLI version, fixture preprocessing, and fixture build all succeed.
4. Inventory every produced snapshot with `compat/tools/artifact_manifest.py`,
   rerun the same case twice, and require identical artifact content hashes.
5. Commit successful environment records and first goldens separately from any
   later modern2 or modern3 implementation work.

The next phase gate remains closed until steps 1-4 produce an evidence-backed
oracle result.  Frozen source failures are results, not permission to repair the
oracle.
