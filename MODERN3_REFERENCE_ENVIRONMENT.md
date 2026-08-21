# Modern3 Reference Environment

Recommended stable reference profile for the msbwt-modern3 Python 3 port. Versions verified against primary upstream sources as of 2026-08-20. Repaired M3-0R: corrected build version (1.5.0, not yanked 1.5.1), removed `pip --no-deps` recommendation, added conditional dependency packaging direction.

---

## 1. Recommended Stable Profile

| Component | Version | Release date | Python support | Notes |
|-----------|---------|-------------|----------------|-------|
| **CPython** | 3.14.7 | 2026-08-05 | — | Latest stable bugfix release. 3.13.15 also stable; 3.15 is RC1. |
| **NumPy** | 2.5.2 | 2026-08-09 | ≥3.12 | Latest stable. Supports 3.12–3.14. |
| **Cython** | 3.2.9 | 2026-07-24 | ≥3.8 | Latest stable. Supports CPython 3.8+, free-threading experimental. |
| **pysam** | 0.24.0 | 2026-04-27 | 3.8–3.14 | Wraps htslib 1.23.1. Requires Cython 3. Linux/macOS only. |
| **pip** | 26.2.1 | 2026-08-04 | ≥3.10 | Latest stable. |
| **setuptools** | 84.0.0 | 2026-08-08 | ≥3.10 | Latest stable. |
| **build** | **1.5.0** | 2026-04-30 | ≥3.10 | PEP 517 build frontend. **1.5.1 exists but IS YANKED** ("considers breaking changes, will discuss re-releasing as a new major version"). |
| **wheel** | 0.48.0 | 2026-08-11 | ≥3.9 | Latest stable. |

---

## 2. Compatibility Assessment

### 2.1 CPython + NumPy

NumPy 2.5 supports Python 3.12–3.14. CPython 3.14.7 is within this range. **Compatible.**

### 2.2 CPython + Cython

Cython 3.2 supports CPython 3.8+ and is tested against latest CPython releases. **Compatible with 3.14.**

### 2.3 CPython + pysam

pysam 0.24.0 states testing with Python 3.8–3.14. **Compatible with 3.14.**

### 2.4 NumPy + Cython

NumPy 2.x provides a stable C API. Cython 3.2 is tested against NumPy 2.x. **Compatible.**

### 2.5 NumPy + pysam

pysam 0.24 requires Cython 3 and builds against htslib. NumPy is not a direct pysam dependency. **Compatible.**

### 2.6 Cython + pysam

pysam 0.24 requires Cython 3. Cython 3.2.9 satisfies this. **Compatible.**

### 2.7 pip + setuptools + build + wheel

pip 26.2 works with modern setuptools. build 1.5.0 works with modern setuptools. wheel 0.48 is the wheel package manager. **All compatible.**

---

## 3. Platform Support

### 3.1 Linux x86-64 (Tier 1)

| Component | Linux x86-64 | Notes |
|-----------|:-:|-------|
| CPython 3.14.7 | Available | Official installer + conda-forge |
| NumPy 2.5.2 | Wheel available | `cp314-cp314-manylinux_2_17_x86_64` |
| Cython 3.2.9 | Pure Python | `py3-none-any` |
| pysam 0.24.0 | Wheel available | `cp314-cp314-manylinux_2_28_x86_64` |
| GCC/build tools | Required | For Cython compilation |

### 3.2 Linux ARM64 (Tier 2)

| Component | Linux ARM64 | Notes |
|-----------|:-:|-------|
| CPython 3.14.7 | Available | conda-forge, deadsnakes |
| NumPy 2.5.2 | Wheel available | `cp314-cp314-manylinux_2_17_aarch64` |
| pysam 0.24.0 | Wheel available | `cp314-cp314-manylinux_2_28_aarch64` |

### 3.3 macOS x86-64 (Tier 2)

| Component | macOS x86-64 | Notes |
|-----------|:-:|-------|
| CPython 3.14.7 | Available | python.org installer |
| NumPy 2.5.2 | Wheel available | `cp314-cp314-macosx_10_15_x86_64` |
| pysam 0.24.0 | Wheel available | `cp314-cp314-macosx_10_15_x86_64` |

### 3.4 macOS ARM64 (Apple Silicon) (Tier 1)

| Component | macOS ARM64 | Notes |
|-----------|:-:|-------|
| CPython 3.14.7 | Available | python.org installer, universal2 |
| NumPy 2.5.2 | Wheel available | `cp314-cp314-macosx_10_15_arm64` |
| pysam 0.24.0 | Wheel available | `cp314-cp314-macosx_10_15_arm64` |

