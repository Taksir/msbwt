# Modern3 Compatibility Matrix

Classifies every persisted/public contract for the Python 2 → Python 3 port. Each entry states the required compatibility level per the AGENTS.md gates.

**Legend:**
- **byte-identical required** — output bytes must match the legacy oracle exactly
- **semantic equality required** — logical content must match but byte-level differences (e.g., `.npy` header formatting) are acceptable if documented
- **migration required** — format or API must change; old readers cannot consume new output without a migration path
- **needs decision** — compatibility promise not yet established by the repository/handoff

---

## 1. Primary Persisted Files

| File | Producer | Consumer | Compatibility level | Notes |
|------|----------|----------|-------------------|-------|
| `msbwt.npy` | builders, merge, decompress | `ByteBWT`, `RLE_BWT` (coexistence), `LZW_BWT` (coexistence) | semantic equality required | `.npy` header may differ between NumPy versions; payload must be identical `\|u1` BWT bytes |
| `comp_msbwt.npy` | RLE builder, compress, convert | `RLE_BWT` | semantic equality required | Same header caveat |
| `comp_msbwt.dat` | no writer in tree (legacy only) | `LZW_BWT` | byte-identical required | Read-only format; no writer to change |
| `comp_offsets.npy` | no writer in tree (legacy only) | `LZW_BWT` | byte-identical required | Read-only |
| `about.npy` | preprocessors | provenance consumers | semantic equality required | Structured dtype descriptor must match |
| `inter0.npy` | `GenericMerge` | merge provenance | semantic equality required | Bit-packed `|u1` |
| `lcps.npy` | external caller saves `LCPGen` result | `RLE_BWT` deletion, LCP-assisted queries | semantic equality required | `<u1` |

---

## 2. Derived Query Indexes

| File | Producer | Consumer | Compatibility level | Notes |
|------|----------|----------|-------------------|-------|
| `totalCounts.npy` | compiled readers (side effect) | compiled readers | semantic equality required | `<u8`, shape `(6,)` |
| `totalCounts.p` | pure-Python reader (side effect) | pure-Python reader | needs decision | **Python-2-pickled file.** Python 3 cannot load protocol-0 pickles containing numpy arrays with long shape elements. Must decide: (a) stop producing `.p` files, (b) produce Python-3-compatible pickles, or (c) drop pure-Python reader support. |
| `fmIndex.npy` | compiled readers (side effect) | `ByteBWT` | semantic equality required | `<u8` |
| `comp_fmIndex.npy` | compiled readers (side effect) | `RLE_BWT` | semantic equality required | `<u8` |
| `comp_refIndex.npy` | compiled readers (side effect) | `RLE_BWT` | semantic equality required | `<u8` |
| `lzw_fmIndex.npy` | compiled readers (side effect) | `LZW_BWT` | semantic equality required | `<u8` |

---

## 3. Recovery and Temporary Artifacts

| Pattern | Producer | Consumer | Compatibility level | Notes |
|---------|----------|----------|-------------------|-------|
| `state.<symbol>.<column>.npy` / `.dat` | uniform builders | builder recovery | needs decision | Filename conventions are a contract |
| `fmStarts.<column>.npy` | builders | builder recovery | needs decision | Same |
| `fmDeltas.<column>.npy` | builders | builder recovery | needs decision | Same |
| `inserts.*.<column>.npy` | builders | builder recovery | needs decision | Same |
| `backup.<group_size>.npy` | multimerge | multimerge recovery | needs decision | Same |
| `msbwt.temp.<offset>.npy` | multimerge | multimerge | needs decision | Same |
| `comp_msbwt.npy.temp.<bin>.npy` | compression | compression recovery | needs decision | Same |
| `deletion_indices.dat` | RLE deletion | RLE deletion | needs decision | Raw indexes |

**Policy:** Recovery artifact names, formats, and detection logic are contracts until tests prove otherwise. Modern3 must produce and consume the same patterns.

---

## 4. CLI Interface

| Contract | Compatibility level | Notes |
|----------|-------------------|-------|
| Command names (`cffq`, `pp`, `cfpp`, `merge`, `query`, `massquery`, `compress`, `decompress`, `convert`) | byte-identical required | Command names are external API |
| `--version` output (`msbwt-script 0.3.0`) | semantic equality required | Version string may update |
| Exit codes | byte-identical required | 0=success, 1=error, 2=argparse |
| stdout/stderr format (log lines, query output, CSV) | semantic equality required | Timestamps in log lines prevent byte-identical stdout |
| `massquery` CSV format (`k-mer,counts\n...`) | byte-identical required | Parsed by downstream tools |
| `query` output format | semantic equality required | `count\n` or `count,seq,dollarID\n` |

