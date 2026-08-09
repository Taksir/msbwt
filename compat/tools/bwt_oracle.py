#!/usr/bin/env python3
"""Host-side independent MSBWT oracle for legacy merge validation.

This module is deliberately independent of the frozen implementation.  It
reconstructs the standard rotation-sorted multi-string BWT of a read multiset
and verifies semantic invariants (symbol multiset, backward-search k-mer
counts, last-to-first read recovery, and the merge interleave source labels).

The oracle is validated against committed legacy goldens in its tests: the
rotation-sort payload of the ``uniform-multifile`` reads reproduces the
committed ``msbwt.npy`` payload byte-for-byte, and the symbol multiset,
backward-search counts, and LF recovery reproduce the committed
``nonuniform-prefix`` primary.

The frozen nonuniform builder is known to produce a *different but equally
valid* ordering than rotation-sort for nonuniform inputs; the canonical merge
baseline therefore uses uniform inputs, where the rotation-sorted ordering is
uniquely determined.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


SYMBOLS = "$ACGNT"
SYMBOL_ORDER = {symbol: index for index, symbol in enumerate(SYMBOLS)}


class OracleError(ValueError):
    """Raised when a legacy artifact contradicts the independent oracle."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_fastq_sequences(path: Path) -> List[str]:
    """Read the sequence lines of a simple four-line FASTQ file."""
    opener = None
    if str(path).endswith(".gz"):
        import gzip

        opener = gzip.open
    else:
        opener = open
    with opener(str(path), "rb") as handle:
        lines = handle.read().splitlines()
    if not lines or len(lines) % 4:
        raise OracleError("fixture is not a complete four-line FASTQ: {0}".format(path))
    sequences = []
    for index in range(0, len(lines), 4):
        header, sequence, separator, _quality = lines[index:index + 4]
        if not header.startswith(b"@") or not separator.startswith(b"+"):
            raise OracleError("fixture has an invalid FASTQ record: {0}".format(path))
        sequences.append(sequence.decode("ascii"))
    return sequences


def rotation_sort_bwt(reads: Sequence[str]) -> bytes:
    """Return the numeric-symbol payload of the rotation-sorted MSBWT.

    Every read is terminated with ``$`` and all cyclic rotations of all reads
    are sorted lexicographically in symbol order ``$ACGNT``; the payload is the
    last character of every rotation.
    """
    rotations: List[str] = []
    for read in reads:
        for char in read:
            if char not in SYMBOL_ORDER:
                raise OracleError("read contains a non-ACGN symbol: {0!r}".format(read))
        terminated = read + "$"
        length = len(terminated)
        for start in range(length):
            rotations.append(terminated[start:] + terminated[:start])
    rotations.sort()
    return bytes(SYMBOL_ORDER[rotation[-1]] for rotation in rotations)


def decode_payload(payload: bytes) -> str:
    return "".join(SYMBOLS[value] for value in payload)


def symbol_counts(payload: bytes) -> Dict[str, int]:
    counts = {symbol: 0 for symbol in SYMBOLS}
    for value in payload:
        if value >= len(SYMBOLS):
            raise OracleError("payload contains an out-of-range symbol index: {0}".format(value))
        counts[SYMBOLS[value]] += 1
    return counts


def expected_symbol_counts(reads: Sequence[str]) -> Dict[str, int]:
    counts = {symbol: 0 for symbol in SYMBOLS}
    for read in reads:
        for char in read:
            counts[char] += 1
        counts["$"] += 1
    return counts


