# Modern3 Compatibility Matrix

Classifies every persisted/public contract for the Python 2 → Python 3 port. Each entry states the required compatibility level per the AGENTS.md gates. Repaired M3-0R: comprehensive enhanced-modern2 coverage, corrected cross-version policy, corrected totalCounts.p claim.

**Legend:**
- **byte-identical required** — output bytes must match the legacy oracle exactly
- **semantic equality required** — logical content must match but byte-level differences (e.g., `.npy` header formatting) are acceptable if documented
- **migration required** — format or API must change; old readers cannot consume new output without a migration path
- **needs decision** — compatibility promise not yet established by the repository/handoff

---

## 1. Primary Persisted Files

| File | Producer | Consumer | Compatibility level | Notes |
|---|---|---|---|---|
| `msbwt.npy` | builders, merge, decompress | `ByteBWT`, `RLE_BWT`, `LZW_BWT`, all enhanced modules | semantic equality required | `.npy` header may differ; payload must be identical `\|u1` |
| `comp_msbwt.npy` | RLE builder, compress, convert | `RLE_BWT` | semantic equality required | Same header caveat |
| `comp_msbwt.dat` | none in tree (legacy only) | `LZW_BWT` | byte-identical required | Read-only |
| `comp_offsets.npy` | none in tree (legacy only) | `LZW_BWT` | byte-identical required | Read-only |
| `about.npy` | preprocessors | `ReadProvenance`, provenance consumers | semantic equality required | Structured dtype descriptor must match |
| `inter0.npy` | `GenericMerge`, `MultiSourceProvenance` | `SourceIndex`, `MultiSourceQuery`, `BWTTags`, `QualitySidecar` | semantic equality required | Bit-packed `\|u1`; root interleave |
| `lcps.npy` | `LCP` (F11A) | `LCP`, `MultiSourceQuery`, `SourceRemoval` | semantic equality required | uint32/uint64 adjacency array |

---

## 2. Derived Query Indexes

| File | Producer | Consumer | Compatibility level | Notes |
|---|---|---|---|---|
| `totalCounts.npy` | compiled readers (side effect) | compiled readers | semantic equality required | `<u8`, shape `(6,)` |
| `totalCounts.p` | pure-Python reader (side effect) | pure-Python reader | **needs compatibility test** | Produced via `pickle.dump` of a numpy `float64` array using protocol 0. The pickle payload is Python-version and platform-specific (e.g., Windows CPython 2.7 produces `(6L,)` shape literal vs Linux `(6,)`). Python 3 can load protocol-0 pickles of numpy float64 arrays. A cross-version compatibility test is required before asserting incompatibility. Modern2 tests already compare semantic content on Windows rather than byte-identical pickle bytes. |
| `fmIndex.npy` | compiled readers (side effect) | `ByteBWT` | semantic equality required | `<u8` |
| `comp_fmIndex.npy` | compiled readers (side effect) | `RLE_BWT` | semantic equality required | `<u8` |
| `comp_refIndex.npy` | compiled readers (side effect) | `RLE_BWT` | semantic equality required | `<u8` |
| `lzw_fmIndex.npy` | compiled readers (side effect) | `LZW_BWT` | semantic equality required | `<u8` |

---

## 3. Enhanced-Modern2 Persisted Files (F1–F13A/Q1)

### 3.1 Provenance layer (F2)

| File | Classification | Compatibility level | Notes |
|---|---|---|---|
| `provenance.json` | AUTHORITATIVE | semantic equality required | Format/version schema; `msbwt_sha256` identity binding |
| `provenance/interleaves/<uuid>.npy` | AUTHORITATIVE | semantic equality required | Per-merge interleave copies; digest-validated |

### 3.2 Rank caches (F1, F3) — derived/rebuildable

| File | Classification | Compatibility level | Notes |
|---|---|---|---|
| `inter0_rank.npz` | DERIVED | semantic equality required | Silently rebuilt when stale; content-digest bound |
| `provenance/ranks/<node-id>.npz` | DERIVED | semantic equality required | Silently rebuilt; identity-bound to interleave |

### 3.3 Source metadata (F7) — mutable/rebuildable

| File | Classification | Compatibility level | Notes |
|---|---|---|---|
| `source_metadata.json` | MUTABLE | migration required | User-editable; never requires BWT rebuild; pruned on F10 removal |

### 3.4 Read provenance (F9)

