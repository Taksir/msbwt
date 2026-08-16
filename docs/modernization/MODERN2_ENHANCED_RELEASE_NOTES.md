# ENHANCED-MODERN2 — Release notes: enhanced feature track (release candidate)

Distribution: `msbwt-modern2` version `0.3.0` (same distribution identity
as the modern2 baseline; no version bump was made — see "Version policy")
Branch: `enhanced-modern2`
Status: **release candidate** — built, validated, not yet tagged/published.

This release hardens the enhanced-modern2 track into an independently
installable distribution: the baseline release packaging plus the
enhanced feature modules, their six command-line tools, and fresh-install
validation of everything from the built wheel and sdist.

## Relationship to the baseline release

- The modern2 compatibility baseline (release notes:
  `MODERN2_RELEASE_NOTES.md`) is frozen and remains the compatibility
  authority.  Feature layers never modify baseline construction, merge,
  FM search, readers, or compression/decompression code.
- Legacy defects fixed by modern2 and the intentional historical quirks
  are documented in `MODERN2_LEGACY_BUG_TRACKER.md`; this release points
  to that tracker and adds no new entries to it.
- Enhanced feature milestone documents and evidence:
  `docs/enhanced-modern2/` + `packages/msbwt-modern2/evidence/`.

## Added by this release (packaging/validation)

- `MUS/` enhanced modules ship in both the sdist and the wheel (they were
  already covered by `recursive-include MUS *.py`; verified by the new
  artifact content audits).
- `tools/` enhanced CLI package ships in both artifacts and installs six
  console-script entry points: `msbwt-bwt-tags`, `msbwt-lcp`,
  `msbwt-quality-sidecar`, `msbwt-remove-sources`,
  `msbwt-retrofit-read-provenance`, `msbwt-benchmark-index`.
- New validation drivers (committed, executed):
  - `validate/enhanced_installed_gate.py` — self-contained Python-2.7
    gate that runs the whole enhanced feature chain through the
    INSTALLED distribution (imports must resolve from site-packages),
    with embedded independent oracles (naive suffix rows, direct
    bit-array tree walks, explicit adjacent-LCP, per-read quality
    ground truth, raw filesystem byte sums);
  - `validate/enhanced-release-candidate.sh` — WSL driver that builds
    sdist + wheel from a disposable copy of the package tree in the
    pinned environment, bootstraps two brand-new Python-2.7 prefixes,
    installs one artifact each, and runs the legacy fresh-install gate
    (all 9 CLI commands against the committed goldens) plus the
    enhanced installed gate plus every enhanced console script.
  - Executed evidence: `packages/msbwt-modern2/evidence/enhanced-release-candidate.json`.

## Verified in this release

- sdist and wheel built under the pinned profile
  (`modern2-python27-3.0.12`), names/sizes/SHA-256 recorded, archive
  contents audited (enhanced modules, `tools/`, generated C, no
  tests/evidence/environment/validate leakage).
- Wheel and sdist each installed into a brand-new bootstrapped prefix;
  every import (MUS, MUSCython compiled modules, tools) resolved from
  site-packages with no repository path on `sys.path`.
- Legacy surface: `msbwt -V/-h`, `pp`, `cfpp`, `cffq`, `query`,
  `massquery`, `compress`, `decompress`, `convert`, `merge -p 1/-p 2`,
  nonuniform and gzip construction — all reproduced the committed golden
  hashes from the installed artifacts (release-candidate gate).
- Enhanced chain from the installed package: provenance merge, per-source
  counts, sparse listing, frequency/top-k, groups/predicates, extensions,
  read provenance + recovery, tags, quality bytes, LCP (adjacent +
  RMQ), removal with byte-equal independent retained rebuild, and
  benchmark accounting vs raw filesystem sums.
- Enhanced console scripts: `--help` and one real operation each, from
  both installed artifacts.

## Version policy

The distribution version remains `0.3.0` (frozen `MUS.util.VERSION`, the
historical version; changing it would be a compatibility-policy change).
Options for the future, if a distinct release identity is ever wanted:
(a) keep `0.3.0` and identify the track by branch/commit, (b) bump to
`0.3.1` for the enhanced distribution, or (c) a new distribution name.
No decision was made in this release; the artifacts are
`msbwt-modern2-0.3.0.tar.gz` / `msbwt_modern2-0.3.0-cp27-cp27mu-linux_x86_64.whl`.

## Not included (explicitly out of scope)

- Feature 8B (succinct extension storage), 11B/11C (LCP-preserving
  removal / succinct LCP), a new compressed backend, modern3: none of
  these are implemented or claimed.
- No performance superiority claim: Feature-13A's naive u32 RLE
  run-encoding model on the toy fixture was larger than the raw BWT
  payload; that negative result is documented, not hidden.