def expected_substring_counts(reads: Sequence[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for read in reads:
        for start in range(len(read)):
            for end in range(start + 1, len(read) + 1):
                substring = read[start:end]
                counts[substring] = counts.get(substring, 0) + 1
    return counts


def _occurrence_tables(payload: bytes):
    counts = symbol_counts(payload)
    c_table = {}
    running = 0
    for symbol in SYMBOLS:
        c_table[symbol] = running
        running += counts[symbol]
    occ = []
    tally = {symbol: 0 for symbol in SYMBOLS}
    for value in payload:
        tally[SYMBOLS[value]] += 1
        occ.append(dict(tally))
    return c_table, occ


def backward_count(payload: bytes, pattern: str) -> int:
    """Return the number of rotations starting with ``pattern`` via backward search."""
    c_table, occ = _occurrence_tables(payload)
    lo, hi = 0, len(payload)
    for char in reversed(pattern):
        if char not in SYMBOL_ORDER:
            raise OracleError("pattern contains a non-ACGN symbol: {0!r}".format(pattern))
        lo = c_table[char] + (occ[lo - 1][char] if lo > 0 else 0)
        hi = c_table[char] + (occ[hi - 1][char] if hi > 0 else 0)
        if lo >= hi:
            return 0
    return hi - lo


def verify_backward_counts(payload: bytes, reads: Sequence[str]) -> Dict[str, int]:
    expected = expected_substring_counts(reads)
    mismatches = {}
    for pattern, expected_count in sorted(expected.items()):
        actual = backward_count(payload, pattern)
        if actual != expected_count:
            mismatches[pattern] = {"expected": expected_count, "actual": actual}
    if mismatches:
        raise OracleError(
            "backward-search counts differ from the read multiset: {0}".format(mismatches))
    return expected


def lf_recover_reads(payload: bytes) -> List[str]:
    """Recover the read multiset from the numeric-symbol payload via LF mapping.

    Starting at every last-column ``$`` position, the LF mapping reads the
    rotation's characters in reverse order; the accumulated characters form the
    read.  This is the same reconstruction the frozen reader's ``recoverString``
    performs and is independent of any particular BWT byte ordering.
    """
    symbols = SYMBOLS
    n = len(payload)
    counts = symbol_counts(payload)
    c_table = {}
    running = 0
    for symbol in symbols:
        c_table[symbol] = running
        running += counts[symbol]
    occ = []
    tally = {symbol: 0 for symbol in symbols}
    for value in payload:
        tally[symbols[value]] += 1
        occ.append(dict(tally))

    def lf(index: int) -> int:
        symbol = symbols[payload[index]]
        return c_table[symbol] + occ[index][symbol] - 1

    reads = []
    for start in range(n):
        if payload[start] != 0:
            continue
        reversed_chars = []
        index = start
        while True:
            index = lf(index)
            if payload[index] == 0:
                break
            reversed_chars.append(symbols[payload[index]])
        reads.append("".join(reversed(reversed_chars)))
    return sorted(reads)


def interleave_prediction(reads_a: Sequence[str], reads_b: Sequence[str]) -> Dict[str, object]:
    """Predict merged ``inter0.npy`` bit labels for the two input read multisets.

    The merged BWT contains one position per rotation of the union multiset
    (multiplicities included).  ``expected_bits`` has one entry per position in
    sorted-rotation order: 0 for a rotation unique to input A, 1 for one unique
    to input B, and ``None`` for a rotation present in both inputs (its exact
    intra-block order is tie-order-dependent, but its per-input multiplicity is
    not).  ``blocks`` records every distinct rotation's contiguous block with
    its per-input multiplicities.
    """
    from collections import Counter

    rotations_a = []
    for read in reads_a:
        terminated = read + "$"
        for start in range(len(terminated)):
            rotations_a.append(terminated[start:] + terminated[:start])
    rotations_b = []
    for read in reads_b:
        terminated = read + "$"
        for start in range(len(terminated)):
            rotations_b.append(terminated[start:] + terminated[:start])

    count_a = Counter(rotations_a)
    count_b = Counter(rotations_b)
    expected_bits: List[Optional[int]] = []
    blocks: List[Dict[str, object]] = []
    position = 0
    for rotation in sorted(set(rotations_a) | set(rotations_b)):
        in_a = count_a[rotation] > 0
        in_b = count_b[rotation] > 0
        block_a = count_a[rotation]
        block_b = count_b[rotation]
        block_len = block_a + block_b
        if in_a and in_b:
            expected_bit: Optional[int] = None
        elif in_a:
            expected_bit = 0
        elif in_b:
            expected_bit = 1
        else:  # pragma: no cover - union covers every rotation
            raise OracleError("rotation missing from both inputs: {0!r}".format(rotation))
        expected_bits.extend([expected_bit] * block_len)
        blocks.append({
            "rotation": rotation,
            "start": position,
            "end": position + block_len,
            "count_a": block_a,
            "count_b": block_b,
            "expected_bit": expected_bit,
        })
        position += block_len
    return {
        "total_positions": position,
        "unique_to_a": sum(bit == 0 for bit in expected_bits),
        "unique_to_b": sum(bit == 1 for bit in expected_bits),
        "tied": sum(bit is None for bit in expected_bits),
        "expected_bits": expected_bits,
        "blocks": blocks,
        "counts_a": dict(count_a),
        "counts_b": dict(count_b),
    }


def bits_from_interleave_payload(payload: bytes, total_positions: int) -> List[int]:
    """Expand the bit-packed ``inter0.npy`` payload into per-position bits."""
    bits = []
    for value in payload:
        for bit_index in range(8):
            if len(bits) < total_positions:
                bits.append((value >> bit_index) & 1)
    if len(bits) != total_positions:
        raise OracleError(
            "interleave payload covers {0} positions, expected {1}".format(
                len(bits), total_positions))
    return bits


def verify_interleave(
    payload: bytes,
    merged_symbols: int,
    bwt_len_a: int,
    bwt_len_b: int,
    prediction: Dict[str, object],
) -> Dict[str, object]:
    """Verify the bit-packed merge interleave against the source prediction.

    Unambiguous rotation blocks (unique to one input) must match the predicted
    source bit exactly.  Tied blocks (rotations present in both inputs) are
    tie-order-dependent internally, so only their per-input multiplicity is
    checked: the block must contain exactly ``count_a`` zero bits and
    ``count_b`` one bits.  This verifies that the merged structure sources the
    correct number of positions from each input.
    """
    bits = bits_from_interleave_payload(payload, merged_symbols)
    if len(bits) != prediction["total_positions"]:
        raise OracleError("interleave bit count differs from predicted positions")
    zero_count = 0
    one_count = 0
    block_results = []
    mismatches = []
    for block in prediction["blocks"]:
        start = block["start"]
        end = block["end"]
        block_bits = bits[start:end]
        zeros = sum(1 for bit in block_bits if bit == 0)
        ones = len(block_bits) - zeros
        zero_count += zeros
        one_count += ones
        expected = block["expected_bit"]
        if expected is None:
            matched = zeros == block["count_a"] and ones == block["count_b"]
            if not matched:
                mismatches.append({
                    "rotation": block["rotation"], "zeros": zeros, "ones": ones,
                    "count_a": block["count_a"], "count_b": block["count_b"],
                })
        else:
            matched = all(bit == expected for bit in block_bits)
            if not matched:
                mismatches.append({
                    "rotation": block["rotation"], "zeros": zeros, "ones": ones,
                    "expected": expected,
                })
        block_results.append({
            "rotation": block["rotation"],
            "start": start,
            "end": end,
            "zeros": zeros,
            "ones": ones,
            "expected_bit": expected,
            "matched": matched,
        })
    if mismatches:
        raise OracleError("interleave source labels differ from prediction: {0}".format(mismatches))
    if zero_count != bwt_len_a or one_count != bwt_len_b:
        raise OracleError(
            "interleave bit counts are inconsistent: zeros={0} (expected {1}) ones={2} (expected {3})".format(
                zero_count, bwt_len_a, one_count, bwt_len_b))
    return {
        "zero_count": zero_count,
        "one_count": one_count,
        "unique_a_positions": prediction["unique_to_a"],
        "unique_b_positions": prediction["unique_to_b"],
        "tied_positions_count": prediction["tied"],
        "blocks": block_results,
        "unambiguous_mismatches": len([item for item in mismatches if "expected" in item]),
    }