| File | Classification | Compatibility level | Notes |
|---|---|---|---|
| `read_provenance.npy` | AUTHORITATIVE | semantic equality required | 20 bytes/read packed dtype; `align=False`; ordered by dollar ID |
| `read_provenance.json` | AUTHORITATIVE | semantic equality required | Metadata with `bwt_sha256` identity binding |

### 3.5 BWT tags (F12)

| File | Classification | Compatibility level | Notes |
|---|---|---|---|
| `bwt_tags.json` | AUTHORITATIVE | semantic equality required | Registry; SHA-256 hash filenames; `allow_pickle=False` |
| `bwt_tags/tag_<hash>.npy` | AUTHORITATIVE | semantic equality required | Row-aligned; `T.shape[0] == msbwt.npy.shape[0]` |

### 3.6 Quality sidecar (Q1)

| File | Classification | Compatibility level | Notes |
|---|---|---|---|
| `quality_sidecar.json` | AUTHORITATIVE | semantic equality required | Semantic metadata; `bwt_sha256` bound |
| `bwt_tags/tag_<hash>.npy` (tag `fastq_quality_ascii`) | AUTHORITATIVE | semantic equality required | uint8, 1 byte/BWT row; terminal `$` = sentinel 255 |

### 3.7 LCP (F11A)

| File | Classification | Compatibility level | Notes |
|---|---|---|---|
| `lcps.npy` | AUTHORITATIVE | semantic equality required | length N-1, uint32; `lcps[i] = LCP(SA[i], SA[i+1])` |
| `lcp.json` | AUTHORITATIVE | semantic equality required | Metadata with `bwt_sha256` identity binding |

### 3.8 Benchmark reports (F13A)

| File | Classification | Compatibility level | Notes |
|---|---|---|---|
| Benchmark JSON reports | informational | needs decision | No persistence contract; machine-readable |

---

## 4. Recovery and Temporary Artifacts

| Pattern | Producer | Consumer | Compatibility level | Notes |
|---|---|---|---|---|
| `state.<symbol>.<column>.npy` / `.dat` | uniform builders | builder recovery | needs decision | Filename conventions are a contract |
| `fmStarts.<column>.npy` | builders | builder recovery | needs decision | Same |
| `fmDeltas.<column>.npy` | builders | builder recovery | needs decision | Same |
| `inserts.*.<column>.npy` | builders | builder recovery | needs decision | Same |
| `backup.<group_size>.npy` | multimerge | multimerge recovery | needs decision | Same |
| `msbwt.temp.<offset>.npy` | multimerge | multimerge | needs decision | Same |
| `comp_msbwt.npy.temp.<bin>.npy` | compression | compression recovery | needs decision | Same |
| `deletion_indices.dat` | RLE deletion | RLE deletion | needs decision | Raw indexes |

---

## 5. CLI Interface

### 5.1 Legacy CLI (9 commands)

| Contract | Compatibility level | Notes |
|---|---|---|
| Command names (`cffq`, `pp`, `cfpp`, `merge`, `query`, `massquery`, `compress`, `decompress`, `convert`) | byte-identical required | External API |
| `--version` output | semantic equality required | Version string |
| Exit codes | byte-identical required | 0=success, 1=error, 2=argparse |
| stdout/stderr format (log lines, query output, CSV) | semantic equality required | Timestamps prevent byte-identical stdout |
| `massquery` CSV format (`k-mer,counts\n...`) | byte-identical required | Parsed by downstream tools |
| `query` output format | semantic equality required | `count\n` or `count,seq,dollarID\n` |

### 5.2 Enhanced console scripts (6 tools)

| Script | Compatibility level | Notes |
|---|---|---|
| `msbwt-bwt-tags` | semantic equality required | |
| `msbwt-lcp` | semantic equality required | |
| `msbwt-quality-sidecar` | semantic equality required | |
| `msbwt-remove-sources` | semantic equality required | |
| `msbwt-retrofit-read-provenance` | semantic equality required | |
| `msbwt-benchmark-index` | semantic equality required | |

---

## 6. Public Python API

### 6.1 Legacy API

| Module path | Compatibility level | Notes |
|---|---|---|
| `MUS.MultiStringBWT.loadBWT()` | semantic equality required | Returns compiled object |
| `MUS.MultiStringBWT.BasicBWT.*` | semantic equality required | All query/recovery methods |
| `MUS.MultiStringBWT.MultiStringBWT.*` | semantic equality required | FM-index construction |
| `MUS.MultiStringBWT.CompressedMSBWT.*` | semantic equality required | RLE reader |
| `MUSCython.MultiStringBWTCython.loadBWT()` | semantic equality required | Same |
| All `MUSCython.*` module paths | semantic equality required | Must remain importable |