---

## 5. Public Python API

| Module path | Compatibility level | Notes |
|-------------|-------------------|-------|
| `MUS.MultiStringBWT.loadBWT()` | semantic equality required | Returns compiled object; type changes acceptable if interface matches |
| `MUS.MultiStringBWT.BasicBWT.*` | semantic equality required | All query/recovery methods |
| `MUS.MultiStringBWT.MultiStringBWT.*` | semantic equality required | FM-index construction |
| `MUS.MultiStringBWT.CompressedMSBWT.*` | semantic equality required | RLE reader |
| `MUSCython.MultiStringBWTCython.loadBWT()` | semantic equality required | Same |
| `MUSCython.MultiStringBWTCython.createMSBWT*()` | semantic equality required | Builder APIs |
| `MUSCython.MultiStringBWTCython.preprocess*()` | semantic equality required | Preprocessing APIs |
| All `MUSCython.*` module paths | semantic equality required | Must remain importable |

### Return-type contracts (needs decision)

| Method | Python 2 return | Python 3 decision needed |
|--------|----------------|-------------------------|
| `getCharAtIndex()` | `str` (1-byte) | `bytes` or `str`? |
| `recoverString()` | `str` | `bytes` or `str`? |
| `countOccurrencesOfSeq()` input | `str` | Accept both `str` and `bytes`? |
| `findIndicesOfStr()` input | `str` | Accept both? |
| FASTQ/FASTA iterators | `str` lines | `str` (text mode) — OK |
| Profile CSV output | `str` lines | `str` (text mode) — OK |

---

## 6. Cython ABI (`BasicBWT.pxd`)

| Contract | Compatibility level | Notes |
|----------|-------------------|-------|
| `BasicBWT.pxd` cdef layout | byte-identical required | Installed as package data; downstream Cython modules cimport it |
| `bwtRange` struct | byte-identical required | Part of the ABI |
| All cdef method signatures | byte-identical required | Changing these breaks binary compatibility |

**Policy:** Do NOT change `BasicBWT.pxd` layout during the initial port. Version or deprecate if changes are eventually needed.

---

## 7. NumPy `.npy` Header Format

| Aspect | Compatibility level | Notes |
|--------|-------------------|-------|
| `.npy` magic bytes (`\x93NUMPY`) | byte-identical required | Format version 1.0 |
| dtype descriptor spelling | semantic equality required | Comma-string without field names; descriptor is part of the byte contract |
| Shape tuple literal | semantic equality required | `(54,)` vs `(54L,)` — Python 3 eliminates `L`; modern2 normalized to `(54,)` |
| Header padding | needs decision | NumPy version may change padding; may affect byte-identical requirements |
| Payload bytes | byte-identical required | The actual array data |

---

## 8. Cross-Version Interoperability

| Direction | Compatibility level | Notes |
|-----------|-------------------|-------|
| modern3 writer → modern2 reader | needs decision | Primary BWT files (`.npy`) should be interchangeable if headers match |
| modern2 writer → modern3 reader | needs decision | Same |
| modern3 writer → legacy oracle reader | semantic equality required | Must validate against frozen goldens |
| modern3 reader → legacy golden data | semantic equality required | Must load and query Python-2-produced datasets |

---

## 9. Enhanced Console Scripts

| Script | Compatibility level | Notes |
|--------|-------------------|-------|
| `msbwt-bwt-tags` | semantic equality required | |
| `msbwt-lcp` | semantic equality required | |
| `msbwt-quality-sidecar` | semantic equality required | |
| `msbwt-remove-sources` | semantic equality required | |
| `msbwt-retrofit-read-provenance` | semantic equality required | |
| `msbwt-benchmark-index` | semantic equality required | |

---

## 10. Determinism Contracts

| Aspect | Compatibility level | Notes |
|--------|-------------------|-------|
| BWT payload bytes (same input, same `-p N`) | byte-identical required | Per golden determinism evidence |
| BWT payload bytes across process counts | byte-identical required | `-p 1` = `-p 2` = `-p 4` |
| `.npy` header bytes | needs decision | NumPy version may cause header drift |
| File sets in dataset directories | semantic equality required | Stale temp files may differ |
| `about.npy` ordering | semantic equality required | Depends on input ordering and sort stability |
