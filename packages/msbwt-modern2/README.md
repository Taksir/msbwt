# msbwt-modern2

Independently installable Python-2.7 modernization of the MSBWT package
(distribution name `msbwt-modern2`).  It preserves the legacy public surface:

```python
import MUS
import MUSCython
```

and the `msbwt` CLI entrypoint.

Target runtime: CPython 2.7.18 (cp27mu/UCS4) in an isolated Linux
environment.  Build toolchain: Cython exactly 3.0.12 (the last Cython 3.0.x;
Cython 3.1+ is prohibited), NumPy 1.16.6, pysam 0.15.4, GCC 7.3.0
x86_64-conda_cos6-linux-gnu.  See `environment/modern2-profile.json` and
`environment/locks/` for exact artifacts and hashes.

## Bootstrap milestone 1 scope

The uniform-multifile construction/read/query slice is fully migrated and
validated byte-for-byte against the committed legacy golden:

- `pp -u OUT uniform-a.fastq uniform-b.fastq`
- `cfpp -p 1 -u OUT`
- reader (`ByteBWT`) + queries + derived-index side effects

Migrated compiled modules: `AlignmentUtil`, `BasicBWT`, `ByteBWTCython`,
`CompressToRLE` (milestone 10), `GenericMerge` (milestone 9),
`MSBWTCompGenCython`, `MSBWTGenCython`, `MultiStringBWTCython`,
`MultimergeCython` (milestone 8), `RLE_BWTCython`, `LZW_BWTCython`.

Not migrated (intentional stub classified DEAD/PRIVATE — no public CLI/API
path reaches it): `LCPGen`.

Full milestone report: `docs/modernization/MODERN2_BOOTSTRAP_MILESTONE1.md`.

## Environment bootstrap

```bash
bash environment/bootstrap-modern2.sh \
  --micromamba /absolute/path/to/micromamba-2.8.1 \
  --prefix /new/absolute/prefix
```

## Build

```bash
bash environment/build-modern2.sh \
  --prefix /absolute/prefix --source /absolute/packages/msbwt-modern2
```

## Validate

```bash
bash validate/bootstrap-milestone1.sh \
  --prefix /absolute/prefix \
  --package /absolute/packages/msbwt-modern2 \
  --repository /absolute/msbwt \
  --build --install --evidence /absolute/evidence.json
```

## Tests (inside the modern2 environment)

```bash
MSBWT_MODERN2_REPO=/absolute/msbwt python -B -m unittest discover -s tests
```

## Generated C policy

Per `docs/modernization/ARCHITECTURE.md`, generated C from the pinned Cython
3.0.12 toolchain is committed alongside the `.pyx` sources so the sdist
remains buildable without running Cython.  Never hand-edit generated C;
regenerate only with the pinned modern2 environment.
