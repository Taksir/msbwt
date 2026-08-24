# Modern3 numeric-domain width policy (M3-R64 / R64-0)

Status: authoritative developer contract for `packages/msbwt-modern3`.
Established by M3-R64 W2. Later repair units (W3/W4/W5) must conform; any
deviation requires a recorded compatibility decision.

## Platform premise

Native Windows x86-64 is LLP64 (`sizeof(long) == sizeof(unsigned long) == 4`);
Linux x86-64 is LP64 (`== 8`). Therefore `long` / `unsigned long` are
**forbidden as representations of any numeric domain whose valid range may
exceed 2^32−1** (BWT lengths, row indexes, occurrence counts, merge/file
offsets, allocation sizes). Their continued presence in source is a defect
unless the domain is provably small (see "narrow domains" below).

## Domain table

| Domain | Meaning | Required range | Canonical Python | Canonical NumPy dtype (persisted/in-memory) | Canonical Cython/C scalar | `long` allowed? | Persistence constraints |
|---|---|---|---|---|---|---|---|
| BWT length / totalSize | number of symbols N in the structure | [0, 2^64) | `int` | `<u8` (totalCounts, fmIndex shapes) | `np.uint64_t` | **NO** | `totalCounts.npy`/FM files already `<u8`; never narrow |
| Row index | position of one BWT row/symbol | [0, N) | `int` | `<u8` (startIndex/endIndex, rank samples, read-provenance rows) | `np.uint64_t` | **NO** | none narrower exists in contracts |
| Suffix/rotation position | synonym of row index during construction/query | [0, N) | `int` | `<u8` | `np.uint64_t` | **NO** | — |
| FM occurrence count | Occ(c,i)/C[c]+Occ(c,i) values, interval bounds l/h | [0, N] | `int` | `<u8` (fmIndex.npy, partialFM) | `np.uint64_t` | **NO** | persisted FM is `<u8` |
| C-array cumulative count | cumulative per-symbol counts (startIndex) | [0, N] | `int` | `<u8` | `np.uint64_t` | **NO** | derived from totalCounts |
| Run/merge/interleave position | byte/bit positions inside interleave or merge spans | [0, ~N] (bit positions up to 8N) | `int` | `<u8` | `np.uint64_t` | **NO** | interleave stays bit-packed `\|u1`; positions are compute-side only |
| File/mmap offset | offset or size on disk | [0, 2^64) | `int` | `<u8` (comp_offsets.npy, quality offsets) | `np.uint64_t` / `size_t` | **NO** | offsets persisted `<Q`/`<u8` |
| NumPy shape/index | array shape element, fancy index | [0, 2^64) | `int` (normalize via `int(x)` before header writes) | intp (64-bit on both target platforms) | `Py_ssize_t` (signed contexts) / `np.uint64_t` | NO (use fixed-width) | `.npy` headers serialize decimal text; normalize shapes with `int()` |
| Signed length/difference | len(seq), kmerSize, numCounts, stack indexes, `end-start` sentinels | [-2^63, 2^63) | `int` | `<i8` | `Py_ssize_t` / `np.int64_t` | NO (use Py_ssize_t) | — |
| Source ID | provenance source identifier | [0, number of sources) (bit-packed column) | `int` | bit-packed `\|u1` interleave; rank prefix `<u8` | `np.uint8_t` per row value; counts `np.uint64_t` | NO for counts | interleave format frozen |
| Read ID / dollar ID | identity of one recovered string | [0, #reads) ⊂ [0, 2^64) | `int` | `<u8` fields (read_provenance mate id) | `np.uint64_t` | **NO** (future-proofing; ABI cannot express ≥2^32 reads otherwise) | read_provenance `<u8` fields unchanged |
| Symbol/alphabet value | symbol-index byte | [0, vcLen) ⊂ [0, 255] | `int` | `\|u1` (msbwt.npy) | `np.uint8_t` | yes (byte-sized, but prefer uint8 for clarity) | msbwt.npy stays `\|u1` |
| LCP value | LCP(SA[i], SA[i+1]) boundary value | [0, max_read_length]; primary persisted dtype `<u4`, writer escape `<u8` | `int` | `<u4` primary (frozen F11A contract; W1 binding) | consumed through `np.uint32_t[:]` view; comparisons via small temporaries | NO for array element type | `<u4` primary format frozen by W1; do NOT widen |
| Quality byte | exact FASTQ ASCII Phred byte | [0, 254]; 255 = terminal sentinel | `int` | `u1` tag array | `np.uint8_t` | yes | quality tag `u1` + JSON sidecar frozen |
| Tag byte/value | BWT-tag primitive payload | per-tag primitive dtype (enforced by BWTTags store) | `int` | primitive dtypes only (`allow_pickle=False`) | matching numpy width | NO for wide tags | registry JSON + npy frozen |
| binSize/bitPower | FM sampling geometry | bitPower ≤ 63; binSize = 2^bitPower ≤ 2^63 | `int` | n/a (compute-only) | may remain `unsigned long` ONLY because bounded ≪ 2^32; products with indexes must promote (compute in `np.uint64_t`) | exception, documented | none |
| Process/thread counts, percentages, iteration counters of control loops | operational scalars | tiny | `int` | n/a | `unsigned int` acceptable | yes | none |

## Rules

1. Any scalar whose domain includes values ≥ 2^31 or ≥ 2^32 (row/index/count/
   offset domains above) MUST be declared `np.uint64_t` (or `size_t` for
   pointer-adjacent arithmetic) in Cython/C, and `<u8` when persisted.
2. Signed quantities that can legitimately be negative (differences before
   clamping, error/sentinel returns, string-length arithmetic) use
   `Py_ssize_t` / `np.int64_t`. Never convert a previously-signed sentinel to
   unsigned.
3. Narrow domains stay narrow: symbols `uint8`, quality `uint8`, LCP persisted
   `<u4`, tags per registered primitive dtype. Do not inflate storage for
   intrinsically small domains.
4. Mixed-width arithmetic: at least one operand of every index-domain product
   or sum must already be `np.uint64_t` so the result is computed in 64 bits
   BEFORE any store (wrap-before-store in a 32-bit intermediate is a defect
   even when the destination is `<u8`).
5. Loop counters ranging over data positions/counts inherit the widest bound's
   type (`np.uint64_t`). Counters over alphabet/control iterations may stay
   narrow.
6. Python-facing signatures accept/return exact ints; widening an ABI parameter
   from 32-bit to 64-bit only enlarges the accepted input domain and never
   breaks existing callers.
7. Persistence compatibility (M3-12) is a hard constraint: this policy changes
   NO persisted dtype. Where a persisted representation is itself insufficient
   for a claimed domain (e.g., insert-state `<u4` sequence IDs, `about.npy`
   u1 file IDs), that is flagged as a separate compatibility-design decision,
   not silently changed here.
8. Cross-platform requirement: the chosen types are fixed-width and identical
   under Win64 LLP64 and Linux LP64. Linux runtime validation remains a
   deferred gate (carried blocker); type choices are inherently portable.

## Test-support probes

Core modules expose cheap compiled probes so tests can prove width at real
Cython boundaries without allocating large structures:

```text
SIZEOF_UNSIGNED_LONG     # module-level constant: sizeof(unsigned long).
                         # Platform data model, NOT a repair target:
                         # LLP64 win_amd64 reports 4; LP64 linux_x86_64
                         # reports 8.  The committed test compares it with
                         # ctypes.sizeof(c_ulong) of the running interpreter.
u64_roundtrip(v)         # cpdef: np.uint64_t -> arithmetic (*3+7) -> np.uint64_t return
bwt_range_roundtrip(lo, hi)  # cpdef: values through the repaired bwtRange struct
sol_r1_seq_length_transport(seq)  # M3-SOL-R1: len(seq) through the canonical
                         # Py_ssize_t length domain + descending loop bound;
                         # must preserve reported lengths >= 2**32 (Win64 probe)
```

A `SIZEOF_UNSIGNED_LONG != ctypes.sizeof(c_ulong)` failure proves a core
module was built against a mismatched data model.  On win_amd64 the correct
value is 4 -- which is exactly why `long`/`unsigned long` are forbidden for
wide domains there; the R64/SOL-R1 repairs replaced them with fixed-width
`np.uint64_t` / `Py_ssize_t`, so NO length/index/count scalar depends on the
platform's `long` width anymore.  A compiled query whose reported pattern
length >= 2**32 is truncated (`len % 2**32`) or treated as the empty pattern
is an LLP64 length-domain defect and fails `test_m3_sol_r1_signed_lengths.py`.
