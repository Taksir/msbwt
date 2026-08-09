# Original 0.3.0 compatibility goldens

These files were written by the unmodified 40-file frozen source projection at
commit `7503346ec072ddb89520db86fef85569a9ba093a` under genuine CPython 2.7.
They are compatibility evidence, not regenerated test conveniences.

Each case is keyed by a resolved environment profile and build route.  The
stage `manifest.json` inventories every artifact, its complete SHA-256, and its
raw NumPy header and payload when applicable.  `provenance.json` records the
fixture and command contract; the profile records exact dependency sources,
hashes, compiler, build flags, OS, ABI, and bootstrap source.

Verify a stage from the repository root with:

```text
python compat/tools/artifact_manifest.py verify \
  --artifact-dir compat/goldens/original-0.3.0/uniform-multifile/PROFILE/pyx-historical-cython/build/artifacts \
  --manifest compat/goldens/original-0.3.0/uniform-multifile/PROFILE/pyx-historical-cython/build/manifest.json \
  --output PATH_OUTSIDE_THE_ARTIFACT_DIRECTORY
```

Never replace these bytes because a modernization differs.  Diagnose the
difference first; an intentional correctness or security change needs a
compatibility entry and a separately named expected result.