### 6.2 Enhanced API

| Module path | Compatibility level | Notes |
|---|---|---|
| `MUS.SourceIndex.TwoSourceBWT.*` | semantic equality required | F1 rank queries |
| `MUS.MultiSourceProvenance.*` | semantic equality required | F2 provenance tree |
| `MUS.MultiSourceQuery.MultiSourceBWT.*` | semantic equality required | F3–F9, F11A, F12, Q1 queries |
| `MUS.SourceMetadata.SourceMetadataCatalog.*` | semantic equality required | F7 metadata |
| `MUS.ReadProvenance.ReadProvenanceIndex.*` | semantic equality required | F9 read identity |
| `MUS.SourceRemoval.retain_sources/remove_sources` | semantic equality required | F10 source removal |
| `MUS.BWTTags.BWTTagStore.*` | semantic equality required | F12 tag access |
| `MUS.QualitySidecar.QualitySidecar.*` | semantic equality required | Q1 quality recovery |
| `MUS.LCP.LCPIndex.*` | semantic equality required | F11A LCP access |
| `MUS.Benchmarking.*` | semantic equality required | F13A benchmarking |
| `MUS.BackendContract.*` | semantic equality required | F13A contract |

### 6.3 Return-type contracts (needs decision)

| Method | Python 2 return | Python 3 decision needed |
|---|---|---|
| `getCharAtIndex()` | `str` (1-byte) | `bytes` or `str`? |
| `recoverString()` | `str` | `bytes` or `str`? |
| `countOccurrencesOfSeq()` input | `str` | Accept both `str` and `bytes`? |
| `findIndicesOfStr()` input | `str` | Accept both? |
| `QualitySidecar.quality_for_row()` | `str` or `None` | `bytes` or `str`? |

---

## 7. Cython ABI (`BasicBWT.pxd`)

| Contract | Compatibility level | Notes |
|---|---|---|
| `BasicBWT.pxd` cdef layout | **source-compatible required** | Python 2→3 does NOT guarantee binary ABI compatibility |
| `bwtRange` struct | source-compatible required | Must compile against new Cython |
| All cdef method signatures | source-compatible required | Changing these breaks downstream compiled modules |

**Policy:** The `.pxd` must compile and produce working extensions under Cython 3.2 + Python 3. Binary ABI compatibility with Python-2-era compiled extensions is NOT required (they cannot be loaded into Python 3 anyway).

---

## 8. NumPy `.npy` Header Format

| Aspect | Compatibility level | Notes |
|---|---|---|
| `.npy` magic bytes | byte-identical required | Format version 1.0 |
| dtype descriptor spelling | semantic equality required | Part of the byte contract |
| Shape tuple literal | semantic equality required | Python 3 eliminates `L` suffix |
| Header padding | needs decision | NumPy version may change padding |
| Payload bytes | byte-identical required | The actual array data |

---

## 9. Cross-Version Interoperability

| Direction | Compatibility level | Notes |
|---|---|---|
| **modern2 writer → modern3 reader** | **mandatory** | modern3 must read all files produced by modern2 |
| modern3 writer → modern2 reader | needs decision | Primary BWT files (`.npy`) should be interchangeable if headers match |
| modern3 writer → legacy oracle reader | semantic equality required | Must validate against frozen goldens |
| modern3 reader → legacy golden data | semantic equality required | Must load and query Python-2-produced datasets |

---

## 10. Determinism Contracts

| Aspect | Compatibility level | Notes |
|---|---|---|
| BWT payload bytes (same input, same `-p N`) | byte-identical required | Per golden determinism evidence |
| BWT payload bytes across process counts | byte-identical required | `-p 1` = `-p 2` = `-p 4` |
| `.npy` header bytes | needs decision | NumPy version may cause header drift |
| File sets in dataset directories | semantic equality required | Stale temp files may differ |
| `about.npy` ordering | semantic equality required | Depends on input ordering and sort stability |

---

## 11. Packaging Metadata

| Contract | Compatibility level | Notes |
|---|---|---|
| Distribution name `msbwt-modern3` | migration required | New distribution; separate from `msbwt-modern2` |
| `MUS`/`MUSCython` import paths | semantic equality required | Must remain importable |
| `bin/msbwt` CLI entry point | semantic equality required | Same command name |
| 6 enhanced console script entry points | semantic equality required | Same command names |
| `install_requires` | migration required | pysam conditional on platform |