### 3.5 Native Windows x86-64 (Tier 1)

| Component | Windows x86-64 | Notes |
|-----------|:-:|-------|
| CPython 3.14.7 | Available | python.org installer (64-bit) |
| NumPy 2.5.2 | Wheel available | `cp314-cp314-win_amd64` |
| Cython 3.2.9 | Pure Python | Works on Windows |
| **pysam 0.24.0** | **NOT AVAILABLE** | **No native Windows wheels. Build from source fails.** |
| MSVC compiler | Required | Visual Studio 2022+ for C extensions |

---

## 4. pysam/Native-Windows Conclusion

**pysam does not provide native Windows support.** This is a confirmed, ongoing limitation:

- **GitHub issue #1320** (2024-12-12, open, duplicate): "Build fails on Windows"
- **pysam maintainer response**: "Pysam does not currently support Windows."
- **PR #1274**: Windows support efforts exist but are incomplete.
- **Wheel availability**: macOS and Linux only (manylinux_2_28, musllinux_1_2, ARM, x86-64).

**Impact on modern3:**
- BAM preprocessing (`preprocessBams`) is the only pysam consumer.
- All FASTQ/FASTA construction, query, compression, decompression, and merge operations work without pysam.

**Packaging direction for M3-1:** Use conditional dependency packaging, NOT `pip install --no-deps` as a package design. Options:
- `extras_require={"bam": ["pysam>=0.24"]}` — users install `msbwt-modern3[bam]` on supported platforms
- `install_requires` with platform markers: `pysam>=0.24; sys_platform != 'win32'`
- Lazy import in `preprocessBams` (matches modern2 approach) with clear error message on Windows

Do NOT recommend `pip install --no-deps` as the packaging strategy. The distribution must be installable with standard `pip install` on all supported platforms.

---

## 5. Compiler/Toolchain Requirements

### 5.1 Linux

| Tool | Version | Purpose |
|------|---------|---------|
| GCC | ≥7.3.0 | C extension compilation (manylinux_2_17 baseline) |
| Cython | 3.2.9 | `.pyx` → `.c` translation |
| Python dev headers | 3.14.7 | `Python.h` for C extensions |

### 5.2 macOS

| Tool | Version | Purpose |
|------|---------|---------|
| Xcode Command Line Tools | — | Clang compiler |
| Cython | 3.2.9 | `.pyx` → `.c` translation |

### 5.3 Windows

| Tool | Version | Purpose |
|------|---------|---------|
| Visual Studio 2022 | ≥17.0 | MSVC compiler for C extensions |
| Windows SDK | — | `windows.h`, `BaseTsd.h` for `uint64_t` |
| Cython | 3.2.9 | `.pyx` → `.c` translation |

---

## 6. Recommended Installation Sequence

### 6.1 Linux/macOS

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools==84.0.0 wheel==0.48.0 build==1.5.0
pip install Cython==3.2.9 numpy==2.5.2
pip install pysam==0.24.0  # Linux/macOS only
pip install -e packages/msbwt-modern3/
```

### 6.2 Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip setuptools==84.0.0 wheel==0.48.0 build==1.5.0
pip install Cython==3.2.9 numpy==2.5.2
pip install -e packages/msbwt-modern3/  # pysam not available; BAM path raises NotImplementedError
```

---

## 7. Alternative Profiles

### 7.1 Conservative Fallback

| Component | Version | Notes |
|-----------|---------|-------|
| CPython | 3.12.9 | Widest NumPy 2.x compatibility |
| NumPy | 2.4.6 | Previous stable minor |
| Cython | 3.2.9 | Same |
| pysam | 0.24.0 | Same |

### 7.2 Maximum Compatibility

| Component | Version | Notes |
|-----------|---------|-------|
| CPython | 3.13.15 | Previous stable minor |
| NumPy | 2.5.2 | Same |
| Cython | 3.2.9 | Same |
| pysam | 0.24.0 | Same |

---

## 8. Known Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| NumPy 2.x `.npy` header format differences vs 1.x | Potential golden mismatch | Validate header bytes; accept semantic equality if needed |
| Cython 3.2 language-level vs 3.0.x | Generated C differences | Use `language_level=3str` explicitly; regenerate and test |
| pysam API changes (deprecated `Samfile`, `.qname`, `.seq`) | BAM path breakage | Update to modern pysam API |
| `unsigned long` width on Windows vs Linux | ABI/platform divergence | Document; do not fix in initial port |
| Free-threaded CPython 3.13+ | GIL-less Cython execution | Experimental; not needed for initial port |
| build 1.5.1 yanked | Must use 1.5.0 | Pin `build==1.5.0` in build requirements |
